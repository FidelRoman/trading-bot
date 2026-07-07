"""Motor del bot: evalúa la estrategia al cierre de cada vela de 15 minutos.

Corre como tarea asyncio; las llamadas al bróker (bloqueantes) van por
asyncio.to_thread. El estado running/paused se persiste en SQLite para
sobrevivir reinicios.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from .config import PIP, RiskParams, Settings, StrategyParams
from .store import Store
from .strategy import entry_allowed, latest_signal, size_position, spread_ok

# Rangos permitidos para ajustes desde la interfaz: clave -> (min, max, tipo)
SETTING_BOUNDS = {
    "bb_period": (10, 50, int),
    "bb_std": (1.0, 3.0, float),
    "atr_period": (5, 50, int),
    "sl_atr_mult": (0.5, 5.0, float),
    "risk_per_trade": (0.001, 0.02, float),
    "daily_loss_limit": (0.01, 0.10, float),
    "max_trades_per_day": (1, 20, int),
    "max_spread_pips": (0.5, 5.0, float),
    "fixed_units": (0, 500_000, int),  # 0 = tamaño automático por riesgo
}

log = logging.getLogger(__name__)

CANDLE_SECONDS = 15 * 60
GRACE_SECONDS = 10          # margen tras el cierre de vela antes de pedir histórico
FAST_TICK_SECONDS = 5       # cadencia de vigilancia de posición/equity


def last_closed_boundary(now: datetime) -> datetime:
    """Apertura de la última vela de 15m ya CERRADA."""
    epoch = int(now.timestamp())
    current_open = epoch - (epoch % CANDLE_SECONDS)
    return datetime.fromtimestamp(current_open - CANDLE_SECONDS, tz=timezone.utc)


class BotEngine:
    def __init__(self, broker, store: Store, settings: Settings):
        self.broker = broker
        self.store = store
        self.s = settings
        self._stop = False
        self._last_processed: Optional[datetime] = None
        self._last_equity_snap = 0.0
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

    # -- ajustes en runtime (editables desde la web) -----------------------

    def _overrides(self) -> dict:
        return self.store.get_state("settings_override", {}) or {}

    def strategy_params(self) -> StrategyParams:
        o, b = self._overrides(), self.s.strategy
        return StrategyParams(
            bb_period=int(o.get("bb_period", b.bb_period)),
            bb_std=float(o.get("bb_std", b.bb_std)),
            atr_period=int(o.get("atr_period", b.atr_period)),
            sl_atr_mult=float(o.get("sl_atr_mult", b.sl_atr_mult)),
        )

    def risk_params(self) -> RiskParams:
        o, b = self._overrides(), self.s.risk
        return RiskParams(
            risk_per_trade=float(o.get("risk_per_trade", b.risk_per_trade)),
            daily_loss_limit=float(o.get("daily_loss_limit", b.daily_loss_limit)),
            max_trades_per_day=int(o.get("max_trades_per_day", b.max_trades_per_day)),
            max_spread_pips=float(o.get("max_spread_pips", b.max_spread_pips)),
            min_lot=b.min_lot,
        )

    def current_settings(self) -> dict:
        sp, rp = self.strategy_params(), self.risk_params()
        return {
            "bb_period": sp.bb_period,
            "bb_std": sp.bb_std,
            "atr_period": sp.atr_period,
            "sl_atr_mult": sp.sl_atr_mult,
            "risk_per_trade": rp.risk_per_trade,
            "daily_loss_limit": rp.daily_loss_limit,
            "max_trades_per_day": rp.max_trades_per_day,
            "max_spread_pips": rp.max_spread_pips,
            "fixed_units": int(self._overrides().get("fixed_units", 0)),
        }

    def update_settings(self, payload: dict) -> dict:
        """Valida, acota y persiste ajustes; aplican desde la próxima vela."""
        merged = self._overrides()
        for key, raw in payload.items():
            if key not in SETTING_BOUNDS:
                continue
            lo, hi, cast = SETTING_BOUNDS[key]
            try:
                merged[key] = min(max(cast(float(raw)), lo), hi)
            except (TypeError, ValueError):
                continue
        self.store.set_state("settings_override", merged)
        self.store.log("info", "Ajustes actualizados desde la interfaz")
        return self.current_settings()

    # -- órdenes manuales ---------------------------------------------------

    def manual_order(self, side: str, lots: float, sl_pips: float, tp_pips: float) -> dict:
        """Orden manual desde la UI. 1 lote = 100k unidades (0.10 = 10k)."""
        if side not in ("long", "short"):
            return {"ok": False, "error": "Dirección inválida"}
        if self.store.current_open_trade() is not None:
            return {"ok": False, "error": "Ya hay una posición del bot abierta"}
        if sl_pips <= 0 or tp_pips <= 0:
            return {"ok": False, "error": "SL y TP deben ser mayores que 0"}
        units = self.broker.normalize_units(int(lots * 100_000))
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
            f"ORDEN MANUAL {('COMPRA' if side == 'long' else 'VENTA')} {units} EUR/USD "
            f"— SL {sl_pips:.1f} / TP {tp_pips:.1f} pips (orden {order_id})",
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
                await asyncio.to_thread(self._ensure_connected)
                await asyncio.to_thread(self._watch_position)
                self._maybe_snapshot_equity()
                now = datetime.now(timezone.utc)
                boundary = last_closed_boundary(now)
                due = (now - boundary).total_seconds() >= CANDLE_SECONDS + GRACE_SECONDS
                if due and self._last_processed != boundary:
                    await asyncio.to_thread(self._candle_tick, boundary)
                    self._last_processed = boundary
                    await self._emit("candle", {"boundary": boundary.isoformat()})
            except Exception:
                log.exception("Error en el loop del engine")
                self.store.log("error", "Loop: error transitorio (ver consola)")
            await asyncio.sleep(FAST_TICK_SECONDS)
        self.store.log("info", "Engine detenido")

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
            pips = direction * (info["close_rate"] - (rec["entry_rate"] or info["close_rate"])) / PIP
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
        candles = self.broker.get_candles(count=250)
        if candles.empty:
            self.store.log("warn", "Sin velas del bróker")
            return
        now = datetime.now(timezone.utc)
        candles = candles[[ts + timedelta(seconds=CANDLE_SECONDS) <= now for ts in candles.index]]
        if candles.empty or len(candles) < sp.bb_period + 2:
            return

        sig = latest_signal(candles, sp)
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
        if not spread_ok(prices["bid"], prices["ask"], rp.max_spread_pips):
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
            units = size_position(equity, rp.risk_per_trade, sig.stop_distance, rp.min_lot)
        units = self.broker.normalize_units(units)
        if units <= 0:
            self.store.log("warn", "Señal ignorada: tamaño calculado 0 (equity/SL)")
            return

        stop_pips = sig.stop_distance / PIP
        order_id = self.broker.open_position(sig.side, units, stop_pips, sig.take_profit)
        self.store.open_trade(order_id, sig.side, units)
        self.store.log(
            "info",
            f"ORDEN {sig.side.upper()} {units} EUR/USD — SL {stop_pips:.1f} pips, "
            f"TP {sig.take_profit:.5f} (orden {order_id})",
        )

    # -- estado para la web -------------------------------------------------

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
            "account": info,
            "daily_pl_pct": daily_pl_pct,
            "daily_pl_abs": daily_pl_abs,
            "max_drawdown_pct": self.store.max_drawdown_pct(),
            "trades_today": self.store.trades_today(),
            "max_trades_per_day": self.risk_params().max_trades_per_day,
            "open_trade": self.store.current_open_trade(),
            "stats": self.store.stats(),
            "last_candle": self._last_processed.isoformat() if self._last_processed else None,
        }
