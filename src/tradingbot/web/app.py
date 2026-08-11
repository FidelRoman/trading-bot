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
from pathlib import Path

from fastapi import Body, FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import PROJECT_ROOT, load_settings
from ..engine import BotEngine
from ..store import Store
from ..strategy import add_indicators
from .backtest_job import UPLOAD_CSV, BacktestJob
from .auth import BearerAuthMiddleware, allowed_origins
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


def _make_broker(settings, store=None):
    """Bróker según el entorno.

    FSRPPO gestiona una posición neta, no operaciones con SL/TP, así que en modo
    paper se envuelve la fuente de precios en un ``PaperBroker``: el mercado es
    el real de FXCM y lo simulado es únicamente la ejecución. Es el alcance
    acordado para esta versión — no se envían órdenes reales.
    """
    from ..paper_broker import PaperBroker

    if os.getenv("MOCK") == "1" or not settings.fxcm.user:
        log.warning("Sin credenciales FXCM (o MOCK=1): precios SIMULADOS, ejecución en papel")
        return PaperBroker(
            persisted_state=store.get_state("paper_broker", {}) if store else {},
            state_callback=(lambda value: store.set_state("paper_broker", value)) if store else None,
        )

    from ..broker import FxcmBroker

    log.info("Precios reales de FXCM con ejecución en papel (no se envían órdenes)")
    return PaperBroker(
        price_source=FxcmBroker(settings.fxcm),
        persisted_state=store.get_state("paper_broker", {}) if store else {},
        state_callback=(lambda value: store.set_state("paper_broker", value)) if store else None,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    store = Store(settings.db_path)
    broker = _make_broker(settings, store)
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

    bucle = asyncio.get_running_loop()

    def notificar(payload: dict) -> None:
        # El job corre en un hilo: hay que volver al bucle de eventos para emitir.
        asyncio.run_coroutine_threadsafe(hub.broadcast(payload), bucle)

    app.state.training = TrainingJob(store, notify=notificar)

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
        await asyncio.gather(pump_task, engine_task, return_exceptions=True)
        await asyncio.to_thread(app.state.broker.disconnect)


app = FastAPI(title="FSRPPO·BOT — EUR/USD H1", lifespan=lifespan)

# En producción la UI se sirve desde este mismo origen y CORS sobra. Hace falta
# para `next dev`, que sirve el frontend en otro puerto.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(BearerAuthMiddleware)
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


VALID_TF = {"m5", "m15", "m30", "h1", "h4"}


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

    # Recargar configuración y re-crear store para el nuevo modo si cambió
    from ..config import load_settings

    new_settings = load_settings()
    if str(app.state.store.path) != str(new_settings.db_path):
        old_store = app.state.store
        new_store = Store(new_settings.db_path)
        
        # Swap store references
        app.state.store = new_store
        app.state.engine.store = new_store
        app.state.backtest.store = new_store
        
        # Close old db
        try:
            old_store.close()
        except Exception:
            pass

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
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return {"ok": False, "error": "El archivo debe ser .csv"}
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        return {"ok": False, "error": "CSV demasiado grande (máx. 50 MB)"}
    UPLOAD_CSV.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_CSV.write_bytes(data)
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
    from ..config import PpoParams, get_instrument_spec
    from ..rl.env import EnvParams

    job: TrainingJob = app.state.training
    ppo = replace(
        PpoParams(),
        iterations=int(max(1, min(int(payload.get("iterations", 200)), 2000))),
        seed=int(payload.get("seed", 0)),
        learning_rate=float(payload.get("learning_rate", PpoParams.learning_rate)),
        entropy_coef=float(payload.get("entropy_coef", PpoParams.entropy_coef)),
    )
    try:
        instrument = get_instrument_spec(str(payload.get("instrument", "EUR/USD")))
    except ValueError as exc:
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
        csv_name=payload.get("dataset"),
        timeframe=str(payload.get("timeframe", "h1")).lower(),
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
    run_id = payload.get("run_id") or registro.active_id()
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
    from ..rl.registry import ModelRegistry

    registro = ModelRegistry()
    activo = registro.active_id()
    return {
        "active": activo,
        "models": [
            {**registro_modelo.as_dict(), "is_active": registro_modelo.run_id == activo}
            for registro_modelo in registro.list()
        ],
    }


@app.get("/api/instruments")
async def instruments_list():
    from ..config import INSTRUMENTS

    return {
        "instruments": [
            {
                "symbol": spec.symbol,
                "pip": spec.pip,
                "min_lot": spec.min_lot,
                "typical_spread_pips": spec.typical_spread_pips,
                "quote_currency": spec.quote_currency,
            }
            for spec in INSTRUMENTS.values()
        ]
    }


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
    from ..rl.registry import ModelRegistry

    try:
        ModelRegistry().activate(run_id)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}
    app.state.store.log("info", f"Modelo activo: {run_id}")
    return {"ok": True, "active": run_id}


@app.post("/api/models/deactivate")
async def model_deactivate():
    from ..rl.registry import ModelRegistry

    ModelRegistry().deactivate()
    app.state.store.log("warn", "Sin modelo activo: FSRPPO no operará")
    return {"ok": True, "active": None}


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
