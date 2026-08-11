"""Contratos del runtime local: persistencia del bróker en papel e idempotencia."""
from datetime import datetime, timezone

from tradingbot.config import load_settings
from tradingbot.engine import BotEngine
from tradingbot.paper_broker import PaperBroker
from tradingbot.store import Store


def test_paper_broker_restaura_y_persiste_su_posicion():
    saved = []
    broker = PaperBroker(
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
    monkeypatch.setattr(BotEngine, "_candle_tick", lambda self, boundary: calls.append(boundary))

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
