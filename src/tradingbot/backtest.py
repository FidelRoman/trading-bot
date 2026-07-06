"""Backtester: ejecuta la misma estrategia de strategy.py sobre histórico m15.

Modelo de ejecución (conservador):
- La señal se evalúa al cierre de la vela t; la entrada es al open de t+1.
- Si SL y TP caen dentro de la misma vela, se asume que tocó primero el SL.
- Coste de spread: se descuenta ``spread_pips`` por operación (ida y vuelta).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import PIP, RiskParams, StrategyParams
from .strategy import (
    LONG,
    SHORT,
    add_indicators,
    compute_signals,
    entry_allowed,
    size_position,
)


@dataclass
class BtTrade:
    side: str
    entry_time: datetime
    exit_time: datetime
    entry: float
    exit: float
    units: int
    pnl: float
    pips: float
    reason: str  # "tp" | "sl" | "end"


@dataclass
class BacktestResult:
    trades: list[BtTrade]
    equity_curve: pd.Series
    initial_equity: float

    def summary(self) -> dict:
        eq = self.equity_curve
        pnls = np.array([t.pnl for t in self.trades])
        wins, losses = pnls[pnls > 0], pnls[pnls < 0]
        gross_win, gross_loss = wins.sum(), -losses.sum()
        peak = eq.cummax()
        dd = ((eq - peak) / peak).min() if len(eq) else 0.0
        return {
            "trades": len(self.trades),
            "net_profit": round(float(pnls.sum()), 2),
            "return_pct": round(float(pnls.sum()) / self.initial_equity * 100, 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if len(pnls) else 0.0,
            "profit_factor": round(float(gross_win / gross_loss), 2)
            if gross_loss > 0
            else float("inf"),
            "max_drawdown_pct": round(float(dd) * 100, 2),
            "avg_trade": round(float(pnls.mean()), 2) if len(pnls) else 0.0,
            "total_pips": round(float(sum(t.pips for t in self.trades)), 1),
        }


def run_backtest(
    df: pd.DataFrame,
    strategy_params: StrategyParams = StrategyParams(),
    risk: RiskParams = RiskParams(),
    initial_equity: float = 10_000.0,
    spread_pips: float = 1.2,
) -> BacktestResult:
    d = add_indicators(df, strategy_params)
    signals = compute_signals(d, strategy_params)

    equity = initial_equity
    trades: list[BtTrade] = []
    eq_times: list[datetime] = []
    eq_values: list[float] = []

    pos: Optional[dict] = None
    day = None
    day_start_equity = equity
    day_trades = 0
    spread_cost_price = spread_pips * PIP

    rows = d.itertuples()
    idx = d.index
    opens, highs, lows = d["open"].values, d["high"].values, d["low"].values

    for i in range(len(d)):
        ts = idx[i].to_pydatetime()

        if day != ts.date():
            day = ts.date()
            day_start_equity = equity
            day_trades = 0

        # Gestión de posición abierta: SL primero (conservador), luego TP
        if pos is not None:
            hit = None
            if pos["side"] == LONG:
                if lows[i] <= pos["sl"]:
                    hit = (pos["sl"], "sl")
                elif highs[i] >= pos["tp"]:
                    hit = (pos["tp"], "tp")
            else:
                if highs[i] >= pos["sl"]:
                    hit = (pos["sl"], "sl")
                elif lows[i] <= pos["tp"]:
                    hit = (pos["tp"], "tp")
            if hit:
                exit_price, reason = hit
                direction = 1 if pos["side"] == LONG else -1
                pnl = direction * (exit_price - pos["entry"]) * pos["units"]
                pnl -= spread_cost_price * pos["units"]
                pips = direction * (exit_price - pos["entry"]) / PIP - spread_pips
                equity += pnl
                trades.append(
                    BtTrade(
                        side=pos["side"],
                        entry_time=pos["time"],
                        exit_time=ts,
                        entry=pos["entry"],
                        exit=exit_price,
                        units=pos["units"],
                        pnl=pnl,
                        pips=pips,
                        reason=reason,
                    )
                )
                pos = None
                eq_times.append(ts)
                eq_values.append(equity)

        # Entrada: señal en la vela anterior, ejecutada al open de esta
        if pos is None and i > 0 and isinstance(signals.iloc[i - 1], str):
            side = signals.iloc[i - 1]
            if (
                entry_allowed(ts)
                and day_trades < risk.max_trades_per_day
                and (equity - day_start_equity) / day_start_equity > -risk.daily_loss_limit
            ):
                entry = opens[i]
                stop_distance = strategy_params.sl_atr_mult * d["atr"].iloc[i - 1]
                tp = d["bb_mid"].iloc[i - 1]
                units = size_position(equity, risk.risk_per_trade, stop_distance, risk.min_lot)
                # TP debe quedar del lado correcto tras el gap de apertura
                tp_valid = tp > entry if side == LONG else tp < entry
                if units > 0 and tp_valid:
                    sl = entry - stop_distance if side == LONG else entry + stop_distance
                    pos = {
                        "side": side,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "units": units,
                        "time": ts,
                    }
                    day_trades += 1

    # Cerrar posición pendiente al final del histórico
    if pos is not None:
        ts = idx[-1].to_pydatetime()
        last_close = float(d["close"].iloc[-1])
        direction = 1 if pos["side"] == LONG else -1
        pnl = direction * (last_close - pos["entry"]) * pos["units"] - spread_cost_price * pos["units"]
        equity += pnl
        trades.append(
            BtTrade(
                side=pos["side"],
                entry_time=pos["time"],
                exit_time=ts,
                entry=pos["entry"],
                exit=last_close,
                units=pos["units"],
                pnl=pnl,
                pips=direction * (last_close - pos["entry"]) / PIP - spread_pips,
                reason="end",
            )
        )
        eq_times.append(ts)
        eq_values.append(equity)

    curve = pd.Series(eq_values, index=pd.DatetimeIndex(eq_times), dtype=float)
    return BacktestResult(trades=trades, equity_curve=curve, initial_equity=initial_equity)


def load_csv(path: str | Path) -> pd.DataFrame:
    """Carga velas desde CSV genérico (time,open,high,low,close) o HistData M1
    (``YYYYMMDD HHMMSS;O;H;L;C;V``) y las devuelve en m15 UTC."""
    path = Path(path)
    sample = path.read_text(encoding="utf-8", errors="ignore")[:200]
    if ";" in sample.splitlines()[0]:
        df = pd.read_csv(
            path,
            sep=";",
            header=None,
            names=["time", "open", "high", "low", "close", "volume"],
        )
        df["time"] = pd.to_datetime(df["time"], format="%Y%m%d %H%M%S")
    else:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    ohlc = df[["open", "high", "low", "close"]].astype(float)
    if len(ohlc) > 1 and (ohlc.index[1] - ohlc.index[0]) < pd.Timedelta(minutes=15):
        ohlc = (
            ohlc.resample("15min")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
    return ohlc
