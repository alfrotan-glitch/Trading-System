"""Guided-workflow API tests — the plain-language product surface for DEMO.

The guided endpoints (``/api/demo/guide`` and ``/api/demo/guide/*``) are what
a normal human meets: one status, one reason, one next action. These tests pin
that surface WITHOUT relaxing a single gate:

* every block is reported honestly and fail-closed (no terminal, no
  authorization, failing readiness, kill switch, drifted reconciliation);
* record/confirm identity drive the SAME pin machinery as the CLI;
* prepare re-proves every CLI prerequisite against the live (fake) terminal
  through the SAME stage machine and authority enablement;
* refresh is a permission re-verification at the current order stage, never a
  transition; resume clears the kill flag with a recorded reason but the stage
  machine stays HALTED until prepared again.

No internal lifecycle name may leak into the product surface: everything above
the ``technical`` key must read like product copy.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_demo_api import _armed_session

from qts.api import server

# Reuse the hermetic DEMO-API fixtures (api_env, client, passing/failing
# readiness) from the sibling contract suite instead of re-implementing them.
pytest_plugins = ["test_demo_api"]

PRODUCT_KEYS = (
    "checked_at",
    "instrument",
    "live_locked",
    "real_capital_exposure_usd",
    "mode_ok",
    "mode",
    "authorization_ok",
    "authorization_detail",
    "connection",
    "identity",
    "readiness",
    "quote",
    "kill_switch",
    "reconciliation",
    "stage_allows_orders",
    "permission",
    "plan_registered",
    "plan_reasons",
    "plan_id",
    "order_defaults",
    "steps",
    "can_trade",
    "status",
    "headline",
    "reason",
    "next",
)


def _assert_product_surface_is_plain(body: dict) -> None:
    """No stage names, gate ids or policy hashes above the technical key."""
    surface = json.dumps({k: body.get(k) for k in PRODUCT_KEYS})
    for forbidden in ("STAGE_1", "STAGE_2", "STAGE_3", "DISABLED", "HALTED", "readiness_passed"):
        assert forbidden not in surface, f"internal name {forbidden!r} leaked into the product surface"


def _register_plan(api_env: Path) -> None:
    """The armed-path tests trade a registered, frozen research plan."""
    import fakes_demo_provider as provider_fixture

    (Path(api_env) / "registry.json").write_text(
        json.dumps(
            {
                "schema": "qts.demo_forward_registry.v1",
                "research_integrity": {"optimization_allowed": False, "no_forward_fitting": True},
                "entries": [provider_fixture.registry_entry()],
            }
        ),
        encoding="utf-8",
    )


def _fresh_session(tmp_path: Path, terminal, *, with_pin: bool):
    """A session wired to the fake terminal — without pin or stage advance."""
    from qts.execution.demo_identity import confirm_pin, write_pin
    from qts.execution.demo_session import DemoSession, DemoSessionConfig

    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=tmp_path / "qts.db",
            actor="api-test",
            mt5_module=terminal,
        )
    )
    if with_pin:
        write_pin(session.adapter.broker_identity(), actor="api-test")
        assert confirm_pin(actor="owner")[0] is True
    return session


def _inject(session, monkeypatch) -> None:
    monkeypatch.setattr(server, "_demo_session", lambda symbol=None: session)


# ------------------------------------------------------------------ read side


def test_guide_fails_closed_without_a_terminal(client):
    """No MT5 in the sandbox ⇒ honest 'Not connected', never a guess or a crash."""
    body = client.get("/api/demo/guide").json()
    assert body["connection"]["connected"] is False
    assert body["can_trade"] is False
    assert body["status"] == "blocked"
    assert body["headline"] == "Not connected"
    assert body["next"]["action"] == "check_connection"
    assert body["live_locked"] is True
    assert body["real_capital_exposure_usd"] == 0
    _assert_product_surface_is_plain(body)


def test_guide_is_blocked_without_an_owner_authorization(client, monkeypatch):
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(Path("/nonexistent/authorization.json")))
    body = client.get("/api/demo/guide").json()
    assert body["authorization_ok"] is False
    assert body["can_trade"] is False
    assert body["headline"] == "Not ready"
    assert body["next"]["action"] == "review_authorization"


def test_guide_is_ready_with_an_armed_session_and_plan(client, api_env, monkeypatch):
    import fakes_demo_provider as provider_fixture
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    body = client.get("/api/demo/guide").json()
    assert body["status"] == "ready", body
    assert body["headline"] == "Ready for demo trading"
    assert body["can_trade"] is True
    assert body["next"] is None
    assert [s["state"] for s in body["steps"]] == ["done", "done", "done", "done"]
    # Order ticket default is measured from the broker spec, never invented.
    assert body["order_defaults"]["size"] == str(FakeTerminal().symbol_spec.volume_min)
    assert body["plan_id"] == provider_fixture.registry_entry()["strategy_id"]
    _assert_product_surface_is_plain(body)
    # Engineering internals remain available for Advanced views.
    assert body["technical"]["stage"]["stage"] == "STAGE_2_MIN_SIZE_ORDER"


def test_guide_reports_kill_switch_as_stopped(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    assert client.post("/api/demo/kill", json={"reason": "guide test"}).json()["killed"] is True
    body = client.get("/api/demo/guide").json()
    assert body["status"] == "stopped"
    assert body["headline"] == "Stopped"
    assert body["reason"] == "Trading is stopped by the kill switch."
    assert body["next"]["action"] == "resume"
    assert body["can_trade"] is False


def test_guide_resume_is_reachable_when_the_terminal_is_gone(client, api_env, monkeypatch):
    """Journey regression: a stopped system must offer "Review and resume"
    even when no terminal can be connected.

    The UI tells the operator "You can review and resume from Trading" after
    Stop trading. If the resume action hid behind the connection/identity/
    readiness steps, a machine without MetaTrader 5 could never clear the
    stop — a dead end. Clearing never grants order permission: the stage
    must be prepared again and every gate still applies."""
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    def _no_terminal() -> dict:
        raise RuntimeError(
            "MetaTrader5 package not installed — DEMO identity cannot be verified (fail closed)"
        )

    monkeypatch.setattr(session, "connectivity_report", _no_terminal)

    assert client.post("/api/demo/kill", json={"reason": "guide test"}).json()["killed"] is True
    body = client.get("/api/demo/guide").json()
    assert body["connection"]["connected"] is False
    assert body["kill_switch"]["active"] is True
    assert body["status"] == "stopped"
    assert body["headline"] == "Stopped"
    assert body["next"]["action"] == "resume"
    assert body["can_trade"] is False

    # Clearing the stop requires a reason and still grants nothing: the guide
    # falls back to the honest connection blocker, never to permission.
    refused = client.post("/api/demo/guide/resume", json={"confirmed": True, "reason": ""})
    assert refused.status_code == 400
    ok = client.post(
        "/api/demo/guide/resume", json={"confirmed": True, "reason": "reviewed the stop; clearing"}
    )
    assert ok.status_code == 200
    body2 = client.get("/api/demo/guide").json()
    assert body2["kill_switch"]["active"] is False
    assert body2["can_trade"] is False
    assert body2["next"]["action"] == "check_connection"


def test_guide_reports_unreconciled_state_without_crashing(client, api_env, monkeypatch):
    """A drift report must surface as a human blocker, not a stack trace."""
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)
    monkeypatch.setattr(session, "reconcile", lambda: {"requires_suspend": True, "drift": "SIMULATED", "details": "x"})

    body = client.get("/api/demo/guide").json()
    assert body["reconciliation"]["clean"] is False
    assert body["can_trade"] is False
    if body["readiness"]["ready"] and body["kill_switch"]["active"] is False:
        assert body["headline"] == "Not ready"
        assert body["reason"] == "QTS and the broker disagree about open positions."


# --------------------------------------------------------------- identity flow


def test_record_and_confirm_identity_flow(client, api_env, monkeypatch, passing_readiness):
    from fakes_mt5_demo import FakeTerminal

    terminal = FakeTerminal()
    session = _fresh_session(api_env, terminal, with_pin=False)
    _inject(session, monkeypatch)

    body = client.get("/api/demo/guide").json()
    assert body["identity"]["recorded"] is False
    assert body["next"]["action"] == "record_identity"

    recorded = client.post("/api/demo/guide/record-identity", json={})
    assert recorded.status_code == 200, recorded.text
    result = recorded.json()
    assert result["result"]["ok"] is True
    assert result["guide"]["identity"]["recorded"] is True
    assert result["guide"]["identity"]["confirmed"] is False
    assert result["guide"]["next"]["action"] == "confirm_identity"

    # Confirmation is an explicit owner act.
    refused = client.post("/api/demo/guide/confirm-identity", json={})
    assert refused.status_code == 400

    confirmed = client.post("/api/demo/guide/confirm-identity", json={"confirmed": True})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result"]["ok"] is True
    assert confirmed.json()["guide"]["identity"]["confirmed"] is True
    assert confirmed.json()["guide"]["identity"]["verified"] is True


def test_record_identity_refuses_without_a_terminal(client):
    """Recording is evidence, not permission: no live identity ⇒ refusal."""
    response = client.post("/api/demo/guide/record-identity", json={})
    assert response.status_code == 409
    body = response.json()
    assert body["result"]["ok"] is False
    assert body["result"]["headline"] == "The account could not be recorded."


# ------------------------------------------------------------------- prepare


def test_prepare_requires_explicit_confirmation(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    session = _fresh_session(api_env, FakeTerminal(), with_pin=True)
    _inject(session, monkeypatch)
    for payload in ({}, {"confirmed": True}, {"risk_ack": True}):
        response = client.post("/api/demo/guide/prepare", json=payload)
        assert response.status_code == 400, payload


def test_prepare_arms_a_fresh_session(client, api_env, monkeypatch, passing_readiness):
    """The guided prepare re-proves the CLI arm prerequisites and reaches READY."""
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _fresh_session(api_env, terminal, with_pin=True)
    _inject(session, monkeypatch)

    response = client.post("/api/demo/guide/prepare", json={"confirmed": True, "risk_ack": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["ok"] is True
    guide = body["guide"]
    assert guide["status"] == "ready", guide
    assert guide["can_trade"] is True
    assert guide["stage_allows_orders"] is True

    # The stage machine recorded real transitions (DISABLED → 1 → 2), audited.
    from qts.lifecycle.demo_stage import DemoStage

    assert session.stage.current().stage == DemoStage.STAGE_2_MIN_SIZE_ORDER.value
    assert session.authority.current().execution_permitted is True


def test_prepare_refuses_when_readiness_fails(client, api_env, monkeypatch, failing_readiness):
    from fakes_mt5_demo import FakeTerminal

    terminal = FakeTerminal()
    session = _fresh_session(api_env, terminal, with_pin=True)
    _inject(session, monkeypatch)

    response = client.post("/api/demo/guide/prepare", json={"confirmed": True, "risk_ack": True})
    assert response.status_code == 409
    body = response.json()
    assert body["result"]["ok"] is False
    assert body["result"]["headline"] == "Demo trading could not be prepared."
    assert "safety checks" in (body["result"]["detail"] or "")

    # Fail closed: the stage machine did NOT move.
    assert session.stage.current().stage == "DISABLED"
    assert session.authority.current().execution_permitted is False


# ------------------------------------------------------------------- refresh


def test_refresh_requires_confirmation_and_an_order_stage(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    session = _fresh_session(api_env, FakeTerminal(), with_pin=True)
    _inject(session, monkeypatch)

    assert client.post("/api/demo/guide/refresh", json={}).status_code == 400
    refused = client.post("/api/demo/guide/refresh", json={"confirmed": True, "risk_ack": True})
    assert refused.status_code == 409
    assert refused.json()["result"]["headline"] == "Nothing to refresh yet."


def test_refresh_reverifies_at_the_order_stage(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    response = client.post("/api/demo/guide/refresh", json={"confirmed": True, "risk_ack": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["ok"] is True
    assert body["result"]["headline"] == "Connection refreshed."
    # Refresh is permission renewal, never a transition.
    assert body["guide"]["technical"]["stage"]["stage"] == "STAGE_2_MIN_SIZE_ORDER"
    assert body["guide"]["can_trade"] is True


# -------------------------------------------------------------------- resume


def test_resume_requires_a_reason(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    session = _fresh_session(api_env, FakeTerminal(), with_pin=True)
    _inject(session, monkeypatch)
    for payload in ({}, {"confirmed": True}, {"reason": "   "}):
        assert client.post("/api/demo/guide/resume", json=payload).status_code == 400, payload


def test_resume_clears_the_kill_switch_but_keeps_the_stage_halted(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    assert client.post("/api/demo/kill", json={"reason": "guide test"}).json()["killed"] is True
    assert session.stage.current().stage == "HALTED"

    response = client.post(
        "/api/demo/guide/resume", json={"confirmed": True, "reason": "reviewed the stop; continuing test"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["ok"] is True
    guide = body["guide"]
    assert guide["kill_switch"]["active"] is False
    # Clearing the stop never resumes trading: the stage stays HALTED until
    # the account is prepared again.
    assert guide["technical"]["stage"]["stage"] == "HALTED"
    assert guide["can_trade"] is False
    assert guide["next"]["action"] == "prepare"
