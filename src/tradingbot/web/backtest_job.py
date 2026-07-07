"""Ejecución de backtests en segundo plano para la pestaña Backtesting.

Un solo backtest a la vez; el resultado completo se persiste en el Store
(clave ``last_backtest``) para repoblar la pestaña tras recargar la página.
"""
from __future__ import annotations

import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..backtest import download_history, load_csv, run_backtest, synthetic_df
from ..config import PROJECT_ROOT, RiskParams, StrategyParams

log = logging.getLogger(__name__)

HISTORY_DIR = PROJECT_ROOT / "data" / "history"
UPLOAD_CSV = HISTORY_DIR / "upload.csv"
MAX_TRADES_PAYLOAD = 500


def _scrub(obj):
    """Sustituye floats no finitos (inf/nan) por None: no son JSON válidos."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


class BacktestJob:
    def __init__(self, store, engine, broker):
        self.store = store
        self.engine = engine
        self.broker = broker
        self._lock = threading.Lock()
        self._running = False
        self._note = ""

    # -- estado ----------------------------------------------------------

    def state(self) -> dict:
        with self._lock:
            if self._running:
                return {"status": "running", "note": self._note}
        last = self.store.get_state("last_backtest")
        return _scrub(last) if last else {"status": "idle"}

    def _set_note(self, note: str) -> None:
        with self._lock:
            self._note = note

    # -- ejecución ---------------------------------------------------------

    def start_allowed(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._note = "Preparando datos…"
            return True

    def run_sync(
        self,
        source: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
        equity: float,
        spread_pips: float,
    ) -> None:
        """Corre en un thread (asyncio.to_thread). start_allowed() debe ser True."""
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            df, source_label = self._load_data(source, timeframe, date_from, date_to)
            sp, rp = self.engine.strategy_params(), self.engine.risk_params()
            self._set_note(f"Simulando {len(df)} velas…")
            result = run_backtest(
                df, strategy_params=sp, risk=rp, initial_equity=equity, spread_pips=spread_pips
            )
            eq = result.equity_curve
            seen: set[int] = set()
            equity_points = []
            for ts, val in eq.items():
                t = int(ts.timestamp())
                if t not in seen:
                    seen.add(t)
                    equity_points.append({"time": t, "value": round(float(val), 2)})
            trades = [
                {
                    "side": t.side,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "entry": round(t.entry, 5),
                    "exit": round(t.exit, 5),
                    "units": t.units,
                    "pnl": round(t.pnl, 2),
                    "pips": round(t.pips, 1),
                    "reason": t.reason,
                }
                for t in result.trades[-MAX_TRADES_PAYLOAD:]
            ]
            payload = {
                "status": "done",
                "source": source_label,
                "synthetic": source == "synthetic",
                "timeframe": timeframe,
                "candles": len(df),
                "period": {
                    "from": df.index[0].isoformat(),
                    "to": df.index[-1].isoformat(),
                },
                "params": {
                    "bb_period": sp.bb_period,
                    "bb_std": sp.bb_std,
                    "atr_period": sp.atr_period,
                    "sl_atr_mult": sp.sl_atr_mult,
                    "risk_per_trade": rp.risk_per_trade,
                    "spread_pips": spread_pips,
                    "initial_equity": equity,
                },
                "summary": result.summary(),
                "equity": equity_points,
                "trades": trades,
                "started": started,
                "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self.store.set_state("last_backtest", payload)
            s = payload["summary"]
            self.store.log(
                "info",
                f"Backtest terminado ({source_label}): {s['trades']} trades, "
                f"PF {s['profit_factor']}, retorno {s['return_pct']}%",
            )
        except Exception as e:
            log.exception("Backtest fallido")
            self.store.set_state(
                "last_backtest",
                {"status": "error", "error": str(e), "started": started},
            )
            self.store.log("error", f"Backtest fallido: {e}")
        finally:
            with self._lock:
                self._running = False

    def _load_data(self, source: str, timeframe: str, date_from: datetime, date_to: datetime):
        label_range = f"{date_from:%Y-%m-%d} → {date_to:%Y-%m-%d} ({timeframe.upper()})"
        if source == "synthetic":
            df = synthetic_df(timeframe=timeframe, date_from=date_from, date_to=date_to)
            return df, f"Sintético {label_range}"
        if source == "csv":
            if not UPLOAD_CSV.exists():
                raise RuntimeError("No hay CSV subido: usa 'Subir CSV' primero")
            df = load_csv(UPLOAD_CSV, timeframe=timeframe)
            df = df.loc[(df.index >= date_from) & (df.index <= date_to)]
            if len(df) < 30:
                raise RuntimeError(
                    "El CSV no tiene suficientes velas dentro del rango de fechas elegido"
                )
            return df, f"CSV {label_range}"
        if source == "fxcm":
            if getattr(self.broker, "mode", "") == "simulado":
                raise RuntimeError("Histórico FXCM no disponible en modo simulado")
            if not self.broker.connected:
                raise RuntimeError("Sin conexión con FXCM")
            df = download_history(
                self.broker, date_from, date_to, timeframe, HISTORY_DIR, progress=self._set_note
            )
            return df, f"FXCM {label_range}"
        raise RuntimeError(f"Fuente desconocida: {source}")
