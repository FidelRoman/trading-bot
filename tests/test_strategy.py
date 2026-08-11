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

# Estos tests cubren las estrategias por regla que sirven de referencia;
# la estrategia por defecto del bot es FSRPPO, que no genera señales así.
P = StrategyParams(active_strategy="bollinger")


def make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 00:00", periods=len(closes), freq="15min", tz="UTC")
    close = pd.Series(closes, index=idx)
    df = pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.0003,
            "low": close - 0.0003,
            "close": close,
        }
    )
    if volumes is not None:
        df["volume"] = pd.Series(volumes, index=idx)
    return df


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


def test_size_position_con_multiplicador_de_contrato():
    # Un contrato que mueve 100 unidades de cuenta por unidad de precio necesita
    # 100 veces menos unidades para arriesgar lo mismo.
    assert size_position(10_000, 0.005, 0.0010, 1, contract_multiplier=100.0) == 500
    assert size_position(10_000, 0.005, 0.0010, 1, contract_multiplier=0.0) == 0


def test_spread_ok():
    assert spread_ok(1.10000, 1.10012, 1.5)      # 1.2 pips
    assert not spread_ok(1.10000, 1.10020, 1.5)  # 2.0 pips


def test_spread_relativo_admite_activos_no_forex():
    """El umbral en pips absolutos vetaba el 100% de oro, índices y acciones."""
    from tradingbot.config import INSTRUMENT_SEEDS, InstrumentSpec
    from tradingbot.strategy import spread_bps

    oro = INSTRUMENT_SEEDS["XAU/USD"]
    # 35 pips de oro a 2.400 son ~1,5 bps: caro en pips, normal en relativo.
    assert spread_bps(2400.00, 2400.35) < 2.0
    assert spread_ok(2400.00, 2400.35, max_spread_pips=1.5,
                     max_spread_bps=2.0, spec=oro)

    accion = InstrumentSpec("AAPL", pip=0.01, min_lot=1, typical_spread_pips=2.0,
                            asset_class="share", digits=2)
    assert spread_ok(200.00, 200.02, max_spread_pips=1.5,
                     max_spread_bps=2.0, spec=accion)
    # Un spread desbocado sigue vetado aunque sea otra clase de activo.
    assert not spread_ok(200.00, 201.00, max_spread_pips=1.5,
                         max_spread_bps=2.0, spec=accion)


def test_spread_en_divisas_mantiene_la_puerta_en_pips():
    """En divisas el umbral ya estaba afinado: no debe cambiar de comportamiento."""
    from tradingbot.config import INSTRUMENT_SEEDS

    eurusd = INSTRUMENT_SEEDS["EUR/USD"]
    assert spread_ok(1.10000, 1.10012, 1.5, 100.0, eurusd)       # 1,2 pips
    assert not spread_ok(1.10000, 1.10020, 1.5, 100.0, eurusd)   # 2,0 pips
    # Y la puerta relativa también aplica en divisas.
    assert not spread_ok(1.10000, 1.10012, 1.5, 0.5, eurusd)


def test_spread_bps_con_precio_invalido_no_revienta():
    from tradingbot.strategy import spread_bps

    assert spread_bps(0.0, 0.0) == float("inf")
    assert not spread_ok(0.0, 0.0, 1.5, 2.0)


def test_indicators_no_lookahead():
    # Cambiar la última vela no puede alterar señales anteriores
    closes = zigzag(40) + [1.0950, 1.0985] + zigzag(5)
    a = compute_signals(make_df(closes), P)
    closes2 = closes[:-1] + [1.2000]
    b = compute_signals(make_df(closes2), P)
    assert a.iloc[:-1].astype(str).equals(b.iloc[:-1].astype(str))


def test_wyckoff_long_signal():
    closes = [1.1000] * 20 + [1.1010]
    volumes = [100.0] * 20 + [200.0]
    p = StrategyParams(active_strategy="wyckoff_1", wyckoff_range_period=20, wyckoff_volume_mult=1.5)
    df = make_df(closes, volumes)
    sigs = compute_signals(df, p)
    assert sigs.iloc[-1] == LONG
    assert sigs.iloc[:-1].isna().all()


def test_wyckoff_short_signal():
    closes = [1.1000] * 20 + [1.0990]
    volumes = [100.0] * 20 + [200.0]
    p = StrategyParams(active_strategy="wyckoff_1", wyckoff_range_period=20, wyckoff_volume_mult=1.5)
    df = make_df(closes, volumes)
    sigs = compute_signals(df, p)
    assert sigs.iloc[-1] == SHORT
    assert sigs.iloc[:-1].isna().all()


def test_wyckoff_no_signal_low_volume():
    closes = [1.1000] * 20 + [1.1010]
    volumes = [100.0] * 20 + [110.0]
    p = StrategyParams(active_strategy="wyckoff_1", wyckoff_range_period=20, wyckoff_volume_mult=1.5)
    df = make_df(closes, volumes)
    sigs = compute_signals(df, p)
    assert sigs.iloc[-1] is np.nan


def test_fsrppo_no_genera_senales_por_regla():
    """Sin esta guarda, un backtest de FSRPPO devolvería señales de Bollinger.

    FSRPPO decide con una política entrenada (rl/policy.py), no con una regla
    sobre indicadores, así que pedirle señales tiene que fallar en vez de caer
    silenciosamente en la rama por defecto.
    """
    df = make_df([1.10 + 0.0001 * i for i in range(60)])
    with pytest.raises(ValueError, match="no genera señales"):
        compute_signals(df, StrategyParams(active_strategy="fsrppo"))
