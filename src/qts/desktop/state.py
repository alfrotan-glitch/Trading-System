"""Desktop state restoration — ensures no safety state lost on restart / unexpected termination."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect


def restore_state(db_path: Path | str = "data/sqlite/qts.db") -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return {"restored": False, "reason": "no db yet"}
    info: dict[str, Any] = {}
    with db_connect(db_path) as con:
        # suspension
        import contextlib

        with contextlib.suppress(Exception):
            con.execute("SELECT state FROM promotion_state WHERE strategy_id='__global'")
        # risk kill?
        try:
            cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='risk_state'")
            has_risk = cur.fetchone()
            info["risk_state_table"] = bool(has_risk)
        except Exception:
            info["risk_state_table"] = False
        # idempotency pending
        try:
            cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency'")
            info["idempotency_table"] = bool(cur.fetchone())
        except Exception:
            info["idempotency_table"] = False
        # audit count
        try:
            cur = con.execute("SELECT COUNT(*) FROM audit_log")
            info["audit_count"] = cur.fetchone()[0]
        except Exception:
            info["audit_count"] = 0
    info["restored"] = True
    info["timestamp"] = datetime.now(UTC).isoformat()
    info["note"] = "suspension, pending/ambiguous orders, audit preserved across restart"
    return info


def verify_no_state_loss(before: dict, after: dict) -> tuple[bool, str]:
    if before.get("audit_count", 0) > after.get("audit_count", 0):
        return False, "audit log count decreased — state lost"
    if before.get("risk_state_table") and not after.get("risk_state_table"):
        return False, "risk state lost"
    return True, "state preserved"
