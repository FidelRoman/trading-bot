"""Dashboard web: FastAPI + WebSocket sobre el engine.

Sirve también la interfaz Next.js exportada a estático (``web-ui/out``), de modo
que UI, ``/api/*`` y ``/ws`` comparten un único origen y un único puerto: basta
exponer ese puerto para acceder desde fuera.

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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import PROJECT_ROOT, load_settings
from ..engine import BotEngine
from ..store import Store
from ..strategy import add_indicators
from .backtest_job import UPLOAD_CSV, BacktestJob
from .auth import allowed_origins
from .training_job import TrainingJob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# Export estático de Next (`cd web-ui && npm run build`). Puede no existir aún.
UI_DIR = PROJECT_ROOT / "web-ui" / "out"


class WsHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def add(self, ws: WebSocket, subprotocol: str | None = None) -> None:
        await ws.accept(subprotocol=subprotocol)
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


def execution_mode() -> str:
    """``sim`` | ``live``, en orden creciente de consecuencias."""
    if os.getenv("MOCK") == "1":
        return "sim"
    from ..config import load_settings
    if not load_settings().fxcm.user:
        return "sim"
    return "live"


def _is_real_broker(broker) -> bool:
    return str(getattr(broker, "mode", "")).lower() == "fxcm-real"


def _real_acknowledged(payload: dict | None) -> bool:
    """Consentimiento explícito para una acción que mueve dinero real.

    No juzga ni restringe la estrategia o el modelo: únicamente impide que un
    cliente omita por accidente el destino Real que el operador decidió usar.
    """
    return isinstance(payload, dict) and payload.get("acknowledge_real") is True


async def _all_open_trades(broker) -> list[dict]:
    reader = getattr(broker, "all_open_trades", None) or broker.open_trades
    return await asyncio.to_thread(reader)


def _selected_symbol(store=None) -> str:
    """Instrumento elegido en la interfaz, o EUR/USD si no hay ninguno guardado."""
    from ..config import INSTRUMENT, normalize_symbol

    if store is None:
        return INSTRUMENT
    value = store.get_state("selected_instrument", None)
    symbol = value.get("symbol") if isinstance(value, dict) else value
    return normalize_symbol(symbol) if symbol else INSTRUMENT


def _spec_for(symbol, store=None):
    """Especificación del instrumento: catálogo descubierto o semilla.

    Nunca lanza: un símbolo que no resuelve cae en la semilla de EUR/USD para no
    impedir el arranque del backend.
    """
    from ..config import DEFAULT_SPEC, get_instrument_spec

    catalog = store.get_state("instrument_catalog", None) if store else None
    try:
        return get_instrument_spec(symbol, catalog)
    except ValueError:
        log.warning("Sin especificación para %s; se usa la de %s",
                    symbol, DEFAULT_SPEC.symbol)
        return DEFAULT_SPEC


def pause_if_real(engine, settings) -> bool:
    if settings.fxcm.connection != "Real":
        return False
    pausado = False
    if engine.running:
        engine.pause()
        pausado = True
    engine.store.log("warn", "CUENTA REAL en modo LIVE: bot pausado al arrancar; "
                             "actívalo a mano cuando quieras que opere")
    return pausado


def _make_broker(settings, store=None):
    from ..mock import MockBroker

    modo = execution_mode()
    symbol = _selected_symbol(store)

    if modo == "sim" or not settings.fxcm.user:
        log.warning("Modo SIM sobre %s: precios simulados y ejecución en papel", symbol)
        persisted = store.get_state("mock_broker", None) if store else None
        if not persisted and store:
            persisted = store.get_state("paper_broker", {})
        return MockBroker(
            persisted_state=persisted or {},
            state_callback=(lambda value: store.set_state("mock_broker", value)) if store else None,
            spec=_spec_for(symbol, store)
        )

    from ..broker import FxcmBroker

    log.warning("Modo LIVE sobre %s en cuenta %s: las órdenes son REALES",
                symbol, settings.fxcm.connection)
    return FxcmBroker(settings.fxcm, instrument=symbol)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    store = Store(settings.db_path)
    broker = _make_broker(settings, store)
    engine = BotEngine(broker, store, settings)

    pause_if_real(engine, settings)
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

    bucle = asyncio.get_running_loop()

    def notificar(payload: dict) -> None:
        # El job corre en un hilo: hay que volver al bucle de eventos para emitir.
        asyncio.run_coroutine_threadsafe(hub.broadcast(payload), bucle)

    app.state.training = TrainingJob(store, notify=notificar)
    app.state.reconfigure_lock = asyncio.Lock()

    app.state.engine_task = asyncio.create_task(engine.run())

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
        app.state.engine_task.cancel()
        await asyncio.gather(pump_task, app.state.engine_task, return_exceptions=True)
        await asyncio.to_thread(app.state.broker.disconnect)


app = FastAPI(title="FSRPPO·BOT — FXCM multi-instrumento", lifespan=lifespan)

# En producción la UI se sirve desde este mismo origen y CORS sobra. Hace falta
# para `next dev`, que sirve el frontend en otro puerto.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "ui_built": UI_DIR.is_dir()}


@app.get("/api/status")
async def status():
    return app.state.engine.status()


VALID_TF = {"m5", "m15", "m30", "h1", "h4", "d1"}


@app.get("/api/candles")
async def candles(count: int = 200, tf: str = "m15"):
    tf = tf if tf in VALID_TF else "m15"
    params = app.state.engine.strategy_params()
    max_period = max(params.bb_period, getattr(params, "wyckoff_range_period", 20))
    df = await asyncio.to_thread(
        lambda: app.state.broker.get_candles(count + max_period, timeframe=tf)
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
    if params.active_strategy == "wyckoff_1":
        bands = [
            {"time": t, "upper": round(u, 5), "mid": round((u + lo) / 2, 5), "lower": round(lo, 5)}
            for t, u, lo in zip(ts, d["wyckoff_r_high"], d["wyckoff_r_low"])
            if u == u  # descarta NaN
        ]
    else:
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
async def control(action: str, payload: dict = Body(default={})):
    engine: BotEngine = app.state.engine
    if action == "pause":
        engine.pause()
    elif action == "resume":
        if _is_real_broker(app.state.broker) and not _real_acknowledged(payload):
            return {
                "ok": False,
                "error": "Confirma explícitamente que deseas iniciar el bot en cuenta Real",
                "requires_real_ack": True,
            }
        if _is_real_broker(app.state.broker):
            engine.store.log(
                "warn",
                "OPERADOR CONFIRMÓ INICIO EN REAL; el rendimiento del modelo o estrategia no se usa como bloqueo",
            )
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
    if _is_real_broker(app.state.broker) and not _real_acknowledged(payload):
        return {
            "ok": False,
            "error": "Confirma explícitamente que la orden manual se enviará a cuenta Real",
            "requires_real_ack": True,
        }
    try:
        lots = float(payload.get("lots", 0.01))
        sl_pips = float(payload.get("sl_pips", 0))
        tp_pips = float(payload.get("tp_pips", 0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Lotes, SL y TP deben ser números válidos"}
    result = await asyncio.to_thread(
        app.state.engine.manual_order,
        side,
        lots,
        sl_pips,
        tp_pips,
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
        "has_demo": bool(os.getenv("FXCM_USER_DEMO") and os.getenv("FXCM_PASS_DEMO")) or bool(os.getenv("FXCM_USER") and os.getenv("FXCM_PASS")),
        "has_real": bool(os.getenv("FXCM_USER_REAL") and os.getenv("FXCM_PASS_REAL")),
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
    async with app.state.reconfigure_lock:
        return await _set_credentials_locked(payload)


async def _set_credentials_locked(payload: dict):
    import os

    from ..broker import FxcmBroker
    from ..config import FxcmCredentials, Settings, db_path_for_connection, update_env_file

    if app.state.engine.running:
        return {"ok": False, "error": "Detén el bot antes de cambiar de cuenta o credenciales"}
    try:
        abiertas = await _all_open_trades(app.state.broker)
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo verificar que la cuenta esté plana: {exc}"}
    if abiertas:
        return {
            "ok": False,
            "error": "Cierra todas las posiciones de la cuenta antes de cambiar credenciales",
            "open_positions": len(abiertas),
        }

    user = str(payload.get("user", "")).strip()
    password = str(payload.get("password", "")).strip()
    connection = str(payload.get("connection", "auto"))
    if connection not in ("auto", "Demo", "Real"):
        return {"ok": False, "error": "Conexión inválida"}

    if not user and not password and connection in ("Demo", "Real"):
        if connection == "Demo":
            user = os.getenv("FXCM_USER_DEMO") or os.getenv("FXCM_USER", "")
            password = os.getenv("FXCM_PASS_DEMO") or os.getenv("FXCM_PASS", "")
        else:
            user = os.getenv("FXCM_USER_REAL") or os.getenv("FXCM_USER", "")
            password = os.getenv("FXCM_PASS_REAL") or os.getenv("FXCM_PASS", "")
        if not user or not password:
            return {"ok": False, "error": f"No hay credenciales guardadas para la cuenta {connection}"}
    else:
        if not password:
            password = os.getenv("FXCM_PASS", "")
        if not user or not password:
            return {"ok": False, "error": "Usuario y contraseña son obligatorios"}

    url = os.getenv("FXCM_URL", "https://www.fxcorporate.com/Hosts.jsp")
    attempts = ["Demo", "Real"] if connection == "auto" else [connection]
    new_broker = None
    used_connection = None
    errors: list[str] = []
    for conn in attempts:
        candidate = FxcmBroker(
            FxcmCredentials(user=user, password=password, connection=conn, url=url),
            instrument=_selected_symbol(app.state.store),
        )
        try:
            await asyncio.to_thread(candidate.connect)
            new_broker = candidate
            used_connection = conn
            break
        except Exception as e:
            errors.append(f"{conn}: {e}")
    if new_broker is None:
        return {"ok": False, "error": "Login fallido — " + " | ".join(errors)}

    if used_connection == "Real" and not _real_acknowledged(payload):
        try:
            await asyncio.to_thread(new_broker.disconnect)
        finally:
            return {
                "ok": False,
                "error": "La conexión resolvió a Real; selecciónala y confirma explícitamente el uso de dinero real",
                "requires_real_ack": True,
            }

    credentials = FxcmCredentials(
        user=user, password=password, connection=str(used_connection), url=url
    )
    new_settings = Settings(
        fxcm=credentials,
        db_path=db_path_for_connection(str(used_connection), mock=False),
    )
    old_store = app.state.store
    try:
        new_store = (
            old_store
            if str(old_store.path) == str(new_settings.db_path)
            else Store(new_settings.db_path)
        )
    except Exception as exc:
        await asyncio.to_thread(new_broker.disconnect)
        return {"ok": False, "error": f"No se pudo abrir la base de datos de la cuenta: {exc}"}

    # Persistir y hacer swap en caliente
    env_updates = {"FXCM_USER": user, "FXCM_PASS": password, "FXCM_CONNECTION": used_connection}
    if used_connection == "Demo":
        env_updates["FXCM_USER_DEMO"] = user
        env_updates["FXCM_PASS_DEMO"] = password
    elif used_connection == "Real":
        env_updates["FXCM_USER_REAL"] = user
        env_updates["FXCM_PASS_REAL"] = password
    # Detener el loop durante el cambio evita que use un Store cerrado o mezcle
    # el bróker anterior con el nuevo. La ejecución se reinicia ya pausada.
    app.state.engine_task.cancel()
    await asyncio.gather(app.state.engine_task, return_exceptions=True)

    try:
        update_env_file(env_updates)
    except Exception as exc:
        app.state.engine_task = asyncio.create_task(app.state.engine.run())
        if new_store is not old_store:
            new_store.close()
        await asyncio.to_thread(new_broker.disconnect)
        return {"ok": False, "error": f"No se pudieron persistir las credenciales: {exc}"}
    os.environ.update(env_updates)

    # Re-crear referencias al Store del nuevo modo si cambió.
    if new_store is not old_store:
        # Swap store references
        app.state.store = new_store
        app.state.engine.store = new_store
        app.state.backtest.store = new_store
        
        # Close old db
        old_store.close()

    # El candidato ya se conectó con el instrumento seleccionado: reutilizarlo
    # elimina un segundo login que podía fallar después de persistir credenciales.
    old = app.state.broker
    definitivo = new_broker
    app.state.broker = definitivo
    app.state.engine.broker = definitivo
    app.state.engine.s = new_settings
    app.state.backtest.broker = definitivo
    app.state.engine.reset_policy()
    try:
        await asyncio.to_thread(old.disconnect)
    except Exception:
        pass
    new_broker = definitivo

    is_real = used_connection == "Real"
    # Todo cambio de cuenta termina pausado, pero no congelado: el operador puede
    # iniciarlo inmediatamente. En Real no se valida ni restringe el modelo.
    app.state.engine.pause()
    if is_real:
        app.state.store.log(
            "warn",
            "CUENTA REAL conectada — bot pausado tras el cambio; el operador puede iniciarlo bajo su responsabilidad",
        )
    else:
        app.state.store.log("info", f"Credenciales actualizadas: cuenta {used_connection}")

    app.state.engine_task = asyncio.create_task(app.state.engine.run())

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

    strategy = payload.get("strategy")
    if strategy and strategy not in ("bollinger", "rsi", "wyckoff_1"):
        return {"ok": False, "error": f"Estrategia inválida: {strategy}"}

    strategy_params = payload.get("strategy_params")
    risk_per_trade = payload.get("risk_per_trade")
    if risk_per_trade is not None:
        try:
            risk_per_trade = float(risk_per_trade)
            import math
            if math.isnan(risk_per_trade) or math.isinf(risk_per_trade) or risk_per_trade <= 0:
                risk_per_trade = None
        except (ValueError, TypeError):
            risk_per_trade = None
    fixed_units = payload.get("fixed_units")
    if fixed_units is not None:
        try:
            fixed_units = int(fixed_units)
            if fixed_units < 0:
                fixed_units = 0
        except (ValueError, TypeError):
            fixed_units = 0

    if not job.start_allowed():
        return {"ok": False, "error": "Ya hay un backtest en ejecución"}

    async def _runner():
        await asyncio.to_thread(
            job.run_sync,
            source,
            timeframe,
            date_from,
            date_to,
            equity,
            spread,
            strategy,
            strategy_params,
            risk_per_trade,
            fixed_units,
        )
        await app.state.hub.broadcast({"type": "backtest"})

    asyncio.create_task(_runner())
    return {"ok": True}


@app.post("/api/backtest/csv")
async def backtest_upload(file: UploadFile):
    import hashlib
    import tempfile

    if not file.filename or not file.filename.lower().endswith(".csv"):
        return {"ok": False, "error": "El archivo debe ser .csv"}
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        return {"ok": False, "error": "CSV demasiado grande (máx. 50 MB)"}
    UPLOAD_CSV.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".upload.", suffix=".csv", dir=UPLOAD_CSV.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, UPLOAD_CSV)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    app.state.store.set_state("backtest_upload_manifest", {
        "original_filename": file.filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "instrument": app.state.engine.symbol(),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })
    app.state.store.log("info", f"CSV subido para backtest: {file.filename} ({len(data) // 1024} KB)")
    return {"ok": True, "filename": file.filename, "kb": len(data) // 1024}


# -- FSRPPO: representación, entrenamiento y modelos -------------------------


def _fsr_params(payload: dict):
    """FsrParams con solo los campos que la interfaz puede tocar."""
    from ..config import FsrParams

    base = FsrParams()
    permitidos = {"window", "ensemble_size", "noise_scale", "n_curves",
                  "hurst_threshold", "patience", "max_imfs"}
    valores = {k: v for k, v in payload.items() if k in permitidos and v is not None}
    return replace(base, **valores)


def _training_available() -> bool:
    """La imagen minima sirve inferencia y precalculo, pero no entrenamiento."""
    from importlib.util import find_spec

    return find_spec("torch") is not None


@app.get("/api/fsr")
async def fsr_preview(bars: int = 50, timeframe: str = "h1"):
    """Descomposición de la última ventana: IMFs, Hurst y señal reconstruida.

    Es lo que alimenta el visor: deja ver qué se descarta como ruido y por qué.
    """
    from ..config import FsrParams
    from ..fsr.represent import fsr_window

    params = FsrParams()
    candles = await asyncio.to_thread(
        app.state.broker.get_candles, max(params.window, bars), None, None, timeframe
    )
    if candles.empty or len(candles) < params.window:
        return {"ok": False, "error": "Histórico insuficiente para calcular FSR"}

    closes = candles["close"].to_numpy(dtype=float)[-params.window:]
    resultado = await asyncio.to_thread(fsr_window, closes, params)

    return {
        "ok": True,
        "window": params.window,
        "times": [str(t) for t in candles.index[-params.window:]],
        "prices": [round(float(p), 5) for p in closes],
        "signal": [round(float(v), 5) for v in resultado.signal],
        "imfs": [[round(float(v), 6) for v in imf] for imf in resultado.imfs],
        "hursts": [round(float(h), 3) for h in resultado.hursts],
        "kept": [bool(k) for k in resultado.kept],
        "discarded_energy": round(resultado.discarded_energy, 4),
    }


@app.get("/api/training")
async def training_state():
    return app.state.training.state()


@app.get("/api/training/datasets")
async def training_datasets():
    return {"datasets": TrainingJob.available_datasets()}


@app.post("/api/training/download")
async def training_download(payload: dict = Body(...)):
    """Descarga histórico de FXCM sin salir del navegador.

    Va por la sesión ya autenticada del bróker (ver ``FxcmBroker.get_candles``),
    así que solo funciona con el bot conectado a FXCM y nunca en modo simulado.
    """
    from ..config import normalize_symbol

    broker = app.state.broker
    if execution_mode() != "live":
        return {"ok": False, "error": "En modo simulado no hay histórico real que descargar"}
    if not getattr(broker, "connected", False):
        return {"ok": False, "error": "El bróker no está conectado a FXCM"}

    simbolo = normalize_symbol(str(payload.get("symbol") or _selected_symbol(app.state.store)))
    timeframe = str(payload.get("timeframe", "h1")).lower()
    if timeframe not in ("m1", "m5", "m15", "m30", "h1", "h4", "d1"):
        return {"ok": False, "error": f"Timeframe no soportado: {timeframe}"}
    # Diez años es el tope del script equivalente; más abajo de 1 no tiene sentido.
    years = int(max(1, min(int(payload.get("years", 3)), 10)))

    started = app.state.training.start_download(
        broker=broker, symbol=simbolo, timeframe=timeframe, years=years,
    )
    return {"ok": started, "error": None if started else "Ya hay un trabajo en curso"}


@app.post("/api/training/precompute")
async def training_precompute(payload: dict = Body(...)):
    job: TrainingJob = app.state.training
    started = job.start_precompute(
        csv_name=payload.get("dataset"),
        timeframe=str(payload.get("timeframe", "h1")).lower(),
        params=_fsr_params(payload),
    )
    return {"ok": started, "error": None if started else "Ya hay un trabajo en curso"}


@app.post("/api/training")
async def training_start(payload: dict = Body(...)):
    if not _training_available():
        return {
            "ok": False,
            "error": "Entrenamiento no disponible en la imagen del bot; usa el entorno completo",
        }
    from ..config import PpoParams, normalize_symbol
    from ..rl.env import EnvParams

    job: TrainingJob = app.state.training
    ppo = replace(
        PpoParams(),
        iterations=int(max(1, min(int(payload.get("iterations", 200)), 2000))),
        seed=int(payload.get("seed", 0)),
        learning_rate=float(payload.get("learning_rate", PpoParams.learning_rate)),
        entropy_coef=float(payload.get("entropy_coef", PpoParams.entropy_coef)),
    )
    # La ficha sale del catálogo descubierto en la cuenta, no solo de las cuatro
    # semillas: sin esto no se puede entrenar un índice o una acción desde la web.
    simbolo = normalize_symbol(str(payload.get("instrument") or _selected_symbol(app.state.store)))
    catalogo = app.state.store.get_state("instrument_catalog", None)
    try:
        from ..config import get_instrument_spec

        instrument = get_instrument_spec(simbolo, catalogo)
    except ValueError as exc:
        return {"ok": False, "error": f"{exc}. Pulsa ACTUALIZAR en el selector de instrumentos."}

    dataset_name = str(payload.get("dataset") or "")
    timeframe = str(payload.get("timeframe", "h1")).lower()
    try:
        TrainingJob.validate_dataset(dataset_name, instrument.symbol, timeframe)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}

    spread = payload.get("spread_pips")
    default_max_units = 20_000 if instrument.min_lot >= 1_000 else 5
    max_units = int(payload.get("max_units", default_max_units))
    env = replace(
        EnvParams(),
        instrument=instrument,
        max_units=max(instrument.min_lot, min(max_units, 1_000_000)),
        spread_pips=(
            None if spread is None
            else float(max(0.0, min(float(spread), 1_000.0)))
        ),
    )

    started = job.start_training(
        csv_name=dataset_name,
        timeframe=timeframe,
        train_end=payload.get("train_end"),
        fsr=_fsr_params(payload),
        ppo=ppo,
        env=env,
        instrument=instrument.symbol,
        activate=bool(payload.get("activate", False)),
    )
    return {"ok": started, "error": None if started else "Ya hay un trabajo en curso"}


@app.post("/api/fsrppo/compare")
async def fsrppo_compare(payload: dict = Body(...)):
    """Compara el modelo indicado contra Buy & Hold y las estrategias por regla.

    Se evalúa sobre el **tramo de test** del modelo, que es el único que no vio
    durante el entrenamiento.
    """
    if not _training_available():
        return {
            "ok": False,
            "error": "Comparativa no disponible en la imagen del bot; usa el entorno completo",
        }

    from ..config import FsrParams
    from ..rl.dataset import build_dataset
    from ..rl.env import EnvParams
    from ..rl.policy import FsrppoPolicy
    from ..rl.registry import ModelRegistry
    from ..rl.train import compare_with_benchmarks
    from .training_job import TrainingJob

    registro = ModelRegistry()
    run_id = payload.get("run_id") or registro.active_id(app.state.engine.symbol())
    if not run_id:
        return {"ok": False, "error": "No hay modelo indicado ni activo"}

    record = registro.get(run_id)
    if record is None:
        return {"ok": False, "error": f"No existe el modelo {run_id}"}

    job: TrainingJob = app.state.training

    def ejecutar() -> list[dict]:
        candles = job._load_candles(payload.get("dataset"), record.timeframe)
        dataset = build_dataset(candles, FsrParams(**record.fsr_params))
        _entrena, evalua = dataset.split(record.test_range[0])
        politica = FsrppoPolicy.from_record(registro, run_id)
        return compare_with_benchmarks(
            politica.agent, evalua, candles,
            EnvParams(**record.env_params), record.timeframe,
        )

    try:
        filas = await asyncio.to_thread(ejecutar)
    except Exception as exc:
        log.exception("comparativa FSRPPO")
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "run_id": run_id, "test_range": record.test_range, "rows": filas}


@app.get("/api/models")
async def models_list():
    from ..rl.registry import ModelRegistry, meets_acceptance

    from ..config import normalize_symbol

    registro = ModelRegistry()
    # Un activo por instrumento: `is_active` significa "activo para el suyo".
    activos = registro.active_map()
    simbolo = normalize_symbol(app.state.engine.symbol())
    return {
        "active": activos,
        "active_for_current": activos.get(simbolo),
        "current_instrument": simbolo,
        "models": [
            {
                **modelo.as_dict(),
                "is_active": activos.get(normalize_symbol(modelo.instrument)) == modelo.run_id,
                "meets_acceptance": meets_acceptance(modelo),
            }
            for modelo in registro.list()
        ],
    }


def _seed_catalog() -> list[dict]:
    """Especificaciones semilla, para cuando aún no se descubrió el catálogo."""
    from ..config import INSTRUMENT_SEEDS

    return [
        {
            "symbol": spec.symbol,
            "pip": spec.pip,
            "min_lot": spec.min_lot,
            "lot_size": spec.lot_size,
            "digits": spec.digits,
            "asset_class": spec.asset_class,
            "typical_spread_pips": spec.typical_spread_pips,
            "quote_currency": spec.quote_currency,
            "contract_multiplier": spec.contract_multiplier,
            "subscription_status": "T",
            "tradable": True,
        }
        for spec in INSTRUMENT_SEEDS.values()
    ]


@app.get("/api/instruments")
async def instruments_list(asset_class: str = "", q: str = "", tradable: int = 0):
    """Universo descubierto de la cuenta FXCM; semillas si aún no hay catálogo."""
    catalog = app.state.store.get_state("instrument_catalog", None) or {}
    instruments = catalog.get("instruments") or _seed_catalog()
    if asset_class:
        instruments = [i for i in instruments if i.get("asset_class") == asset_class]
    if q:
        needle = q.strip().upper()
        instruments = [i for i in instruments if needle in str(i.get("symbol", "")).upper()]
    if tradable:
        instruments = [i for i in instruments if i.get("tradable")]
    return {
        "instruments": instruments,
        "selected": _selected_symbol(app.state.store),
        "updated_at": catalog.get("updated_at"),
        "total": catalog.get("total", len(instruments)),
        "truncated": catalog.get("truncated", False),
    }


@app.get("/api/instrument")
async def instrument_current():
    """Instrumento activo, con lo que la interfaz necesita para etiquetar precios."""
    broker = app.state.broker
    spec = getattr(broker, "spec", None)
    catalog = app.state.store.get_state("instrument_catalog", None) or {}
    return {
        "symbol": getattr(broker, "instrument", _selected_symbol(app.state.store)),
        "asset_class": getattr(spec, "asset_class", "forex"),
        "pip": getattr(spec, "pip", 0.0001),
        "digits": getattr(spec, "digits", 5),
        "min_lot": getattr(spec, "min_lot", 1000),
        "lot_size": getattr(broker, "lot_size", getattr(spec, "lot_size", 100_000)),
        "quote_currency": getattr(spec, "quote_currency", "USD"),
        "contract_multiplier": getattr(spec, "contract_multiplier", 1.0),
        # El bróker simulado no tiene suscripción: se reporta "T" para que la
        # interfaz no marque como no operable algo que sí puede simular.
        "subscription_status": await asyncio.to_thread(
            lambda: getattr(broker, "subscription_status", "T")),
        "execution_mode": execution_mode(),
        "connection": app.state.engine.s.fxcm.connection,
        "catalog_updated_at": catalog.get("updated_at"),
        "open_positions": len(await asyncio.to_thread(broker.open_trades)),
        "running": app.state.engine.running,
    }


@app.post("/api/instrument")
async def instrument_select(payload: dict = Body(...)):
    """Cambia el instrumento que opera el bot y reconstruye el bróker.

    Se niega con el bot iniciado o con posiciones abiertas: ``open_trades()``
    filtra por instrumento, así que cambiarlo dejaría una posición invisible para
    el motor, que nunca la cerraría.
    """
    from ..config import normalize_symbol

    symbol = normalize_symbol(str(payload.get("symbol", "")))
    if not symbol:
        return {"ok": False, "error": "Indica el instrumento"}

    store = app.state.store
    catalog = store.get_state("instrument_catalog", None) or {}
    conocidos = {str(i.get("symbol")) for i in (catalog.get("instruments") or _seed_catalog())}
    if symbol not in conocidos:
        return {"ok": False, "error": f"{symbol} no está en el catálogo de la cuenta"}

    if app.state.engine.running:
        return {"ok": False, "error": "Detén el bot antes de cambiar de instrumento"}
    abiertas = await asyncio.to_thread(app.state.broker.open_trades)
    if abiertas:
        return {"ok": False, "error": "Cierra las posiciones abiertas antes de cambiar"}

    store.set_state("selected_instrument", {
        "symbol": symbol,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    # La frontera de vela procesada es global: sin reiniciarla, el instrumento
    # nuevo se saltaría la vela en curso.
    store.set_state("last_processed_boundary", None)

    old = app.state.broker
    nuevo = _make_broker(load_settings(), store)
    try:
        await asyncio.to_thread(nuevo.connect)
    except Exception as e:
        return {"ok": False, "error": f"No se pudo conectar a {symbol}: {e}"}

    app.state.broker = nuevo
    app.state.engine.broker = nuevo
    app.state.backtest.broker = nuevo
    app.state.engine.reset_policy()
    try:
        await asyncio.to_thread(old.disconnect)
    except Exception:
        pass

    spec = getattr(nuevo, "spec", None)
    store.log("warn", f"Instrumento cambiado a {symbol}")
    await app.state.hub.broadcast({"type": "status", "status": app.state.engine.status()})
    return {
        "ok": True,
        "symbol": symbol,
        "asset_class": getattr(spec, "asset_class", "forex"),
        "digits": getattr(spec, "digits", 5),
        # Solo "T" permite operar; la interfaz ofrece activarlo si no lo está.
        "subscription_status": await asyncio.to_thread(
            lambda: getattr(nuevo, "subscription_status", "T")),
    }


@app.post("/api/instruments/refresh")
async def instruments_refresh():
    """Relee la tabla OFFERS de FXCM y republica el catálogo."""
    broker = app.state.broker
    if not hasattr(broker, "instrument_catalog"):
        return {"ok": False, "error": "El bróker simulado no tiene catálogo FXCM"}
    try:
        catalog = await asyncio.to_thread(broker.instrument_catalog)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    app.state.store.set_state("instrument_catalog", catalog)
    app.state.store.log("info", f"Catálogo actualizado: {catalog.get('count')} instrumentos, "
                                f"{catalog.get('tradable')} operables")
    return {"ok": True, "count": catalog.get("count"), "tradable": catalog.get("tradable"),
            "truncated": catalog.get("truncated")}


@app.post("/api/instrument/subscribe")
async def instrument_subscribe(payload: dict = Body(...)):
    """Pone un instrumento en estado "T" para poder operarlo por API."""
    from ..config import normalize_symbol

    symbol = normalize_symbol(str(payload.get("symbol", ""))) or _selected_symbol(app.state.store)
    broker = app.state.broker
    if not hasattr(broker, "subscribe"):
        return {"ok": False, "error": "El bróker actual no puede suscribir instrumentos"}
    try:
        result = await asyncio.to_thread(broker.subscribe, symbol)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if symbol == getattr(broker, "instrument", None):
        await asyncio.to_thread(broker.refresh_spec)
    return {"ok": True, **result}


@app.get("/api/selection/latest")
async def selection_latest():
    """Último barrido auditable; las pérdidas también forman parte del ranking."""
    from ..config import PROJECT_ROOT

    selection_dir = PROJECT_ROOT / "data" / "selection"
    files = sorted(selection_dir.glob("*.json"), reverse=True) if selection_dir.exists() else []
    if not files:
        return {"ok": False, "error": "Todavía no hay barridos de selección"}
    try:
        return {"ok": True, "filename": files[0].name, **json.loads(files[0].read_text())}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"No se pudo leer {files[0].name}: {exc}"}


@app.get("/api/models/{run_id}/history")
async def model_history(run_id: str):
    from ..rl.registry import ModelRegistry

    return {"run_id": run_id, "history": ModelRegistry().history(run_id)}


@app.post("/api/models/{run_id}/activate")
async def model_activate(run_id: str):
    from ..rl.registry import ModelRegistry, meets_acceptance

    try:
        registro = ModelRegistry()
        instrumento = registro.activate(run_id)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}
    # El instrumento lo decide el modelo, no la pantalla desde la que se pulsó:
    # la interfaz lo devuelve al usuario para que no crea que armó otra cosa.
    record = registro.get(run_id)
    accepted = bool(record and meets_acceptance(record))
    app.state.store.log(
        "info" if accepted else "warn",
        f"Modelo activo para {instrumento}: {run_id}; "
        f"criterio de aceptación={'cumplido' if accepted else 'no cumplido'}; activación permitida bajo responsabilidad del operador",
    )
    app.state.engine.reset_policy()
    await app.state.hub.broadcast({"type": "status", "status": app.state.engine.status()})
    return {
        "ok": True,
        "active": run_id,
        "instrument": instrumento,
        "meets_acceptance": accepted,
    }


@app.post("/api/models/deactivate")
async def model_deactivate(payload: dict = Body(default={})):
    from ..rl.registry import ModelRegistry

    instrumento = payload.get("instrument") or app.state.engine.symbol()
    ModelRegistry().deactivate(instrumento)
    app.state.store.log("warn", f"Sin modelo activo para {instrumento}: FSRPPO no operará")
    app.state.engine.reset_policy()
    await app.state.hub.broadcast({"type": "status", "status": app.state.engine.status()})
    return {"ok": True, "active": None, "instrument": instrumento}


@app.delete("/api/models/{run_id}")
async def model_delete(run_id: str):
    from ..rl.registry import ModelRegistry

    ModelRegistry().delete(run_id)
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    hub: WsHub = app.state.hub
    selected = "bearer" if "bearer" in ws.scope.get("subprotocols", []) else None
    await hub.add(ws, subprotocol=selected)
    try:
        await ws.send_text(json.dumps({"type": "status", "status": app.state.engine.status()}, default=str))
        while True:
            await ws.receive_text()  # keepalive del cliente; no esperamos comandos
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)


if UI_DIR.is_dir():
    # Va al final a propósito: este mount captura toda ruta que no haya casado
    # antes con /api, /ws o /healthz. `html=True` resuelve /fsr/ →
    # out/fsr/index.html y devuelve out/404.html cuando no existe el fichero.
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
else:
    @app.get("/")
    async def ui_missing():
        return JSONResponse(
            {
                "ok": False,
                "error": "Interfaz sin compilar. Ejecuta: cd web-ui && npm run build",
            },
            status_code=503,
        )
