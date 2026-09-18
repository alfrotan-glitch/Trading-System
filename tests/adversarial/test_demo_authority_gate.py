"""Adversarial tests for the current DEMO execution policy boundary.

``DEMO_EXECUTION = DISABLED BY POLICY`` today. The retained authority,
readiness, audit, and execution-boundary architecture remains the future path
for an explicitly authorized re-enable after research and safety milestones.
A readiness report, request payload, acknowledgement, direct authority call,
restart, or tampered SQLite row must not bypass today's policy. Refusals remain
inspectable and durable so negative evidence is not lost.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qts.db import connect as db_connect
from qts.lifecycle.demo_authority import (
    DEMO_EXECUTION_DISABLED,
    DEMO_EXECUTION_POLICY,
    REVERIFY_TTL_S,
    DemoExecutionAuthority,
)


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


def test_current_policy_is_explicit_and_authority_boundary_is_retained(authority: DemoExecutionAuthority):
    assert DEMO_EXECUTION_DISABLED is True
    assert DEMO_EXECUTION_POLICY == "DISABLED BY POLICY"
    decision = authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert decision.detail["product_policy"] == "DEMO_EXECUTION = DISABLED BY POLICY"
    assert decision.enabled is False
    assert decision.execution_permitted is False
    # The durable authority remains present for audit/history rather than being
    # deleted; a future policy decision must still pass through this boundary.
    with db_connect(authority.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM demo_execution_state").fetchone()[0] == 1


def test_enable_refused_when_readiness_failed(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(passed=False), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert d.execution_permitted is False
    assert any("readiness" in r.lower() for r in d.reasons)
    assert authority.current().enabled is False


def test_enable_refused_without_explicit_confirmation(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(), confirmed=False, risk_ack=True)
    assert d.enabled is False
    assert "confirmed=true" in " ".join(d.reasons)
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in d.reasons[0]


def test_enable_refused_even_with_full_gate(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False and d.execution_permitted is False and d.state == "DISABLED"
    assert any("DEMO_EXECUTION = DISABLED BY POLICY" in reason for reason in d.reasons)
    cur = authority.current()
    assert cur.enabled is False
    assert cur.execution_permitted is False
    assert cur.as_dict()["readiness_evidence"] == "passed"

    with db_connect(authority.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM demo_execution_state WHERE enabled=1").fetchone()[0] == 0


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


def test_policy_refusal_is_not_reenabled_by_ttl_or_fresh_readiness(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    with db_connect(authority.db_path) as con:
        old = (datetime.now(UTC) - timedelta(seconds=REVERIFY_TTL_S + 10)).isoformat()
        con.execute("UPDATE demo_execution_state SET decided_at=? WHERE enabled=0", (old,))
        con.commit()

    cur = authority.current()
    assert cur.enabled is False
    assert cur.execution_permitted is False
    assert cur.state == "DISABLED"
    cur2 = authority.current(fresh_readiness=_readiness())
    assert cur2.enabled is False
    assert cur2.execution_permitted is False
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in cur2.reasons[0]


def test_fresh_failed_readiness_cannot_override_policy_refusal(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    cur = authority.current(fresh_readiness=_readiness(passed=False))
    assert cur.enabled is False
    assert cur.execution_permitted is False
    assert cur.state == "DISABLED"


def test_observe_only_mode_can_never_hold_execution_permission(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEMO_FORWARD")
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("observation-only" in r or "product policy" in r for r in d.reasons)
    with db_connect(auth.db_path) as con:
        con.execute(
            "INSERT INTO demo_execution_state (enabled, decided_at, reason, mode, gate_version)"
            " VALUES (1, ?, 'tampered', 'DEMO_FORWARD', 2)",
            (datetime.now(UTC).isoformat(),),
        )
        con.commit()
    cur = auth.current()
    assert cur.enabled is False
    assert cur.execution_permitted is False


def test_unknown_stored_mode_fails_closed(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="NOT_A_MODE")
    auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    cur = auth.current()
    assert cur.enabled is False
    assert cur.execution_permitted is False
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in cur.reasons[0]


def test_disable_disables_and_persists(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    d = authority.disable(reason="test")
    assert d.enabled is False
    assert authority.current().enabled is False
    assert authority.current().execution_permitted is False


def test_audit_failure_prevents_enablement(tmp_path: Path):
    class ExplodingAudit:
        def emit(self, event):  # noqa: ANN001
            raise RuntimeError("audit sink down")

    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", audit=ExplodingAudit())
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert "audit failed" in " ".join(d.reasons)
    assert auth.current().enabled is False


def test_state_survives_restart_as_disabled_policy_state(tmp_path: Path):
    db = tmp_path / "q.db"
    a1 = DemoExecutionAuthority(db_path=db)
    a1.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    a2 = DemoExecutionAuthority(db_path=db)
    assert a2.current().enabled is False
    assert a2.current().execution_permitted is False


def test_readiness_age_seconds_uses_report_timestamp():
    from qts.lifecycle.demo_authority import readiness_age_seconds

    rpt = {"timestamp": datetime.now(UTC).isoformat()}
    assert readiness_age_seconds(rpt) < 5.0
    old = {"timestamp": (datetime.now(UTC) - timedelta(seconds=999)).isoformat()}
    assert 998 < readiness_age_seconds(old) < 1005
    assert readiness_age_seconds({}) == 0.0


# ---------------------------------------------------------------------------
# Persisted readiness evidence remains inspectable even though it cannot
# authorize execution.  The fresh probe and the historical refusal are kept
# as separate facts.
# ---------------------------------------------------------------------------


def test_readiness_passed_false_with_fresh_probe_passing_is_coherent(authority: DemoExecutionAuthority):
    cur = authority.current(fresh_readiness=_readiness(passed=True))
    d = cur.as_dict()
    assert d["state"] == "DISABLED"
    assert d["enabled"] is False
    assert d["execution_permitted"] is False
    assert d["readiness_passed"] is False
    assert d["readiness_evidence"] == "none"
    assert d["readiness_expired"] is False


def test_refused_enablement_records_failed_readiness_evidence(authority: DemoExecutionAuthority):
    d = authority.enable(readiness=_readiness(passed=False), confirmed=True, risk_ack=True).as_dict()
    assert d["readiness_passed"] is False
    assert d["readiness_evidence"] == "failed"
    cur = authority.current().as_dict()
    assert cur["readiness_evidence"] == "failed"


def test_refused_enablement_records_passed_readiness_evidence(authority: DemoExecutionAuthority):
    authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    cur = authority.current().as_dict()
    assert cur["readiness_passed"] is True
    assert cur["readiness_evidence"] == "passed"
    assert cur["execution_permitted"] is False


# ---------------------------------------------------------------------------
# Tampering and restart checks: even an enabled row cannot cross the product
# policy boundary.
# ---------------------------------------------------------------------------


def _tamper_enabled_row(db_path: Path, *, mode: str | None) -> None:
    with db_connect(db_path) as con:
        con.execute(
            "INSERT INTO demo_execution_state (enabled, decided_at, reason, readiness_passed,"
            " readiness_report, readiness_age_s, mode, gate_version)"
            " VALUES (1, ?, 'tampered', 1, '{\"passed\": true}', 0.0, ?, 2)",
            (datetime.now(UTC).isoformat(), mode),
        )
        con.commit()


def test_tampered_capable_mode_row_refused_in_observe_only_process(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEMO_FORWARD")
    _tamper_enabled_row(auth.db_path, mode="DEMO_EXECUTION")
    d = auth.current().as_dict()
    assert d["enabled"] is False
    assert d["execution_permitted"] is False
    assert d["state"] == "DISABLED"
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in d["reasons"]


def test_tampered_null_mode_row_refused_in_observe_only_process(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEMO_FORWARD")
    _tamper_enabled_row(auth.db_path, mode=None)
    d = auth.current().as_dict()
    assert d["enabled"] is False
    assert d["execution_permitted"] is False
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in d["reasons"]


def test_tampered_row_refused_in_development_process(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEVELOPMENT")
    _tamper_enabled_row(auth.db_path, mode="DEMO_EXECUTION")
    assert auth.current().execution_permitted is False
    assert auth.is_execution_permitted()[0] is False


def test_policy_veto_is_not_mislabeled_as_readiness_expired(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEVELOPMENT")
    _tamper_enabled_row(auth.db_path, mode="DEMO_EXECUTION")
    d = auth.current().as_dict()
    assert d["execution_permitted"] is False
    assert d["readiness_expired"] is False
    assert not any("expired" in r for r in d["reasons"])


def test_demo_execution_process_honors_disabled_product_policy(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", mode="DEMO_EXECUTION")
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.execution_permitted is False
    cur = auth.current()
    assert cur.execution_permitted is False
    assert cur.enabled is False
    assert cur.state == "DISABLED"
