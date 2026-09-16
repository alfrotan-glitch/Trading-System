"""Phase 2: True out-of-sample protocol — immutable chronological partitions.

DISCOVERY (60%) | VALIDATION (20%) | LOCKED TEST (20%) | LIVE/PAPER (future)

LOCKED TEST must never influence design/params/thresholds/feature selection.
Code-level separation + audit of every access attempt.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.domain.value_objects import Bar


class LockedTestViolation(RuntimeError):
    pass


class LockedTestPartitioner:
    """Chronological partitioner with immutable LOCKED TEST."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS locked_partitions (
                data_version TEXT PRIMARY KEY,
                discovery_start TEXT, discovery_end TEXT,
                validation_start TEXT, validation_end TEXT,
                locked_start TEXT, locked_end TEXT,
                created_at TEXT, hash TEXT
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS locked_access_log (
                id TEXT PRIMARY KEY, data_version TEXT, accessor TEXT, purpose TEXT, timestamp TEXT, allowed INTEGER
            )""")
            con.commit()

    def partition(self, bars: list[Bar], data_version: str, discovery_ratio: float = 0.6, validation_ratio: float = 0.2) -> dict[str, list[Bar]]:
        """Chronological split: discovery, validation, locked. Immutable once created."""
        if not bars:
            raise ValueError("no bars")
        bars = sorted(bars, key=lambda b: b.open_time)
        n = len(bars)
        d_end = int(n * discovery_ratio)
        v_end = int(n * (discovery_ratio + validation_ratio))
        discovery = bars[:d_end]
        validation = bars[d_end:v_end]
        locked = bars[v_end:]
        # Check if already partitioned — immutable
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM locked_partitions WHERE data_version=?", (data_version,)).fetchone() if False else None
            # Actually query correct table
            row2 = con.execute("SELECT * FROM locked_partitions WHERE data_version=?", (data_version,)).fetchone()
            if row2:
                # Verify same hash
                h = self._hash_bars(locked)
                if row2[8] != h:
                    raise LockedTestViolation(f"locked test for {data_version} already exists with different hash — immutable")
        # Store
        h = self._hash_bars(locked)
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR IGNORE INTO locked_partitions VALUES (?,?,?,?,?,?,?,?,?)",
                        (data_version,
                         discovery[0].open_time.isoformat() if discovery else "",
                         discovery[-1].close_time.isoformat() if discovery else "",
                         validation[0].open_time.isoformat() if validation else "",
                         validation[-1].close_time.isoformat() if validation else "",
                         locked[0].open_time.isoformat() if locked else "",
                         locked[-1].close_time.isoformat() if locked else "",
                         datetime.now(UTC).isoformat(),
                         h))
            con.commit()
        return {"discovery": discovery, "validation": validation, "locked": locked}

    def get_locked(self, bars: list[Bar], data_version: str, accessor: str = "unknown", purpose: str = "research", allow: bool = False) -> list[Bar]:
        """Access locked test — logs every attempt, requires explicit allow."""
        # Log attempt
        import uuid
        access_id = str(uuid.uuid4())[:8]
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO locked_access_log VALUES (?,?,?,?,?,?)",
                        (access_id, data_version, accessor, purpose, datetime.now(UTC).isoformat(), int(allow)))
            con.commit()
        if not allow:
            raise LockedTestViolation(f"locked test access denied for {accessor}:{purpose} — requires allow=True and freeze")
        # Return locked partition
        parts = self.partition(bars, data_version)
        return parts["locked"]

    def is_frozen(self, data_version: str) -> bool:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT 1 FROM locked_partitions WHERE data_version=?", (data_version,)).fetchone()
            return row is not None

    def access_log(self, data_version: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as con:
            if data_version:
                rows = con.execute("SELECT * FROM locked_access_log WHERE data_version=? ORDER BY timestamp", (data_version,)).fetchall()
            else:
                rows = con.execute("SELECT * FROM locked_access_log ORDER BY timestamp").fetchall()
            return [{"id": r[0], "data_version": r[1], "accessor": r[2], "purpose": r[3], "timestamp": r[4], "allowed": bool(r[5])} for r in rows]

    def _hash_bars(self, bars: list[Bar]) -> str:
        h = hashlib.sha256()
        for b in bars:
            h.update(f"{b.open_time.isoformat()}{b.close}".encode())
        return h.hexdigest()[:12]

    def verify_no_leak(self, strategy_params: dict, locked_hash: str) -> bool:
        """Ensure strategy params don't contain locked data — placeholder for code-level separation."""
        # In real, we would check that param hash doesn't depend on locked test
        # Here we just ensure locked_hash not in params string
        return locked_hash not in json.dumps(strategy_params)
