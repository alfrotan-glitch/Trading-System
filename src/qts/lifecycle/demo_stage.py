"""DEMO execution state machine — staged progression, never a jump.

The owner's staged progression is encoded as an explicit, persisted state
machine so that "we are allowed to trade" can never be inferred from a flag:

    DISABLED ──► STAGE_1_CONNECTIVITY ──► STAGE_2_MIN_SIZE_ORDER
                                                │
                                                ▼
                                    STAGE_3_FORWARD_OBSERVATION
    any stage ──► HALTED (kill switch / operator / any failed safeguard)

Rules:

* every transition is recorded with actor, reason and the prerequisite
  evidence that justified it;
* a transition whose prerequisites are unmet is **refused and recorded** — the
  refusal is durable evidence, never a silent no-op;
* ``HALTED`` is reachable from anywhere and only leaves through an explicit
  re-arm (``DISABLED``), so a halt cannot be aged away;
* only ``STAGE_2`` and ``STAGE_3`` permit order submission (:data:`ORDER_STAGES`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect


class DemoStage(StrEnum):
    DISABLED = "DISABLED"
    STAGE_1_CONNECTIVITY = "STAGE_1_CONNECTIVITY"
    STAGE_2_MIN_SIZE_ORDER = "STAGE_2_MIN_SIZE_ORDER"
    STAGE_3_FORWARD_OBSERVATION = "STAGE_3_FORWARD_OBSERVATION"
    HALTED = "HALTED"


#: Stages in which a DEMO order may actually be sent.
ORDER_STAGES = frozenset({DemoStage.STAGE_2_MIN_SIZE_ORDER.value, DemoStage.STAGE_3_FORWARD_OBSERVATION.value})

_TRANSITIONS: dict[DemoStage, frozenset[DemoStage]] = {
    DemoStage.DISABLED: frozenset({DemoStage.STAGE_1_CONNECTIVITY, DemoStage.HALTED}),
    DemoStage.STAGE_1_CONNECTIVITY: frozenset(
        {DemoStage.STAGE_2_MIN_SIZE_ORDER, DemoStage.HALTED, DemoStage.DISABLED}
    ),
    DemoStage.STAGE_2_MIN_SIZE_ORDER: frozenset(
        {DemoStage.STAGE_3_FORWARD_OBSERVATION, DemoStage.HALTED, DemoStage.STAGE_1_CONNECTIVITY}
    ),
    DemoStage.STAGE_3_FORWARD_OBSERVATION: frozenset({DemoStage.HALTED, DemoStage.STAGE_1_CONNECTIVITY}),
    DemoStage.HALTED: frozenset({DemoStage.DISABLED}),
}

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_execution_stage (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    previous_stage TEXT,
    decided_at TEXT NOT NULL,
    reason TEXT,
    actor TEXT,
    prerequisites TEXT,
    allowed INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class StageRecord:
    stage: str
    previous_stage: str | None
    decided_at: str
    reason: str
    actor: str
    allowed: bool
    prerequisites: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "previous_stage": self.previous_stage,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "actor": self.actor,
            "allowed": self.allowed,
            "prerequisites": dict(self.prerequisites),
            "orders_permitted": self.stage in ORDER_STAGES,
        }


class StageTransitionError(RuntimeError):
    """A requested transition was refused (illegal edge or unmet prerequisites)."""


class DemoStageMachine:
    """Durable staged-progression controller for DEMO execution."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            # Anchored at the machine-local state root, never at cwd: a stage
            # machine read from a different directory would report DISABLED
            # while another process reports STAGE_2.
            from qts.config.paths import artifact_path

            db_path = artifact_path("stage_db")
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ store
    def _init_db(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute(STATE_SCHEMA)
            con.commit()

    def _insert(self, *, stage: str, previous: str | None, reason: str, actor: str, allowed: bool, prereq: dict) -> None:
        import json

        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO demo_execution_stage (stage, previous_stage, decided_at, reason, actor,"
                " prerequisites, allowed) VALUES (?,?,?,?,?,?,?)",
                (
                    stage,
                    previous,
                    datetime.now(UTC).isoformat(),
                    reason,
                    actor,
                    json.dumps(prereq, default=str),
                    1 if allowed else 0,
                ),
            )
            con.commit()

    # ---------------------------------------------------------------- queries
    def current(self) -> StageRecord:
        with db_connect(self.db_path) as con:
            row = con.execute(
                "SELECT stage, previous_stage, decided_at, reason, actor, prerequisites, allowed"
                " FROM demo_execution_stage ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return StageRecord(
                stage=DemoStage.DISABLED.value,
                previous_stage=None,
                decided_at=datetime.now(UTC).isoformat(),
                reason="no transition recorded — DEMO execution starts DISABLED",
                actor="system",
                allowed=True,
                prerequisites={},
            )
        import json

        try:
            prereq = json.loads(row[5]) if row[5] else {}
        except ValueError:
            prereq = {"unparseable": True}
        return StageRecord(
            stage=row[0],
            previous_stage=row[1],
            decided_at=row[2],
            reason=row[3] or "",
            actor=row[4] or "",
            allowed=bool(row[6]),
            prerequisites=prereq,
        )

    def history(self, limit: int = 50) -> list[StageRecord]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT stage, previous_stage, decided_at, reason, actor, prerequisites, allowed"
                " FROM demo_execution_stage ORDER BY seq DESC LIMIT ?",
                (limit,),
            ).fetchall()
        import json

        out: list[StageRecord] = []
        for row in rows:
            try:
                prereq = json.loads(row[5]) if row[5] else {}
            except ValueError:
                prereq = {"unparseable": True}
            out.append(
                StageRecord(
                    stage=row[0],
                    previous_stage=row[1],
                    decided_at=row[2],
                    reason=row[3] or "",
                    actor=row[4] or "",
                    allowed=bool(row[6]),
                    prerequisites=prereq,
                )
            )
        return out

    # ----------------------------------------------------------- transitions
    def can_advance(self, target: DemoStage | str, prerequisites: dict[str, bool] | None = None) -> tuple[bool, str]:
        current = self.current()
        try:
            target_stage = DemoStage(str(target))
        except ValueError:
            return False, f"unknown stage {target!r} — fail closed"
        if target_stage not in _TRANSITIONS[DemoStage(current.stage)]:
            return False, f"transition {current.stage} → {target_stage.value} is not allowed"
        unmet = [name for name, ok in (prerequisites or {}).items() if not ok]
        if unmet:
            return False, f"prerequisites unmet: {', '.join(sorted(unmet))}"
        return True, "ok"

    def advance(
        self,
        target: DemoStage | str,
        *,
        actor: str = "cli",
        reason: str = "",
        prerequisites: dict[str, bool] | None = None,
    ) -> StageRecord:
        """Attempt a transition; record it either way (refusals included)."""
        current = self.current()
        allowed, detail = self.can_advance(target, prerequisites)
        record = StageRecord(
            stage=DemoStage(str(target)).value if allowed else current.stage,
            previous_stage=current.stage,
            decided_at=datetime.now(UTC).isoformat(),
            reason=reason or detail,
            actor=actor,
            allowed=allowed,
            prerequisites=dict(prerequisites or {}),
        )
        self._insert(
            stage=record.stage,
            previous=current.stage,
            reason=record.reason,
            actor=actor,
            allowed=allowed,
            prereq=record.prerequisites,
        )
        if not allowed:
            raise StageTransitionError(detail)
        return record

    def halt(self, *, reason: str, actor: str = "system") -> StageRecord:
        """Immediate, always-allowed transition to HALTED."""
        current = self.current()
        record = StageRecord(
            stage=DemoStage.HALTED.value,
            previous_stage=current.stage,
            decided_at=datetime.now(UTC).isoformat(),
            reason=reason,
            actor=actor,
            allowed=True,
            prerequisites={},
        )
        self._insert(
            stage=record.stage,
            previous=current.stage,
            reason=reason,
            actor=actor,
            allowed=True,
            prereq={},
        )
        return record

    def reset_to_disabled(self, *, reason: str, actor: str = "cli") -> StageRecord:
        """Re-arm path: only from HALTED (a halt must be acknowledged)."""
        return self.advance(DemoStage.DISABLED, actor=actor, reason=reason)

    def as_dict(self) -> dict[str, Any]:
        current = self.current()
        return {
            "current": current.as_dict(),
            "order_stages": sorted(ORDER_STAGES),
            "allowed_next": sorted(s.value for s in _TRANSITIONS[DemoStage(current.stage)]),
            "history": [r.as_dict() for r in self.history(limit=20)],
        }
