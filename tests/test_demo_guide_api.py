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
    "execution_readiness",
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


# ------------------------------------------- resume: HTTP == the real outcome
#
# The Windows host answered ``200 OK`` to ``POST /api/demo/guide/resume`` while
# the system stayed suspended and every order kept returning 409: resume
# cleared ``risk_state.killed`` but never ``reconcile_state.suspended``, which
# had no recovery edge at all. These tests pin the contract that a 2xx now
# means the requested recovery ACTUALLY happened, and that a remaining blocker
# is reported as 409 with a machine-readable reason.


def _venue_drift_position():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    return SimpleNamespace(
        ticket=555_001,
        symbol="XAUUSD@",
        volume=0.01,
        type=0,
        price_open=2000.0,
        price_current=2000.0,
        profit=-1.0,
        time=int(datetime.now(UTC).timestamp()) - 60,
        comment="",
        magic=0,
    )


def _suspend_reconciliation(client, session, terminal) -> None:
    """Drive the REAL drift path: a venue position QTS cannot account for."""
    terminal.positions = [_venue_drift_position()]
    terminal.deals = []
    assert session.reconcile()["requires_suspend"] is True
    refused = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True},
    )
    assert refused.status_code == 409, refused.text
    assert "reconciliation_ready" in refused.json()["verdict"]["failed"]
    assert terminal.requests == [], "a refused gate must never reach the broker"


def test_resume_reports_409_while_a_real_blocker_remains(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    from qts.execution.engine import load_reconcile_suspension

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)
    _suspend_reconciliation(client, session, terminal)

    # The drift is still present: recovery is impossible and must say so.
    response = client.post(
        "/api/demo/guide/resume", json={"confirmed": True, "reason": "trying to clear the halt"}
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["result"]["ok"] is False
    recovery = body["recovery"]
    assert recovery["recovered"] is False
    assert recovery["changed"] is False
    assert recovery["cleared"] == []
    assert "reconciliation_suspension" in {b["id"] for b in recovery["active_blockers"]}
    assert recovery["recovery_checks"]["reconciliation_verified_clean"]["satisfied"] is False

    # The operator reads plain language; the gate id stays machine-readable
    # in `recovery`, not in the message shown on the product surface.
    detail = body["result"]["detail"]
    assert "QTS and the broker still disagree about open positions" in detail
    assert not detail.startswith("reconciliation_suspension:")

    # Nothing was cleared — all-or-nothing, and durable.
    assert load_reconcile_suspension(session.db_path).suspended is True
    assert session.kill_switch_state()["killed"] is True
    assert client.get("/api/demo/guide").json()["status"] == "stopped"


def test_resume_recovers_the_whole_durable_suspension_set_once_it_is_safe(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    from qts.execution.engine import load_reconcile_suspension

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)
    _suspend_reconciliation(client, session, terminal)

    # The operator resolves the divergence at the venue.
    terminal.positions = []
    terminal.deals = []

    response = client.post(
        "/api/demo/guide/resume", json={"confirmed": True, "reason": "venue position closed and verified"}
    )
    assert response.status_code == 200, response.text
    recovery = response.json()["recovery"]
    assert recovery["recovered"] is True
    assert set(recovery["cleared"]) == {"reconciliation_suspension", "kill_switch"}
    assert recovery["active_blockers"] == []
    # A successful recovery must NOT imply that trading is ready.
    assert recovery["orders_permitted"] is False
    assert recovery["next"] == "prepare"

    assert load_reconcile_suspension(session.db_path).suspended is False
    assert session.kill_switch_state()["killed"] is False

    guide = response.json()["guide"]
    assert guide["kill_switch"]["active"] is False
    assert guide["reconciliation"]["suspended"] is False
    assert guide["can_trade"] is False
    assert guide["next"]["action"] == "prepare"


def test_resume_prepare_order_surfaces_agree_after_recovery(client, api_env, monkeypatch, passing_readiness):
    """resume → prepare → order must describe ONE state, not three."""
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)
    _suspend_reconciliation(client, session, terminal)
    terminal.positions = []
    terminal.deals = []

    assert (
        client.post("/api/demo/guide/resume", json={"confirmed": True, "reason": "resolved"}).status_code == 200
    )
    prepared = client.post("/api/demo/guide/prepare", json={"confirmed": True, "risk_ack": True})
    assert prepared.status_code == 200, prepared.text

    guide = client.get("/api/demo/guide").json()
    assert guide["status"] == "ready"
    assert guide["can_trade"] is True

    # The order path sees the SAME readiness — proved without sending an order.
    dry = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "dry_run": True},
    )
    assert dry.status_code == 200, dry.text
    verdict = dry.json()["verdict"]
    assert verdict["passed"] is True, verdict["failed"] + verdict["unknown"]
    assert verdict["checks"]["reconciliation_ready"]["status"] == "PASS"
    assert verdict["checks"]["kill_switch_functional"]["status"] == "PASS"
    assert terminal.requests == [], "no broker order was submitted anywhere in this test"


