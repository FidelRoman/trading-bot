"""Motor del bot: evalúa la estrategia al cierre de cada vela de 15 minutos.

Corre como tarea asyncio; las llamadas al bróker (bloqueantes) van por
asyncio.to_thread. El estado running/paused se persiste en SQLite para
sobrevivir reinicios.
"""
from __future__ import annotations

import asyncio
from functools import partial
import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from .config import DEFAULT_SPEC, InstrumentSpec, RiskParams, Settings, StrategyParams
from .store import Store
from .strategy import entry_allowed, latest_signal, size_position, spread_ok

# Rangos permitidos para ajustes desde la interfaz: clave -> (min, max, tipo) o (opciones, tipo)
SETTING_BOUNDS = {
    "active_strategy": (["fsrppo", "bollinger", "rsi", "wyckoff_1"], str),
    "timeframe": (["m5", "m15", "m30", "h1", "h4"], str),
    "bb_period": (10, 50, int),
    "bb_std": (1.0, 3.0, float),
    "atr_period": (5, 50, int),
    "sl_atr_mult": (0.5, 5.0, float),
    "min_band_width_pips": (0.0, 50.0, float),
    "rsi_period": (5, 50, int),
    "rsi_overbought": (50.0, 90.0, float),
    "rsi_oversold": (10.0, 50.0, float),
    "wyckoff_range_period": (5, 100, int),
    "wyckoff_volume_mult": (1.0, 5.0, float),
    "wyckoff_tp_mult": (0.5, 10.0, float),
    "risk_per_trade": (0.001, 0.02, float),
    "daily_loss_limit": (0.01, 0.10, float),
    "max_trades_per_day": (1, 20, int),
    "max_spread_pips": (0.5, 5.0, float),      # solo divisas
    "max_spread_bps": (0.1, 100.0, float),     # puerta relativa, cualquier activo
    "fixed_units": (0, 500_000, int),  # 0 = tamaño automático por riesgo
}

log = logging.getLogger(__name__)

TF_SECONDS = {
    "m5": 5 * 60,
    "m15": 15 * 60,
    "m30": 30 * 60,
    "h1": 60 * 60,
    "h4": 4 * 60 * 60,
}

GRACE_SECONDS = 10          # margen tras el cierre de vela antes de pedir histórico
FAST_TICK_SECONDS = 5       # cadencia de vigilancia de posición/equity


