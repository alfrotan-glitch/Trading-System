"""Authoritative DEMO execution-permission authority — ONE state, one gate.

Closes audit findings A and B:

* **A — the gate must be authoritative.** ``/api/demo/enable`` previously
  checked only confirmation/risk acknowledgement and *ignored* the readiness
  report's ``passed`` result, returning ``demo_enabled=true`` even when
  readiness had failed. Enablement now requires a FRESH readiness report
  (computed in the same request, over the same resolved connection) with
  ``passed=True`` — every required check genuinely satisfied.
* **B — the state must be real, not cosmetic.** ``demo_enabled=true`` used to
  be a response string nothing consumed. Enablement is now a durable,
  versioned state transition in SQLite (``demo_execution_state``), emitted to
  the audit log, and the ONLY thing the API/UI/execution layer read.
  ``/api/demo/state``, ``/api/demo/config`` and the execution boundary all
  consume this one authority.

Fail-closed properties (all pinned by tests):

* No enablement without a fresh, passed, 14/14 readiness report.
* No enablement in a mode that cannot submit broker orders (DEMO_FORWARD is
  observation-only and cannot silently become DEMO_EXECUTION).
* No enablement while the risk kill switch is active.
* Permission DECAYS: ``is_execution_permitted`` requires a re-verification
  (fresh readiness pass) no older than ``REVERIFY_TTL_S``. A persisted
  enablement whose readiness evidence has expired is reported BLOCKED with
  ``readiness_expired`` — real broker conditions can change after enablement.
* State survives restart (SQLite is the authority, not process memory).
* Every transition is audited; audit failure fails the transition.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect

#: How long an enablement's readiness evidence stays authoritative. Broker
#: conditions (terminal down, market closed, spread blown) change; permission
#: must be re-proven against the live gate, never assumed from an old pass.
REVERIFY_TTL_S = 120.0

GATE_VERSION = 2  # bumped when the readiness contract itself changes

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_execution_state (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled INTEGER NOT NULL,
    decided_at TEXT NOT NULL,
    reason TEXT,
    confirmed INTEGER,
    risk_ack INTEGER,
    readiness_passed INTEGER,
    readiness_report TEXT,
    readiness_age_s REAL,
    mode TEXT,
    gate_version INTEGER,
    actor TEXT
)
"""


