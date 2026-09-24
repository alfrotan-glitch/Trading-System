"""Autonomous DEMO loop integration test (fake terminal, fake frozen provider).

Everything here runs against a simulated MT5 terminal and a deterministic
provider: **no broker is contacted and no real order exists anywhere**. The
point is to prove the autonomous path actually works — generate, submit, manage,
close, journal — and that it stops for the right reasons.

The loop is exercised with an eligible, parameter-frozen strategy registered, so
this file covers the *trading* half of the contract that
``test_demo_session_wiring.py`` covers the *refusal* half of.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import fakes_demo_provider as provider_fixture
import pytest
from fakes_mt5_demo import FakeTerminal

from qts.db import connect
from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot
from qts.execution.demo_identity import confirm_pin, write_pin
from qts.execution.demo_session import DemoSession, DemoSessionConfig
from qts.lifecycle.demo_authority import readiness_age_seconds
from qts.lifecycle.demo_authorization import document_fingerprint
from qts.lifecycle.demo_gate import demo_forward_readiness_report
from qts.lifecycle.demo_stage import DemoStage

# --------------------------------------------------------------- fake terminal


# ------------------------------------------------------------------ fixtures


@pytest.fixture()
def authorized(tmp_path: Path, monkeypatch):
    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": "DEMO-AUTH-INTEGRATION",
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "integration test",
        "statement": "integration authorization — DEMO only, LIVE locked, zero real capital",
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
    (tmp_path / "authorization.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(tmp_path / "authorization.json"))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    monkeypatch.setenv("QTS_MODE", "demo_execution")
    return doc


def _write_registry(tmp_path: Path, entry: dict | None) -> None:
    registry = {
        "schema": "qts.demo_forward_registry.v1",
        "research_integrity": {
            "optimization_allowed": False,
            "no_forward_fitting": True,
            "hypothesis_preregistered": True,
        },
        "entries": [entry] if entry else [],
    }
    (tmp_path / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    import os

    os.environ["QTS_DEMO_REGISTRY"] = str(tmp_path / "registry.json")


def _armed_session(tmp_path: Path, terminal: FakeTerminal) -> DemoSession:
    """A session with identity pinned, authority enabled and Stage 3 armed."""
    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=tmp_path / "qts.db",
            actor="integration-test",
            mt5_module=terminal,
        )
    )
    write_pin(session.adapter.broker_identity(), actor="test")
    assert confirm_pin(actor="owner")[0] is True

    report = session.connectivity_report()
    session.stage.advance(
        DemoStage.STAGE_1_CONNECTIVITY,
        actor="test",
        reason="integration arming",
        prerequisites={
            "readiness_passed": bool(report["readiness"]["passed"]),
            "account_is_demo": report["identity"]["is_demo"] is True,
            "symbol_ok": bool(report["symbol_mapping"]["ok"]),
            "quote_fresh": bool(report["quote"]["fresh"]),
        },
    )
    rpt = demo_forward_readiness_report(
        mt5_module=terminal, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"}
    )
    decision = session.authority.enable(
        readiness=rpt,
        confirmed=True,
        risk_ack=True,
        readiness_age_s=readiness_age_seconds(rpt),
        actor="integration-test",
    )
    assert decision.execution_permitted is True, decision.reasons
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test", reason="integration arming")
    session.stage.advance(DemoStage.STAGE_3_FORWARD_OBSERVATION, actor="test", reason="integration arming")
    session.reconcile()
    return session


# ---------------------------------------------------------------------- tests


def test_autopilot_submits_a_labelled_research_demo_order(tmp_path: Path, authorized):
    _write_registry(tmp_path, provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test")
    )
    assert report.halted is False, report.halt_reason
    assert report.orders_submitted == 1

    # The broker received exactly one order, minimum size, with its stop.
    assert len(terminal.requests) == 1
    request = terminal.requests[0]
    assert request["symbol"] == "XAUUSD@"
    assert request["volume"] == 0.01
    assert request["type"] == terminal.ORDER_TYPE_BUY
    assert request["sl"] == pytest.approx(1995.00)
    assert request["tp"] == pytest.approx(2010.20)

    # The journal carries the whole execution record.
    rows = session.journal.list_orders()
    assert len(rows) == 1
    row = rows[0]
    assert "RESEARCH_DEMO_ORDER" in (row["notes"] or "")
    assert row["broker_order_id"]
    assert row["broker_position_id"]
    assert Decimal(row["requested_price"]) == Decimal("2000.20")
    assert row["executed_price"]
    assert row["spread_bps"] is not None and float(row["spread_bps"]) > 0
    assert row["slippage_bps"] is not None
    assert row["latency_ms"] is not None
    assert row["strategy_config_hash"] == provider_fixture.registry_entry()["params_hash"]
    assert row["state"] in ("ACCEPTED", "FILLED")


def test_open_position_is_managed_and_closed_with_a_recorded_exit(tmp_path: Path, authorized):
    _write_registry(tmp_path, provider_fixture.registry_entry(max_hold_seconds=60.0))
    terminal = FakeTerminal(open_age_s=600.0)
    session = _armed_session(tmp_path, terminal)

    # Cycle 1 opens the position; cycle 2 finds it past max hold and closes it.
    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=2, poll_interval_s=0, actor="test")
    )
    assert report.orders_submitted == 1
    closes = [r for r in terminal.requests if "position" in r]
    assert len(closes) == 1, "position past max_hold_seconds must be closed"

    row = session.journal.list_orders()[0]
    assert row["state"] == "CLOSED"
    assert "max_hold_seconds" in (row["exit_reason"] or "")
    assert Decimal(row["realized_pnl"]) == Decimal("-1.00")
    assert terminal.positions == []


def test_unrealized_pnl_is_recorded_while_the_position_is_open(tmp_path: Path, authorized):
    _write_registry(tmp_path, provider_fixture.registry_entry(max_hold_seconds=3600.0))
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    run_autopilot(session, AutopilotConfig(symbol="XAUUSD", max_iterations=2, poll_interval_s=0, actor="test"))
    row = session.journal.list_orders()[0]
    assert row["state"] != "CLOSED"
    assert Decimal(row["unrealized_pnl"]) == Decimal("-1.00")


def test_provider_exposing_an_optimization_hook_is_refused(tmp_path: Path, authorized):
    entry = provider_fixture.registry_entry(provider="fakes_demo_provider:SelfOptimizingProvider")
    _write_registry(tmp_path, entry)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test")
    )
    assert report.halted is True
    assert "optimization hook" in (report.halt_reason or "").lower()
    assert report.orders_submitted == 0
    assert terminal.requests == []


def test_parameter_drift_after_registration_halts_the_loop(tmp_path: Path, authorized):
    entry = provider_fixture.registry_entry(provider="fakes_demo_provider:DriftingSignalProvider")
    _write_registry(tmp_path, entry)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test")
    )
    assert report.halted is True
    assert "parameter drift" in (report.halt_reason or "").lower()
    assert report.orders_submitted == 0


def test_daily_order_cap_stops_new_orders_without_halting(tmp_path: Path, authorized):
    _write_registry(tmp_path, provider_fixture.registry_entry(max_orders_per_day=1))
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    first = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test")
    )
    assert first.orders_submitted == 1
    assert session.journal.orders_today() == 1

    # A fresh provider instance would happily emit again; the cap must not.
    from qts.execution.demo_autopilot import AutopilotConfig as Cfg

    second = run_autopilot(session, Cfg(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test"))
    assert second.orders_submitted == 0
    assert any(event["kind"] == "skip" for event in second.events)
    assert len([r for r in terminal.requests if "position" not in r]) == 1


def test_eligible_strategy_may_still_decline_to_trade(tmp_path: Path, authorized):
    """A registered strategy returning no signal is a recorded NO_TRADE, not an error."""
    entry = provider_fixture.registry_entry(provider="fakes_demo_provider:NoSignalProvider")
    _write_registry(tmp_path, entry)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=2, poll_interval_s=0, actor="test")
    )
    assert report.halted is False
    assert report.orders_submitted == 0
    assert report.no_trade == 2
    assert terminal.requests == []
    with connect(session.db_path) as con:
        rows = con.execute("SELECT decision, reason FROM demo_signal_journal").fetchall()
    assert len(rows) == 2
    assert all(row[0] == "NO_TRADE" for row in rows)


def test_daily_loss_limit_blocks_further_orders(tmp_path: Path, authorized):
    """Once the DEMO daily loss limit is consumed, orders stop (not more risk)."""
    _write_registry(tmp_path, provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    # Simulate a day that already lost more than the DEMO limit allows.
    journal_id = session.journal.open_order(
        client_order_id="demo-earlier-loss",
        strategy_id="TEST-PREREG-01",
        strategy_config_hash="x",
        symbol="XAUUSD",
        broker_symbol="XAUUSD@",
        side="BUY",
        requested_lots=Decimal("0.01"),
        requested_price=Decimal("2000.20"),
        order_request={"symbol": "XAUUSD@", "volume": 0.01, "type": 0},
    )
    session.journal.mark_outcome(
        journal_id,
        state="CLOSED",
        exit_reason="earlier loss in the same UTC day",
        realized_pnl=Decimal("-99999"),
    )
    assert session.journal.daily_realized_pnl() <= Decimal("-99999")

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test")
    )
    assert report.orders_submitted == 0
    assert terminal.requests == []
    verdict = session.preflight(side="BUY", stop_loss=Decimal("1995.00"))["verdict"]
    assert "max_daily_loss" in verdict["failed"]
