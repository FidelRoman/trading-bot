"""Dashboard web: FastAPI + WebSocket sobre el engine.

Arranque: si hay credenciales FXCM en .env usa el bróker real (Demo/Real según
FXCM_CONNECTION); si faltan credenciales o MOCK=1, usa el bróker simulado para
poder ver el dashboard y probar el pipeline sin cuenta.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import load_settings
from ..engine import BotEngine
from ..store import Store
from ..strategy import add_indicators

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class WsHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def add(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        msg = json.dumps(payload, default=str)
        for ws in self._clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)

    @property
    def busy(self) -> bool:
        return bool(self._clients)


def _make_broker(settings):
    if os.getenv("MOCK") == "1" or not settings.fxcm.user:
        from ..mock import MockBroker

        log.warning("Sin credenciales FXCM (o MOCK=1): usando bróker SIMULADO")
        return MockBroker()
    from ..broker import FxcmBroker

    return FxcmBroker(settings.fxcm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    store = Store(settings.db_path)
    broker = _make_broker(settings)
    engine = BotEngine(broker, store, settings)
    hub = WsHub()

    async def on_event(kind: str, data: dict) -> None:
        await hub.broadcast({"type": kind, **data})
        await hub.broadcast({"type": "status", "status": engine.status()})

    engine.on_event = on_event
    app.state.engine = engine
    app.state.store = store
    app.state.broker = broker
    app.state.hub = hub

    engine_task = asyncio.create_task(engine.run())

    async def price_pump() -> None:
        while True:
            try:
                if hub.busy and broker.connected:
                    prices = await asyncio.to_thread(broker.current_prices)
                    open_trades = await asyncio.to_thread(broker.open_trades)
                    floating = sum(t.get("gross_pl", 0.0) for t in open_trades)
                    await hub.broadcast(
                        {
                            "type": "tick",
                            "prices": prices,
                            "floating_pl": round(floating, 2),
                            "positions": open_trades,
                        }
                    )
            except Exception:
                log.exception("price_pump")
            await asyncio.sleep(2)

    pump_task = asyncio.create_task(price_pump())
    try:
        yield
    finally:
        engine.stop()
        pump_task.cancel()
        engine_task.cancel()
        await asyncio.gather(engine_task, pump_task, return_exceptions=True)
        await asyncio.to_thread(broker.disconnect)


app = FastAPI(title="EUR/USD Bollinger Bot", lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    return app.state.engine.status()


VALID_TF = {"m5", "m15", "m30", "h1", "h4"}


@app.get("/api/candles")
async def candles(count: int = 200, tf: str = "m15"):
    tf = tf if tf in VALID_TF else "m15"
    params = app.state.engine.strategy_params()
    df = await asyncio.to_thread(
        lambda: app.state.broker.get_candles(count + params.bb_period, timeframe=tf)
    )
    if df.empty:
        return {"candles": [], "bands": []}
    d = add_indicators(df, params)
    d = d.tail(count)
    ts = [int(t.timestamp()) for t in d.index]
    candles_out = [
        {"time": t, "open": round(o, 5), "high": round(h, 5), "low": round(l, 5), "close": round(c, 5)}
        for t, o, h, l, c in zip(ts, d["open"], d["high"], d["low"], d["close"])
    ]
    bands = [
        {"time": t, "upper": round(u, 5), "mid": round(m, 5), "lower": round(lo, 5)}
        for t, u, m, lo in zip(ts, d["bb_upper"], d["bb_mid"], d["bb_lower"])
        if u == u  # descarta NaN del warm-up
    ]
    return {"candles": candles_out, "bands": bands}


@app.get("/api/trades")
async def trades(limit: int = 50):
    return app.state.store.recent_trades(limit)


@app.get("/api/equity")
async def equity():
    return app.state.store.equity_curve()


@app.get("/api/logs")
async def logs(limit: int = 80):
    return app.state.store.recent_logs(limit)


@app.post("/api/control/{action}")
async def control(action: str):
    engine: BotEngine = app.state.engine
    if action == "pause":
        engine.pause()
    elif action == "resume":
        engine.resume()
    else:
        return {"ok": False, "error": "acción inválida"}
    status = engine.status()
    await app.state.hub.broadcast({"type": "status", "status": status})
    return {"ok": True, "status": status}


@app.get("/api/settings")
async def get_settings():
    return app.state.engine.current_settings()


@app.post("/api/settings")
async def set_settings(payload: dict = Body(...)):
    result = app.state.engine.update_settings(payload)
    await app.state.hub.broadcast({"type": "status", "status": app.state.engine.status()})
    return {"ok": True, "settings": result}


@app.get("/api/positions")
async def positions():
    return await asyncio.to_thread(app.state.broker.open_trades)


@app.post("/api/manual/{side}")
async def manual(side: str, payload: dict = Body(...)):
    result = await asyncio.to_thread(
        app.state.engine.manual_order,
        side,
        float(payload.get("lots", 0.01)),
        float(payload.get("sl_pips", 0)),
        float(payload.get("tp_pips", 0)),
    )
    await app.state.hub.broadcast({"type": "status", "status": app.state.engine.status()})
    return result


@app.post("/api/close/{trade_id}")
async def close_position(trade_id: str):
    try:
        app.state.store.set_state("manual_close", trade_id)
        await asyncio.to_thread(app.state.broker.close_trade, trade_id)
        app.state.store.log("warn", f"Cierre manual del trade {trade_id} solicitado")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/close-all")
async def close_all():
    trades = await asyncio.to_thread(app.state.broker.open_trades)
    closed, errors = 0, []
    for t in trades:
        try:
            app.state.store.set_state("manual_close", t["trade_id"])
            await asyncio.to_thread(app.state.broker.close_trade, t["trade_id"])
            closed += 1
        except Exception as e:
            errors.append(str(e))
    if closed:
        app.state.store.log("warn", f"Cierre manual de {closed} posición(es) solicitado")
    return {"ok": not errors, "closed": closed, "errors": errors}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    hub: WsHub = app.state.hub
    await hub.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "status", "status": app.state.engine.status()}, default=str))
        while True:
            await ws.receive_text()  # keepalive del cliente; no esperamos comandos
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
