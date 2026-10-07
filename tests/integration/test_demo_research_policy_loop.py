"""The registered DEMO research policy drives the autonomous loop.

This is the contract that matters after registration: the policy in
``data/evidence/demo_forward_validation_registry_2026-09-23.json`` is not a
document — it is the thing that decides what the loop may do. These tests use
the REAL registered provider (``qts.research.demo_execution_probe``) and the
REAL frozen parameters, against a simulated terminal, so a policy that has
drifted away from its registration, or a gate that ignores the policy's limits,
fails here.

No broker is contacted and no order exists anywhere: the terminal is a fake.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fakes_mt5_demo import FakeTerminal

from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot
from qts.execution.demo_identity import confirm_pin, write_pin
from qts.execution.demo_session import DemoSession, DemoSessionConfig
from qts.lifecycle.demo_authority import readiness_age_seconds
from qts.lifecycle.demo_authorization import document_fingerprint
from qts.lifecycle.demo_gate import demo_forward_readiness_report
from qts.lifecycle.demo_policy import policy_fingerprint
from qts.lifecycle.demo_registry import load_registry, resolve_entry
from qts.lifecycle.demo_stage import DemoStage
from qts.research.demo_execution_probe import STRATEGY_ID, ExecutionCostProbe

PROVIDER_SOURCE = Path(__file__).resolve().parents[2] / "src/qts/research/demo_execution_probe.py"


def _any_hours() -> dict:
    """A window that contains now, so the loop test is not clock-dependent.

    The policy's real session (Mon-Fri 08:00-16:00 UTC) is asserted as
    registered data in ``test_shipped_policy_declares_a_liquid_session``; these
    loop tests override it so the *enforcement* under test is not a coin toss
    on when CI happens to run.
    """
    return {
        "timezone": "UTC",
        "sessions": [
            {"days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "start": "00:00", "end": "23:59"}
        ],
    }


def _outside_hours() -> dict:
    """A session window guaranteed to exclude now (today and tomorrow omitted).

    Day-based exclusion is used instead of a clock patch so the test stays
    deterministic without a seam in production code; a midnight crossing during
    the run still lands on an excluded day.
    """
    now = datetime.now(UTC)
    excluded = {now.strftime("%a").upper()}
    for offset in (1, 2):
        excluded.add(datetime.fromtimestamp(now.timestamp() + offset * 86400, UTC).strftime("%a").upper())
    days = [d for d in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN") if d not in excluded]
    return {
        "timezone": "UTC",
        "sessions": [{"days": days, "start": "00:00", "end": "23:59"}],
    }


def _policy_block(**overrides) -> dict:
    """The shipped policy block, re-sealed against the source on disk."""
    block = json.loads(
        (Path(__file__).resolve().parents[2] / "data/evidence/demo_forward_validation_registry_2026-09-23.json")
        .read_text(encoding="utf-8")
    )
    entry = next(e for e in block["entries"] if e["strategy_id"] == STRATEGY_ID)
    policy = dict(entry["policy"])
    policy["code_hash"] = hashlib.sha256(PROVIDER_SOURCE.read_bytes()).hexdigest()
    policy.update(overrides)
    # Re-seal: changing a policy invalidates its hash, and an unsealed policy is
    # (correctly) refused. Registering a change means re-sealing it, exactly as
    # scripts/register_demo_research_policy.py does.
    policy["policy_hash"] = policy_fingerprint(policy)
    return policy


def _registry_doc(entry_overrides: dict | None = None, policy_overrides: dict | None = None) -> dict:
    shipped = json.loads(
        (Path(__file__).resolve().parents[2] / "data/evidence/demo_forward_validation_registry_2026-09-23.json")
        .read_text(encoding="utf-8")
    )
    entry = next(e for e in shipped["entries"] if e["strategy_id"] == STRATEGY_ID)
    entry = json.loads(json.dumps(entry))  # deep copy
    overrides = dict(policy_overrides or {})
    overrides.setdefault("allowed_trading_hours", _any_hours())
    entry["policy"] = _policy_block(**overrides)
    entry.update(entry_overrides or {})
    return {
        "schema": "qts.demo_forward_registry.v2",
        "research_integrity": {
            "optimization_allowed": False,
            "no_forward_fitting": True,
            "parameters_frozen": True,
        },
        "entries": [entry],
    }


@pytest.fixture()
def authorized(tmp_path: Path, monkeypatch):
    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": "DEMO-AUTH-POLICY-TEST",
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "integration test",
        "statement": "registered research policy integration — DEMO only, LIVE locked, zero real capital",
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


def _armed_session(tmp_path: Path, terminal: FakeTerminal) -> DemoSession:
    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=tmp_path / "qts.db",
            actor="policy-test",
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
        actor="policy-test",
    )
    assert decision.execution_permitted is True, decision.reasons
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test", reason="integration arming")
    session.stage.advance(DemoStage.STAGE_3_FORWARD_OBSERVATION, actor="test", reason="integration arming")
    session.reconcile()
    return session


def _write_registry(tmp_path: Path, doc: dict, monkeypatch=None) -> None:
    """Write the registry; ``monkeypatch`` owns the env var when provided.

    Only the ad-hoc entry point (no monkeypatch — a scratch session) touches
    ``os.environ``; tests must use monkeypatch so the path cannot leak into
    other modules and change their registry-dependent results.
    """
    (tmp_path / "registry.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setenv("QTS_DEMO_REGISTRY", str(tmp_path / "registry.json"))
    else:
        import os

        os.environ["QTS_DEMO_REGISTRY"] = str(tmp_path / "registry.json")


# ---------------------------------------------------------------------- tests


def test_shipped_policy_declares_a_liquid_session_and_a_complete_spec():
    """The registered policy's declared limits are what the operator approved."""
    policy = _policy_block()
    assert policy["policy_class"] == "DEMO_FORWARD_RESEARCH_POLICY"
    assert policy["validated_edge"] is False
    assert policy["hypothesis_id"] == "H-EXEC-01"
    assert Path(policy["preregistration_artifact"]).exists()
    hours = policy["allowed_trading_hours"]
    assert hours["timezone"] == "UTC"
    assert hours["sessions"] == [{"days": ["MON", "TUE", "WED", "THU", "FRI"], "start": "08:00", "end": "16:00"}]
    assert policy["max_orders_per_day"] == 2
    assert policy["max_daily_loss"] == 5.00
    assert policy["max_drawdown"] == 10.00
    assert policy["max_simultaneous_exposure_lots"] == 0.01
    assert policy["stop_loss_logic"]["distance_price"] == 2.00
    assert policy["exit_conditions"]["max_hold_seconds"] == 900


