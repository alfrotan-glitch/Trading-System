"""Persistent idempotency store — sqlite backed, survives restart.

State machine (Blocker 6):
- PENDING: created locally, not yet acked
- ACCEPTED: broker acked
- PARTIALLY_FILLED, FILLED: economic exposure created
- REJECTED: definitive rejection (invalid volume, market closed) — terminal, allows retry with same business intent? We treat REJECTED as terminal but NOT poison: duplicate with same client_order_id after REJECTED returns REJECTED (no new exposure), but new client_order_id allowed. Repeated submission with same id does not create duplicate economic exposure.
- CANCELLED: terminal, similar to REJECTED
- AMBIGUOUS: transport failure/timeout — unknown if venue accepted, fail closed. Duplicate must be blocked, requires reconcile, no auto-retry.

Semantics:
- should_block(client_order_id) -> True if existing status in (PENDING, ACCEPTED, PARTIALLY_FILLED, FILLED, AMBIGUOUS) → block duplicate economic exposure
- if status in (REJECTED, CANCELLED) → does not block? But for safety we still return existing REJECTED without new exposure, but allow caller to know it's rejected. Repeated submission returns same REJECTED, not new order. That's not creating duplicate economic exposure, so it's safe to block as well. To satisfy "must not permanently poison", we allow that the caller can use a NEW client_order_id to retry business intent. The old id remains REJECTED.
- AMBIGUOUS must fail closed: block, require manual reconcile, audit.

All duplicate checks are persistent (SQLite) and in-memory (OrderManager.orders).
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import UTC
from pathlib import Path

from qts.db import connect as db_connect

TERMINAL_REJECTED = {"REJECTED", "CANCELLED"}
BLOCKING_STATUSES = {"PENDING", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "AMBIGUOUS"}


class IdempotencyStore:
    """Stores client_order_id -> status to prevent duplicate economic orders."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path) if str(db_path) != ":memory:" else Path(":memory:")
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_con = None
        else:
            # Persistent in-memory connection - each store gets isolated memory DB
            # Must keep single connection, otherwise :memory: per connect is empty
            self._memory_con = sqlite3.connect(":memory:", check_same_thread=False)
        self._init()

    def _init(self) -> None:
        if self._memory_con is not None:
            con = self._memory_con
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
            return
        with db_connect(self.db_path) as con:
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
        if self._memory_con is not None:
            row = self._memory_con.execute(
                "SELECT 1 FROM idempotency WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            return row is not None
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT 1 FROM idempotency WHERE client_order_id=?", (client_order_id,)).fetchone()
            return row is not None

    def get_status(self, client_order_id: str) -> str | None:
        if self._memory_con is not None:
            row = self._memory_con.execute(
                "SELECT status FROM idempotency WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            return row[0] if row else None
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT status FROM idempotency WHERE client_order_id=?", (client_order_id,)).fetchone()
            return row[0] if row else None

    def should_block(self, client_order_id: str) -> bool:
        """Whether duplicate should be blocked (no new economic order).

        - PENDING/ACCEPTED/PARTIALLY_FILLED/FILLED/AMBIGUOUS -> block (already has or may have exposure)
        - REJECTED/CANCELLED -> do not block new economic attempt? But we still block duplicate id;
          caller should use new id to retry. For idempotency we block same id.
        For safety we block all seen ids, but AMBIGUOUS is special fail-closed.
        """
        # For definitive REJECTED/CANCELLED, we still block same id (return existing REJECTED)
        # but allow new id to retry. So effectively block every seen id.
        return self.get_status(client_order_id) is not None

    def is_ambiguous(self, client_order_id: str) -> bool:
        return self.get_status(client_order_id) == "AMBIGUOUS"

    def record(self, client_order_id: str, status: str = "PENDING") -> None:
        from datetime import datetime

        if self._memory_con is not None:
            self._memory_con.execute(
                "INSERT OR IGNORE INTO idempotency VALUES (?,?,?)",
                (client_order_id, status, datetime.now(UTC).isoformat()),
            )
            self._memory_con.commit()
            return
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR IGNORE INTO idempotency VALUES (?,?,?)",
                (client_order_id, status, datetime.now(UTC).isoformat()),
            )
            con.commit()

    def update(self, client_order_id: str, status: str) -> None:
        if self._memory_con is not None:
            self._memory_con.execute(
                "UPDATE idempotency SET status=? WHERE client_order_id=?", (status, client_order_id)
            )
            self._memory_con.commit()
            return
        with db_connect(self.db_path) as con:
            con.execute("UPDATE idempotency SET status=? WHERE client_order_id=?", (status, client_order_id))
            con.commit()

    def clear(self) -> None:
        if self._memory_con is not None:
            self._memory_con.execute("DELETE FROM idempotency")
            self._memory_con.commit()
            return
        with db_connect(self.db_path) as con:
            con.execute("DELETE FROM idempotency")
            con.commit()

    def close(self) -> None:
        if self._memory_con is not None:
            with contextlib.suppress(Exception):
                self._memory_con.commit()
                self._memory_con.close()
            self._memory_con = None