def test_resume_on_an_unsuspended_system_is_an_honest_no_op(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    response = client.post("/api/demo/guide/resume", json={"confirmed": True, "reason": "nothing is stopped"})
    assert response.status_code == 200, response.text
    recovery = response.json()["recovery"]
    assert recovery["recovered"] is True
    assert recovery["changed"] is False
    assert recovery["cleared"] == []
    assert recovery["recovery_checks"]["no_active_suspension"]["satisfied"] is True
    assert terminal.requests == []


# ------------------------------------------- readiness-evidence decay handoff


def _decay_authority_evidence(session, seconds: float = 284.0) -> None:
    """Time-travel the durable authority row: last transition `seconds` ago.

    This does NOT weaken the 120s reverify TTL — it exercises it, simulating
    the field sequence (prepared at T, order attempted at T+284s).
    """
    from datetime import UTC, datetime, timedelta

    from qts.db import connect as db_connect

    stale = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    with db_connect(session.authority.db_path) as con:
        con.execute(
            "UPDATE demo_execution_state SET decided_at = ? WHERE seq = "
            "(SELECT MAX(seq) FROM demo_execution_state)",
            (stale,),
        )


def test_order_auto_reproves_decayed_evidence_inside_the_request(client, api_env, monkeypatch):
    """Canonical workflow: evidence decay is never the operator's problem.

    284s-old durable evidence + an order request (which IS explicit
    confirmed+risk_ack operator intent) ⇒ the backend re-proves readiness
    itself — a fresh live-terminal probe, durably recorded through the same
    authority gates — and the order is judged on evidence measured in this
    very request. No client refresh call, no manual TTL management.
    """
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    _decay_authority_evidence(session, seconds=284.0)
    assert session.authority.current().readiness_expired is True

    res = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "rationale": "decay probe"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["allowed"] is True
    assert body["broker_order_id"] is not None
    assert len(terminal.requests) == 1, "exactly one broker order, judged on fresh evidence"

    renewed = session.authority.current()
    assert renewed.execution_permitted is True
    assert renewed.readiness_expired is False, "the re-proof must be durably recorded, not transient"


def test_order_fails_closed_when_the_fresh_reproof_fails(client, api_env, monkeypatch):
    """Nothing weakened: the auto-re-proof can refuse, and then the order refuses.

    Decayed evidence + a terminal that no longer passes the readiness probe
    ⇒ the in-request re-verification fails, permission stays refused, the
    order is 409 and no broker request is ever sent. The TTL still forbids
    trading on stale evidence — it is renewable only by a PASSING fresh probe.
    """
    from fakes_mt5_demo import FakeTerminal
    from test_demo_api import _readiness

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    _decay_authority_evidence(session, seconds=284.0)
    # The terminal degrades AFTER arming: the fresh probe now fails.
    monkeypatch.setattr(
        "qts.lifecycle.demo_gate.demo_forward_readiness_report", lambda **kwargs: _readiness(False)
    )

    res = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "rationale": "degraded probe"},
    )
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["allowed"] is False
    assert body["reasons"], "the refusal must carry the actual reasons"
    assert terminal.requests == [], "no broker order may be submitted when the fresh re-proof fails"
    assert session.authority.current().execution_permitted is False


def test_guide_refresh_renews_decayed_evidence_and_the_order_consumes_it(client, api_env, monkeypatch):
    """The explicit refresh remains a valid operator action (not a requirement).

    Decayed durable evidence -> POST /api/demo/guide/refresh (fresh
    live-terminal probe, durably recorded with explicit confirmation) ->
    the order is judged on evidence measured seconds ago and proceeds.
    Since the order path re-proves decayed evidence itself, this endpoint
    is a convenience for the UI, never a prerequisite.
    """
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    _decay_authority_evidence(session, seconds=284.0)

    refreshed = client.post("/api/demo/guide/refresh", json={"confirmed": True, "risk_ack": True})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["result"]["ok"] is True

    res = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "rationale": "fresh evidence order"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["allowed"] is True
    assert body["broker_order_id"] is not None
    assert body["broker_position_id"] is not None
    assert len(terminal.requests) == 1, "exactly one broker order, on fresh evidence only"


# ------------------------------------- continuous execution-readiness state


def test_execution_readiness_classifies_a_bare_system_as_environment_not_ready(client):
    """No terminal, no plan, no arming ⇒ ENVIRONMENT_NOT_READY, each blocker named."""
    er = client.get("/api/demo/guide").json()["execution_readiness"]
    assert er["state"] == "ENVIRONMENT_NOT_READY"
    assert er["blockers"], "a bare system must name its blockers"
    ids = {b["id"] for b in er["blockers"]}
    assert "connection" in ids
    for b in er["blockers"]:
        assert b["category"] in ("environment", "market", "policy")
        assert b["plain"].strip(), f"blocker {b['id']} must carry plain language"
    assert er["last_execution"] is None


