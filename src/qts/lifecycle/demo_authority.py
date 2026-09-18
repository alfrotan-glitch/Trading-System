"""Authoritative DEMO execution boundary — observation only.

QTS deliberately ships without DEMO_EXECUTION. DEMO_FORWARD may collect
real demo-account observations with zero orders; it cannot be upgraded into an
order-capable state by a readiness report, a request payload, SQLite contents,
or a direct call to :meth:`DemoExecutionAuthority.enable`.

The durable state table is retained for audit/history and fail-closed
inspection. ``current()`` and ``is_execution_permitted()`` never grant broker
permission while this product policy is active. API/UI readiness therefore
remains an observation concern, not an execution switch.
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
# Product policy: the shipped build has no DEMO_EXECUTION order path.
DEMO_EXECUTION_DISABLED = True

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
    """The single authoritative answer consumed by API, UI, and execution.

    Field semantics (two DIFFERENT questions — they may legitimately disagree):

    * ``readiness_passed`` / ``readiness_evidence`` describe the PERSISTED
      DECISION STATE: the readiness report attached to the latest recorded
      authority transition (enablement, refusal, or disable). ``false`` /
      ``none_recorded`` means no passing readiness evidence is durably bound
      to a decision — it is NOT a live statement about the terminal right now.
    * ``current_readiness`` (added by the API layer) describes a FRESH probe
      of the terminal/account/symbol computed in the same request.

    Example of a legitimate, non-contradictory combination: an authority that
    has never been enabled (or whose last recorded decision was a refusal)
    reports ``readiness_passed=false`` while the fresh probe passes and
    ``current_readiness.passed=true``. Execution remains forbidden either way:
    only a FRESH passing report supplied to ``enable()`` can create a durable
    enablement, and permission decays per ``REVERIFY_TTL_S``.
    """

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
            # Disambiguates the two readiness facts that can legitimately
            # disagree. `readiness_evidence` describes the PERSISTED decision
            # record only:
            #   "none"   -> no readiness report is bound to the latest decision
            #               (never enabled, or a disable/refusal with no report).
            #   "failed" -> a readiness report IS recorded and it did not pass.
            #   "passed" -> a readiness report IS recorded and it passed.
            # It is NOT a live probe; `current_readiness.passed` (API layer)
            # is the fresh probe. Both can be true/false independently.
            "readiness_evidence": (
                "none" if not self.readiness else ("passed" if self.readiness.get("passed") else "failed")
            ),
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

        self._audit.emit(DomainEvent(event_type=EventType.LIFECYCLE, payload={"action": action, **payload}))

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
                reasons=(
                    [str(row["reason"] or "disabled")]
                    if row and not row["enabled"]
                    else ["never enabled"]
                ),
                readiness=row["readiness"] if row else None,
                readiness_age_s=None,
                readiness_expired=False,
                mode=row["mode"] if row else None,
            )

        if DEMO_EXECUTION_DISABLED:
            return DemoPermissionDecision(
                enabled=False,
                execution_permitted=False,
                state="DISABLED",
                decided_at=row["decided_at"],
                reasons=[
                    "DEMO_EXECUTION is disabled by product policy",
                    "DEMO_FORWARD observation-only is the only broker mode",
                ],
                readiness=row["readiness"],
                readiness_age_s=row["readiness_age_s"],
                readiness_expired=False,
                mode=row["mode"],
                detail={"historical_enabled_row": True},
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
                reasons.append(
                    f"readiness evidence expired ({age:.0f}s old > {REVERIFY_TTL_S:.0f}s) — re-verify required"
                )

        permitted = not reasons
        from qts.domain.modes import ExecutionMode

        # LIVE mode binding (fail-closed): the process ASKING whether execution
        # is permitted must itself run in a mode that may submit broker orders.
        # This is checked against the authority's CURRENTLY resolved mode, not
        # only the stored row: a DEMO_FORWARD (observe-only) process can never
        # hold execution permission, even if the stored row is tampered to
        # enabled=1 with a broker-capable or NULL mode (documented contract).
        if self._mode is not None:
            try:
                live_mode = ExecutionMode(str(self._mode))
                if not live_mode.can_submit_broker_orders:
                    permitted = False
                    reasons.append(f"live mode {live_mode.value} cannot submit broker orders")
            except ValueError:
                permitted = False
                reasons.append(f"live mode {self._mode!r} unresolvable — fail closed")

        if row.get("mode") is not None:
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
            # Expiry is ONLY about evidence age. A refusal for a different
            # reason (mode not broker-capable, unreadable timestamp, tampering)
            # must not masquerade as "readiness expired" — distinct blockers,
            # distinct operator actions.
            readiness_expired=bool(age is not None and age > REVERIFY_TTL_S),
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
        """Refuse every DEMO_EXECUTION enablement in the shipped product.

        This method remains as an explicit fail-closed boundary for callers
        that still use the historical authority API. It records a refusal for
        audit/history, but never writes ``enabled=1`` and never returns an
        execution-permitted decision. Readiness is useful for observation
        startup only and cannot be converted into order permission.
        """
        reason = "DEMO_EXECUTION is disabled by product policy; use DEMO_FORWARD OBSERVE_ONLY"
        reasons = [reason]
        if not confirmed or not risk_ack:
            reasons.append("explicit confirmation (confirmed=true) and risk acknowledgement (risk_ack=true) are still required")
        if not readiness.get("passed"):
            blocked = readiness.get("blocked_reasons") or ["readiness report does not show passed=true"]
            reasons.extend(f"readiness: {item}" for item in blocked)
        if readiness.get("warn_live_in_demo"):
            reasons.append("LIVE account supplied to DEMO mode — blocked")
        checks = readiness.get("checks") or {}
        required = readiness.get("required_checks") or []
        reasons.extend(f"readiness check failed: {item}" for item in required if not checks.get(item))
        if self._mode == "DEMO_FORWARD":
            reasons.append("mode DEMO_FORWARD is observation-only and cannot submit broker orders")
        if self._audit is not None:
            try:
                self._emit_audit("demo_execution_refused", {"reason": reason, "actor": actor})
            except Exception as exc:
                reasons.append(f"audit failed while recording refusal: {exc}")
        self._record(
            enabled=False,
            reason=f"refused: {reason}",
            confirmed=confirmed,
            risk_ack=risk_ack,
            readiness=readiness,
            readiness_age_s=readiness_age_s,
            actor=actor,
            audit=False,  # explicit refusal audit attempted above
        )
        return DemoPermissionDecision(
            enabled=False,
            execution_permitted=False,
            state="DISABLED",
            decided_at=datetime.now(UTC).isoformat(),
            reasons=reasons,
            readiness=readiness,
            readiness_age_s=readiness_age_s,
            readiness_expired=False,
            mode=self._mode,
            detail={"product_policy": "DEMO_EXECUTION_DISABLED"},
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
        return max(((now or datetime.now(UTC)) - t).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return 0.0
