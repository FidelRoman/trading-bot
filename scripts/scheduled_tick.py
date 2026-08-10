"""Ejecutor FXCM para comandos de Vercel y estrategia programada.

Vercel solo escribe intenciones autenticadas en Firestore. Este proceso es el
unico que posee secretos FXCM y que puede crear solicitudes de orden.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.broker import FxcmBroker  # noqa: E402
from tradingbot.config import FxcmCredentials, load_settings  # noqa: E402
from tradingbot.engine import BotEngine  # noqa: E402
from tradingbot.store import create_store  # noqa: E402
from tradingbot.strategy import add_indicators  # noqa: E402
from tradingbot.web.backtest_job import BacktestJob  # noqa: E402

CONNECTIONS = ("Demo", "Real")


def selected_connection(store):
    value = store.get_state("fxcm_connection", "Demo")
    connection = value.get("connection") if isinstance(value, dict) else value
    return connection if connection in CONNECTIONS else "Demo"


def fxcm_credentials(connection):
    suffix = connection.upper()
    credentials = FxcmCredentials(
        user=os.getenv("FXCM_USER_{}".format(suffix), ""),
        password=os.getenv("FXCM_PASS_{}".format(suffix), ""),
        connection=connection,
        url=os.getenv("FXCM_URL", "http://www.fxcorporate.com/Hosts.jsp"),
    )
    credentials.validate()
    return credentials


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


def _execute_backtest(command, store, engine, broker):
    payload = command.get("payload") or {}
    source = payload.get("source", "fxcm")
    if source not in ("fxcm", "synthetic"):
        raise ValueError("El runtime gratuito solo admite backtests FXCM o sintéticos")
    try:
        date_from = datetime.strptime(payload["date_from"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        date_to = datetime.strptime(payload["date_to"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        raise ValueError("Rango de fechas inválido para el backtest")
    if date_to <= date_from:
        raise ValueError("La fecha final debe ser posterior a la inicial")

    job = BacktestJob(store, engine, broker)
    if not job.start_allowed():
        raise RuntimeError("Ya hay un backtest en ejecución")
    store.set_state("last_backtest", {"status": "running", "note": "Preparando datos…"})
    job.run_sync(
        source=source,
        timeframe=str(payload.get("timeframe", "h1")),
        date_from=date_from,
        date_to=date_to,
        equity=float(payload.get("equity", 10_000)),
        spread_pips=float(payload.get("spread_pips", 1.2)),
        strategy=payload.get("strategy"),
        strategy_params=payload.get("strategy_params"),
        risk_per_trade=payload.get("risk_per_trade"),
        fixed_units=payload.get("fixed_units"),
    )
    result = store.get_state("last_backtest", {})
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "Backtest fallido"))
    return {"status": result.get("status"), "trades": result.get("summary", {}).get("trades", 0)}


def _execute_command(command, store, engine, broker):
    kind = command.get("kind")
    payload = command.get("payload") or {}
    if kind == "open":
        if not engine.running:
            raise RuntimeError("El bot está detenido; inicia el bot antes de abrir una posición")
        if command.get("connection") == "Real" and not payload.get("confirm_real"):
            raise PermissionError("Una orden real exige confirmación explícita")
        result = engine.manual_order(
            str(payload.get("side", "")),
            float(payload.get("lots", 0)),
            float(payload.get("sl_pips", 0)),
            float(payload.get("tp_pips", 0)),
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "No se pudo abrir la orden"))
        return result
    if kind == "close":
        trade_id = str(payload.get("trade_id", ""))
        if not trade_id:
            raise ValueError("Falta el identificador de la posición")
        return {"order_id": broker.close_trade(trade_id), "trade_id": trade_id}
    if kind == "close_all":
        closed = []
        for trade in broker.open_trades():
            closed.append(broker.close_trade(str(trade["trade_id"])))
        return {"closed": len(closed), "order_ids": closed}
    if kind == "backtest":
        return _execute_backtest(command, store, engine, broker)
    raise ValueError("Comando de ejecución desconocido")


def _process_commands(store, engine, broker, connection):
    completed = []
    for command in store.queued_commands(connection):
        store.start_command(command["id"])
        try:
            result = _execute_command(command, store, engine, broker)
        except Exception as exc:
            store.fail_command(command["id"], str(exc))
            store.log("error", "Comando {} fallido: {}".format(command.get("kind"), exc))
            completed.append({"id": command["id"], "status": "error"})
        else:
            store.finish_command(command["id"], result)
            store.log("warn", "Comando {} ejecutado en {}".format(command.get("kind"), connection))
            completed.append({"id": command["id"], "status": "done", "result": result})
    return completed


async def run():
    settings = load_settings()
    store = create_store(settings.db_path)
    connection = selected_connection(store)
    broker = FxcmBroker(fxcm_credentials(connection))
    engine = BotEngine(broker, store, settings)
    try:
        broker.connect()
        commands = _process_commands(store, engine, broker, connection)
        result = await engine.run_once()
        try:
            prices = broker.current_prices()
        except Exception as exc:
            prices = None
            store.log("warn", "Precios no disponibles para snapshot: {}".format(exc))
        candles = {}
        for timeframe in ("m5", "m15", "h1", "h4"):
            try:
                candles[timeframe] = _candles_payload(broker, engine, timeframe)
            except Exception as exc:
                candles[timeframe] = {"candles": [], "bands": []}
                store.log("warn", "Velas {} no disponibles: {}".format(timeframe, exc))
        snapshot = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "connection": connection,
            "tick": result,
            "commands": commands,
            "status": engine.status(),
            "prices": prices,
            "positions": broker.open_trades(),
            "candles": candles,
        }
        store.set_state("runtime_snapshot", snapshot)
        print({"connection": connection, "tick": result, "commands": commands})
    finally:
        broker.disconnect()
        store.close()


if __name__ == "__main__":
    asyncio.run(run())
