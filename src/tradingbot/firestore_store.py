"""Persistencia Firestore para el runtime efimero de coste cero."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FirestoreStore:
    """Implementa el contrato de ``Store`` sin requerir indices compuestos.

    Los volumenes son deliberadamente pequenos (paper trading horario), por lo
    que se filtra en memoria. Asi el proyecto funciona con la base gratuita y
    no necesita crear indices facturables ni activar billing.
    """

    def __init__(self, project_id: str, client=None):
        self.project_id = project_id
        self.path = f"firestore://{project_id}"
        self._client = client or self._build_client(project_id)
        prefix = os.getenv("FIRESTORE_COLLECTION_PREFIX", "tradingbot").strip() or "tradingbot"
        self._state = self._client.collection(f"{prefix}_state")
        self._trades = self._client.collection(f"{prefix}_trades")
        self._equity = self._client.collection(f"{prefix}_equity")
        self._logs = self._client.collection(f"{prefix}_logs")
        self._commands = self._client.collection(f"{prefix}_commands")

    @staticmethod
    def _build_client(project_id: str):
        from google.cloud import firestore

        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            return firestore.Client(project=project_id)
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(json.loads(raw))
        return firestore.Client(project=project_id, credentials=credentials)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            close()

    @staticmethod
    def _rows(collection) -> list[dict]:
        result = []
        for snapshot in collection.stream():
            row = snapshot.to_dict() or {}
            row.setdefault("id", snapshot.id)
            result.append(row)
        return result

    # -- estado ---------------------------------------------------------

    def get_state(self, key: str, default: Any = None) -> Any:
        snapshot = self._state.document(key).get()
        if not snapshot.exists:
            return default
        return (snapshot.to_dict() or {}).get("value", default)

    def set_state(self, key: str, value: Any) -> None:
        self._state.document(key).set({"value": value, "updated_at": _now()})

    # -- trades ---------------------------------------------------------

    def open_trade(self, order_id: str, side: str, units: int) -> str:
        row_id = uuid.uuid4().hex
        self._trades.document(row_id).set(
            {
                "id": row_id,
                "order_id": order_id,
                "trade_id": None,
                "side": side,
                "units": int(units),
                "entry_time": _now(),
                "entry_rate": None,
                "exit_time": None,
                "exit_rate": None,
                "pnl": None,
                "pips": None,
                "status": "open",
                "reason": None,
            }
        )
        return row_id

    def link_trade(self, row_id: str, trade_id: str, entry_rate: float) -> None:
        self._trades.document(str(row_id)).update(
            {"trade_id": trade_id, "entry_rate": float(entry_rate)}
        )

    def close_trade(
        self,
        row_id: str,
        exit_rate: Optional[float],
        pnl: Optional[float],
        pips: Optional[float],
        reason: str,
    ) -> None:
        self._trades.document(str(row_id)).update(
            {
                "exit_time": _now(),
                "exit_rate": exit_rate,
                "pnl": pnl,
                "pips": pips,
                "status": "closed",
                "reason": reason,
            }
        )

    def current_open_trade(self) -> Optional[dict]:
        rows = [row for row in self._rows(self._trades) if row.get("status") == "open"]
        return max(rows, key=lambda row: row.get("entry_time", "")) if rows else None

    def recent_trades(self, limit: int = 50) -> list[dict]:
        rows = [row for row in self._rows(self._trades) if row.get("status") == "closed"]
        return sorted(rows, key=lambda row: row.get("exit_time") or "", reverse=True)[:limit]

    def trades_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(row.get("entry_time", "") >= today for row in self._rows(self._trades))

    def stats(self) -> dict:
        rows = [
            row
            for row in self._rows(self._trades)
            if row.get("status") == "closed" and row.get("pnl") is not None
        ]
        pnls = [float(row["pnl"]) for row in rows]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]
        gross_loss = -sum(losses)
        return {
            "trades": len(pnls),
            "net_pnl": round(sum(pnls), 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss > 0 else None,
            "total_pips": round(sum(float(row.get("pips") or 0) for row in rows), 1),
        }

    # -- equity ---------------------------------------------------------

    def snapshot_equity(self, equity: float, balance: Optional[float] = None) -> None:
        timestamp = _now()
        self._equity.document(uuid.uuid4().hex).set(
            {"ts": timestamp, "equity": float(equity), "balance": balance}
        )

    def equity_curve(self, limit: int = 2000) -> list[dict]:
        rows = sorted(self._rows(self._equity), key=lambda row: row.get("ts", ""))[-limit:]
        return [{"ts": row["ts"], "equity": row["equity"]} for row in rows]

    def max_drawdown_pct(self) -> float:
        peak, drawdown = None, 0.0
        for row in self.equity_curve(limit=10000):
            equity = float(row["equity"])
            peak = equity if peak is None or equity > peak else peak
            if peak:
                drawdown = min(drawdown, (equity - peak) / peak)
        return round(drawdown * 100, 2)

    def day_start_equity(self) -> Optional[float]:
        today = datetime.now(timezone.utc).date().isoformat()
        rows = [row for row in self.equity_curve(limit=10000) if row["ts"] >= today]
        return float(rows[0]["equity"]) if rows else None

    # -- log ------------------------------------------------------------

    def log(self, level: str, message: str) -> None:
        self._logs.document(uuid.uuid4().hex).set(
            {"ts": _now(), "level": level, "message": message}
        )

    def recent_logs(self, limit: int = 100) -> list[dict]:
        rows = sorted(self._rows(self._logs), key=lambda row: row.get("ts", ""))[-limit:]
        return [
            {"ts": row["ts"], "level": row["level"], "message": row["message"]}
            for row in rows
        ]

    # -- cola de ejecucion ---------------------------------------------

    def enqueue_command(self, kind: str, connection: str, payload: dict) -> dict:
        command_id = uuid.uuid4().hex
        row = {
            "id": command_id,
            "kind": kind,
            "connection": connection,
            "payload": payload,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
        self._commands.document(command_id).set(row)
        return row

    def queued_commands(self, connection: str | None = None) -> list[dict]:
        rows = [row for row in self._rows(self._commands) if row.get("status") == "queued"]
        if connection:
            rows = [row for row in rows if row.get("connection") == connection]
        return sorted(rows, key=lambda row: row.get("created_at", ""))

    def command_count(self, status: str = "queued") -> int:
        return sum(row.get("status") == status for row in self._rows(self._commands))

    def start_command(self, command_id: str) -> None:
        self._commands.document(command_id).update({"status": "running", "started_at": _now()})

    def finish_command(self, command_id: str, result: dict | None = None) -> None:
        self._commands.document(command_id).update(
            {"status": "done", "finished_at": _now(), "result": result or {}, "error": None}
        )

    def fail_command(self, command_id: str, error: str) -> None:
        self._commands.document(command_id).update(
            {"status": "error", "finished_at": _now(), "error": str(error)[:500]}
        )

    def cancel_pending_opens(self) -> int:
        cancelled = 0
        for row in self.queued_commands():
            if row.get("kind") != "open":
                continue
            self._commands.document(row["id"]).update(
                {
                    "status": "cancelled",
                    "finished_at": _now(),
                    "error": "Bot detenido antes de ejecutar la orden",
                }
            )
            cancelled += 1
        return cancelled
