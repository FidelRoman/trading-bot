from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from tradingbot.config import StrategyParams
from tradingbot.strategy import (
    LONG,
    SHORT,
    add_indicators,
    compute_signals,
    entry_allowed,
    latest_signal,
    size_position,
    spread_ok,
)

P = StrategyParams()


def make_df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 00:00", periods=len(closes), freq="15min", tz="UTC")
    close = pd.Series(closes, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.0003,
            "low": close - 0.0003,
            "close": close,
        }
    )


def zigzag(n: int, base: float = 1.1000, amp: float = 0.00025) -> list[float]:
    return [base + (amp if i % 2 == 0 else -amp) for i in range(n)]


def test_long_signal_on_reentry_from_below():
    closes = zigzag(40) + [1.0950, 1.0985] + zigzag(5)
    df = make_df(closes)
    sigs = compute_signals(df, P)
    assert sigs.iloc[41] == LONG          # vela de re-entrada
    assert sigs.iloc[:40].isna().all()    # nada en la zona estable


def test_short_signal_on_reentry_from_above():
    closes = zigzag(40) + [1.1050, 1.1015] + zigzag(5)
    df = make_df(closes)
    sigs = compute_signals(df, P)
    assert sigs.iloc[41] == SHORT


def test_no_signal_without_band_breach():
    df = make_df(zigzag(60))
    assert compute_signals(df, P).isna().all()


def test_latest_signal_fields():
    closes = zigzag(40) + [1.0950, 1.0985]
    df = make_df(closes)
    sig = latest_signal(df, P)
    assert sig is not None and sig.side == LONG
    ind = add_indicators(df, P)
    assert sig.take_profit == pytest.approx(ind["bb_mid"].iloc[-1])
    assert sig.stop_distance == pytest.approx(P.sl_atr_mult * ind["atr"].iloc[-1])
    assert sig.take_profit > sig.ref_close  # TP de un largo queda arriba


def test_latest_signal_none_on_quiet_market():
    assert latest_signal(make_df(zigzag(60)), P) is None


@pytest.mark.parametrize(
    "ts,expected",
    [
        (datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc), True),    # martes normal
        (datetime(2026, 7, 10, 19, 0, tzinfo=timezone.utc), False),  # viernes 19:00
        (datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc), False),  # sábado
        (datetime(2026, 7, 12, 21, 0, tzinfo=timezone.utc), False),  # domingo pre-apertura
        (datetime(2026, 7, 12, 23, 0, tzinfo=timezone.utc), True),   # domingo tras apertura
        (datetime(2026, 7, 7, 21, 50, tzinfo=timezone.utc), False),  # rollover
    ],
)
def test_entry_allowed(ts, expected):
    assert entry_allowed(ts) is expected


def test_size_position():
    # 10k equity, 0.5% riesgo = 50 USD; SL de 10 pips -> 50/0.0010 = 50000
    assert size_position(10_000, 0.005, 0.0010, 1000) == 50_000
    assert size_position(100, 0.005, 0.0010, 1000) == 0      # no alcanza un micro-lote
    assert size_position(10_000, 0.005, 0.0, 1000) == 0      # SL inválido


def test_spread_ok():
    assert spread_ok(1.10000, 1.10012, 1.5)      # 1.2 pips
    assert not spread_ok(1.10000, 1.10020, 1.5)  # 2.0 pips


def test_indicators_no_lookahead():
    # Cambiar la última vela no puede alterar señales anteriores
    closes = zigzag(40) + [1.0950, 1.0985] + zigzag(5)
    a = compute_signals(make_df(closes), P)
    closes2 = closes[:-1] + [1.2000]
    b = compute_signals(make_df(closes2), P)
    assert a.iloc[:-1].astype(str).equals(b.iloc[:-1].astype(str))