def test_registered_policy_drives_a_minimum_size_order_with_its_stop(tmp_path: Path, authorized, monkeypatch):
    """One scheduled round turn: broker minimum, protective stop, full record."""
    _write_registry(tmp_path, _registry_doc(), monkeypatch)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="policy-test")
    )
    assert report.halted is False, report.halt_reason
    assert report.orders_submitted == 1, report.events

    assert len(terminal.requests) == 1
    request = terminal.requests[0]
    assert request["symbol"] == "XAUUSD@"
    assert request["volume"] == pytest.approx(0.01)  # broker minimum, not equity-scaled
    assert request["sl"] is not None  # the stop is on the order, not just the plan

    # Direction is the deterministic UTC-hour rule, and the stop sits 2.00 away
    # from the executable side of the quote — both frozen by the policy.
    parity_side = "BUY" if datetime.now(UTC).hour % 2 == 0 else "SELL"
    reference = Decimal("2000.20") if parity_side == "BUY" else Decimal("2000.00")
    expected = reference - Decimal("2.00") if parity_side == "BUY" else reference + Decimal("2.00")
    assert request["sl"] == pytest.approx(float(expected), abs=0.01)

    row = session.journal.list_orders()[0]
    assert row["side"] == parity_side
    assert row["strategy_id"] == STRATEGY_ID
    assert row["strategy_config_hash"] == ExecutionCostProbe().config_hash()
    assert row["hypothesis_id"] == "H-EXEC-01"
    assert "RESEARCH_DEMO_ORDER" in (row["notes"] or "")
    assert row["broker_order_id"] and row["broker_position_id"]
    assert row["requested_price"] and row["executed_price"]
    assert row["spread_bps"] is not None and row["latency_ms"] is not None


