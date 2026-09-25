"""Adversarial tests for the DEMO execution policy boundary.

Two regimes are exercised explicitly, because "the default" and "authorized"
must never be confused:

* **Un-authorized** (``authorization=None``) — the shipped default of a
  checkout with no owner authorization artifact. Here the answer is always
  ``DEMO_EXECUTION = DISABLED BY POLICY``: a readiness report, request payload,
  acknowledgement, direct authority call, restart, or tampered SQLite row must
  not produce permission.
* **Authorized** — a valid, in-scope, un-revoked owner authorization artifact
  exists. Every gate still applies and is tested here too: explicit
  confirmation, risk acknowledgement, FRESH passing readiness, required checks,
  DEMO-only account, broker-capable mode, TTL decay, and audit-before-write.

Refusals remain inspectable and durable in both regimes so negative evidence
is never lost.
"""

from __future__ import annotations

import json
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
    """Un-authorized authority — the shipped default of a clean checkout."""
    return DemoExecutionAuthority(db_path=tmp_path / "qts.db", authorization=None)


def _authorization_doc(**overrides) -> dict:
    from qts.lifecycle.demo_authorization import document_fingerprint

    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": "DEMO-AUTH-TEST",
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "test harness",
        "statement": "test authorization — DEMO only, LIVE locked, zero real capital exposure",
        "scope": {
            "account_type": "demo",
            "modes_allowed": ["DEMO_EXECUTION"],
            "symbols_allowed": ["XAUUSD"],
            "live_locked": True,
            "real_capital_exposure_usd": 0,
            "funds_transfer_permitted": False,
            "broker_switch_permitted": False,
            "autonomous_order_management": True,
        },
        "risk_ceiling": {},
        "research_integrity": {
            "no_forward_optimization": True,
            "strategy_registry_required": True,
        },
        "expires_at": None,
    }
    doc.update(overrides)
    doc["integrity"] = {"content_sha256": document_fingerprint(doc)}
    return doc


@pytest.fixture()
def authorized_authority(tmp_path: Path):
    """Authority carrying a valid owner authorization artifact."""
    from qts.lifecycle.demo_authorization import load_authorization

    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(_authorization_doc(), indent=2), encoding="utf-8")
    auth, reasons = load_authorization(path)
    assert auth is not None, reasons
    return DemoExecutionAuthority(db_path=tmp_path / "auth.db", authorization=auth, mode="DEMO_EXECUTION")


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
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="DEMO_FORWARD")
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
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="NOT_A_MODE")
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

    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, audit=ExplodingAudit())
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert "audit failed" in " ".join(d.reasons)
    assert auth.current().enabled is False


def test_state_survives_restart_as_disabled_policy_state(tmp_path: Path):
    db = tmp_path / "q.db"
    a1 = DemoExecutionAuthority(db_path=db, authorization=None)
    a1.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    a2 = DemoExecutionAuthority(db_path=db, authorization=None)
    assert a2.current().enabled is False
    assert a2.current().execution_permitted is False


def test_readiness_age_seconds_uses_report_timestamp():
    import math

    from qts.lifecycle.demo_authority import REVERIFY_TTL_S, readiness_age_seconds

    rpt = {"timestamp": datetime.now(UTC).isoformat()}
    assert readiness_age_seconds(rpt) < 5.0
    old = {"timestamp": (datetime.now(UTC) - timedelta(seconds=999)).isoformat()}
    assert 998 < readiness_age_seconds(old) < 1005
    # FAIL CLOSED. Undated or unparseable evidence has NO provable age, so it
    # must be infinitely old — never "just verified". This helper used to
    # return 0.0 for a missing timestamp, which made the least trustworthy
    # possible report look like the freshest possible one, and the old
    # assertion `readiness_age_seconds({}) == 0.0` enshrined that trap.
    for undated in (
        {},
        {"timestamp": None},
        {"timestamp": ""},
        {"timestamp": "not-a-timestamp"},
        {"timestamp": 12345},
        "not-a-dict",
        None,
    ):
        age = readiness_age_seconds(undated)
        assert age == math.inf
        # the operative consequence: always beyond the re-verify TTL, so
        # permission can never be assumed from undated evidence
        assert age > REVERIFY_TTL_S
    # a naive timestamp is read as UTC, never as local time
    naive = {"timestamp": (datetime.now(UTC) - timedelta(seconds=999)).replace(tzinfo=None).isoformat()}
    assert 998 < readiness_age_seconds(naive) < 1005


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
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in d["reasons"]
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
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="DEMO_FORWARD")
    _tamper_enabled_row(auth.db_path, mode="DEMO_EXECUTION")
    d = auth.current().as_dict()
    assert d["enabled"] is False
    assert d["execution_permitted"] is False
    assert d["state"] == "DISABLED"
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in d["reasons"]


