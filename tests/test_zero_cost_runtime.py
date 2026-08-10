from datetime import datetime, timezone

from tradingbot.config import load_settings
from tradingbot.engine import BotEngine
from tradingbot.firestore_store import FirestoreStore
from tradingbot.paper_broker import PaperBroker
from tradingbot.store import Store


class Snapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Document:
    def __init__(self, collection, doc_id):
        self.collection = collection
        self.id = doc_id

    def get(self):
        return Snapshot(self.id, self.collection.rows.get(self.id))

    def set(self, data, **_kwargs):
        self.collection.rows[self.id] = dict(data)

    def update(self, data):
        self.collection.rows[self.id].update(data)


class Collection:
    def __init__(self):
        self.rows = {}

    def document(self, doc_id=None):
        return Document(self, doc_id or f"auto-{len(self.rows)}")

    def stream(self):
        return [Snapshot(key, value) for key, value in self.rows.items()]


class FirestoreClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, Collection())


def test_firestore_store_cubre_estado_trades_equity_y_logs(monkeypatch):
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", "test")
    store = FirestoreStore("free-project", client=FirestoreClient())
    store.set_state("running", True)
    assert store.get_state("running") is True

    row_id = store.open_trade("order-1", "long", 1000)
    store.link_trade(row_id, "trade-1", 1.08)
    assert store.current_open_trade()["trade_id"] == "trade-1"
    store.close_trade(row_id, 1.09, 10.0, 100.0, "manual")
    assert store.current_open_trade() is None
    assert store.stats()["net_pnl"] == 10.0

    store.snapshot_equity(10_010.0, 10_010.0)
    store.log("info", "tick")
    assert store.equity_curve()[0]["equity"] == 10_010.0
    assert store.recent_logs()[0]["message"] == "tick"


def test_firestore_store_persiste_y_cancela_comandos_de_apertura(monkeypatch):
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", "test")
    store = FirestoreStore("free-project", client=FirestoreClient())
    opening = store.enqueue_command("open", "Demo", {"side": "long", "lots": 0.01})
    closing = store.enqueue_command("close_all", "Demo", {})

    assert [row["id"] for row in store.queued_commands("Demo")] == [opening["id"], closing["id"]]
    assert store.cancel_pending_opens() == 1
    assert [row["kind"] for row in store.queued_commands("Demo")] == ["close_all"]

    store.start_command(closing["id"])
    store.finish_command(closing["id"], {"closed": 2})
    assert store.command_count("done") == 1


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