def test_registered_policy_order_budget_is_enforced_by_the_gate(tmp_path: Path, authorized, monkeypatch):
    """The daily order budget is a gate check, not a loop convention.

    Exposure and interval limits are relaxed in the override so the budget is
    the ONLY thing that can refuse — otherwise a second order would be blocked
    by ``max_simultaneous_exposure_lots`` first and the test would prove the
    wrong thing.
    """
    _write_registry(
        tmp_path,
        _registry_doc(
            # The entry and the policy must agree on the order budget — the
            # registry refuses an entry whose own limit contradicts its policy.
            entry_overrides={"max_orders_per_day": 1},
            policy_overrides={
                "max_orders_per_day": 1,
                "min_order_interval_s": 0,
                "max_simultaneous_exposure_lots": 0.05,
                "position_sizing": {"mode": "fixed", "lots": 0.01},
            }
        ),
        monkeypatch,
    )
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    entry = resolve_entry(load_registry())[0]
    first = session.submit(
        side="BUY", lots=Decimal("0.01"), stop_loss=Decimal("1998.20"), rationale="budget test", entry=entry
    )
    assert first.allowed, first.reasons

    second = session.submit(
        side="BUY", lots=Decimal("0.01"), stop_loss=Decimal("1998.20"), rationale="over budget", entry=entry
    )
    assert second.allowed is False
    assert "order_frequency_within_policy" in (second.verdict or {}).get("failed", [])
    assert len(terminal.requests) == 1


def test_policy_outside_its_declared_hours_does_not_trade(tmp_path: Path, authorized, monkeypatch):
    _write_registry(tmp_path, _registry_doc(policy_overrides={"allowed_trading_hours": _outside_hours()}), monkeypatch)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="policy-test")
    )
    assert report.orders_submitted == 0
    assert terminal.requests == []
    # The loop stopped rather than retrying forever: the refusal names the reason.
    assert any("trading_hours" in str(e.get("detail")) for e in report.events)


def test_code_drift_halts_the_loop(tmp_path: Path, authorized, monkeypatch):
    """A provider whose source no longer matches ``code_hash`` must not trade."""
    _write_registry(
        tmp_path,
        _registry_doc(policy_overrides={"code_hash": hashlib.sha256(b"edited-after-registration").hexdigest()}),
        monkeypatch,
    )
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="policy-test")
    )
    assert report.orders_submitted == 0
    assert report.halted is True
    assert "code drift" in (report.halt_reason or "").lower()
    assert terminal.requests == []


def test_policy_exposure_cap_blocks_a_second_position(tmp_path: Path, authorized, monkeypatch):
    """One position at a time: ``max_simultaneous_exposure_lots`` is enforceable.

    With the shipped policy (0.01 lots cap, 900 s between orders) a second
    position can never be opened — the cap, not the schedule, is what stops it.
    """
    _write_registry(tmp_path, _registry_doc(), monkeypatch)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    entry = resolve_entry(load_registry())[0]
    first = session.submit(
        side="BUY", lots=Decimal("0.01"), stop_loss=Decimal("1998.20"), rationale="first", entry=entry
    )
    assert first.allowed, first.reasons

    second = session.submit(
        side="BUY", lots=Decimal("0.01"), stop_loss=Decimal("1998.20"), rationale="second", entry=entry
    )
    assert second.allowed is False
    failed = (second.verdict or {}).get("failed", [])
    assert "max_total_exposure" in failed
    assert len(terminal.requests) == 1


def test_an_entry_without_a_complete_policy_cannot_trade(tmp_path: Path, authorized, monkeypatch):
    """Registration without a specification is not a registered experiment."""
    doc = _registry_doc()
    doc["entries"][0].pop("policy")
    _write_registry(tmp_path, doc, monkeypatch)
    terminal = FakeTerminal()
    session = _armed_session(tmp_path, terminal)

    entry, reasons = resolve_entry(load_registry())
    assert entry is None
    assert any("policy" in r for r in reasons)

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="policy-test")
    )
    assert report.orders_submitted == 0
    assert report.halted is True
    assert "NO_TRADE" in (report.halt_reason or "")
    assert terminal.requests == []
