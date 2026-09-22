"""Desktop state restoration — ensures no safety state lost on restart / unexpected termination."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect


def _optional_row(con: Any, sql: str) -> tuple[Any, str | None]:
    """One row, or ``(None, None)`` when the table was never created.

    Any other read failure is returned as an error string. A missing table is
    not a loss; an unreadable table is.
    """
    try:
        return con.execute(sql).fetchone(), None
    except Exception as exc:
        if "no such table" in str(exc).lower():
            return None, None
        return None, f"{type(exc).__name__}: {exc}"


def restore_state(db_path: Path | str = "data/sqlite/qts.db") -> dict[str, Any]:
    """Read the durable safety rows. Does not claim preservation by itself.

    The previous implementation queried ``promotion_state`` and discarded the
    result, looked for an ``audit_log`` table that does not exist (the store is
    ``audit_events``), and then reported that suspension, pending orders and
    the audit log had been preserved. A missing table became ``audit_count=0``,
    so ``verify_no_state_loss`` passed without reading anything that matters.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {"restored": False, "reason": "no db yet", "read_error": None}
    info: dict[str, Any] = {"read_error": None}
    errors: list[str] = []
    with db_connect(db_path) as con:
        row, err = _optional_row(con, "SELECT killed, reason FROM risk_state WHERE k=1")
        if err:
            errors.append(f"risk_state: {err}")
            info["killed"] = None
        else:
            info["killed"] = bool(row[0]) if row else False
            info["kill_reason"] = row[1] if row else None
        row, err = _optional_row(con, "SELECT suspended, reason FROM reconcile_state WHERE k=1")
        if err:
            errors.append(f"reconcile_state: {err}")
            info["suspended"] = None
        else:
            info["suspended"] = bool(row[0]) if row else False
            info["suspend_reason"] = row[1] if row else None
        row, err = _optional_row(con, "SELECT COUNT(*) FROM audit_events")
        if err:
            errors.append(f"audit_events: {err}")
            info["audit_count"] = None
        else:
            info["audit_count"] = int(row[0]) if row else 0
        row, err = _optional_row(con, "SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency'")
        if err:
            errors.append(f"idempotency: {err}")
            info["idempotency_table"] = None
        else:
            info["idempotency_table"] = row is not None
    info["restored"] = True
    info["read_error"] = "; ".join(errors) if errors else None
    info["timestamp"] = datetime.now(UTC).isoformat()
    info["note"] = "read risk_state.killed, reconcile_state.suspended, and audit_events count; nothing else was checked"
    return info


def verify_no_state_loss(before: dict, after: dict) -> tuple[bool, str]:
    """Fail closed when a durable kill, suspension, or audit row disappears.

    Absent on both sides is not loss. An unreadable side is not "preserved".
    """
    if before.get("read_error") or after.get("read_error"):
        return False, (
            f"state not verified — read error before={before.get('read_error')!r} after={after.get('read_error')!r}"
        )
    before_audit = before.get("audit_count")
    after_audit = after.get("audit_count")
    if isinstance(before_audit, int) and isinstance(after_audit, int) and before_audit > after_audit:
        return False, "audit log count decreased — state lost"
    if before.get("killed") is True and after.get("killed") is not True:
        return False, "kill switch cleared across restart"
    if before.get("suspended") is True and after.get("suspended") is not True:
        return False, "reconcile suspension cleared across restart"
    return True, "compared kill, suspension, and audit count; no loss observed"
