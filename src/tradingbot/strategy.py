"""Estrategia Bollinger de reversión a la media — funciones puras sobre pandas.

Contrato del DataFrame de velas: índice DatetimeIndex en UTC, columnas
``open, high, low, close`` (precios bid o mid, consistentes entre sí).
Todas las señales se evalúan sobre velas CERRADAS: la señal de la fila ``t``
usa solo información disponible al cierre de ``t`` (sin repintado).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Optional

import numpy as np
import pandas as pd

from .config import PIP, StrategyParams

LONG = "long"
SHORT = "short"


@dataclass(frozen=True)
class Signal:
    side: str            # LONG | SHORT
    time: datetime       # cierre de la vela que generó la señal
    ref_close: float     # cierre de esa vela
    take_profit: float   # banda media al momento de la señal
    stop_distance: float # distancia de SL en precio (sl_atr_mult * ATR)


def add_indicators(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    """Añade bb_upper/bb_mid/bb_lower, rsi y atr. Devuelve una copia."""
    out = df.copy()
    close = out["close"]
    
    # Bollinger Bands
    mid = close.rolling(p.bb_period).mean()
    std = close.rolling(p.bb_period).std(ddof=0)
    out["bb_mid"] = mid
    out["bb_upper"] = mid + p.bb_std * std
    out["bb_lower"] = mid - p.bb_std * std

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    gain_wilder = gain.ewm(alpha=1.0 / p.rsi_period, adjust=False).mean()
    loss_wilder = loss.ewm(alpha=1.0 / p.rsi_period, adjust=False).mean()
    rs = gain_wilder / loss_wilder.replace(0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs)).fillna(50)

    # ATR
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.ewm(alpha=1.0 / p.atr_period, adjust=False, min_periods=p.atr_period).mean()
    return out


def compute_signals(df: pd.DataFrame, p: StrategyParams) -> pd.Series:
    """Serie con LONG/SHORT/NaN por vela (vectorizado, para backtest).

    Bollinger: Largo si la anterior cerró bajo la banda inf y esta vuelve adentro.
    RSI: Largo si el RSI cruza hacia arriba de rsi_oversold.
    """
    d = df if "atr" in df.columns else add_indicators(df, p)
    
    if p.active_strategy == "rsi":
        rsi = d["rsi"]
        prev_rsi = rsi.shift(1)
        long_sig = (prev_rsi < p.rsi_oversold) & (rsi >= p.rsi_oversold)
        short_sig = (prev_rsi > p.rsi_overbought) & (rsi <= p.rsi_overbought)
    else:
        close, prev_close = d["close"], d["close"].shift(1)
        lower, prev_lower = d["bb_lower"], d["bb_lower"].shift(1)
        upper, prev_upper = d["bb_upper"], d["bb_upper"].shift(1)

        long_sig = (prev_close < prev_lower) & (close > lower) & (close < d["bb_mid"])
        short_sig = (prev_close > prev_upper) & (close < upper) & (close > d["bb_mid"])

        if p.min_band_width_pips > 0:
            wide = (upper - lower) / PIP >= p.min_band_width_pips
            long_sig &= wide
            short_sig &= wide

    out = pd.Series(np.nan, index=d.index, dtype=object)
    out[long_sig] = LONG
    out[short_sig] = SHORT
    return out


def latest_signal(df: pd.DataFrame, p: StrategyParams) -> Optional[Signal]:
    """Señal de la última vela cerrada del DataFrame, o None."""
    d = add_indicators(df, p)
    sigs = compute_signals(d, p)
    side = sigs.iloc[-1]
    last = d.iloc[-1]
    if not isinstance(side, str) or math.isnan(last["atr"]):
        return None
    ts = d.index[-1].to_pydatetime()
    ref_close = float(last["close"])
    stop_distance = float(p.sl_atr_mult * last["atr"])
    
    if p.active_strategy == "rsi":
        take_profit = ref_close + (1.5 * stop_distance) if side == LONG else ref_close - (1.5 * stop_distance)
    else:
        take_profit = float(last["bb_mid"])

    return Signal(
        side=side,
        time=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        ref_close=ref_close,
        take_profit=take_profit,
        stop_distance=stop_distance,
    )


def entry_allowed(ts: datetime) -> bool:
    """Filtro de sesión para ENTRADAS nuevas (las salidas siempre se permiten).

    Bloquea: sábado; domingo antes de 22:00 UTC (mercado cerrado); viernes
    desde 19:00 UTC (evitar cierre semanal); ventana de rollover diaria
    21:45–22:15 UTC (spreads amplios).
    """
    ts = ts.astimezone(timezone.utc)
    wd, t = ts.weekday(), ts.time()
    if wd == 5:  # sábado
        return False
    if wd == 6 and t < time(22, 0):  # domingo pre-apertura
        return False
    if wd == 4 and t >= time(19, 0):  # viernes tarde
        return False
    if time(21, 45) <= t < time(22, 15):  # rollover
        return False
    return True


def size_position(equity: float, risk_frac: float, stop_distance: float, min_lot: int) -> int:
    """Unidades a operar arriesgando ``risk_frac`` del equity con ese SL.

    Para EUR/USD con cuenta en USD la pérdida al tocar SL es
    ``units * stop_distance`` USD. Redondea hacia abajo a múltiplos de
    ``min_lot``; devuelve 0 si el riesgo no alcanza ni para un micro-lote.
    """
    if math.isnan(stop_distance) or stop_distance <= 0 or equity <= 0:
        return 0
    units = (equity * risk_frac) / stop_distance
    return int(units // min_lot) * min_lot


def spread_ok(bid: float, ask: float, max_spread_pips: float) -> bool:
    return (ask - bid) / PIP <= max_spread_pips
