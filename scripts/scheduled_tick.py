"""Ejecuta una evaluacion idempotente y publica el snapshot para Vercel."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.config import load_settings  # noqa: E402
from tradingbot.engine import BotEngine  # noqa: E402
from tradingbot.paper_broker import PaperBroker  # noqa: E402
from tradingbot.store import create_store  # noqa: E402
from tradingbot.strategy import add_indicators  # noqa: E402


def _broker(settings, store):
    from tradingbot.broker import FxcmBroker

    return PaperBroker(
        price_source=FxcmBroker(settings.fxcm, read_only=True),
        persisted_state=store.get_state("paper_broker", {}),
        state_callback=lambda value: store.set_state("paper_broker", value),
    )


def _candles_payload(broker, engine, timeframe):
    frame = broker.get_candles(count=220, timeframe=timeframe)
    params = engine.strategy_params()
    enriched = add_indicators(frame, params).tail(200)
    timestamps = [int(value.timestamp()) for value in enriched.index]
    candles = [
        {
            "time": timestamp,
            "open": round(float(row.open), 5),
            "high": round(float(row.high), 5),
            "low": round(float(row.low), 5),
            "close": round(float(row.close), 5),
        }
        for timestamp, row in zip(timestamps, enriched.itertuples())
    ]
    bands = []
    for timestamp, row in zip(timestamps, enriched.itertuples()):
        upper = getattr(row, "bb_upper", float("nan"))
        if upper == upper:
            bands.append(
                {
                    "time": timestamp,
                    "upper": round(float(upper), 5),
                    "mid": round(float(row.bb_mid), 5),
                    "lower": round(float(row.bb_lower), 5),
                }
            )
    return {"candles": candles, "bands": bands}


async def run():
    settings = load_settings()
    settings.fxcm.validate()
    store = create_store(settings.db_path)
    broker = _broker(settings, store)
    engine = BotEngine(broker, store, settings)
    try:
        broker.connect()
        if store.get_state("force_flatten", False):
            broker.set_position(0)
            store.set_state("force_flatten", False)
            store.log("warn", "Posicion paper cerrada por solicitud remota")

        result = await engine.run_once()
        snapshot = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tick": result,
            "status": engine.status(),
            "prices": broker.current_prices(),
            "positions": broker.open_trades(),
            "candles": {
                timeframe: _candles_payload(broker, engine, timeframe)
                for timeframe in ("m5", "m15", "h1", "h4")
            },
        }
        store.set_state("runtime_snapshot", snapshot)
        print(result)
    finally:
        broker.disconnect()
        store.close()


if __name__ == "__main__":
    asyncio.run(run())