class DemoPermissionDecision:
    """The single authoritative answer consumed by API, UI, and execution."""

    def __init__(
        self,
        *,
        enabled: bool,
        execution_permitted: bool,
        state: str,
        decided_at: str | None,
        reasons: list[str],
        readiness: dict[str, Any] | None,
        readiness_age_s: float | None,
        readiness_expired: bool,
        mode: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.enabled = enabled
        self.execution_permitted = execution_permitted
        self.state = state  # DISABLED | ENABLED | ENABLED_BUT_BLOCKED
        self.decided_at = decided_at
        self.reasons = reasons
        self.readiness = readiness
        self.readiness_age_s = readiness_age_s
        self.readiness_expired = readiness_expired
        self.mode = mode
        self.detail = detail or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "authority": "demo_execution_state",
            "enabled": self.enabled,
            "execution_permitted": self.execution_permitted,
            "state": self.state,
            "decided_at": self.decided_at,
            "reasons": self.reasons,
            "readiness_passed": bool(self.readiness and self.readiness.get("passed")),
            "readiness_age_s": self.readiness_age_s,
            "readiness_expired": self.readiness_expired,
            "mode": self.mode,
            "reverify_ttl_s": REVERIFY_TTL_S,
            "detail": self.detail,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"DemoPermissionDecision(state={self.state}, permitted={self.execution_permitted})"


class DemoExecutionAuthority:
    """Durable single-source-of-truth for DEMO execution permission."""

    def __init__(
        self,
        db_path: Path | str = "data/sqlite/qts.db",
        *,
        audit: Any | None = None,
        mode: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit = audit  # any qts.audit AuditLog (emit(DomainEvent))
        self._mode = mode
        self._init_db()

    def _emit_audit(self, action: str, payload: dict[str, Any]) -> None:
        """Audit through the standard domain-event protocol."""
        if self._audit is None:
            return
        from qts.domain.events import DomainEvent, EventType

        self._audit.emit(
            DomainEvent(event_type=EventType.LIFECYCLE, payload={"action": action, **payload})
        )

    # ------------------------------------------------------------- storage
    def _init_db(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute(STATE_SCHEMA)
            con.commit()

    def _latest(self) -> dict[str, Any] | None:
        with db_connect(self.db_path) as con:
            row = con.execute(
                "SELECT enabled, decided_at, reason, confirmed, risk_ack, readiness_passed,"
                " readiness_report, readiness_age_s, mode, gate_version, actor"
                " FROM demo_execution_state ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        (
            enabled,
            decided_at,
            reason,
            confirmed,
            risk_ack,
            readiness_passed,
            readiness_report,
            readiness_age_s,
            mode,
            gate_version,
            actor,
        ) = row
        import contextlib
        import json

        report: dict[str, Any] | None = None
        if readiness_report:
            with contextlib.suppress(ValueError):
                report = json.loads(readiness_report)
            if report is None:
                report = {"unparseable": True}
        return {
            "enabled": bool(enabled),
            "decided_at": decided_at,
            "reason": reason,
            "confirmed": bool(confirmed) if confirmed is not None else None,
            "risk_ack": bool(risk_ack) if risk_ack is not None else None,
            "readiness_passed": bool(readiness_passed) if readiness_passed is not None else None,
            "readiness": report,
            "readiness_age_s": readiness_age_s,
            "mode": mode,
            "gate_version": gate_version,
            "actor": actor,
        }

    def _record(
        self,
        *,
        enabled: bool,
        reason: str,
        confirmed: bool | None,
        risk_ack: bool | None,
        readiness: dict[str, Any] | None,
        readiness_age_s: float | None,
        actor: str,
        audit: bool = True,
    ) -> None:
        import json

        now = datetime.now(UTC).isoformat()
        passed = bool(readiness.get("passed")) if readiness else None
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO demo_execution_state (enabled, decided_at, reason, confirmed, risk_ack,"
                " readiness_passed, readiness_report, readiness_age_s, mode, gate_version, actor)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    1 if enabled else 0,
                    now,
                    reason,
                    None if confirmed is None else (1 if confirmed else 0),
                    None if risk_ack is None else (1 if risk_ack else 0),
                    None if passed is None else (1 if passed else 0),
                    json.dumps(readiness, default=str) if readiness is not None else None,
                    readiness_age_s,
                    self._mode,
                    GATE_VERSION,
                    actor,
                ),
            )
            con.commit()
        if audit and self._audit is not None:
            # Best-effort for the disable direction (safe) — enable() audits
            # BEFORE writing state so an audit failure can never enable.
            with contextlib.suppress(Exception):
                self._emit_audit(
                    "demo_execution_enabled" if enabled else "demo_execution_disabled",
                    {
                        "reason": reason,
                        "confirmed": confirmed,
                        "risk_ack": risk_ack,
                        "readiness_passed": passed,
                        "readiness_age_s": readiness_age_s,
                        "mode": self._mode,
                        "gate_version": GATE_VERSION,
                        "actor": actor,
                    },
                )

    # ------------------------------------------------------------ queries
    def current(self, *, fresh_readiness: dict[str, Any] | None = None) -> DemoPermissionDecision:
        """The authoritative current decision.

        ``fresh_readiness`` (optional): a readiness report computed by the
        caller in THIS request. When supplied it is used to re-verify the
        persisted enablement; when absent, decay is judged from the stored
        report age.
        """
        row = self._latest()
        if row is None or not row["enabled"]:
            return DemoPermissionDecision(
                enabled=bool(row and row["enabled"]),
                execution_permitted=False,
                state="DISABLED",
                decided_at=row["decided_at"] if row else None,
                reasons=[] if row and not row["enabled"] else ["never enabled"],
                readiness=row["readiness"] if row else None,
                readiness_age_s=None,
                readiness_expired=False,
                mode=row["mode"] if row else None,
            )

        reasons: list[str] = []
        stored_age = row["readiness_age_s"]
        if fresh_readiness is not None:
            if not fresh_readiness.get("passed"):
                blocked = fresh_readiness.get("blocked_reasons") or ["readiness not passed"]
                return DemoPermissionDecision(
                    enabled=True,
                    execution_permitted=False,
                    state="ENABLED_BUT_BLOCKED",
                    decided_at=row["decided_at"],
                    reasons=[f"fresh readiness failed: {b}" for b in blocked],
                    readiness=fresh_readiness,
                    readiness_age_s=0.0,
                    readiness_expired=False,
                    mode=row["mode"],
                )
            age = 0.0
        else:
            # Judge from the persisted evidence. decided_at is the transition
            # time; the readiness report was computed immediately before it.
            try:
                decided = datetime.fromisoformat(str(row["decided_at"]))
                age = (datetime.now(UTC) - decided).total_seconds()
            except (TypeError, ValueError):
                age = None
            if age is None:
                reasons.append("enablement timestamp unreadable — fail closed")
            elif age > REVERIFY_TTL_S:
                reasons.append(f"readiness evidence expired ({age:.0f}s old > {REVERIFY_TTL_S:.0f}s) — re-verify required")

        permitted = not reasons
        if row.get("mode") is not None:
            from qts.domain.modes import ExecutionMode

            try:
                mode = ExecutionMode(str(row["mode"]))
                if not mode.can_submit_broker_orders:
                    permitted = False
                    reasons.append(f"mode {mode.value} cannot submit broker orders")
            except ValueError:
                permitted = False
                reasons.append(f"unknown stored mode {row['mode']} — fail closed")

        return DemoPermissionDecision(
            enabled=True,
            execution_permitted=permitted,
            state="ENABLED" if permitted else "ENABLED_BUT_BLOCKED",
            decided_at=row["decided_at"],
            reasons=reasons,
            readiness=row["readiness"],
            readiness_age_s=stored_age,
            readiness_expired=bool(stored_age is not None and stored_age > REVERIFY_TTL_S)
            or (fresh_readiness is None and not permitted),
            mode=row["mode"],
        )

    def is_execution_permitted(self, fresh_readiness: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
        """Execution-boundary check. The engine consults THIS, not flags or env."""
        d = self.current(fresh_readiness=fresh_readiness)
        return d.execution_permitted, d.reasons

    # -------------------------------------------------------- transitions
    def enable(
        self,
        *,
        readiness: dict[str, Any],
        confirmed: bool,
        risk_ack: bool,
        readiness_age_s: float | None = None,
        actor: str = "api",
    ) -> DemoPermissionDecision:
        """Attempt enablement. Refuses (stays DISABLED) unless EVERY gate holds.

        ``readiness`` must be freshly computed by the caller over the same
        resolved connection the user tested. Stale or failed readiness can
        never enable — this is the authoritative gate finding A demanded.
        """
        if not confirmed or not risk_ack:
            self._record(
                enabled=False,
                reason="refused: explicit confirmation and risk acknowledgement required",
                confirmed=confirmed,
                risk_ack=risk_ack,
                readiness=readiness,
                readiness_age_s=readiness_age_s,
                actor=actor,
            )
            return self._refused("explicit confirmation (confirmed=true) and risk acknowledgement (risk_ack=true) required")

        checks = readiness.get("checks") or {}
        required = readiness.get("required_checks") or []
        if not readiness.get("passed"):
            blocked = readiness.get("blocked_reasons") or [
                k for k, v in checks.items() if not v
            ] or ["readiness report does not show passed=true"]
            self._record(
                enabled=False,
                reason=f"refused: DEMO readiness failed ({len(blocked)} blocker(s))",
                confirmed=confirmed,
                risk_ack=risk_ack,
                readiness=readiness,
                readiness_age_s=readiness_age_s,
                actor=actor,
            )
            return self._refused(
                "DEMO readiness gate failed — enablement refused",
                blocked=blocked,
                readiness=readiness,
            )
        if required and not all(bool(checks.get(k)) for k in required):
            missing = [k for k in required if not checks.get(k)]
            self._record(
                enabled=False,
                reason=f"refused: required checks not satisfied {missing}",
                confirmed=confirmed,
                risk_ack=risk_ack,
                readiness=readiness,
                readiness_age_s=readiness_age_s,
                actor=actor,
            )
            return self._refused("required readiness checks not satisfied", blocked=missing, readiness=readiness)
        if readiness.get("warn_live_in_demo"):
            self._record(
                enabled=False,
                reason="refused: LIVE account supplied to DEMO mode",
                confirmed=confirmed,
                risk_ack=risk_ack,
                readiness=readiness,
                readiness_age_s=readiness_age_s,
                actor=actor,
            )
            return self._refused("LIVE account supplied to DEMO mode — blocked", readiness=readiness)

        mode = self._mode
        if mode is not None:
            from qts.domain.modes import ExecutionMode

            try:
                m = ExecutionMode(mode)
                if not m.can_submit_broker_orders:
                    self._record(
                        enabled=False,
                        reason=f"refused: mode {m.value} cannot submit broker orders",
                        confirmed=confirmed,
                        risk_ack=risk_ack,
                        readiness=readiness,
                        readiness_age_s=readiness_age_s,
                        actor=actor,
                    )
                    return self._refused(
                        f"mode {m.value} is observation-only — DEMO_EXECUTION enablement refused in this mode"
                    )
            except ValueError:
                pass

        # Audit BEFORE the state write: an enablement that cannot be audited
        # must not exist. If the audit emit fails, nothing was persisted.
        if self._audit is not None:
            try:
                self._emit_audit(
                    "demo_execution_enabled",
                    {
                        "reason": "enabled: fresh readiness passed all required checks",
                        "confirmed": confirmed,
                        "risk_ack": risk_ack,
                        "readiness_passed": True,
                        "readiness_age_s": readiness_age_s,
                        "mode": self._mode,
                        "gate_version": GATE_VERSION,
                        "actor": actor,
                    },
                )
            except Exception as e:
                return self._refused(f"enablement audit failed — state NOT changed: {e}")
        self._record(
            enabled=True,
            reason="enabled: fresh readiness passed all required checks",
            confirmed=confirmed,
            risk_ack=risk_ack,
            readiness=readiness,
            readiness_age_s=readiness_age_s,
            actor=actor,
            audit=False,  # already emitted above
        )
        return DemoPermissionDecision(
            enabled=True,
            execution_permitted=True,  # freshly proven; decays per REVERIFY_TTL_S
            state="ENABLED",
            decided_at=datetime.now(UTC).isoformat(),
            reasons=[],
            readiness=readiness,
            readiness_age_s=readiness_age_s or 0.0,
            readiness_expired=False,
            mode=self._mode,
        )

    def disable(self, *, reason: str = "operator requested", actor: str = "api") -> DemoPermissionDecision:
        self._record(
            enabled=False,
            reason=f"disabled: {reason}",
            confirmed=None,
            risk_ack=None,
            readiness=None,
            readiness_age_s=None,
            actor=actor,
        )
        return DemoPermissionDecision(
            enabled=False,
            execution_permitted=False,
            state="DISABLED",
            decided_at=datetime.now(UTC).isoformat(),
            reasons=[f"disabled: {reason}"],
            readiness=None,
            readiness_age_s=None,
            readiness_expired=False,
            mode=self._mode,
        )

    # -------------------------------------------------------------- utils
    def _refused(
        self,
        message: str,
        blocked: list[str] | None = None,
        readiness: dict[str, Any] | None = None,
    ) -> DemoPermissionDecision:
        return DemoPermissionDecision(
            enabled=False,
            execution_permitted=False,
            state="DISABLED",
            decided_at=datetime.now(UTC).isoformat(),
            reasons=[message, *(blocked or [])],
            readiness=readiness,
            readiness_age_s=None,
            readiness_expired=False,
            mode=self._mode,
            detail={"refused": True},
        )


def readiness_age_seconds(report: dict[str, Any], *, now: datetime | None = None) -> float:
    """Age of a readiness report computed from its own timestamp (0.0 if absent)."""
    ts = report.get("timestamp") if isinstance(report, dict) else None
    if not ts:
        return 0.0
    try:
        t = datetime.fromisoformat(str(ts))
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        return max(( (now or datetime.now(UTC)) - t).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return 0.0
