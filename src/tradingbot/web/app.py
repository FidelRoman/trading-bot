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

from fastapi import Body, FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import load_settings
from ..engine import BotEngine
from ..store import Store
from ..strategy import add_indicators
from .backtest_job import UPLOAD_CSV, BacktestJob

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
    app.state.backtest = BacktestJob(store, engine, broker)

    engine_task = asyncio.create_task(engine.run())

    async def price_pump() -> None:
        while True:
            try:
                # Leer siempre app.state.broker: puede cambiar en caliente
                # al editar credenciales desde la interfaz
                broker = app.state.broker
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
        await asyncio.to_thread(app.state.broker.disconnect)


app = FastAPI(title="EUR/USD Bollinger Bot", lifespan=lifespan)

# El frontend Next.js corre en otro puerto en desarrollo (localhost únicamente)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/credentials")
async def get_credentials():
    """Estado de las credenciales. NUNCA devuelve la contraseña."""
    import os

    broker = app.state.broker
    mode = getattr(broker, "mode", "simulado")
    account = {}
    if broker.connected and mode != "simulado":
        try:
            account = await asyncio.to_thread(broker.account_info)
        except Exception:
            pass
    return {
        "user": os.getenv("FXCM_USER", ""),
        "has_password": bool(os.getenv("FXCM_PASS", "")),
        "connection": os.getenv("FXCM_CONNECTION", "Demo"),
        "mode": mode,
        "connected": broker.connected,
        "is_real": mode == "fxcm-real",
        "account_id": account.get("account_id"),
        "balance": account.get("balance"),
    }


@app.post("/api/credentials")
async def set_credentials(payload: dict = Body(...)):
    """Guarda credenciales en .env, valida con login real y hace swap del
    bróker en caliente. connection="auto" prueba Demo y luego Real; si la
    cuenta resulta ser REAL, el bot queda pausado automáticamente."""
    import os

    from ..broker import FxcmBroker
    from ..config import FxcmCredentials, update_env_file

    user = str(payload.get("user", "")).strip()
    password = str(payload.get("password", "")).strip()
    connection = str(payload.get("connection", "auto"))
    if connection not in ("auto", "Demo", "Real"):
        return {"ok": False, "error": "Conexión inválida"}

    # Contraseña vacía = conservar la actual
    if not password:
        password = os.getenv("FXCM_PASS", "")
    if not user or not password:
        return {"ok": False, "error": "Usuario y contraseña son obligatorios"}

    url = os.getenv("FXCM_URL", "http://www.fxcorporate.com/Hosts.jsp")
    attempts = ["Demo", "Real"] if connection == "auto" else [connection]
    new_broker = None
    used_connection = None
    errors: list[str] = []
    for conn in attempts:
        candidate = FxcmBroker(FxcmCredentials(user=user, password=password, connection=conn, url=url))
        try:
            await asyncio.to_thread(candidate.connect)
            new_broker = candidate
            used_connection = conn
            break
        except Exception as e:
            errors.append(f"{conn}: {e}")
    if new_broker is None:
        return {"ok": False, "error": "Login fallido — " + " | ".join(errors)}

    # Persistir y hacer swap en caliente
    update_env_file({"FXCM_USER": user, "FXCM_PASS": password, "FXCM_CONNECTION": used_connection})
    os.environ.update(
        {"FXCM_USER": user, "FXCM_PASS": password, "FXCM_CONNECTION": used_connection}
    )
    old = app.state.broker
    app.state.broker = new_broker
    app.state.engine.broker = new_broker
    app.state.backtest.broker = new_broker
    try:
        await asyncio.to_thread(old.disconnect)
    except Exception:
        pass

    is_real = used_connection == "Real"
    if is_real:
        # Cuenta con dinero real: el bot nunca arranca solo
        app.state.engine.pause()
        app.state.store.log(
            "warn",
            "CUENTA REAL conectada — bot pausado automáticamente; actívalo solo con una estrategia validada",
        )
    else:
        app.state.store.log("info", f"Credenciales actualizadas: cuenta {used_connection}")

    info = await asyncio.to_thread(new_broker.account_info)
    await app.state.hub.broadcast({"type": "status", "status": app.state.engine.status()})
    return {
        "ok": True,
        "connection": used_connection,
        "is_real": is_real,
        "account_id": info.get("account_id"),
        "balance": info.get("balance"),
        "paused": app.state.engine.status()["paused"],
    }


@app.get("/api/backtest")
async def backtest_state():
    return app.state.backtest.state()


BACKTEST_TF = {"m5", "m15", "m30", "h1", "h4", "d1"}


@app.post("/api/backtest")
async def backtest_start(payload: dict = Body(...)):
    from datetime import datetime, timedelta, timezone

    job: BacktestJob = app.state.backtest
    source = str(payload.get("source", "synthetic"))
    timeframe = str(payload.get("timeframe", "m15")).lower()
    if timeframe not in BACKTEST_TF:
        return {"ok": False, "error": f"Timeframe inválido: {timeframe}"}
    equity = max(100.0, float(payload.get("equity", 10_000)))
    spread = max(0.0, min(float(payload.get("spread_pips", 1.2)), 10.0))

    now = datetime.now(timezone.utc)
    try:
        raw_from = payload.get("date_from")
        raw_to = payload.get("date_to")
        date_from = (
            datetime.fromisoformat(raw_from).replace(tzinfo=timezone.utc)
            if raw_from
            else now - timedelta(days=730)
        )
        date_to = (
            datetime.fromisoformat(raw_to).replace(tzinfo=timezone.utc)
            + timedelta(hours=23, minutes=59)
            if raw_to
            else now
        )
    except ValueError:
        return {"ok": False, "error": "Fechas inválidas (formato AAAA-MM-DD)"}
    date_to = min(date_to, now)
    if date_from >= date_to:
        return {"ok": False, "error": "La fecha inicial debe ser anterior a la final"}
    if (date_to - date_from).days > 365 * 5:
        return {"ok": False, "error": "Rango máximo: 5 años"}

    if not job.start_allowed():
        return {"ok": False, "error": "Ya hay un backtest en ejecución"}

    async def _runner():
        await asyncio.to_thread(job.run_sync, source, timeframe, date_from, date_to, equity, spread)
        await app.state.hub.broadcast({"type": "backtest"})

    asyncio.create_task(_runner())
    return {"ok": True}


@app.post("/api/backtest/csv")
async def backtest_upload(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return {"ok": False, "error": "El archivo debe ser .csv"}
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        return {"ok": False, "error": "CSV demasiado grande (máx. 50 MB)"}
    UPLOAD_CSV.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_CSV.write_bytes(data)
    app.state.store.log("info", f"CSV subido para backtest: {file.filename} ({len(data) // 1024} KB)")
    return {"ok": True, "filename": file.filename, "kb": len(data) // 1024}


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
