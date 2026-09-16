"""Hypothesis, Experiment, ExperimentStore with lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.db import connect as db_connect
from qts.domain.value_objects import uuid7


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: f"H-{uuid7()[:6]}")
    statement: str
    rationale: str = ""
    falsifiability: str = ""
    created_by: str = "human"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "OPEN"


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: f"E-{uuid7()[:6]}")
    hypothesis_id: str
    strategy_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    data_version: str
    code_version: str = "0.1.0"
    seed: int = 42
    manifest_hash: str = ""
    status: str = "CREATED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "hypothesis_id": self.hypothesis_id,
                "strategy_id": self.strategy_id,
                "params": self.params,
                "data_version": self.data_version,
                "code_version": self.code_version,
                "seed": self.seed,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


class ExperimentStore:
    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS hypotheses (id TEXT PRIMARY KEY, payload TEXT)")
            con.execute(
                "CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, hypothesis_id TEXT, payload TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS rejections (id TEXT PRIMARY KEY, experiment_id TEXT, reason TEXT, payload TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS lineage (parent TEXT, child TEXT, relation TEXT, PRIMARY KEY(parent, child))"
            )
            con.commit()

    def put_hypothesis(self, h: Hypothesis) -> None:
        with db_connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO hypotheses VALUES (?,?)", (h.id, h.model_dump_json()))
            con.commit()

    def get_hypothesis(self, hid: str) -> Hypothesis | None:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM hypotheses WHERE id=?", (hid,)).fetchone()
            return Hypothesis.model_validate_json(row[0]) if row else None

    def put(self, exp: Experiment) -> None:
        exp.manifest_hash = exp.compute_hash()
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?,?)",
                (exp.id, exp.hypothesis_id, exp.model_dump_json()),
            )
            con.commit()

    def get(self, exp_id: str) -> Experiment | None:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM experiments WHERE id=?", (exp_id,)).fetchone()
            return Experiment.model_validate_json(row[0]) if row else None

    def all_experiments(self) -> list[Experiment]:
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM experiments").fetchall()
            return [Experiment.model_validate_json(r[0]) for r in rows]

    def reject(self, experiment_id: str, reason: str, details: dict[str, object] | None = None) -> None:
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO rejections VALUES (?,?,?,?)",
                (f"R-{uuid7()[:6]}", experiment_id, reason, json.dumps(details or {})),
            )
            con.commit()

    def lineage(self, parent: str, child: str, relation: str = "derived") -> None:
        with db_connect(self.db_path) as con:
            con.execute("INSERT OR IGNORE INTO lineage VALUES (?,?,?)", (parent, child, relation))
            con.commit()

    def count_trials(self) -> int:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT COUNT(*) FROM experiments").fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        # File-backed connections are opened/closed per operation via qts.db.connect,
        # so no persistent handle exists here. We must NOT re-open the database file
        # in close()/__del__: that recreates deleted files and re-acquires Windows
        # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
