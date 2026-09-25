"""API contract tests for the DEMO execution surface.

The question that started this work was *"why does ``POST /api/demo/enable``
return 409 with ``execution_permitted=false``?"* — this file pins the answer at
the HTTP layer, where an operator actually meets it:

* with no recorded owner authorization the 409 is the shipped default
  (``DEMO_EXECUTION = DISABLED BY POLICY``);
* with one, the enablement still has to clear every retained gate — explicit
  confirmation, risk acknowledgement and a **fresh** passing readiness report;
* an order endpoint never trades on hope: with no strategy registered it
  answers 409 ``NO_TRADE``, and with an armed session and a registered strategy
  it submits exactly one labelled ``RESEARCH_DEMO_ORDER``.

No terminal is contacted: the readiness probe and the session are injected, and
every path (DB, audit log, kill-switch self test, identity pin) is redirected
into ``tmp_path``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qts.api import server
from qts.execution import demo_session as demo_session_module
from qts.lifecycle.demo_authorization import document_fingerprint
from qts.lifecycle.demo_gate import READINESS_REQUIRED_CHECKS

REQUIRED_CHECKS = list(READINESS_REQUIRED_CHECKS)


def _authorization_doc(authorization_id: str = "DEMO-AUTH-API-TEST") -> dict:
    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": authorization_id,
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "api contract test",
        "statement": "test authorization — DEMO only, LIVE locked, zero real capital",
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
        "expires_at": None,
    }
    doc["integrity"] = {"content_sha256": document_fingerprint(doc)}
    return doc


@pytest.fixture()
def api_env(tmp_path: Path, monkeypatch):
    """Hermetic environment: every durable side effect lands in ``tmp_path``."""
    auth_path = tmp_path / "authorization.json"
    auth_path.write_text(json.dumps(_authorization_doc(), indent=2), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "qts.demo_forward_registry.v1",
                "research_integrity": {"optimization_allowed": False, "no_forward_fitting": True},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QTS_MODE", "demo_execution")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(auth_path))
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))

    monkeypatch.setattr(server, "_db_path", lambda: tmp_path / "qts.db")
    monkeypatch.setattr(server, "_DEMO_AUTHORITY", None)
    monkeypatch.setattr(demo_session_module, "SELF_TEST_DB", tmp_path / "selftest.db")

    from qts.observability import audit as audit_module

    real_audit = audit_module.SqliteAuditLog
    monkeypatch.setattr(
        audit_module,
        "SqliteAuditLog",
        lambda *a, **k: real_audit(db_path=tmp_path / "audit.db", jsonl_path=tmp_path / "audit.jsonl"),
    )
    yield tmp_path
    server._DEMO_AUTHORITY = None


@pytest.fixture()
def client(api_env):
    from fastapi.testclient import TestClient

    with TestClient(server.app) as c:
        yield c


def _readiness(passed: bool) -> dict:
    checks = dict.fromkeys(REQUIRED_CHECKS, passed)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
        "details": {},
        "blocked_reasons": [] if passed else [f"simulated failure: {REQUIRED_CHECKS[0]}"],
        "passed": passed,
        "demo_enabled": False,
        "required_checks": REQUIRED_CHECKS,
        "account_is_demo": passed,
        "warn_live_in_demo": False,
    }


@pytest.fixture()
def passing_readiness(monkeypatch):
    monkeypatch.setattr(
        "qts.lifecycle.demo_gate.demo_forward_readiness_report", lambda **kwargs: _readiness(True)
    )
    return _readiness(True)


@pytest.fixture()
def failing_readiness(monkeypatch):
    monkeypatch.setattr(
        "qts.lifecycle.demo_gate.demo_forward_readiness_report", lambda **kwargs: _readiness(False)
    )
    return _readiness(False)


# --------------------------------------------------------------- authorization


def test_authorization_endpoint_reports_the_artifact_and_the_lock(client):
    body = client.get("/api/demo/authorization").json()
    assert body["live_locked"] is True
    assert body["real_capital_exposure_usd"] == 0
    assert body["resolved_policy"]["enabled"] is True
    assert body["resolved_policy"]["policy"] == "ENABLED_AUTHORIZED"
    assert body["resolved_policy"]["live_locked"] is True
    assert "DEMO-AUTH-API-TEST" in json.dumps(body)


def test_safety_endpoint_keeps_live_locked(client):
    body = client.get("/api/demo/safety").json()
    assert body["live_locked"] is True


# -------------------------------------------------------------- /api/demo/enable


def test_enable_requires_explicit_confirmation_and_risk_ack(client):
    for payload in ({}, {"confirmed": True}, {"risk_ack": True}):
        response = client.post("/api/demo/enable", json=payload)
        assert response.status_code == 400, payload
        assert "confirmed" in response.json()["detail"]


def test_enable_returns_409_without_an_owner_authorization(client, monkeypatch):
    """The shipped default: no artifact ⇒ durable 409, exactly as before."""
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(Path("/nonexistent/authorization.json")))
    response = client.post("/api/demo/enable", json={"confirmed": True, "risk_ack": True})
    assert response.status_code == 409
    body = response.json()
    assert body["execution_permitted"] is False
    assert body["state"] == "DISABLED"
    assert body["policy"] == "DISABLED BY POLICY"
    assert body["demo_execution_disabled"] is True
    assert body["reasons"]


def test_enable_returns_409_when_readiness_fails(client, failing_readiness):
    response = client.post("/api/demo/enable", json={"confirmed": True, "risk_ack": True})
    assert response.status_code == 409
    body = response.json()
    assert body["execution_permitted"] is False
    assert body["policy"] == "ENABLED_AUTHORIZED"  # authorized, but the gate refused
    assert any("readiness" in reason.lower() for reason in body["reasons"])


def test_enable_returns_200_when_every_gate_passes(client, passing_readiness):
    response = client.post("/api/demo/enable", json={"confirmed": True, "risk_ack": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_permitted"] is True
    assert body["enabled"] is True
    assert body["authorization_id"] == "DEMO-AUTH-API-TEST"

    state = client.get("/api/demo/state").json()
    assert state["execution_permitted"] is True
    assert state["demo_execution_disabled"] is False

    # Revocable, and refusal is the default again afterwards.
    disabled = client.post("/api/demo/disable").json()
    assert disabled["execution_permitted"] is False


# ------------------------------------------------------------------- preflight


def test_preflight_refuses_with_unresolved_checks(client):
    response = client.get("/api/demo/preflight", params={"side": "BUY", "stop_loss": "1995.00"})
    assert response.status_code == 409
    body = response.json()
    assert body["verdict"]["passed"] is False
    assert "strategy_registered_frozen" in body["verdict"]["failed"]
    # Fail closed: nothing unresolved is treated as a pass.
    assert body["verdict"]["checks"]["no_unknown_checks"]["status"] == "FAIL"


# ----------------------------------------------------------------------- order


def test_order_endpoint_refuses_while_no_strategy_is_registered(client):
    response = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["allowed"] is False
    assert body["state"] == "NO_TRADE"
    assert any("strategy" in reason for reason in body["reasons"])


def test_order_endpoint_rejects_a_bad_request(client):
    assert client.post("/api/demo/order", json={"side": "SIDEWAYS"}).status_code == 400
    assert client.post("/api/demo/order", json={"side": "BUY"}).status_code == 400


def test_order_endpoint_submits_exactly_one_labelled_demo_order(client, api_env, monkeypatch):
    """With an armed session and a registered strategy the API really trades DEMO."""
    import fakes_demo_provider as provider_fixture
    from fakes_mt5_demo import FakeTerminal

    registry_path = Path(api_env) / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "qts.demo_forward_registry.v1",
                "research_integrity": {"optimization_allowed": False, "no_forward_fitting": True},
                "entries": [provider_fixture.registry_entry()],
            }
        ),
        encoding="utf-8",
    )

    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    monkeypatch.setattr(server, "_demo_session", lambda symbol=None: session)

    response = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["allowed"] is True
    assert body["broker_order_id"]
    assert len(terminal.requests) == 1
    assert terminal.requests[0]["volume"] == 0.01

    row = session.journal.list_orders()[0]
    assert "RESEARCH_DEMO_ORDER" in (row["notes"] or "")
    assert row["strategy_config_hash"] == provider_fixture.registry_entry()["params_hash"]


def _armed_session(tmp_path: Path, terminal, monkeypatch):
    """A session wired to the fake terminal, armed through the real gates."""
    from qts.execution.demo_identity import confirm_pin, write_pin
    from qts.execution.demo_session import DemoSession, DemoSessionConfig
    from qts.lifecycle.demo_authority import readiness_age_seconds
    from qts.lifecycle.demo_registry import load_registry, resolve_entry
    from qts.lifecycle.demo_stage import DemoStage

    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=tmp_path / "qts.db",
            actor="api-test",
            mt5_module=terminal,
        )
    )
    entry, reasons = resolve_entry(load_registry())
    assert entry is not None, reasons
    session._entry = entry  # what the API handler reads instead of re-resolving

    write_pin(session.adapter.broker_identity(), actor="api-test")
    assert confirm_pin(actor="owner")[0] is True

    report = session.connectivity_report()
    session.stage.advance(
        DemoStage.STAGE_1_CONNECTIVITY,
        actor="api-test",
        reason="api contract test",
        prerequisites={
            "readiness_passed": bool(report["readiness"]["passed"]),
            "account_is_demo": report["identity"]["is_demo"] is True,
            "symbol_ok": bool(report["symbol_mapping"]["ok"]),
            "quote_fresh": bool(report["quote"]["fresh"]),
        },
    )
    readiness = _readiness(True)
    decision = session.authority.enable(
        readiness=readiness,
        confirmed=True,
        risk_ack=True,
        readiness_age_s=readiness_age_seconds(readiness),
        actor="api-test",
    )
    assert decision.execution_permitted is True, decision.reasons
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="api-test", reason="api contract test")
    session.reconcile()
    return session


# ------------------------------------------------------------ kill and journal


def test_kill_endpoint_halts_the_stage_machine(client):
    response = client.post("/api/demo/kill", json={"reason": "api contract test"})
    assert response.status_code == 200
    assert response.json()["killed"] is True
    assert client.get("/api/demo/stage").json()["current"]["stage"] == "HALTED"


def test_journal_endpoint_is_labelled_demo_and_empty_by_default(client):
    body = client.get("/api/demo/journal").json()
    assert body["label"] == "RESEARCH_DEMO_ORDER"
    assert body["capital_class"] == "DEMO"
    assert body["orders"] == []
    assert body["summary"]["orders"] == 0


def test_stage_endpoint_starts_disabled(client):
    body = client.get("/api/demo/stage").json()
    assert body["current"]["stage"] == "DISABLED"
    assert body["current"]["orders_permitted"] is False


def test_positions_and_close_endpoints_full_lifecycle(client, api_env, monkeypatch):
    """Prove GET /api/demo/positions and POST /api/demo/close complete the position lifecycle."""
    import fakes_demo_provider as provider_fixture
    from fakes_mt5_demo import FakeTerminal

    registry_path = Path(api_env) / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "qts.demo_forward_registry.v1",
                "research_integrity": {"optimization_allowed": False, "no_forward_fitting": True},
                "entries": [provider_fixture.registry_entry()],
            }
        ),
        encoding="utf-8",
    )

    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)

    import qts.api.server as server_module

    monkeypatch.setattr(server_module, "_demo_session", lambda *args, **kwargs: session)

    # Initially no positions
    res = client.get("/api/demo/positions")
    assert res.status_code == 200
    assert res.json()["count"] == 0
    assert res.json()["positions"] == []

    # Submit an order
    res_order = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "rationale": "test-order"},
    )
    assert res_order.status_code == 200
    assert res_order.json()["allowed"] is True

    # Now position exists
    res_pos = client.get("/api/demo/positions")
    assert res_pos.status_code == 200
    data = res_pos.json()
    assert data["count"] == 1
    pos = data["positions"][0]
    ticket = pos["ticket"]
    assert ticket is not None
    assert pos["canonical_symbol"] == "XAUUSD"

    # Close without confirmation fails closed
    res_fail1 = client.post("/api/demo/close", json={"ticket": ticket})
    assert res_fail1.status_code == 400
    assert "confirmed=true" in res_fail1.text

    # Close with invalid ticket fails closed
    res_fail2 = client.post("/api/demo/close", json={"ticket": "not-an-int", "confirmed": True, "risk_ack": True})
    assert res_fail2.status_code == 400

    # Explicit close with confirmation and risk ack succeeds
    res_close = client.post(
        "/api/demo/close",
        json={"ticket": ticket, "confirmed": True, "risk_ack": True, "reason": "test-close"},
    )
    assert res_close.status_code == 200
    close_data = res_close.json()
    assert close_data["success"] is True
    assert close_data["ticket"] == ticket
    assert close_data["reconciliation"]["requires_suspend"] is False

    # Position is now gone
    res_empty = client.get("/api/demo/positions")
    assert res_empty.status_code == 200
    assert res_empty.json()["count"] == 0

    # Order journal records CLOSED
    journal_row = session.journal.list_orders()[0]
    assert journal_row["state"] == "CLOSED"
    assert "test-close" in (journal_row["exit_reason"] or "")

