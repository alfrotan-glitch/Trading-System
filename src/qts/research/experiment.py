"""Canonical research records and the append-only experiment ledger.

The research plane has one durable vocabulary:

* :class:`Hypothesis` states a question and how it could be disproved.
* :class:`Experiment` freezes the configuration that was actually tested.
* :class:`ExperimentStore` preserves the cumulative trial ledger, outcomes,
  rejections, and lineage.

This module intentionally stays small and SQLite-backed.  It is not a
workflow engine and it does not decide whether a strategy is good.  Its job is
to make a research claim reproducible and to make it impossible to silently
replace an old trial with a new configuration.

A result can be updated only through an explicit outcome write, while the
experiment configuration hash remains immutable.  This is important for DSR /
multiple-testing accounting: rejected, failed, blocked, and successful trials
all remain in the denominator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from qts.db import connect as db_connect
from qts.domain.value_objects import uuid7


class ConclusionCode(StrEnum):
    """Small, machine-readable vocabulary for experiment conclusions."""

    NO_EDGE_FOUND = "NO_EDGE_FOUND"
    BLOCKED_INSUFFICIENT_DATA = "BLOCKED_INSUFFICIENT_DATA"
    EDGE_BEFORE_COSTS_ONLY = "EDGE_BEFORE_COSTS_ONLY"
    REGIME_DEPENDENT = "REGIME_DEPENDENT"
    PROMISING_INSUFFICIENT = "PROMISING_INSUFFICIENT"
    SURVIVES_OOS_AND_FORWARD = "SURVIVES_OOS_AND_FORWARD"
    REJECTED = "REJECTED"


class ExperimentStatus(StrEnum):
    """Execution state, deliberately separate from the scientific conclusion."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ImmutableRecordError(ValueError):
    """An existing record was submitted with a different immutable payload."""


def _canonical_json(value: Any) -> str:
    """Serialize configuration deterministically, including Decimal-like values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class Hypothesis(BaseModel):
    """A falsifiable research question.

    The legacy ``statement``/``falsifiability`` fields remain supported because
    old ledger rows and the CLI use them.  New callers should fill the
    explicit fields below.  ``missing_specification`` lets a caller block a
    meaningful run without making historical records impossible to read.
    """

    id: str = Field(default_factory=lambda: f"H-{uuid7()[:8]}")
    statement: str
    question: str = ""
    mechanism: str = ""
    prediction: str = ""
    null_hypothesis: str = ""
    competing_explanations: list[str] = Field(default_factory=list)
    falsification_criteria: list[str] = Field(default_factory=list)
    rationale: str = ""
    falsifiability: str = ""
    required_data: dict[str, Any] = Field(default_factory=dict)
    intended_horizon: str = ""
    intended_population: str = ""
    intended_regime: str = ""
    created_by: str = "human"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "OPEN"

    @model_validator(mode="after")
    def _normalise_legacy_fields(self) -> Hypothesis:
        # A legacy statement is a valid question label, but never pretend it is
        # a complete preregistration.  These are convenience copies only; the
        # explicit fields are still exposed in the serialized record.
        if not self.question.strip() and self.statement.strip():
            self.question = self.statement
        if not self.prediction.strip() and self.falsifiability.strip():
            self.prediction = self.falsifiability
        return self

    def missing_specification(self) -> list[str]:
        """Return fields required before a *meaningful* experiment may run."""
        missing: list[str] = []
        required_text = {
            "question": self.question,
            "mechanism": self.mechanism,
            "prediction": self.prediction,
            "null_hypothesis": self.null_hypothesis,
            "intended_horizon": self.intended_horizon,
            "intended_population": self.intended_population,
        }
        missing.extend(name for name, value in required_text.items() if not str(value).strip())
        if not self.falsification_criteria and not self.falsifiability.strip():
            missing.append("falsification_criteria")
        if not self.required_data:
            missing.append("required_data")
        return missing

    @property
    def is_falsifiable(self) -> bool:
        return not self.missing_specification()


class Experiment(BaseModel):
    """One immutable research configuration plus its recorded outcome.

    Configuration fields are covered by :meth:`compute_hash`; outcome fields
    are intentionally not.  That permits a run to move from CREATED to
    COMPLETED/FAILED while preventing a caller from changing the dataset,
    parameters, split, costs, seed, or lineage under the same experiment ID.
    """

    id: str = Field(default_factory=lambda: f"E-{uuid7()[:8]}")
    hypothesis_id: str
    strategy_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    data_version: str
    dataset_provenance: str = "UNVERIFIED"
    dataset_manifest_hash: str = ""
    code_version: str = "0.1.0"
    seed: int = 42
    split_definition: dict[str, Any] = Field(default_factory=dict)
    cost_assumptions: dict[str, Any] = Field(default_factory=dict)
    exclusions: list[str] = Field(default_factory=list)
    parent_experiment_id: str | None = None

    # Outcome / accounting fields. These do not alter the configuration hash.
    trial_count: int = 0
    results: dict[str, Any] = Field(default_factory=dict)
    conclusion: str | None = None
    failure_reason: str | None = None
    status: str = ExperimentStatus.CREATED.value
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    manifest_hash: str = ""  # historical name retained; this is the config hash

    @model_validator(mode="after")
    def _basic_contract(self) -> Experiment:
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id required")
        if not self.strategy_id.strip():
            raise ValueError("strategy_id required")
        if not self.data_version.strip():
            raise ValueError("data_version required")
        if self.trial_count < 0:
            raise ValueError("trial_count cannot be negative")
        return self

    def configuration(self) -> dict[str, Any]:
        """Return only fields that define what was tested."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "strategy_id": self.strategy_id,
            "params": self.params,
            "data_version": self.data_version,
            "dataset_provenance": self.dataset_provenance,
            "dataset_manifest_hash": self.dataset_manifest_hash,
            "code_version": self.code_version,
            "seed": self.seed,
            "split_definition": self.split_definition,
            "cost_assumptions": self.cost_assumptions,
            "exclusions": self.exclusions,
            "parent_experiment_id": self.parent_experiment_id,
        }

    def compute_hash(self) -> str:
        """Hash the complete immutable configuration, not just strategy params."""
        return hashlib.sha256(_canonical_json(self.configuration()).encode("utf-8")).hexdigest()[:16]

    @property
    def configuration_hash(self) -> str:
        return self.manifest_hash or self.compute_hash()

    def with_outcome(
        self,
        *,
        results: dict[str, Any] | None = None,
        conclusion: ConclusionCode | str | None = None,
        failure_reason: str | None = None,
        status: ExperimentStatus | str | None = None,
        completed_at: datetime | None = None,
    ) -> Experiment:
        """Return a copy with outcome fields changed, never configuration fields."""
        code = conclusion.value if isinstance(conclusion, ConclusionCode) else conclusion
        return self.model_copy(
            update={
                "results": self.results if results is None else results,
                "conclusion": code,
                "failure_reason": failure_reason,
                "status": status.value if isinstance(status, ExperimentStatus) else (status or self.status),
                "completed_at": completed_at or datetime.now(UTC),
            }
        )


