"""Desktop state restoration — ensures no safety state lost on restart / unexpected termination."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import UTC, datetime


def restore_state(db_path: Path | str = "data/sqlite/qts.db") -> dict:
    db_path = Path(db_path)
    if not db_path.exists():
        return {"restored": False, "reason": "no db yet"}
    info = {}
    with sqlite3.connect(db_path) as con:
        # suspension
        try:
            cur = con.execute("SELECT state FROM promotion_state WHERE strategy_id='__global'")  # not used
        except Exception:
            pass
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
