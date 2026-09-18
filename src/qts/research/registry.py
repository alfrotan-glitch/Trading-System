"""Strategy/Hypothesis Registry — durable, documented, no undocumented strategies."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.domain.value_objects import uuid7


class StrategyRecord(BaseModel):
    strategy_id: str = Field(description="unique strategy ID")
    name: str
    version: str = "1.0.0"
    hypothesis: str
    market: str = "XAUUSD"
    symbol: str = "XAUUSD"
    timeframe: str = "1H"
    data_manifest: str
    feature_definition: dict[str, Any] = Field(default_factory=dict)
    parameter_definition: dict[str, Any] = Field(default_factory=dict)
    execution_assumptions: dict[str, Any] = Field(default_factory=dict)
    risk_assumptions: dict[str, Any] = Field(default_factory=dict)
    creation_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    code_revision: str = "0.1.0"
    lifecycle_state: str = "RESEARCH"
    # extra metadata
    family: str = "trend"
    created_by: str = "system"

    def validate_documented(self) -> tuple[bool, str]:
        if not self.strategy_id or not self.strategy_id.strip():
            return False, "strategy_id required"
        if not self.name or not self.name.strip():
            return False, "name required"
        if not self.hypothesis or not self.hypothesis.strip():
            return False, "hypothesis required"
        if not self.data_manifest or not self.data_manifest.strip():
            return False, "data_manifest required"
        if not self.feature_definition:
            return False, "feature_definition required (cannot be empty)"
        if not self.parameter_definition:
            return False, "parameter_definition required"
        if not self.execution_assumptions:
            return False, "execution_assumptions required"
        if not self.risk_assumptions:
            return False, "risk_assumptions required"
        return True, "ok"


class StrategyRegistry:
    """Durable registry — SQLite backed. No undocumented strategies allowed."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS strategy_registry (
                    strategy_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS registry_log (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    details TEXT
                )
            """)
            con.commit()

    def register(self, record: StrategyRecord) -> StrategyRecord:
        ok, reason = record.validate_documented()
        if not ok:
            raise ValueError(f"undocumented strategy rejected: {reason}")
        # version uniqueness: strategy_id + version must be unique? For now strategy_id unique.
        with sqlite3.connect(self.db_path) as con:
            exists = con.execute("SELECT 1 FROM strategy_registry WHERE strategy_id=?", (record.strategy_id,)).fetchone()
            if exists:
                raise ValueError(f"strategy_id {record.strategy_id} already exists — version must be new ID or bump version with new ID")
            now = datetime.now(UTC).isoformat()
            con.execute(
                "INSERT INTO strategy_registry VALUES (?,?,?,?)",
                (record.strategy_id, record.model_dump_json(), record.creation_timestamp.isoformat(), now),
            )
            con.execute(
                "INSERT INTO registry_log VALUES (?,?,?,?,?)",
                (f"reg-{uuid7()[:8]}", record.strategy_id, "REGISTER", now, json.dumps({"version": record.version})),
            )
            con.commit()
        return record

    def get(self, strategy_id: str) -> StrategyRecord | None:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM strategy_registry WHERE strategy_id=?", (strategy_id,)).fetchone()
            if not row:
                return None
            return StrategyRecord.model_validate_json(row[0])

    def list(self, lifecycle_state: str | None = None, family: str | None = None) -> list[StrategyRecord]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM strategy_registry").fetchall()
            recs = [StrategyRecord.model_validate_json(r[0]) for r in rows]
            if lifecycle_state:
                recs = [r for r in recs if r.lifecycle_state == lifecycle_state]
            if family:
                recs = [r for r in recs if r.family == family]
            return recs

    def update_lifecycle(self, strategy_id: str, new_state: str, reason: str = "") -> StrategyRecord:
        """Lifecycle must be updated via PromotionLedger; this is a convenience that enforces registry update after ledger transition.
        Direct call without ledger is allowed only for initial RESEARCH, otherwise caller must use PromotionLedger.
        """
        rec = self.get(strategy_id)
        if not rec:
            raise ValueError(f"strategy {strategy_id} not found")
        # validate state is known
        from qts.edge.promotion import PromotionState

        try:
            PromotionState(new_state)
        except ValueError:
            raise ValueError(f"unknown lifecycle_state {new_state}")
        rec.lifecycle_state = new_state
        with sqlite3.connect(self.db_path) as con:
            now = datetime.now(UTC).isoformat()
            con.execute(
                "UPDATE strategy_registry SET payload=?, updated_at=? WHERE strategy_id=?",
                (rec.model_dump_json(), now, strategy_id),
            )
            con.execute(
                "INSERT INTO registry_log VALUES (?,?,?,?,?)",
                (f"reg-{uuid7()[:8]}", strategy_id, f"STATE->{new_state}", now, json.dumps({"reason": reason})),
            )
            con.commit()
        return rec

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT COUNT(*) FROM strategy_registry").fetchone()
            return row[0] if row else 0

    def log(self, strategy_id: str | None = None, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.db_path) as con:
            if strategy_id:
                rows = con.execute("SELECT action, timestamp, details FROM registry_log WHERE strategy_id=? ORDER BY timestamp DESC LIMIT ?", (strategy_id, limit)).fetchall()
            else:
                rows = con.execute("SELECT strategy_id, action, timestamp, details FROM registry_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
            if strategy_id:
                return [{"action": r[0], "timestamp": r[1], "details": r[2]} for r in rows]
            return [{"strategy_id": r[0], "action": r[1], "timestamp": r[2], "details": r[3]} for r in rows]
    def close(self) -> None:
        try:
            db = getattr(self, "db_path", getattr(self, "_db_path", None))
            if db is not None:
                db = Path(db)
                if db.exists() and str(db) != ":memory:":
                    import sqlite3
                    with sqlite3.connect(db) as con:
                        try:
                            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            con.commit()
                        except Exception:
                            pass
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                try:
                    mem.commit()
                    mem.close()
                except Exception:
                    pass
                self._memory_con = None
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
