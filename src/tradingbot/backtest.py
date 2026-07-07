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
            # None cuando no hay pérdidas (PF sería infinito y no es JSON-válido)
            "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else None,
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


# Timeframes soportados y su frecuencia pandas
TF_FREQ = {"m1": "1min", "m5": "5min", "m15": "15min", "m30": "30min",
           "h1": "1h", "h4": "4h", "d1": "1D"}


def synthetic_df(
    days: int = 365,
    seed: int = 42,
    timeframe: str = "m15",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> pd.DataFrame:
    """Random walk para probar el pipeline. NO representa el mercado real.

    Con ``date_from``/``date_to`` genera ese rango exacto; si no, ``days``
    hacia atrás desde ahora. La volatilidad por vela escala con √minutos.
    """
    from datetime import timezone as _tz

    freq = TF_FREQ.get(timeframe, "15min")
    bar_minutes = pd.Timedelta(freq).total_seconds() / 60
    if date_from is not None and date_to is not None:
        idx = pd.date_range(start=date_from, end=date_to, freq=freq)
    else:
        n = max(int(days * 24 * 60 / bar_minutes), 50)
        idx = pd.date_range(end=datetime.now(_tz.utc), periods=n, freq=freq)
    n = len(idx)
    if n < 30:
        raise ValueError("Rango demasiado corto para el timeframe elegido")
    rng = np.random.default_rng(seed)
    vol = 0.00035 * (bar_minutes / 15) ** 0.5
    steps = rng.normal(0, vol, n) + 0.000002 * np.sin(np.arange(n) / 200)
    close = 1.08 + np.cumsum(steps)
    high = close + np.abs(rng.normal(0, vol * 0.6, n))
    low = close - np.abs(rng.normal(0, vol * 0.6, n))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def download_history(
    broker,
    date_from: datetime,
    date_to: datetime,
    timeframe: str = "m15",
    cache_dir: Optional[Path] = None,
    progress=None,
) -> pd.DataFrame:
    """Descarga histórico de FXCM por trozos de 90 días; cachea en CSV.

    ``progress`` es un callback opcional ``fn(str)`` para reportar avance.
    """
    from datetime import timedelta

    chunks = []
    cursor = date_from
    while cursor < date_to:
        chunk_end = min(cursor + timedelta(days=90), date_to)
        if progress:
            progress(f"Descargando {cursor:%Y-%m-%d} → {chunk_end:%Y-%m-%d}")
        chunks.append(
            broker.get_candles(count=0, date_from=cursor, date_to=chunk_end, timeframe=timeframe)
        )
        cursor = chunk_end
    df = pd.concat(chunks)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_dir / f"eurusd_{timeframe}_{date_from:%Y%m%d}_{date_to:%Y%m%d}.csv")
    return df[["open", "high", "low", "close"]]


def load_csv(path: str | Path, timeframe: str = "m15") -> pd.DataFrame:
    """Carga velas desde CSV genérico (time,open,high,low,close) o HistData M1
    (``YYYYMMDD HHMMSS;O;H;L;C;V``) y las devuelve en el timeframe pedido (UTC).
    Si el CSV es más fino que el timeframe, re-muestrea; si es más grueso, se
    usa tal cual (no se puede inventar detalle)."""
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
    freq = TF_FREQ.get(timeframe, "15min")
    if len(ohlc) > 1 and (ohlc.index[1] - ohlc.index[0]) < pd.Timedelta(freq):
        ohlc = (
            ohlc.resample(freq)
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
    return ohlc