def test_execution_readiness_is_system_ready_when_armed(client, api_env, monkeypatch):
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    session = _armed_session(api_env, FakeTerminal(), monkeypatch)
    _inject(session, monkeypatch)

    er = client.get("/api/demo/guide").json()["execution_readiness"]
    assert er["state"] == "SYSTEM_READY", er
    assert er["blockers"] == []


def test_execution_readiness_full_transition_ready_blocked_ready(client, api_env, monkeypatch, passing_readiness):
    """READY → kill (policy block) → resume (environment: re-prepare) → prepare → READY.

    The classification tracks the durable state at every step and never
    misnames the cause: a halted stage during a kill is reported as the
    policy stop, not as a configuration defect.
    """
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    assert client.get("/api/demo/guide").json()["execution_readiness"]["state"] == "SYSTEM_READY"

    assert client.post("/api/demo/kill", json={"reason": "transition test"}).json()["killed"] is True
    er = client.get("/api/demo/guide").json()["execution_readiness"]
    assert er["state"] == "BLOCKED_MARKET_POLICY", er
    kill_blockers = [b for b in er["blockers"] if b["id"] == "kill_switch"]
    assert kill_blockers and kill_blockers[0]["category"] == "policy"
    assert "kill switch" in kill_blockers[0]["plain"]
    assert not any(b["category"] == "environment" for b in er["blockers"]), (
        "a halted stage during a kill is a consequence of the stop, not an environment defect"
    )

    assert client.post("/api/demo/guide/resume", json={"confirmed": True, "reason": "reviewed"}).status_code == 200
    er = client.get("/api/demo/guide").json()["execution_readiness"]
    assert er["state"] == "ENVIRONMENT_NOT_READY", er
    assert any(b["id"] == "stage" for b in er["blockers"]), "after resume, re-preparation is the honest next step"

    assert client.post("/api/demo/guide/prepare", json={"confirmed": True, "risk_ack": True}).status_code == 200
    er = client.get("/api/demo/guide").json()["execution_readiness"]
    assert er["state"] == "SYSTEM_READY", er


def test_execution_readiness_reports_the_last_execution_and_decay_note(client, api_env, monkeypatch):
    """After a fill: SYSTEM_READY again, last_execution carries broker evidence,
    and pure evidence decay is a note (auto-renewed at order), never a blocker."""
    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    res = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "rationale": "readiness evidence"},
    )
    assert res.status_code == 200, res.text
    placed = res.json()

    _decay_authority_evidence(session, seconds=284.0)

    body = client.get("/api/demo/guide").json()
    er = body["execution_readiness"]
    assert er["state"] == "SYSTEM_READY", er
    assert all(b["id"] != "permission" for b in er["blockers"])
    assert any("re-proven automatically" in n for n in er["notes"])
    assert body["can_trade"] is True, "pure decay must not demand manual TTL management"
    assert er["last_execution"] is not None
    assert er["last_execution"]["broker_order_id"] == placed["broker_order_id"]


# --------------------------------------------- engine refusal must be named


def test_engine_refusal_surfaces_the_recorded_reason_not_a_generic_label(client, api_env, monkeypatch):
    """The broker's/engine's verbatim answer reaches the operator.

    The session already journals the real refusal detail; the API response
    must surface the SAME detail — never only a generic
    ``execution_engine_refused`` label.
    """
    from types import SimpleNamespace

    from fakes_mt5_demo import FakeTerminal

    _register_plan(api_env)
    terminal = FakeTerminal()
    session = _armed_session(api_env, terminal, monkeypatch)
    _inject(session, monkeypatch)

    broker_answer = "broker rejected order: retcode 10019 (TRADE_RETCODE_NO_MONEY)"
    monkeypatch.setattr(session.engine, "submit_intent", lambda intent, tick=None: (None, []))
    monkeypatch.setattr(
        session.engine.om,
        "get",
        lambda cid: SimpleNamespace(state="REJECTED", reject_reason=broker_answer),
    )

    res = client.post(
        "/api/demo/order",
        json={"side": "BUY", "stop_loss": "1995.00", "confirmed": True, "risk_ack": True, "rationale": "refusal detail"},
    )
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["allowed"] is False
    assert body["reasons"], "the refusal must carry reasons"
    assert broker_answer in body["reasons"][0]
    assert body["reasons"] != ["execution_engine_refused"]

    # The surfaced reason IS the journaled reason — one truth, two surfaces.
    orders = client.get("/api/demo/journal").json()["orders"]
    row = next(o for o in orders if o["client_order_id"] == body["client_order_id"])
    assert row["exit_reason"] == body["reasons"][0]
    assert row["broker_retcode"] == "10019"
