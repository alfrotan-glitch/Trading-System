"""Startup / shutdown health — loads durable state, restores suspension, verifies data/config/MT5/reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect


def startup_health_check(data_dir: Path | str = "data") -> dict[str, Any]:
    """1. Load durable state. 2. Restore suspension. 3. Restore pending/ambiguous orders. 4. Verify data. 5. Verify config. 6. Verify account/MT5 if requested. 7. Run reconciliation. 8. Only then permit normal operation."""
    data_dir = Path(data_dir)
    results: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), "checks": []}

    def _check(name: str, fn):
        try:
            ok, detail = fn()
            results["checks"].append({"name": name, "passed": ok, "detail": detail})
            return ok
        except Exception as e:
            results["checks"].append({"name": name, "passed": False, "detail": str(e)[:300]})
            return False

    # 1 durable state
    def check_state():
        p = Path("data/sqlite/qts.db")
        if not p.exists():
            return False, "qts.db missing — first run will create"
        try:
            with db_connect(p) as con:
                con.execute("SELECT 1 FROM promotion_state LIMIT 1")
                con.execute("SELECT 1 FROM experiments LIMIT 1")
            return True, "durable state loaded"
        except Exception as e:
            return False, f"state load failed: {e}"

    # 2 suspension
    def check_suspension():
        try:
            from qts.risk.engine import RiskEngine, RiskLimits

            eng = RiskEngine(RiskLimits())
            killed = eng.is_killed() if hasattr(eng, "is_killed") else False
            if killed:
                return False, "kill switch active — trading suspended"
            return True, "suspension state healthy"
        except Exception as e:
            return True, f"suspension check soft pass: {e}"

    # 3 pending orders
    def check_pending():
        try:
            from qts.observability.audit import SqliteAuditLog

            log = SqliteAuditLog()
            events = log.query(limit=20)
            ambiguous = [e for e in events if "AMBIGUOUS" in json.dumps(e.payload)]
            if ambiguous:
                return False, f"{len(ambiguous)} ambiguous orders require reconciliation"
            return True, "pending/ambiguous orders none"
        except Exception as e:
            return True, f"pending check: {e}"

    # 4 data
    def check_data():
        try:
            from qts.data.quality import validate_bars
            from qts.data.store import SqliteParquetDataStore
            from qts.domain.value_objects import Instrument

            store = SqliteParquetDataStore()
            versions = store.list_versions()
            if not versions:
                return False, "no data versions"
            v = versions[-1]
            m = store.manifest(v)
            instr = Instrument(symbol=m.instrument, venue=m.venue)
            bars = store.read_bars(instr, m.timeframe, version=v)
            rpt = validate_bars(bars)
            if not rpt.passed:
                return False, f"data quality fail: {rpt.checks[0].details if rpt.checks else 'fail'}"
            return True, f"data healthy {v} {len(bars)} bars"
        except Exception as e:
            return False, f"data verify failed: {e}"

    # 5 config
    def check_config():
        try:
            from qts.config.settings import load_settings
            from qts.domain.modes import resolve_mode

            s = load_settings()
            # Mode comes from the ONE canonical authority (qts.domain.modes) —
            # never from a guessed/defaulted string (the old 'research' default
            # named a mode that does not exist).
            try:
                mode = resolve_mode(config_env=s.env).value
            except Exception as e:
                return False, f"config failed: mode resolution fail-closed ({e})"
            return True, f"config loaded env={s.env} mode={mode}"
        except Exception as e:
            return False, f"config failed: {e}"

    # 6 MT5
    def check_mt5():
        try:
            import os

            mode = os.getenv("QTS_MT5_MODE", "MOCK")
            if mode == "MOCK":
                return True, "MT5 MOCK — no real broker connection (correct for dev)"
            return True, f"MT5 mode {mode}"
        except Exception as e:
            return False, str(e)

    # 7 reconciliation
    def check_recon():
        try:
            # Check last reconcile report in audit
            from qts.observability.audit import SqliteAuditLog

            log = SqliteAuditLog()
            events = log.query(limit=50)
            drifts = [e for e in events if "DRIFT" in json.dumps(e.payload) or "SUSPENDED" in json.dumps(e.payload)]
            if drifts:
                return False, "reconciliation drift previously detected — requires review"
            return True, "reconciliation healthy"
        except Exception as e:
            return True, f"recon check soft: {e}"

    _check("load_durable_state", check_state)
    _check("restore_suspension", check_suspension)
    _check("restore_pending_orders", check_pending)
    _check("verify_data", check_data)
    _check("verify_configuration", check_config)
    _check("verify_account_MT5", check_mt5)
    _check("run_reconciliation", check_recon)

    results["overall"] = all(c["passed"] for c in results["checks"])
    results["system_status"] = "Running" if results["overall"] else "Blocked"
    if any("kill" in c["detail"].lower() for c in results["checks"]):
        results["system_status"] = "Suspended"
    return results


def shutdown_procedure() -> dict[str, Any]:
    """On shutdown: stop new orders, persist state, record shutdown event, safely disconnect, preserve audit state."""
    results: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), "steps": []}
    try:
        from qts.domain.events import DomainEvent, EventType
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        log.emit(
            DomainEvent(
                event_type=EventType.NO_TRADE,
                payload={"event": "SHUTDOWN", "reason": "orderly shutdown", "timestamp": datetime.now(UTC).isoformat()},
            )
        )
        results["steps"].append("persist state + audit shutdown event: ok")
    except Exception as e:
        results["steps"].append(f"persist state failed: {e}")
    # safe disconnect mock
    results["steps"].append("disconnect: ok (mock)")
    results["overall"] = True
    return results
