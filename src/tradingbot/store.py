"""Persistencia SQLite: trades, curva de equity, estado del bot y log."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    trade_id TEXT,
    side TEXT NOT NULL,
    units INTEGER NOT NULL,
    entry_time TEXT NOT NULL,
    entry_rate REAL,
    exit_time TEXT,
    exit_rate REAL,
    pnl REAL,
    pips REAL,
    status TEXT NOT NULL DEFAULT 'open',   -- open | closed
    reason TEXT                            -- tp | sl | manual | unknown
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT PRIMARY KEY,
    equity REAL NOT NULL,
    balance REAL
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- estado ---------------------------------------------------------

    def get_state(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_state(self, key: str, value: Any) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO state(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    # -- trades ---------------------------------------------------------

    def open_trade(self, order_id: str, side: str, units: int) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO trades(order_id, side, units, entry_time, status) "
                "VALUES(?,?,?,?, 'open')",
                (order_id, side, units, _now()),
            )
            return int(cur.lastrowid)

    def link_trade(self, row_id: int, trade_id: str, entry_rate: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE trades SET trade_id=?, entry_rate=? WHERE id=?",
                (trade_id, entry_rate, row_id),
            )

    def close_trade(
        self, row_id: int, exit_rate: Optional[float], pnl: Optional[float],
        pips: Optional[float], reason: str,
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE trades SET exit_time=?, exit_rate=?, pnl=?, pips=?, "
                "status='closed', reason=? WHERE id=?",
                (_now(), exit_rate, pnl, pips, reason, row_id),
            )

    def current_open_trade(self) -> Optional[dict]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM trades WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def recent_trades(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM trades WHERE status='closed' ORDER BY exit_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def trades_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM trades WHERE entry_time >= ?", (today,)
            ).fetchone()
        return int(row["n"])

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute(
                "SELECT pnl, pips FROM trades WHERE status='closed' AND pnl IS NOT NULL"
            ).fetchall()
        pnls = [r["pnl"] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_loss = -sum(losses)
        return {
            "trades": len(pnls),
            "net_pnl": round(sum(pnls), 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss > 0 else None,
            "total_pips": round(sum(r["pips"] or 0 for r in rows), 1),
        }

    # -- equity ---------------------------------------------------------

    def snapshot_equity(self, equity: float, balance: Optional[float] = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO equity(ts, equity, balance) VALUES(?,?,?)",
                (_now(), equity, balance),
            )

    def equity_curve(self, limit: int = 2000) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, equity FROM equity ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def max_drawdown_pct(self) -> float:
        """Máximo drawdown histórico (%) sobre la curva de equity registrada."""
        with self._lock:
            rows = self._db.execute("SELECT equity FROM equity ORDER BY ts ASC").fetchall()
        peak, dd = None, 0.0
        for r in rows:
            e = float(r["equity"])
            peak = e if peak is None or e > peak else peak
            if peak:
                dd = min(dd, (e - peak) / peak)
        return round(dd * 100, 2)

    def day_start_equity(self) -> Optional[float]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self._db.execute(
                "SELECT equity FROM equity WHERE ts >= ? ORDER BY ts ASC LIMIT 1", (today,)
            ).fetchone()
        return float(row["equity"]) if row else None

    # -- log --------------------------------------------------------------

    def log(self, level: str, message: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO log(ts, level, message) VALUES(?,?,?)",
                (_now(), level, message),
            )

    def recent_logs(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, level, message FROM log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