def test_tampered_null_mode_row_refused_in_observe_only_process(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="DEMO_FORWARD")
    _tamper_enabled_row(auth.db_path, mode=None)
    d = auth.current().as_dict()
    assert d["enabled"] is False
    assert d["execution_permitted"] is False
    assert "DEMO_EXECUTION = DISABLED BY POLICY" in d["reasons"]


def test_tampered_row_refused_in_development_process(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="DEVELOPMENT")
    _tamper_enabled_row(auth.db_path, mode="DEMO_EXECUTION")
    assert auth.current().execution_permitted is False
    assert auth.is_execution_permitted()[0] is False


def test_policy_veto_is_not_mislabeled_as_readiness_expired(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="DEVELOPMENT")
    _tamper_enabled_row(auth.db_path, mode="DEMO_EXECUTION")
    d = auth.current().as_dict()
    assert d["execution_permitted"] is False
    assert d["readiness_expired"] is False
    assert not any("expired" in r for r in d["reasons"])


def test_demo_execution_process_honors_disabled_product_policy(tmp_path: Path):
    auth = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=None, mode="DEMO_EXECUTION")
    d = auth.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.execution_permitted is False
    cur = auth.current()
    assert cur.execution_permitted is False
    assert cur.enabled is False
    assert cur.state == "DISABLED"


# ---------------------------------------------------------------------------
# Authorized regime.
#
# A valid owner authorization artifact opens the DEMO execution path. It does
# NOT relax a single gate inside it: confirmation, risk acknowledgement, FRESH
# readiness, required checks, DEMO-only account and broker-capable mode all
# still apply, and LIVE stays locked no matter what the artifact says.
# ---------------------------------------------------------------------------


def test_shipped_default_constant_remains_disabled():
    """The source-level default of a clean checkout is still DISABLED."""
    assert DEMO_EXECUTION_DISABLED is True
    assert DEMO_EXECUTION_POLICY == "DISABLED BY POLICY"


def test_authorized_authority_enables_with_fresh_readiness(authorized_authority: DemoExecutionAuthority):
    d = authorized_authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is True
    assert d.execution_permitted is True
    assert d.state == "ENABLED"
    cur = authorized_authority.current()
    assert cur.execution_permitted is True


def test_authorized_enable_still_requires_explicit_confirmation(
    authorized_authority: DemoExecutionAuthority,
):
    d = authorized_authority.enable(readiness=_readiness(), confirmed=False, risk_ack=True)
    assert d.enabled is False
    assert any("confirmed=true" in r for r in d.reasons)


