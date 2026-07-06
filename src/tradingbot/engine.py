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

from .config import PIP, Settings
from .store import Store
from .strategy import entry_allowed, latest_signal, size_position, spread_ok

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
            # Orden recién enviada: enlazar con el trade que apareció
            if open_trades:
                newest = max(open_trades.values(), key=lambda t: t["open_time"])
                self.store.link_trade(rec["id"], newest["trade_id"], newest["open_rate"])
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
        candles = self.broker.get_candles(count=250)
        if candles.empty:
            self.store.log("warn", "Sin velas del bróker")
            return
        now = datetime.now(timezone.utc)
        candles = candles[[ts + timedelta(seconds=CANDLE_SECONDS) <= now for ts in candles.index]]
        if candles.empty or len(candles) < self.s.strategy.bb_period + 2:
            return

        sig = latest_signal(candles, self.s.strategy)
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
        if self.store.trades_today() >= self.s.risk.max_trades_per_day:
            self.store.log("warn", "Señal ignorada: máximo de trades diarios")
            return

        prices = self.broker.current_prices()
        if not spread_ok(prices["bid"], prices["ask"], self.s.risk.max_spread_pips):
            self.store.log("warn", f"Señal ignorada: spread {prices['spread_pips']} pips")
            return

        info = self.broker.account_info()
        equity = info["equity"]
        day_start = self.store.day_start_equity() or equity
        if day_start > 0 and (equity - day_start) / day_start <= -self.s.risk.daily_loss_limit:
            self.store.set_state(
                "halted_until",
                (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(),
            )
            self.store.log("error", "Límite de pérdida diaria alcanzado: bot en pausa hasta mañana")
            return

        units = size_position(equity, self.s.risk.risk_per_trade, sig.stop_distance, self.s.risk.min_lot)
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
        return {
            "running": self.running and not self._halted_today(),
            "paused": not self.running,
            "halted_today": self._halted_today(),
            "connected": connected,
            "mode": getattr(self.broker, "mode", "fxcm"),
            "account": info,
            "daily_pl_pct": daily_pl_pct,
            "trades_today": self.store.trades_today(),
            "max_trades_per_day": self.s.risk.max_trades_per_day,
            "open_trade": self.store.current_open_trade(),
            "stats": self.store.stats(),
            "last_candle": self._last_processed.isoformat() if self._last_processed else None,
        }
