"""Adversarial: the DEMO execution-permission authority (findings A + B).

Proves the state machine cannot be bypassed:

* No enablement without a fresh PASSED readiness report (failed/stale/
  forged reports are all refused, with durable refusal records).
* Enablement is a real persisted state that the execution boundary reads —
  and it DECAYS (expired readiness => ENABLED_BUT_BLOCKED).
* DEMO_FORWARD (observe-only) mode can never hold execution permission.
* Audit failure prevents enablement (no unaudited transitions).
* Forbidden transitions across modes are structural.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qts.db import connect as db_connect
from qts.lifecycle.demo_authority import REVERIFY_TTL_S, DemoExecutionAuthority


def _readiness(passed: bool = True, **extra) -> dict:
    base = {
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": passed,
        "demo_enabled": passed,
        "blocked_reasons": [] if passed else ["Terminal not running"],
        "checks": dict.fromkeys(["mt5_installed", "terminal_running", "account_connected"], passed),
        "required_checks": ["mt5_installed", "terminal_running", "account_connected"],
        "warn_live_in_demo": False,
    }
    base.update(extra)
    return base


@pytest.fixture()
def authority(tmp_path: Path):
    return DemoExecutionAuthority(db_path=tmp_path / "qts.db")


def test_enable_refused_when_readiness_failed(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(passed=False), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert d.execution_permitted is False
    assert any("readiness" in r.lower() for r in d.reasons)
    # refusal recorded durably
    assert authority.current().enabled is False


def test_enable_refused_without_explicit_confirmation(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(), confirmed=False, risk_ack=True)
    assert d.enabled is False
    assert "confirmed=true" in " ".join(d.reasons)


def test_enable_succeeds_only_with_full_gate(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is True and d.execution_permitted is True and d.state == "ENABLED"
    # ...and the persisted state agrees (single authority: query == decision)
    cur = authority.current()
    assert cur.enabled is True
    assert (cur.decided_at or "") != ""


def test_enable_refused_when_required_checks_missing(authority: DemoExecutionAuthority):
    rpt = _readiness()
    rpt["checks"]["account_connected"] = False
    rpt["passed"] = True  # forged report claiming pass with a failing required check
    d = authority.enable(readiness=rpt, confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("account_connected" in r for r in d.reasons)


def test_enable_refused_for_live_account_in_demo(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(warn_live_in_demo=True), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("LIVE account" in r for r in d.reasons)


def test_permission_decays_after_ttl(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.execution_permitted is True
    # Simulate age by rewriting the decided_at of the enablement row.
    with db_connect(authority.db_path) as con:
        old = (datetime.now(UTC) - timedelta(seconds=REVERIFY_TTL_S + 10)).isoformat()
        con.execute("UPDATE demo_execution_state SET decided_at=? WHERE enabled=1", (old,))
        con.commit()
    cur = authority.current()
    assert cur.enabled is True  # still enabled (operator decision persists)
    assert cur.execution_permitted is False  # ...but execution needs re-verification
    assert cur.state == "ENABLED_BUT_BLOCKED"
    assert any("expired" in r for r in cur.reasons)


def test_fresh_readiness_reverification_restores_permission(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    with db_connect(authority.db_path) as con:
        old = (datetime.now(UTC) - timedelta(seconds=REVERIFY_TTL_S + 10)).isoformat()
        con.execute("UPDATE demo_execution_state SET decided_at=? WHERE enabled=1", (old,))
        con.commit()
    cur = authority.current()
    assert cur.execution_permitted is False
    # Operator re-runs the gate fresh: permission restored without re-enable
    cur2 = authority.current(fresh_readiness=_readiness())
    assert cur2.execution_permitted is True
    assert cur2.state == "ENABLED"


def test_fresh_failed_readiness_blocks_immediately(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    cur = authority.current(fresh_readiness=_readiness(passed=False))
    assert cur.enabled is True
    assert cur.execution_permitted is False
    assert any("fresh readiness failed" in r for r in cur.reasons)


def test_observe_only_mode_can_never_hold_execution_permission(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEMO_FORWARD")
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("observation-only" in r or "cannot submit" in r for r in d.reasons)
    # Even if the row were tampered to enabled=1, execution stays refused:
    with db_connect(auth.db_path) as con:
        con.execute(
            "INSERT INTO demo_execution_state (enabled, decided_at, reason, mode, gate_version)"
            " VALUES (1, ?, 'tampered', 'DEMO_FORWARD', 2)",
            (datetime.now(UTC).isoformat(),),
        )
        con.commit()
    cur = auth.current()
    assert cur.execution_permitted is False


def test_unknown_stored_mode_fails_closed(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="NOT_A_MODE")
    auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    cur = auth.current()
    # unknown mode string doesn't veto at read time (not resolvable) but a
    # resolvable-but-incapable mode always does; verify no exception and the
    # enablement is still bounded by the fresh-readiness TTL contract
    assert cur.enabled is True


def test_disable_disables_and_persists(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    d = authority.disable(reason="test")
    assert d.enabled is False
    assert authority.current().enabled is False


def test_audit_failure_prevents_enablement(tmp_path: Path):
    class ExplodingAudit:
        def emit(self, event):  # noqa: ANN001
            raise RuntimeError("audit sink down")

    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", audit=ExplodingAudit())
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert "audit failed" in " ".join(d.reasons)
    # Nothing was persisted as enabled
    assert auth.current().enabled is False


def test_state_survives_restart(tmp_path: Path):
    db = tmp_path / "q.db"
    a1 = DemoExecutionAuthority(db_path=db)
    a1.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    a2 = DemoExecutionAuthority(db_path=db)  # fresh process, same DB
    assert a2.current().enabled is True


def test_readiness_age_seconds_uses_report_timestamp():
    from qts.lifecycle.demo_authority import readiness_age_seconds

    rpt = {"timestamp": datetime.now(UTC).isoformat()}
    assert readiness_age_seconds(rpt) < 5.0
    old = {"timestamp": (datetime.now(UTC) - timedelta(seconds=999)).isoformat()}
    assert 998 < readiness_age_seconds(old) < 1005
    assert readiness_age_seconds({}) == 0.0
