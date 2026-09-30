"""Research Memory — durable, remembers failures, prevents rediscovery."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.db import connect as db_connect
from qts.domain.value_objects import uuid7


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"MEM-{uuid7()[:6]}")
    hypothesis_id: str
    strategy_id: str
    family: str
    mechanism: str
    params: dict[str, Any] = Field(default_factory=dict)
    failed_stage: str
    reason: str
    regime_failed: str | None = None
    param_range_unstable: str | None = None
    feature_useless: str | None = None
    is_redundant: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchMemory:
    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with db_connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS research_memory (id TEXT PRIMARY KEY, hypothesis_id TEXT, strategy_id TEXT, payload TEXT, created_at TEXT)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_memory_family ON research_memory(payload)")
            con.commit()

    def remember(self, entry: MemoryEntry):
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO research_memory VALUES (?,?,?, ?,?)",
                (
                    entry.id,
                    entry.hypothesis_id,
                    entry.strategy_id,
                    entry.model_dump_json(),
                    entry.created_at.isoformat(),
                ),
            )
            con.commit()

    def has_failed_similar(self, family: str, mechanism: str, params: dict[str, Any]) -> tuple[bool, str]:
        """Check if similar hypothesis already failed — prevents rediscovery under new name."""
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM research_memory").fetchall()
            for (payload,) in rows:
                e = MemoryEntry.model_validate_json(payload)
                # Simple param similarity: same family/mechanism and same param keys
                if e.family == family and e.mechanism == mechanism and set(e.params.keys()) == set(params.keys()):
                    # Check if param values close
                    similar = True
                    for k, v in params.items():
                        if isinstance(v, (int, float)) and abs(float(v) - float(e.params.get(k, 9999))) > 0.5 * abs(
                            float(v) or 1
                        ):
                            similar = False
                            break
                    if similar:
                        return (
                            True,
                            f"Similar {family}/{mechanism} already failed at {e.failed_stage}: {e.reason[:100]}",
                        )
        return False, ""

    def list_failures(self, limit: int = 20) -> list[MemoryEntry]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT payload FROM research_memory ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [MemoryEntry.model_validate_json(r[0]) for r in rows]

    def count(self) -> int:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT COUNT(*) FROM research_memory").fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        with contextlib.suppress(Exception):
            # File-backed connections are opened/closed per operation via qts.db.connect,
            # so no persistent handle exists here. We must NOT re-open the database file
            # in close()/__del__: that recreates deleted files and re-acquires Windows
            # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                with contextlib.suppress(Exception):
                    mem.commit()
                    mem.close()
                self._memory_con = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
