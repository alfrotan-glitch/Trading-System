"""Persistent idempotency store — sqlite backed, survives restart."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class IdempotencyStore:
    """Stores client_order_id -> status to prevent duplicate economic orders."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    client_order_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.commit()

    def seen(self, client_order_id: str) -> bool:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                "SELECT 1 FROM idempotency WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            return row is not None

    def record(self, client_order_id: str, status: str = "PENDING") -> None:
        from datetime import datetime, timezone

        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT OR IGNORE INTO idempotency VALUES (?,?,?)",
                (client_order_id, status, datetime.now(timezone.utc).isoformat()),
            )
            con.commit()

    def update(self, client_order_id: str, status: str) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "UPDATE idempotency SET status=? WHERE client_order_id=?", (status, client_order_id)
            )
            con.commit()

    def clear(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM idempotency")
            con.commit()
