"""Adaptador ForexConnect (FXCM): login, velas, precios, órdenes y cuenta.

Todas las llamadas son síncronas; el engine las invoca vía asyncio.to_thread.
Un lock serializa el acceso porque la sesión ForexConnect no es thread-safe.
Los timestamps del histórico se tratan como UTC.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from forexconnect import Common, ForexConnect, fxcorepy

from .config import (
    DEFAULT_SPEC,
    INSTRUMENT,
    TIMEFRAME,
    FxcmCredentials,
    InstrumentSpec,
    normalize_symbol,
)
from .instruments import asset_class_of, pip_from_offer

log = logging.getLogger(__name__)


class FxcmBroker:
    def __init__(self, creds: FxcmCredentials, instrument: str = INSTRUMENT,
                 read_only: bool = False, spec: Optional[InstrumentSpec] = None):
        self._creds = creds
        self.instrument = normalize_symbol(instrument)
        self.read_only = read_only
        self._fx: Optional[ForexConnect] = None
        self._lock = threading.RLock()
        self._account_id: Optional[str] = None
        self._base_unit_size: int = 1000
        self.last_status: str = "DISCONNECTED"
        # Especificación provisional hasta connect(), que la refina con los datos
        # reales de la oferta. Un global no sirve: pip, lote y decimales dependen
        # del instrumento, y de eso cuelgan el stop y el filtro de spread.
        self.spec: InstrumentSpec = spec or self._seed_spec()

    def _seed_spec(self) -> InstrumentSpec:
        """Semilla de especificación por símbolo, sin necesidad de sesión."""
        from .config import INSTRUMENT_SEEDS

        conocida = INSTRUMENT_SEEDS.get(self.instrument)
        if conocida is not None:
            return conocida
        # Instrumento fuera de la semilla: se asume la forma más conservadora
        # (mínimo 1 unidad) y connect() lo sustituye por los datos del bróker.
        return InstrumentSpec(
            symbol=self.instrument,
            pip=DEFAULT_SPEC.pip,
            min_lot=1,
            typical_spread_pips=0.0,
            asset_class="other",
        )

    # -- sesión ---------------------------------------------------------

    def _on_status(self, _session, status) -> None:
        self.last_status = str(status)
        log.info("Sesión FXCM: %s", self.last_status)

    def connect(self) -> None:
        self._creds.validate()
        with self._lock:
            if self._fx is not None:
                return
            fx = ForexConnect()
            fx.login(
                self._creds.user,
                self._creds.password,
                self._creds.url,
                self._creds.connection,
                None,
                None,
                self._on_status,
            )
            self._fx = fx
            account = Common.get_account(fx, None)
            if account is None:
                raise RuntimeError("La cuenta FXCM no tiene filas en la tabla ACCOUNTS")
            self._account_id = account.account_id
            # Un instrumento desconocido o no suscrito hace fallar estas dos
            # llamadas. Si se dejan propagar, connect() revienta, run() sale por
            # el finally y NO se escribe ningún runtime_snapshot: la UI se queda
            # con datos viejos y sin señal de error. Mejor conectar con la
            # especificación semilla y dejar que el tick reporte el problema.
            provider = fx.login_rules.trading_settings_provider
            try:
                self._base_unit_size = provider.get_base_unit_size(self.instrument, account)
            except Exception as exc:
                log.warning("Sin base_unit_size para %s (%s); se usa %d",
                            self.instrument, exc, self._base_unit_size)
            try:
                self.spec = self._resolve_spec(fx)
            except Exception as exc:
                log.warning("Sin especificación de mercado para %s (%s); se usa la semilla",
                            self.instrument, exc)
            log.info(
                "Conectado a FXCM (%s), cuenta %s, %s (%s) base_unit_size=%d pip=%s",
                self._creds.connection,
                self._account_id,
                self.instrument,
                self.spec.asset_class,
                self._base_unit_size,
                self.spec.pip,
            )

    @staticmethod
    def _find_offer(fx: ForexConnect, symbol: str):
        """Oferta de ``symbol`` **sin** filtrar por estado de suscripción.

        ``Common.get_offer`` descarta todo lo que no esté en "T" (ver
        forexconnect/common.py), así que no sirve para leer la especificación ni
        para suscribir un instrumento: devolvería None justo en los casos que
        necesitan tratamiento. Esta búsqueda recorre la tabla en crudo.
        """
        for offer in fx.get_table(ForexConnect.OFFERS):
            if getattr(offer, "instrument", None) == symbol:
                return offer
        return None

    def _resolve_spec(self, fx: ForexConnect) -> InstrumentSpec:
        """Especificación real del instrumento leída de su oferta.

        Debe llamarse con el lock tomado y ``_base_unit_size`` ya cacheado: el
        mínimo operable sale del bróker, no de una constante escrita a mano.
        """
        offer = self._find_offer(fx, self.instrument)
        if offer is None:
            log.warning("Sin oferta para %s: se mantiene la especificación semilla",
                        self.instrument)
            return self.spec
        asset_class = asset_class_of(offer)
        pip = pip_from_offer(offer, asset_class)
        bid, ask = float(offer.bid), float(offer.ask)
        spread = round((ask - bid) / pip, 2) if pip > 0 and ask > bid else 0.0
        return InstrumentSpec(
            symbol=self.instrument,
            pip=pip,
            min_lot=max(int(self._base_unit_size), 1),
            typical_spread_pips=max(spread, 0.0),
            quote_currency=str(getattr(offer, "contract_currency", None)
                               or self.instrument.partition("/")[2] or "USD").upper(),
            asset_class=asset_class,
            digits=int(getattr(offer, "digits", 5) or 5),
        )

    @property
    def subscription_status(self) -> str:
        """Estado de suscripción del instrumento activo: "T", "D", "V" o "?".

        Solo "T" permite operar. Se lee de la oferta en crudo porque
        ``Common.get_offer`` descarta todo lo que no esté en "T".
        """
        try:
            with self._lock:
                offer = self._find_offer(self._fx_or_raise(), self.instrument)
        except Exception:
            return "?"
        return str(getattr(offer, "subscription_status", "?")) if offer else "?"

    def refresh_spec(self) -> InstrumentSpec:
        """Relee la especificación del instrumento desde su oferta actual.

        Necesario tras suscribir un instrumento: antes de estar en "T" la oferta
        puede no exponer pip ni tamaño base fiables.
        """
        with self._lock:
            fx = self._fx_or_raise()
            account = Common.get_account(fx, self._account_id)
            try:
                self._base_unit_size = int(
                    fx.login_rules.trading_settings_provider.get_base_unit_size(
                        self.instrument, account)
                )
            except Exception as exc:
                log.warning("Sin base_unit_size para %s (%s)", self.instrument, exc)
            self.spec = self._resolve_spec(fx)
        return self.spec

    def disconnect(self) -> None:
        with self._lock:
            if self._fx is not None:
                try:
                    self._fx.logout()
                finally:
                    self._fx = None

    @property
    def connected(self) -> bool:
        return self._fx is not None and "CONNECTED" in self.last_status

    def _fx_or_raise(self) -> ForexConnect:
        if self._fx is None:
            raise RuntimeError("No hay sesión FXCM: llama a connect() primero")
        return self._fx

    # -- datos ----------------------------------------------------------

    # ForexConnect usa minúscula para minutos y mayúscula para horas/días
    _TF_FXCM = {"m1": "m1", "m5": "m5", "m15": "m15", "m30": "m30",
                "h1": "H1", "h4": "H4", "d1": "D1"}

    def get_candles(
        self,
        count: int = 300,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        timeframe: str = TIMEFRAME,
        symbol: Optional[str] = None,
    ) -> pd.DataFrame:
        """Velas Bid OHLC en UTC. Con count solo, trae las últimas ``count``.

        ``symbol`` permite pedir histórico de **otro** instrumento por la misma
        sesión ya autenticada. Lo usa la descarga de históricos desde la web: sin
        esto habría que abrir un segundo login contra FXCM mientras el bot opera.
        Solo lee; no cambia el instrumento que opera el bróker.
        """
        tf = self._TF_FXCM.get(timeframe.lower(), timeframe)
        with self._lock:
            fx = self._fx_or_raise()
            history = fx.get_history(symbol or self.instrument, tf, date_from, date_to, count)
        df = pd.DataFrame(history)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df["Date"] = pd.to_datetime(df["Date"], utc=True)
        df = df.set_index("Date").sort_index()
        out = df[["BidOpen", "BidHigh", "BidLow", "BidClose", "Volume"]].rename(
            columns={
                "BidOpen": "open",
                "BidHigh": "high",
                "BidLow": "low",
                "BidClose": "close",
                "Volume": "volume",
            }
        )
        out.index.name = "time"
        return out

    def current_prices(self) -> dict:
        """Bid/ask/spread actuales desde la tabla OFFERS."""
        with self._lock:
            fx = self._fx_or_raise()
            offer = Common.get_offer(fx, self.instrument)
        if offer is None:
            raise RuntimeError(f"Sin oferta para {self.instrument}")
        return {
            "bid": float(offer.bid),
            "ask": float(offer.ask),
            "spread_pips": round((float(offer.ask) - float(offer.bid)) / self.spec.pip, 2),
            "time": datetime.now(timezone.utc).isoformat(),
        }

    # -- catálogo de instrumentos ---------------------------------------

    def instrument_catalog(self, max_entries: int = 1500) -> dict:
        """Universo de instrumentos de la cuenta, leído de la tabla OFFERS.

        Es la única forma de saber qué divisas, acciones, índices y CFD ofrece
        realmente la cuenta: la lista de ``config.INSTRUMENT_SEEDS`` es solo un
        respaldo. Lo consume el worker para publicar ``instrument_catalog``.
        """
        from .instruments import build_catalog, symbol_of

        tradable = fxcorepy.Constants.SubscriptionStatuses.TRADABLE
        with self._lock:
            fx = self._fx_or_raise()
            rows = list(fx.get_table(ForexConnect.OFFERS))
            account = Common.get_account(fx, self._account_id)
            provider = fx.login_rules.trading_settings_provider
            sizes = {}
            for row in rows:
                symbol = symbol_of(row)
                if not symbol:
                    continue
                # Solo se consulta el tamaño base de lo operable (y del
                # instrumento activo): la tabla puede traer ~2.000 ofertas y una
                # llamada por cada una no cabe en los 15 min del workflow.
                if (str(getattr(row, "subscription_status", "")) != tradable
                        and symbol != self.instrument):
                    continue
                try:
                    sizes[symbol] = int(provider.get_base_unit_size(symbol, account))
                except Exception:
                    # Sin tamaño base se asume 1 unidad; su subscription_status
                    # ya lo marca como no operable en el catálogo.
                    sizes[symbol] = 1
        return build_catalog(rows, self._creds.connection, sizes, max_entries)

    def subscribe(self, instrument: Optional[str] = None) -> dict:
        """Pone un instrumento en estado "T" para poder operarlo por API.

        Las cuentas demo traen la mayoría de instrumentos en "D" (deshabilitado)
        o "V" (solo ver). El cambio persiste en la cuenta entre sesiones.
        """
        self._assert_trading_enabled()
        symbol = normalize_symbol(instrument or self.instrument)
        tradable = fxcorepy.Constants.SubscriptionStatuses.TRADABLE
        with self._lock:
            fx = self._fx_or_raise()
            offer = self._find_offer(fx, symbol)
            if offer is None:
                raise RuntimeError(f"{symbol} no existe en la tabla de ofertas")
            previo = str(getattr(offer, "subscription_status", "?"))
            if previo == tradable:
                return {"symbol": symbol, "status": tradable, "changed": False}
            request = fx.create_request({
                fxcorepy.O2GRequestParamsEnum.COMMAND:
                    fxcorepy.Constants.Commands.SET_SUBSCRIPTION_STATUS,
                fxcorepy.O2GRequestParamsEnum.OFFER_ID: offer.offer_id,
                fxcorepy.O2GRequestParamsEnum.SUBSCRIPTION_STATUS: tradable,
            })
            fx.send_request(request)
            # El cambio no es inmediato en la tabla: se relee para no informar de
            # un estado que el bróker todavía no ha aplicado.
            time.sleep(2)
            confirmado = self._find_offer(fx, symbol)
            actual = str(getattr(confirmado, "subscription_status", "?")) if confirmado else "?"
        log.info("Suscripción de %s: %s -> %s", symbol, previo, actual)
        return {"symbol": symbol, "status": actual, "changed": actual != previo,
                "previous": previo}

    def account_info(self) -> dict:
        with self._lock:
            fx = self._fx_or_raise()
            account = Common.get_account(fx, self._account_id)
        balance = float(account.balance)
        # No todas las versiones exponen equity directamente
        equity = float(getattr(account, "equity", 0.0)) or balance + float(
            getattr(account, "gross_pl", 0.0)
        )
        used_margin = float(getattr(account, "used_margin", 0.0))
        usable = float(getattr(account, "usable_margin", 0.0)) or max(equity - used_margin, 0.0)
        return {
            "account_id": str(account.account_id),
            "balance": balance,
            "equity": equity,
            "day_pl": float(getattr(account, "day_pl", 0.0)),
            "used_margin": used_margin,
            "usable_margin": usable,
            "connection": self._creds.connection,
        }

    def open_trades(self) -> list[dict]:
        with self._lock:
            fx = self._fx_or_raise()
            table = fx.get_table(ForexConnect.TRADES)
            rows = []
            for t in table:
                if t.instrument != self.instrument:
                    continue
                rows.append(
                    {
                        "trade_id": str(t.trade_id),
                        "open_order_id": str(getattr(t, "open_order_id", "")),
                        "side": "long" if t.buy_sell == fxcorepy.Constants.BUY else "short",
                        "units": int(t.amount),
                        "open_rate": float(t.open_rate),
                        "open_time": str(t.open_time),
                        "stop": float(getattr(t, "stop", 0.0)),
                        "limit": float(getattr(t, "limit", 0.0)),
                        "gross_pl": float(getattr(t, "gross_pl", 0.0)),
                    }
                )
            return rows

    def closed_trade_info(self, trade_id: str) -> Optional[dict]:
        """Datos de cierre desde CLOSED_TRADES, o None si aún no aparece."""
        with self._lock:
            fx = self._fx_or_raise()
            table = fx.get_table(ForexConnect.CLOSED_TRADES)
            for t in table:
                if str(t.trade_id) == str(trade_id):
                    return {
                        "close_rate": float(t.close_rate),
                        "gross_pl": float(getattr(t, "gross_pl", 0.0)),
                        "close_time": str(getattr(t, "close_time", "")),
                    }
        return None

    # -- órdenes --------------------------------------------------------

    @property
    def mode(self) -> str:
        return f"fxcm-{self._creds.connection.lower()}"

    def normalize_units(self, units: int) -> int:
        return (units // self._base_unit_size) * self._base_unit_size

    @property
    def lot_size(self) -> int:
        """Unidades equivalentes a 1 lote en este instrumento."""
        if self.spec.asset_class == "forex":
            return 100_000
        return max(int(self._base_unit_size), 1)

    def units_for_lots(self, lots: float) -> int:
        """Convierte lotes de la UI a unidades del bróker.

        En divisas 1 lote = 100.000 unidades. Fuera de divisas esa convención no
        existe (1 lote de una acción no son 100.000 títulos), así que el lote es
        el tamaño base que declara el bróker para el instrumento.
        """
        return self.normalize_units(int(round(lots * self.lot_size)))

    def _assert_trading_enabled(self) -> None:
        if self.read_only:
            raise PermissionError("La sesion FXCM es de solo lectura; las ordenes estan bloqueadas")

    def open_position(
        self, side: str, units: int, stop_pips: float, take_profit: float
    ) -> str:
        """Orden a mercado con SL pegado al precio de apertura y TP absoluto.

        El SL pegado (FROM_OPEN) evita adivinar el precio de fill: FXCM lo
        coloca a ``stop_pips`` del precio real de apertura del trade.
        """
        self._assert_trading_enabled()
        units = self.normalize_units(units)
        if units <= 0:
            raise ValueError("units debe ser >= base_unit_size")
        is_long = side == "long"
        with self._lock:
            fx = self._fx_or_raise()
            offer = Common.get_offer(fx, self.instrument)
            kwargs = {
                "order_type": fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,
                "OFFER_ID": offer.offer_id,
                "ACCOUNT_ID": self._account_id,
                "BUY_SELL": fxcorepy.Constants.BUY if is_long else fxcorepy.Constants.SELL,
                "AMOUNT": units,
            }
            if stop_pips > 0:
                kwargs["PEG_TYPE_STOP"] = fxcorepy.Constants.Peg.FROM_OPEN
                kwargs["PEG_OFFSET_STOP"] = -abs(stop_pips) if is_long else abs(stop_pips)
            if take_profit > 0:
                kwargs["RATE_LIMIT"] = round(take_profit, self.spec.digits)
            request = fx.create_order_request(**kwargs)
            if request is None:
                raise RuntimeError("No se pudo crear la orden")
            resp = fx.send_request(request)
            order_id = str(resp.order_id)
        log.info(
            "Orden enviada: %s %d %s SL=%.1f pips TP=%s (order_id=%s)",
            side, units, self.instrument, stop_pips,
            round(take_profit, self.spec.digits), order_id,
        )
        return order_id

    def open_position_pips(self, side: str, units: int, sl_pips: float, tp_pips: float) -> str:
        """Orden a mercado con SL y TP expresados en pips (para órdenes manuales)."""
        self._assert_trading_enabled()
        prices = self.current_prices()
        ref = prices["ask"] if side == "long" else prices["bid"]
        pip = self.spec.pip
        tp = 0
        if tp_pips > 0:
            tp = ref + tp_pips * pip if side == "long" else ref - tp_pips * pip
        return self.open_position(side, units, sl_pips, tp)

    # -- posición neta (FSRPPO) -----------------------------------------

    @property
    def position(self) -> int:
        """Unidades netas abiertas en este instrumento; negativas si es corto.

        FSRPPO razona en posición neta, no en operaciones con SL/TP, así que se
        agregan los trades abiertos del instrumento en un único número.
        """
        neto = 0
        for trade in self.open_trades():
            neto += trade["units"] if trade["side"] == "long" else -trade["units"]
        return neto

    @property
    def entry_price(self) -> float:
        """Precio medio ponderado de la posición neta, o 0 si está plana."""
        trades = self.open_trades()
        unidades = sum(t["units"] for t in trades)
        if not unidades:
            return 0.0
        return sum(t["open_rate"] * t["units"] for t in trades) / unidades

    def _close_amount(self, trade, amount: int) -> str:
        """Cierra ``amount`` unidades de un trade concreto (cierre parcial)."""
        opposite = (
            fxcorepy.Constants.SELL
            if trade.buy_sell == fxcorepy.Constants.BUY
            else fxcorepy.Constants.BUY
        )
        fx = self._fx_or_raise()
        request = fx.create_order_request(
            order_type=fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE,
            OFFER_ID=str(trade.offer_id),
            ACCOUNT_ID=self._account_id,
            BUY_SELL=opposite,
            AMOUNT=int(amount),
            TRADE_ID=str(trade.trade_id),
        )
        return str(fx.send_request(request).order_id)

    def _reduce_position(self, units: int) -> list:
        """Cierra ``units`` unidades de la posición actual, trade a trade.

        Debe llamarse con el lock tomado. Cierra completo mientras quepa y hace un
        cierre parcial con el resto, para no dejar la posición pasada de largo.
        """
        pendiente = int(units)
        ordenes = []
        # Se fija la lista antes de enviar nada: la tabla TRADES cambia a medida
        # que se ejecutan los cierres, e iterarla en vivo se saltaría filas.
        abiertos = [t for t in self._fx_or_raise().get_table(ForexConnect.TRADES)
                    if t.instrument == self.instrument]
        for trade in abiertos:
            if pendiente <= 0:
                break
            cantidad = min(int(trade.amount), pendiente)
            if cantidad <= 0:
                continue
            ordenes.append(self._close_amount(trade, cantidad))
            pendiente -= cantidad
        if pendiente > 0:
            log.warning("Quedaron %d unidades sin cerrar en %s", pendiente, self.instrument)
        return ordenes

    def set_position(self, target_units: int) -> dict:
        """Lleva la posición neta del instrumento a ``target_units``.

        Es la interfaz que espera FSRPPO (misma forma que ``PaperBroker``). Las
        órdenes van a mercado: reducir cierra (parcialmente si hace falta), dar la
        vuelta cierra todo y abre en el sentido contrario, y ampliar abre solo el
        delta. Sin SL ni TP en el bróker: la política decide la salida en cada
        barra, así que un stop en servidor competiría con ella.
        """
        self._assert_trading_enabled()
        with self._lock:
            actual = self.position
            objetivo = self.normalize_units(abs(int(target_units)))
            objetivo = objetivo if int(target_units) >= 0 else -objetivo
            delta = objetivo - actual
            precio = float(self.current_prices()["bid"])

            if delta == 0:
                return {"traded_units": 0, "price": precio, "cost": 0.0,
                        "position": actual, "realised": 0.0, "order_ids": []}

            ordenes = []
            mismo_signo = (objetivo >= 0) == (actual >= 0)
            if objetivo == 0 or not mismo_signo:
                # Vuelta de signo o cierre: primero se aplana, luego se abre.
                if actual != 0:
                    ordenes += self._reduce_position(abs(actual))
                if objetivo != 0:
                    ordenes.append(self._open_market(objetivo))
            elif abs(objetivo) < abs(actual):
                ordenes += self._reduce_position(abs(actual) - abs(objetivo))
            else:
                # Mismo signo y más exposición: el delta ya lleva el sentido.
                ordenes.append(self._open_market(delta))

            # El coste se estima con el spread vigente sobre las unidades movidas;
            # el P&L real lo liquida el bróker y se ve en account_info().
            prices = self.current_prices()
            coste = abs(delta) * max(float(prices["ask"]) - float(prices["bid"]), 0.0)
        log.warning("Posición neta %s: %d -> %d (%d unidades, %d órdenes)",
                    self.instrument, actual, objetivo, delta, len(ordenes))
        return {"traded_units": delta, "price": precio, "cost": round(coste, 4),
                "position": objetivo, "realised": 0.0, "order_ids": ordenes}

    def _open_market(self, signed_units: int) -> str:
        """Abre a mercado ``abs(signed_units)`` sin SL ni TP. Lock ya tomado."""
        unidades = abs(int(signed_units))
        if unidades <= 0:
            raise ValueError("no hay unidades que abrir")
        fx = self._fx_or_raise()
        offer = self._find_offer(fx, self.instrument)
        if offer is None:
            raise RuntimeError(f"Sin oferta para {self.instrument}")
        request = fx.create_order_request(
            order_type=fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,
            OFFER_ID=offer.offer_id,
            ACCOUNT_ID=self._account_id,
            BUY_SELL=(fxcorepy.Constants.BUY if signed_units > 0
                      else fxcorepy.Constants.SELL),
            AMOUNT=unidades,
        )
        if request is None:
            raise RuntimeError("No se pudo crear la orden de posición neta")
        return str(fx.send_request(request).order_id)

    def close_position(self) -> dict:
        return self.set_position(0)

    def close_trade(self, trade_id: str) -> str:
        self._assert_trading_enabled()
        with self._lock:
            fx = self._fx_or_raise()
            # Nota: Common.get_trade busca por offer_id, no por trade_id
            trade = None
            for t in fx.get_table(ForexConnect.TRADES):
                if str(t.trade_id) == str(trade_id):
                    trade = t
                    break
            if trade is None:
                raise RuntimeError(f"Trade {trade_id} no encontrado")
            opposite = (
                fxcorepy.Constants.SELL
                if trade.buy_sell == fxcorepy.Constants.BUY
                else fxcorepy.Constants.BUY
            )
            request = fx.create_order_request(
                order_type=fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE,
                OFFER_ID=str(trade.offer_id),
                ACCOUNT_ID=self._account_id,
                BUY_SELL=opposite,
                AMOUNT=int(trade.amount),
                TRADE_ID=str(trade.trade_id),
            )
            resp = fx.send_request(request)
            order_id = str(resp.order_id)
        log.info("Cierre enviado para trade %s (order_id=%s)", trade_id, order_id)
        return order_id
