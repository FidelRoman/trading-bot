from tradingbot.config import load_settings
from tradingbot.engine import BotEngine
from tradingbot.store import Store


def make_engine(tmp_path):
    store = Store(tmp_path / "test.db")
    return BotEngine(broker=None, store=store, settings=load_settings())


def test_update_settings_clamps_to_bounds(tmp_path):
    eng = make_engine(tmp_path)
    result = eng.update_settings(
        {"bb_period": 999, "risk_per_trade": 0.5, "bb_std": 0.1, "max_trades_per_day": 0}
    )
    assert result["bb_period"] == 50          # tope superior
    assert result["risk_per_trade"] == 0.02   # máx. 2%
    assert result["bb_std"] == 1.0            # mínimo
    assert result["max_trades_per_day"] == 1  # mínimo


def test_update_settings_ignores_unknown_and_invalid(tmp_path):
    eng = make_engine(tmp_path)
    before = eng.current_settings()
    result = eng.update_settings({"desconocido": 123, "bb_period": "no-numérico"})
    assert "desconocido" not in result
    assert result["bb_period"] == before["bb_period"]


def test_settings_persist_in_store(tmp_path):
    eng = make_engine(tmp_path)
    eng.update_settings({"bb_period": 30, "risk_per_trade": 0.01})
    sp = eng.strategy_params()
    rp = eng.risk_params()
    assert sp.bb_period == 30
    assert rp.risk_per_trade == 0.01
    # y sobrevive a un engine nuevo sobre el mismo store
    eng2 = BotEngine(broker=None, store=eng.store, settings=load_settings())
    assert eng2.strategy_params().bb_period == 30