class ExperimentStore:
    """SQLite-backed cumulative ledger with immutable configuration checks."""

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
            con.execute(
                "CREATE TABLE IF NOT EXISTS experiment_events ("
                "id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, event_type TEXT NOT NULL, "
                "payload TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_experiment_hypothesis ON experiments(hypothesis_id)")
            # strategy_id lives in the immutable JSON payload in the compact
            # legacy schema; do not create an index over a column that does
            # not exist.  Structured search is performed after validation.
            con.commit()

    def put_hypothesis(self, h: Hypothesis) -> None:
        payload = h.model_dump_json()
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM hypotheses WHERE id=?", (h.id,)).fetchone()
            if row:
                existing = Hypothesis.model_validate_json(row[0])
                if _canonical_json(existing.model_dump(mode="json")) != _canonical_json(h.model_dump(mode="json")):
                    raise ImmutableRecordError(f"hypothesis {h.id} already exists with different content")
                return
            con.execute("INSERT INTO hypotheses VALUES (?,?)", (h.id, payload))
            con.commit()

    def get_hypothesis(self, hid: str) -> Hypothesis | None:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM hypotheses WHERE id=?", (hid,)).fetchone()
            return Hypothesis.model_validate_json(row[0]) if row else None

    def all_hypotheses(self) -> list[Hypothesis]:
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM hypotheses ORDER BY rowid").fetchall()
            return [Hypothesis.model_validate_json(r[0]) for r in rows]

    def put(self, exp: Experiment) -> Experiment:
        """Insert or update an outcome without allowing config replacement.

        Re-submitting an identical CREATED record is idempotent.  If the ID is
        already present, the immutable configuration hash must match; otherwise
        the operation fails rather than silently replacing a trial.
        """
        config_hash = exp.compute_hash()
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM experiments WHERE id=?", (exp.id,)).fetchone()
            if row is None:
                # The count is assigned by the store, not by a caller, so it
                # cannot be reset to make DSR look better.
                exp.trial_count = self._count_with_connection(con) + 1
                exp.manifest_hash = config_hash
                con.execute(
                    "INSERT INTO experiments VALUES (?,?,?)",
                    (exp.id, exp.hypothesis_id, exp.model_dump_json()),
                )
                self._event_with_connection(con, exp.id, "CREATED", {"configuration_hash": config_hash})
            else:
                existing = Experiment.model_validate_json(row[0])
                old_hash = existing.configuration_hash
                if old_hash != config_hash:
                    raise ImmutableRecordError(
                        f"experiment {exp.id} configuration is immutable "
                        f"({old_hash} != {config_hash})"
                    )
                # Preserve the original ledger position and creation time.
                exp.trial_count = existing.trial_count
                exp.manifest_hash = old_hash
                exp.created_at = existing.created_at
                con.execute("UPDATE experiments SET hypothesis_id=?, payload=? WHERE id=?", (exp.hypothesis_id, exp.model_dump_json(), exp.id))
                if exp.status != existing.status or exp.conclusion != existing.conclusion or exp.failure_reason != existing.failure_reason:
                    self._event_with_connection(
                        con,
                        exp.id,
                        "OUTCOME_UPDATED",
                        {
                            "from_status": existing.status,
                            "to_status": exp.status,
                            "conclusion": exp.conclusion,
                            "failure_reason": exp.failure_reason,
                        },
                    )
            con.commit()
        return exp

    def _count_with_connection(self, con: Any) -> int:
        row = con.execute("SELECT COUNT(*) FROM experiments").fetchone()
        return int(row[0]) if row else 0

    def get(self, exp_id: str) -> Experiment | None:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM experiments WHERE id=?", (exp_id,)).fetchone()
            return Experiment.model_validate_json(row[0]) if row else None

    def all_experiments(self) -> list[Experiment]:
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM experiments ORDER BY trial_count, rowid").fetchall()
            return [Experiment.model_validate_json(r[0]) for r in rows]

    def complete(
        self,
        experiment_id: str,
        *,
        results: dict[str, Any] | None = None,
        conclusion: ConclusionCode | str | None = None,
        failure_reason: str | None = None,
    ) -> Experiment:
        exp = self.get(experiment_id)
        if exp is None:
            raise KeyError(f"experiment {experiment_id} not found")
        status = ExperimentStatus.BLOCKED if conclusion == ConclusionCode.BLOCKED_INSUFFICIENT_DATA else ExperimentStatus.COMPLETED
        if isinstance(conclusion, str) and conclusion == ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value:
            status = ExperimentStatus.BLOCKED
        return self.put(
            exp.with_outcome(
                results=results,
                conclusion=conclusion,
                failure_reason=failure_reason,
                status=status,
            )
        )

    def reject(self, experiment_id: str, reason: str, details: dict[str, object] | None = None) -> None:
        """Record a rejection without removing or changing the trial."""
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO rejections VALUES (?,?,?,?)",
                (f"R-{uuid7()[:8]}", experiment_id, reason, json.dumps(details or {}, default=str)),
            )
            con.commit()
        exp = self.get(experiment_id)
        if exp is not None:
            self.put(
                exp.with_outcome(
                    conclusion=ConclusionCode.REJECTED,
                    failure_reason=reason,
                    status=ExperimentStatus.FAILED,
                )
            )

    def rejections(self, experiment_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        q = "SELECT id, experiment_id, reason, payload FROM rejections"
        args: list[Any] = []
        if experiment_id:
            q += " WHERE experiment_id=?"
            args.append(experiment_id)
        q += " ORDER BY rowid DESC LIMIT ?"
        args.append(int(limit))
        with db_connect(self.db_path) as con:
            rows = con.execute(q, args).fetchall()
        out = []
        for rid, eid, reason, payload in rows:
            try:
                details = json.loads(payload)
            except (TypeError, ValueError):
                details = {"unparseable": True}
            out.append({"id": rid, "experiment_id": eid, "reason": reason, "details": details})
        return out

    def lineage(self, parent: str, child: str, relation: str = "derived") -> None:
        if parent == child:
            raise ValueError("lineage cannot point an experiment to itself")
        with db_connect(self.db_path) as con:
            con.execute("INSERT OR IGNORE INTO lineage VALUES (?,?,?)", (parent, child, relation))
            con.commit()

    def lineage_for(self, experiment_id: str) -> list[dict[str, str]]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT parent, child, relation FROM lineage WHERE parent=? OR child=? ORDER BY rowid",
                (experiment_id, experiment_id),
            ).fetchall()
        return [{"parent": p, "child": c, "relation": r} for p, c, r in rows]

    def events(self, experiment_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT id, event_type, payload, created_at FROM experiment_events "
                "WHERE experiment_id=? ORDER BY created_at, rowid LIMIT ?",
                (experiment_id, int(limit)),
            ).fetchall()
        out = []
        for eid, kind, payload, created in rows:
            try:
                body = json.loads(payload)
            except (TypeError, ValueError):
                body = {"unparseable": True}
            out.append({"id": eid, "event_type": kind, "payload": body, "created_at": created})
        return out

    def _event_with_connection(self, con: Any, experiment_id: str, event_type: str, payload: dict[str, Any]) -> None:
        con.execute(
            "INSERT INTO experiment_events VALUES (?,?,?,?,?)",
            (
                f"EE-{uuid7()[:12]}",
                experiment_id,
                event_type,
                json.dumps(payload, sort_keys=True, default=str),
                datetime.now(UTC).isoformat(),
            ),
        )

    def count_trials(self) -> int:
        with db_connect(self.db_path) as con:
            return self._count_with_connection(con)

    def close(self) -> None:
        # File-backed connections are opened/closed per operation via qts.db.connect.
        # There is intentionally no persistent handle to close or recreate.
        return None

    def __enter__(self) -> ExperimentStore:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
