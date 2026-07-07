"""Adaptador ForexConnect (FXCM): login, velas, precios, órdenes y cuenta.

Todas las llamadas son síncronas; el engine las invoca vía asyncio.to_thread.
Un lock serializa el acceso porque la sesión ForexConnect no es thread-safe.
Los timestamps del histórico se tratan como UTC.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from forexconnect import Common, ForexConnect, fxcorepy

from .config import INSTRUMENT, PIP, TIMEFRAME, FxcmCredentials

log = logging.getLogger(__name__)


class FxcmBroker:
    def __init__(self, creds: FxcmCredentials):
        self._creds = creds
        self._fx: Optional[ForexConnect] = None
        self._lock = threading.RLock()
        self._account_id: Optional[str] = None
        self._base_unit_size: int = 1000
        self.last_status: str = "DISCONNECTED"

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
            provider = fx.login_rules.trading_settings_provider
            self._base_unit_size = provider.get_base_unit_size(INSTRUMENT, account)
            log.info(
                "Conectado a FXCM (%s), cuenta %s, base_unit_size=%d",
                self._creds.connection,
                self._account_id,
                self._base_unit_size,
            )

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
    ) -> pd.DataFrame:
        """Velas Bid OHLC en UTC. Con count solo, trae las últimas ``count``."""
        tf = self._TF_FXCM.get(timeframe.lower(), timeframe)
        with self._lock:
            fx = self._fx_or_raise()
            history = fx.get_history(INSTRUMENT, tf, date_from, date_to, count)
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
            offer = Common.get_offer(fx, INSTRUMENT)
        if offer is None:
            raise RuntimeError(f"Sin oferta para {INSTRUMENT}")
        return {
            "bid": float(offer.bid),
            "ask": float(offer.ask),
            "spread_pips": round((float(offer.ask) - float(offer.bid)) / PIP, 2),
            "time": datetime.now(timezone.utc).isoformat(),
        }

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
                if t.instrument != INSTRUMENT:
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

    def open_position(
        self, side: str, units: int, stop_pips: float, take_profit: float
    ) -> str:
        """Orden a mercado con SL pegado al precio de apertura y TP absoluto.

        El SL pegado (FROM_OPEN) evita adivinar el precio de fill: FXCM lo
        coloca a ``stop_pips`` del precio real de apertura del trade.
        """
        units = self.normalize_units(units)
        if units <= 0:
            raise ValueError("units debe ser >= base_unit_size")
        is_long = side == "long"
        with self._lock:
            fx = self._fx_or_raise()
            offer = Common.get_offer(fx, INSTRUMENT)
            request = fx.create_order_request(
                order_type=fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,
                OFFER_ID=offer.offer_id,
                ACCOUNT_ID=self._account_id,
                BUY_SELL=fxcorepy.Constants.BUY if is_long else fxcorepy.Constants.SELL,
                AMOUNT=units,
                PEG_TYPE_STOP=fxcorepy.Constants.Peg.FROM_OPEN,
                PEG_OFFSET_STOP=-abs(stop_pips) if is_long else abs(stop_pips),
                RATE_LIMIT=round(take_profit, 5),
            )
            if request is None:
                raise RuntimeError("No se pudo crear la orden")
            resp = fx.send_request(request)
            order_id = str(resp.order_id)
        log.info(
            "Orden enviada: %s %d %s SL=%.1f pips TP=%.5f (order_id=%s)",
            side, units, INSTRUMENT, stop_pips, take_profit, order_id,
        )
        return order_id

    def open_position_pips(self, side: str, units: int, sl_pips: float, tp_pips: float) -> str:
        """Orden a mercado con SL y TP expresados en pips (para órdenes manuales)."""
        prices = self.current_prices()
        ref = prices["ask"] if side == "long" else prices["bid"]
        tp = ref + tp_pips * PIP if side == "long" else ref - tp_pips * PIP
        return self.open_position(side, units, sl_pips, tp)

    def close_trade(self, trade_id: str) -> str:
        with self._lock:
            fx = self._fx_or_raise()
            trade = Common.get_trade(fx, self._account_id, trade_id)
            if trade is None:
                raise RuntimeError(f"Trade {trade_id} no encontrado")
            offer = Common.get_offer(fx, INSTRUMENT)
            opposite = (
                fxcorepy.Constants.SELL
                if trade.buy_sell == fxcorepy.Constants.BUY
                else fxcorepy.Constants.BUY
            )
            request = fx.create_order_request(
                order_type=fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE,
                OFFER_ID=offer.offer_id,
                ACCOUNT_ID=self._account_id,
                BUY_SELL=opposite,
                AMOUNT=int(trade.amount),
                TRADE_ID=str(trade.trade_id),
            )
            resp = fx.send_request(request)
            order_id = str(resp.order_id)
        log.info("Cierre enviado para trade %s (order_id=%s)", trade_id, order_id)
        return order_id