def test_authorized_enable_refuses_failed_readiness(authorized_authority: DemoExecutionAuthority):
    d = authorized_authority.enable(readiness=_readiness(passed=False), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("readiness" in r.lower() for r in d.reasons)


def test_authorized_enable_refuses_stale_readiness_evidence(
    authorized_authority: DemoExecutionAuthority,
):
    stale = _readiness()
    stale["timestamp"] = (datetime.now(UTC) - timedelta(seconds=REVERIFY_TTL_S + 60)).isoformat()
    d = authorized_authority.enable(readiness=stale, confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("fresh" in r.lower() for r in d.reasons)


def test_authorized_enable_refuses_undated_readiness_evidence(
    authorized_authority: DemoExecutionAuthority,
):
    """An undated report is infinitely old — never 'just verified'."""
    undated = _readiness()
    undated.pop("timestamp")
    d = authorized_authority.enable(readiness=undated, confirmed=True, risk_ack=True)
    assert d.enabled is False


def test_authorized_enable_refuses_live_account_in_demo(authorized_authority: DemoExecutionAuthority):
    d = authorized_authority.enable(readiness=_readiness(warn_live_in_demo=True), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("LIVE account" in r for r in d.reasons)


def test_authorized_enable_refuses_when_required_check_missing(
    authorized_authority: DemoExecutionAuthority,
):
    rpt = _readiness()
    rpt["checks"]["account_connected"] = False
    rpt["passed"] = True  # forged pass with a failing required check
    d = authorized_authority.enable(readiness=rpt, confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert any("account_connected" in r for r in d.reasons)


def test_authorized_audit_failure_still_prevents_enablement(tmp_path: Path):
    from qts.lifecycle.demo_authorization import load_authorization

    class ExplodingAudit:
        def emit(self, event):  # noqa: ANN001
            raise RuntimeError("audit sink down")

    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(_authorization_doc(), indent=2), encoding="utf-8")
    auth, _reasons = load_authorization(path)
    authority = DemoExecutionAuthority(
        db_path=tmp_path / "q.db", authorization=auth, mode="DEMO_EXECUTION", audit=ExplodingAudit()
    )
    d = authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert "audit failed" in " ".join(d.reasons)


def test_authorized_permission_decays_after_ttl(authorized_authority: DemoExecutionAuthority):
    authorized_authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    with db_connect(authorized_authority.db_path) as con:
        old = (datetime.now(UTC) - timedelta(seconds=REVERIFY_TTL_S + 10)).isoformat()
        con.execute("UPDATE demo_execution_state SET decided_at=? WHERE enabled=1", (old,))
        con.commit()
    cur = authorized_authority.current()
    assert cur.execution_permitted is False
    assert cur.readiness_expired is True


def test_live_mode_is_never_enabled_by_any_authorization(tmp_path: Path):
    """LIVE = LOCKED is an invariant, not a clause in the artifact."""
    from qts.lifecycle.demo_authorization import load_authorization

    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(_authorization_doc(), indent=2), encoding="utf-8")
    auth, _reasons = load_authorization(path)
    authority = DemoExecutionAuthority(db_path=tmp_path / "q.db", authorization=auth, mode="LIVE")
    d = authority.enable(readiness=_readiness(), confirmed=True, risk_ack=True)
    assert d.enabled is False
    assert d.execution_permitted is False
    assert any("LIVE" in r for r in d.reasons)


def test_tampered_authorization_artifact_disables_execution_again(tmp_path: Path):
    """Editing the artifact after signing breaks the hash → DISABLED."""
    from qts.lifecycle.demo_authorization import load_authorization

    path = tmp_path / "authorization.json"
    doc = _authorization_doc()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    auth, reasons = load_authorization(path)
    assert auth is not None, reasons

    doc["scope"]["live_locked"] = False  # attempt to unlock LIVE
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    auth2, reasons2 = load_authorization(path)
    assert auth2 is None
    assert any("hash mismatch" in r for r in reasons2)


def test_authorization_artifact_cannot_loosen_risk_limits(tmp_path: Path):
    from qts.lifecycle.demo_authorization import load_authorization

    path = tmp_path / "authorization.json"
    doc = _authorization_doc(risk_ceiling={"max_quantity": 999.0})
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    auth, reasons = load_authorization(path)
    assert auth is None
    assert any("exceeds canonical DEMO limit" in r for r in reasons)


def test_authorization_revocation_disables_execution(tmp_path: Path):
    from qts.lifecycle.demo_authorization import load_authorization, revoke_authorization

    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(_authorization_doc(), indent=2), encoding="utf-8")
    assert load_authorization(path)[0] is not None
    revoke_authorization(path, reason="owner withdrew authorization", actor="test")
    auth, reasons = load_authorization(path)
    assert auth is None
    assert any("revoked" in r for r in reasons)