async def _to_thread(function, *args):
    """Compatibilidad con Python 3.7, anterior a ``asyncio.to_thread``."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(function, *args))


def last_closed_boundary(now: datetime, timeframe: str = "m15") -> datetime:
    """Apertura de la última vela ya CERRADA."""
    seconds = TF_SECONDS.get(timeframe.lower(), 15 * 60)
    epoch = int(now.timestamp())
    current_open = epoch - (epoch % seconds)
    return datetime.fromtimestamp(current_open - seconds, tz=timezone.utc)


class BotEngine:
    def __init__(self, broker, store: Store, settings: Settings):
        self.broker = broker
        self.store = store
        self.s = settings
        self._stop = False
        self._last_processed: Optional[datetime] = None
        self._last_equity_snap = 0.0
        self._policy = None
        # Clave de la política cacheada: (símbolo, run_id). El símbolo entra en la
        # clave porque el activo depende del instrumento, no solo del modelo.
        self._policy_key: Optional[tuple] = None
        self._policy_run_id: Optional[str] = None
        # Instrumento con el que se entrenó el modelo activo. Se compara con el
        # del bróker en cada tick para no operar un activo con la política de otro.
        self._policy_instrument: Optional[str] = None
        self._run_once_lock = asyncio.Lock()
        self.on_event: Optional[Callable[[str, dict], Awaitable[None]]] = None
        if self.store.get_state("running") is None:
            self.store.set_state("running", True)

    # -- control --------------------------------------------------------

    @property
    def running(self) -> bool:
        return bool(self.store.get_state("running", True))

    def pause(self) -> None:
        self.store.set_state("running", False)
        self.store.log("warn", "Bot pausado (kill switch)")

    def resume(self) -> None:
        self.store.set_state("running", True)
        self.store.set_state("halted_until", None)
        self.store.log("info", "Bot reanudado")

    def stop(self) -> None:
        self._stop = True

    def reset_policy(self) -> None:
        """Olvida la política cacheada: se recarga en el próximo tick.

        Se llama al cambiar de bróker o de instrumento, para que el modelo activo
        se vuelva a validar contra el instrumento nuevo.
        """
        self._policy = None
        self._policy_key = None
        self._policy_run_id = None
        self._policy_instrument = None

    # -- ajustes en runtime (editables desde la web) -----------------------

    def _overrides(self) -> dict:
        return self.store.get_state("settings_override", {}) or {}

    def strategy_params(self) -> StrategyParams:
        o, b = self._overrides(), self.s.strategy
        return StrategyParams(
            active_strategy=str(o.get("active_strategy", b.active_strategy)),
            timeframe=str(o.get("timeframe", b.timeframe)),
            bb_period=int(o.get("bb_period", b.bb_period)),
            bb_std=float(o.get("bb_std", b.bb_std)),
            atr_period=int(o.get("atr_period", b.atr_period)),
            sl_atr_mult=float(o.get("sl_atr_mult", b.sl_atr_mult)),
            min_band_width_pips=float(o.get("min_band_width_pips", b.min_band_width_pips)),
            rsi_period=int(o.get("rsi_period", b.rsi_period)),
            rsi_overbought=float(o.get("rsi_overbought", b.rsi_overbought)),
            rsi_oversold=float(o.get("rsi_oversold", b.rsi_oversold)),
            wyckoff_range_period=int(o.get("wyckoff_range_period", b.wyckoff_range_period)),
            wyckoff_volume_mult=float(o.get("wyckoff_volume_mult", b.wyckoff_volume_mult)),
            wyckoff_tp_mult=float(o.get("wyckoff_tp_mult", b.wyckoff_tp_mult)),
        )

    def risk_params(self) -> RiskParams:
        o, b = self._overrides(), self.s.risk
        return RiskParams(
            risk_per_trade=float(o.get("risk_per_trade", b.risk_per_trade)),
            daily_loss_limit=float(o.get("daily_loss_limit", b.daily_loss_limit)),
            max_trades_per_day=int(o.get("max_trades_per_day", b.max_trades_per_day)),
            max_spread_pips=float(o.get("max_spread_pips", b.max_spread_pips)),
            max_spread_bps=float(o.get("max_spread_bps", b.max_spread_bps)),
            min_lot=b.min_lot,
        )

    def current_settings(self) -> dict:
        sp, rp = self.strategy_params(), self.risk_params()
        return {
            "active_strategy": sp.active_strategy,
            "timeframe": sp.timeframe,
            "bb_period": sp.bb_period,
            "bb_std": sp.bb_std,
            "atr_period": sp.atr_period,
            "sl_atr_mult": sp.sl_atr_mult,
            "min_band_width_pips": sp.min_band_width_pips,
            "rsi_period": sp.rsi_period,
            "rsi_overbought": sp.rsi_overbought,
            "rsi_oversold": sp.rsi_oversold,
            "wyckoff_range_period": sp.wyckoff_range_period,
            "wyckoff_volume_mult": sp.wyckoff_volume_mult,
            "wyckoff_tp_mult": sp.wyckoff_tp_mult,
            "risk_per_trade": rp.risk_per_trade,
            "daily_loss_limit": rp.daily_loss_limit,
            "max_trades_per_day": rp.max_trades_per_day,
            "max_spread_pips": rp.max_spread_pips,
            "max_spread_bps": rp.max_spread_bps,
            "fixed_units": int(self._overrides().get("fixed_units", 0)),
        }

    def update_settings(self, payload: dict) -> dict:
        """Valida, acota y persiste ajustes; aplican desde la próxima vela."""
        merged = self._overrides()
        for key, raw in payload.items():
            if key not in SETTING_BOUNDS:
                continue
            bounds = SETTING_BOUNDS[key]
            if len(bounds) == 3:
                lo, hi, cast = bounds
                try:
                    merged[key] = min(max(cast(float(raw)), lo), hi)
                except (TypeError, ValueError):
                    continue
            elif len(bounds) == 2:
                options, cast = bounds
                try:
                    val = cast(raw)
                    if val in options:
                        merged[key] = val
                except (TypeError, ValueError):
                    continue
        self.store.set_state("settings_override", merged)
        self.store.log("info", "Ajustes actualizados desde la interfaz")
        return self.current_settings()

    # -- instrumento activo -------------------------------------------------

    def spec(self) -> InstrumentSpec:
        """Especificación del instrumento que opera el bróker.

        El pip, el lote y los decimales dependen del instrumento, así que se leen
        de aquí y nunca de una constante de módulo. Los brókers de papel y los
        dobles de test que no la expongan caen en la de EUR/USD.
        """
        return getattr(self.broker, "spec", None) or DEFAULT_SPEC

    def symbol(self) -> str:
        return str(getattr(self.broker, "instrument", DEFAULT_SPEC.symbol))

    # -- órdenes manuales ---------------------------------------------------

    def manual_order(self, side: str, lots: float, sl_pips: float, tp_pips: float) -> dict:
        """Orden manual desde la UI.

        En divisas 1 lote = 100.000 unidades; fuera de divisas el lote lo define
        el bróker (1 acción, 1 contrato), así que la conversión se delega en él.
        """
        if side not in ("long", "short"):
            return {"ok": False, "error": "Dirección inválida"}
        if self.store.current_open_trade() is not None:
            return {"ok": False, "error": "Ya hay una posición del bot abierta"}
        if sl_pips < 0 or tp_pips < 0:
            return {"ok": False, "error": "SL y TP no pueden ser negativos"}
        if hasattr(self.broker, "units_for_lots"):
            units = self.broker.units_for_lots(lots)
        else:
            units = self.broker.normalize_units(int(round(lots * self.spec().lot_size)))
        if units <= 0:
            return {"ok": False, "error": "Lote demasiado pequeño (mínimo 0.01)"}
        try:
            order_id = self.broker.open_position_pips(side, units, sl_pips, tp_pips)
        except Exception as e:
            log.exception("Orden manual fallida")
            return {"ok": False, "error": str(e)}
        self.store.open_trade(order_id, side, units)
        self.store.log(
            "warn",
            f"ORDEN MANUAL {('COMPRA' if side == 'long' else 'VENTA')} {units} {self.symbol()} "
            f"— SL {sl_pips:.1f} / TP {tp_pips:.1f} pips (orden {order_id})" if sl_pips > 0 or tp_pips > 0 else f"— sin SL/TP (orden {order_id})",
        )
        return {"ok": True, "order_id": order_id, "units": units}

    def _halted_today(self) -> bool:
        halted_until = self.store.get_state("halted_until")
        if not halted_until:
            return False
        return datetime.now(timezone.utc).date().isoformat() < halted_until

    # -- loop -----------------------------------------------------------

    async def run(self) -> None:
        self.store.log("info", "Engine iniciado")
        while not self._stop:
            try:
                await _to_thread(self._ensure_connected)
                await _to_thread(self._watch_position)
                self._maybe_snapshot_equity()
                now = datetime.now(timezone.utc)
                sp = self.strategy_params()
                tf = sp.timeframe
                seconds = TF_SECONDS.get(tf.lower(), 15 * 60)
                boundary = last_closed_boundary(now, tf)
                due = (now - boundary).total_seconds() >= seconds + GRACE_SECONDS
                if due and self._last_processed != boundary:
                    await _to_thread(self._candle_tick, boundary)
                    self._last_processed = boundary
                    await self._emit("candle", {"boundary": boundary.isoformat()})
            except Exception:
                log.exception("Error en el loop del engine")
                self.store.log("error", "Loop: error transitorio (ver consola)")
            await asyncio.sleep(FAST_TICK_SECONDS)
        self.store.log("info", "Engine detenido")

    async def run_once(self, now: Optional[datetime] = None) -> dict:
        """Procesa como maximo una vela cerrada y persiste su frontera.

        Es el punto de entrada de GitHub Actions/Koyeb. Repetir la misma llamada
        es inocuo incluso si el scheduler reintenta despues de un timeout.
        """
        async with self._run_once_lock:
            moment = now or datetime.now(timezone.utc)
            sp = self.strategy_params()
            boundary = last_closed_boundary(moment, sp.timeframe)
            persisted = self.store.get_state("last_processed_boundary")
            if persisted == boundary.isoformat():
                return {"processed": False, "reason": "already_processed", "boundary": persisted}

            await _to_thread(self._ensure_connected)
            await _to_thread(self._watch_position)
            await _to_thread(self._maybe_snapshot_equity)
            await _to_thread(self._candle_tick, boundary)
            value = boundary.isoformat()
            self._last_processed = boundary
            self.store.set_state("last_processed_boundary", value)
            await self._emit("candle", {"boundary": value})
            return {"processed": True, "boundary": value}

    async def _emit(self, kind: str, data: dict) -> None:
        if self.on_event is not None:
            try:
                await self.on_event(kind, data)
            except Exception:
                log.exception("Error notificando evento %s", kind)

    def _ensure_connected(self) -> None:
        if not self.broker.connected:
            self.broker.connect()

    def _maybe_snapshot_equity(self) -> None:
        if _time.monotonic() - self._last_equity_snap < 60:
            return
        try:
            info = self.broker.account_info()
            self.store.snapshot_equity(info["equity"], info.get("balance"))
            self._last_equity_snap = _time.monotonic()
        except Exception:
            log.exception("No se pudo tomar snapshot de equity")

    # -- gestión de posición ---------------------------------------------

    def _watch_position(self) -> None:
        """Detecta el cierre (TP/SL) de nuestro trade y lo registra."""
        rec = self.store.current_open_trade()
        if rec is None:
            return
        open_trades = {t["trade_id"]: t for t in self.broker.open_trades()}

        if rec["trade_id"] is None:
            # Orden recién enviada: enlazar por open_order_id; si el bróker no
            # lo expone, caer al trade más reciente (puede haber posiciones
            # externas, p. ej. abiertas desde TradingView)
            if open_trades:
                match = next(
                    (t for t in open_trades.values() if t.get("open_order_id") == rec["order_id"]),
                    None,
                ) or max(open_trades.values(), key=lambda t: t["open_time"])
                self.store.link_trade(rec["id"], match["trade_id"], match["open_rate"])
            return

        if rec["trade_id"] in open_trades:
            return

        # Ya no está abierto: buscar el resultado en cerrados
        info = None
        if hasattr(self.broker, "closed_trade_info"):
            info = self.broker.closed_trade_info(rec["trade_id"])
        if info:
            direction = 1 if rec["side"] == "long" else -1
            pips = direction * (info["close_rate"] - (rec["entry_rate"] or info["close_rate"])) / self.spec().pip
            if self.store.get_state("manual_close") == rec["trade_id"]:
                reason = "manual"
                self.store.set_state("manual_close", None)
            else:
                reason = "tp" if info["gross_pl"] > 0 else "sl"
            self.store.close_trade(rec["id"], info["close_rate"], info["gross_pl"], round(pips, 1), reason)
            self.store.log(
                "info",
                f"Trade cerrado ({reason.upper()}): {rec['side']} {rec['units']} "
                f"P&L {info['gross_pl']:+.2f}",
            )
        else:
            self.store.close_trade(rec["id"], None, None, None, "unknown")
            self.store.log("warn", f"Trade {rec['trade_id']} cerrado sin datos de cierre")

    # -- decisión por vela -------------------------------------------------

    def _candle_tick(self, boundary: datetime) -> None:
        sp, rp = self.strategy_params(), self.risk_params()
        candles = self.broker.get_candles(count=250, timeframe=sp.timeframe)
        if candles.empty:
            self.store.log("warn", "Sin velas del bróker")
            return
        now = datetime.now(timezone.utc)
        seconds = TF_SECONDS.get(sp.timeframe.lower(), 15 * 60)
        candles = candles[[ts + timedelta(seconds=seconds) <= now for ts in candles.index]]

        if sp.active_strategy == "fsrppo":
            self._fsrppo_tick(candles, rp, now)
            return

        warmup = max(sp.bb_period, sp.rsi_period) + 2
        if candles.empty or len(candles) < warmup:
            return

        spec = self.spec()
        sig = latest_signal(candles, sp, spec.pip)
        if sig is None:
            return
        self.store.log("info", f"Señal {sig.side.upper()} @ {sig.ref_close:.5f}")

        if not self.running or self._halted_today():
            self.store.log("info", "Señal ignorada: bot pausado")
            return
        if self.store.current_open_trade() is not None:
            self.store.log("info", "Señal ignorada: ya hay posición abierta")
            return
        if not entry_allowed(now):
            self.store.log("info", "Señal ignorada: fuera de sesión permitida")
            return
        if self.store.trades_today() >= rp.max_trades_per_day:
            self.store.log("warn", "Señal ignorada: máximo de trades diarios")
            return

        prices = self.broker.current_prices()
        if not spread_ok(prices["bid"], prices["ask"], rp.max_spread_pips,
                         rp.max_spread_bps, spec):
            self.store.log("warn", f"Señal ignorada: spread {prices['spread_pips']} pips")
            return

        info = self.broker.account_info()
        equity = info["equity"]
        day_start = self.store.day_start_equity() or equity
        if day_start > 0 and (equity - day_start) / day_start <= -rp.daily_loss_limit:
            self.store.set_state(
                "halted_until",
                (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(),
            )
            self.store.log("error", "Límite de pérdida diaria alcanzado: bot en pausa hasta mañana")
            return

        fixed = int(self._overrides().get("fixed_units", 0))
        if fixed > 0:
            units = fixed
        else:
            # El mínimo operable lo manda el instrumento (1.000 en micro-lotes FX,
            # 1 en acciones y oro), no la constante FX de RiskParams.min_lot, que
            # redondearía cualquier acción a 1.000 títulos.
            units = size_position(equity, rp.risk_per_trade, sig.stop_distance,
                                  max(spec.min_lot, 1), spec.contract_multiplier)
        units = self.broker.normalize_units(units)
        if units <= 0:
            self.store.log("warn", "Señal ignorada: tamaño calculado 0 (equity/SL)")
            return

        stop_pips = sig.stop_distance / spec.pip
        order_id = self.broker.open_position(sig.side, units, stop_pips, sig.take_profit)
        self.store.open_trade(order_id, sig.side, units)
        self.store.log(
            "info",
            f"ORDEN {sig.side.upper()} {units} {self.symbol()} — SL {stop_pips:.1f} pips, "
            f"TP {sig.take_profit:.{spec.digits}f} (orden {order_id})",
        )

    # -- decisión por vela: FSRPPO -----------------------------------------

    def active_model_id(self) -> Optional[str]:
        """``run_id`` activo para el instrumento que opera el bróker.

        Se resuelve leyendo el registro, no la caché de ``policy()``: esa solo se
        rellena al cierre de vela, y la interfaz pregunta por el modelo activo
        justo después de cambiar de instrumento, cuando aún no ha habido tick.
        """
        from .rl.registry import ModelRegistry

        try:
            return ModelRegistry().active_id(self.symbol())
        except Exception:
            return None

    def policy(self):
        """Política del modelo activo para el instrumento actual.

        El registro guarda un activo por instrumento, así que cambiar de símbolo
        cambia de modelo en vez de desarmar el bot.
        """
        from .rl.policy import FsrppoPolicy
        from .rl.registry import ModelRegistry

        registry = ModelRegistry()
        simbolo = self.symbol()
        activo = registry.active_id(simbolo)
        # La clave lleva el símbolo: el mismo run_id sobre otro instrumento es
        # una situación distinta y no puede reutilizar la política cacheada.
        clave = (simbolo, activo)
        if clave != self._policy_key:
            self._policy = FsrppoPolicy.load_active(registry, simbolo) if activo else None
            self._policy_key = clave
            self._policy_run_id = activo
            self._policy_instrument = self._model_instrument(registry, activo)
        if self._policy is None:
            return None
        # Defensa por si el mapa y el meta.json discrepan (un active.json editado
        # a mano, una carpeta renombrada): dimensionar con la ficha de un
        # instrumento y ejecutar en otro es el fallo que no se puede permitir.
        entrenado = self._policy_instrument
        if entrenado and entrenado != simbolo:
            self.store.log(
                "error",
                f"FSRPPO desactivado: el modelo activo se entrenó en {entrenado} "
                f"y el bróker opera {simbolo}",
            )
            return None
        return self._policy

    @staticmethod
    def _model_instrument(registry, run_id: Optional[str]) -> Optional[str]:
        """Instrumento con el que se entrenó el modelo activo, si se conoce."""
        if not run_id:
            return None
        try:
            record = registry.get(run_id)
        except Exception:
            return None
        return getattr(record, "instrument", None) if record is not None else None

    def _fsrppo_tick(self, candles, rp: RiskParams, now: datetime) -> None:
        """Ajusta la posición neta según lo que decida el agente.

        El agente propone y el overlay de riesgo dispone: fuera de sesión, con
        spread ancho o tras tocar el límite de pérdida diaria, la única acción
        permitida es reducir exposición, nunca ampliarla.
        """
        policy = self.policy()
        if policy is None:
            self.store.log("warn", "FSRPPO activo pero no hay modelo entrenado seleccionado")
            return
        if len(candles) < policy.required_bars:
            self.store.log(
                "warn",
                f"Histórico insuficiente: {len(candles)} velas de {policy.required_bars}",
            )
            return

        if not hasattr(self.broker, "set_position"):
            self.store.log(
                "error",
                "FSRPPO necesita un bróker de posición neta y este no la expone.",
            )
            return

        posicion = int(getattr(self.broker, "position", 0))
        info = self.broker.account_info()
        equity = float(info.get("equity", policy.env_params.initial_equity))

        decision = policy.decide(
            candles["close"].to_numpy(dtype=float),
            position=posicion,
            entry_price=float(getattr(self.broker, "entry_price", 0.0)),
            equity=equity,
        )

        objetivo = decision.target_position
        motivo = self._risk_veto(rp, now, equity)
        if motivo is not None:
            # Vetado: solo se permite lo que reduzca exposición.
            if abs(objetivo) >= abs(posicion) and objetivo * posicion >= 0:
                self.store.log("info", f"Decisión ignorada ({motivo}): {decision.side}")
                return
            self.store.log("warn", f"{motivo}: solo se permite reducir exposición")

        if objetivo == posicion:
            return

        fill = self.broker.set_position(objetivo)
        self.store.log(
            "info",
            f"FSRPPO {decision.side.upper()} {abs(fill['traded_units'])} → posición neta "
            f"{objetivo} @ {fill['price']} (coste {fill['cost']:.2f})",
        )
        self.store.set_state("last_decision", decision.as_dict())

    def _risk_veto(self, rp: RiskParams, now: datetime, equity: float) -> Optional[str]:
        """Motivo por el que no se debe ampliar exposición, o ``None``."""
        if not self.running:
            return "bot pausado"
        if self._halted_today():
            return "bot detenido por hoy"
        if not entry_allowed(now):
            return "fuera de sesión permitida"

        prices = self.broker.current_prices()
        if not spread_ok(prices["bid"], prices["ask"], rp.max_spread_pips,
                         rp.max_spread_bps, self.spec()):
            return f"spread {prices.get('spread_pips')} pips"

        day_start = self.store.day_start_equity() or equity
        if day_start > 0 and (equity - day_start) / day_start <= -rp.daily_loss_limit:
            self.store.set_state(
                "halted_until",
                (now.date() + timedelta(days=1)).isoformat(),
            )
            self.store.log("error", "Límite de pérdida diaria alcanzado: bot en pausa hasta mañana")
            return "límite de pérdida diaria"
        return None

    # -- estado para la web -------------------------------------------------

    def _active_model_status(self) -> dict:
        """Modelo activo del instrumento actual, con lo mínimo para rotularlo.

        La interfaz necesita saber no solo cuál decide, sino con qué se entrenó:
        timeframe, tramos y coste asumido. Sin eso, un modelo entrenado en H1 con
        1,2 pips de spread se ve idéntico a uno de D1 con 35.
        """
        from .rl.registry import ModelRegistry

        vacio = {"active_model": None, "active_model_instrument": None,
                 "active_model_timeframe": None, "active_model_info": None}
        try:
            registry = ModelRegistry()
            run_id = registry.active_id(self.symbol())
            record = registry.get(run_id) if run_id else None
        except Exception:
            return vacio
        if record is None:
            return vacio
        return {
            "active_model": record.run_id,
            "active_model_instrument": record.instrument,
            "active_model_timeframe": record.timeframe,
            "active_model_info": {
                "created_at": record.created_at,
                "train_range": record.train_range,
                "test_range": record.test_range,
                "learning_rate": record.ppo_params.get("learning_rate"),
                "spread_pips": record.env_params.get("spread_pips")
                or record.env_params.get("instrument", {}).get("typical_spread_pips"),
                "max_units": record.env_params.get("max_units"),
                "test_metrics": record.test_metrics,
            },
        }

    def status(self) -> dict:
        connected = getattr(self.broker, "connected", False)
        info = {}
        if connected:
            try:
                info = self.broker.account_info()
            except Exception:
                connected = False
        day_start = self.store.day_start_equity()
        equity = info.get("equity")
        daily_pl_pct = (
            round((equity - day_start) / day_start * 100, 2)
            if equity and day_start
            else 0.0
        )
        daily_pl_abs = round(equity - day_start, 2) if equity and day_start else 0.0
        return {
            "running": self.running and not self._halted_today(),
            "paused": not self.running,
            "halted_today": self._halted_today(),
            "connected": connected,
            "mode": getattr(self.broker, "mode", "fxcm"),
            # La interfaz avisa distinto según si las órdenes son reales o no, así
            # que el modo y el instrumento viajan en cada status.
            "live_execution": not getattr(self.broker, "read_only", False)
            and getattr(self.broker, "mode", "").startswith("fxcm"),
            "instrument": self.symbol(),
            "asset_class": self.spec().asset_class,
            "digits": self.spec().digits,
            "lot_size": getattr(self.broker, "lot_size", self.spec().lot_size),
            "active_strategy": self.strategy_params().active_strategy,
            "account": info,
            "daily_pl_pct": daily_pl_pct,
            "daily_pl_abs": daily_pl_abs,
            "max_drawdown_pct": self.store.max_drawdown_pct(),
            "trades_today": self.store.trades_today(),
            "max_trades_per_day": self.risk_params().max_trades_per_day,
            "open_trade": self.store.current_open_trade(),
            "stats": self.store.stats(),
            "last_candle": (
                self._last_processed.isoformat()
                if self._last_processed
                else self.store.get_state("last_processed_boundary")
            ),
            "net_position": int(getattr(self.broker, "position", 0)),
            **self._active_model_status(),
            "last_decision": self.store.get_state("last_decision"),
        }
