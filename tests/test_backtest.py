from datetime import timezone

import pandas as pd
import pytest

from tradingbot.backtest import run_backtest, synthetic_df
from tradingbot.config import PIP, RiskParams, StrategyParams
from tradingbot.strategy import add_indicators, size_position

P = StrategyParams()
R = RiskParams(risk_per_trade=0.005, daily_loss_limit=0.03, max_trades_per_day=4,
               max_spread_pips=1.5, min_lot=1000)
EQ0 = 10_000.0
SPREAD = 1.2


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


def long_scenario_df() -> pd.DataFrame:
    # dip bajo la banda inferior (bar 40), re-entrada (bar 41 = señal),
    # entrada al open del bar 42, y subida que toca la banda media (TP)
    closes = zigzag(40) + [1.0950, 1.0985] + [1.1000, 1.1005, 1.1005, 1.1005]
    return make_df(closes)


def test_entry_at_next_open_and_tp_exit():
    df = long_scenario_df()
    res = run_backtest(df, P, R, initial_equity=EQ0, spread_pips=SPREAD)
    assert len(res.trades) == 1
    t = res.trades[0]
    ind = add_indicators(df, P)
    assert t.side == "long"
    assert t.entry == pytest.approx(float(df["open"].iloc[42]))   # open del bar siguiente a la señal
    assert t.exit == pytest.approx(float(ind["bb_mid"].iloc[41])) # TP = banda media del bar de señal
    assert t.reason == "tp"
    assert t.entry_time == df.index[42].to_pydatetime()


def test_spread_cost_deducted():
    df = long_scenario_df()
    res = run_backtest(df, P, R, initial_equity=EQ0, spread_pips=SPREAD)
    t = res.trades[0]
    raw = (t.exit - t.entry) * t.units
    assert t.pnl == pytest.approx(raw - SPREAD * PIP * t.units)
    assert t.pips == pytest.approx((t.exit - t.entry) / PIP - SPREAD, abs=0.01)
    assert res.equity_curve.iloc[-1] == pytest.approx(EQ0 + t.pnl)


def test_position_sized_by_risk():
    df = long_scenario_df()
    res = run_backtest(df, P, R, initial_equity=EQ0, spread_pips=SPREAD)
    t = res.trades[0]
    ind = add_indicators(df, P)
    stop_distance = P.sl_atr_mult * float(ind["atr"].iloc[41])
    assert t.units == size_position(EQ0, R.risk_per_trade, stop_distance, R.min_lot)
    assert t.units % R.min_lot == 0


def test_sl_first_when_both_hit_same_candle():
    df = long_scenario_df()
    # bar 43 barre 100 pips en ambas direcciones: toca SL y TP en la misma vela
    df.iloc[43, df.columns.get_loc("high")] = 1.1100
    df.iloc[43, df.columns.get_loc("low")] = 1.0850
    res = run_backtest(df, P, R, initial_equity=EQ0, spread_pips=SPREAD)
    assert len(res.trades) == 1
    t = res.trades[0]
    ind = add_indicators(df, P)
    expected_sl = float(df["open"].iloc[42]) - P.sl_atr_mult * float(ind["atr"].iloc[41])
    assert t.reason == "sl"                      # conservador: SL antes que TP
    assert t.exit == pytest.approx(expected_sl)
    assert t.pnl < 0


def test_no_trades_on_quiet_market():
    res = run_backtest(make_df(zigzag(120)), P, R, initial_equity=EQ0)
    s = res.summary()
    assert s["trades"] == 0
    assert s["net_profit"] == 0.0
    assert len(res.equity_curve) == 0


def test_synthetic_pipeline_runs():
    df = synthetic_df(days=30, seed=1)
    res = run_backtest(df, P, R, initial_equity=EQ0)
    s = res.summary()
    assert s["trades"] > 0
    assert "profit_factor" in s and "max_drawdown_pct" in s
    # el equity final debe cuadrar con la suma de P&L
    assert res.equity_curve.iloc[-1] == pytest.approx(EQ0 + s["net_profit"], abs=0.01)


def test_wyckoff_backtest_execution():
    closes = [1.1000] * 20 + [1.1010] + [1.1015, 1.1020, 1.1025]
    volumes = [100.0] * 20 + [200.0] + [100.0, 100.0, 100.0]
    idx = pd.date_range("2026-01-05 00:00", periods=len(closes), freq="15min", tz="UTC")
    close = pd.Series(closes, index=idx)
    df = pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.0003,
            "low": close - 0.0003,
            "close": close,
            "volume": pd.Series(volumes, index=idx),
        }
    )
    p = StrategyParams(active_strategy="wyckoff_1", wyckoff_range_period=20, wyckoff_volume_mult=1.5, wyckoff_tp_mult=2.0)
    res = run_backtest(df, p, R, initial_equity=EQ0, spread_pips=SPREAD)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.side == "long"
    assert t.entry == pytest.approx(df["open"].iloc[21])
    assert t.reason in ("tp", "end")
