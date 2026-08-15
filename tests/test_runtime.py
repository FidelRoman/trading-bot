"""Contratos del runtime local: persistencia del bróker en papel e idempotencia."""
from datetime import datetime, timezone

from tradingbot.config import DEFAULT_SPEC, load_settings
from tradingbot.engine import BotEngine
from tradingbot.mock import MockBroker
from tradingbot.store import Store


def test_mock_restaura_y_persiste_su_posicion():
    saved = []
    broker = MockBroker(
        persisted_state={"equity": 9_900.0, "position": 1000, "entry_price": 1.0},
        state_callback=saved.append,
    )
    broker.connect()
    broker.set_position(0)

    assert saved[-1]["position"] == 0
    assert saved[-1]["equity"] > 9_900.0


def test_run_once_no_repite_la_misma_vela(tmp_path, monkeypatch):
    monkeypatch.setattr(BotEngine, "_watch_position", lambda self: None)
    monkeypatch.setattr(BotEngine, "_maybe_snapshot_equity", lambda self: None)
    calls = []
    monkeypatch.setattr(BotEngine, "_candle_tick",
                        lambda self, boundary, candles=None: calls.append(boundary))

    class Broker:
        connected = True

    engine = BotEngine(Broker(), Store(tmp_path / "runtime.db"), load_settings())
    moment = datetime(2026, 8, 10, 12, 7, tzinfo=timezone.utc)

    import asyncio

    first = asyncio.run(engine.run_once(moment))
    second = asyncio.run(engine.run_once(moment))
    assert first["processed"] is True
    assert second == {
        "processed": False,
        "reason": "already_processed",
        "boundary": first["boundary"],
    }
    assert len(calls) == 1


def test_status_no_falla_si_el_broker_se_desconecta_al_leer_posicion(tmp_path):
    """El endpoint de estado debe sobrevivir a una caída entre dos lecturas."""
    class BrokerQueSeDesconecta:
        connected = True
        mode = "fxcm-demo"
        read_only = False
        spec = DEFAULT_SPEC
        instrument = DEFAULT_SPEC.symbol

        def account_info(self):
            return {"equity": 10_000.0}

        @property
        def position(self):
            raise RuntimeError("No hay sesión FXCM: llama a connect() primero")

    estado = BotEngine(
        BrokerQueSeDesconecta(), Store(tmp_path / "runtime.db"), load_settings()
    ).status()

    assert estado["connected"] is False
    assert estado["net_position"] == 0
