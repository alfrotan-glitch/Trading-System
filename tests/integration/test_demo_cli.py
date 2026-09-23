"""Operator CLI integration test for the DEMO execution flow.

This exercises the exact sequence documented in
``docs/demo_execution_authorization_and_safety_2026-09-23.md`` §15, through the
CLI an operator would actually type:

    connectivity (--pin, --confirm-pin) → arm 1 → arm 2 → order → journal
    → kill, and separately revoke

The terminal is the stateful fake from ``tests/fakes_mt5_demo.py`` injected as
``sys.modules["MetaTrader5"]``, so the *real* 14-check readiness gate, the real
authority, the real stage machine and the real pre-trade gate all run. No
broker is contacted; every durable side effect lands in ``tmp_path``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qts.execution import demo_session as demo_session_module
from qts.lifecycle.demo_authorization import document_fingerprint


@pytest.fixture()
def operator_env(tmp_path: Path, monkeypatch):
    """A complete, isolated operator environment for the DEMO CLI."""
    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": "DEMO-AUTH-CLI-TEST",
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "cli integration test",
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
    auth_path = tmp_path / "authorization.json"
    auth_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "qts.demo_forward_registry.v1",
                "research_integrity": {"optimization_allowed": False, "no_forward_fitting": True},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    setup_path = tmp_path / "setup.json"
    setup_path.write_text(
        json.dumps({"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("QTS_MODE", "demo_execution")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(auth_path))
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry_path))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    monkeypatch.setenv("QTS_SETUP_FILE", str(setup_path))
    monkeypatch.setattr(demo_session_module, "SELF_TEST_DB", tmp_path / "selftest.db")

    from qts.observability import audit as audit_module

    real_audit = audit_module.SqliteAuditLog
    monkeypatch.setattr(
        audit_module,
        "SqliteAuditLog",
        lambda *a, **k: real_audit(db_path=tmp_path / "audit.db", jsonl_path=tmp_path / "audit.jsonl"),
    )

    from fakes_mt5_demo import FakeTerminal

    terminal = FakeTerminal()
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", terminal)

    return {
        "tmp": tmp_path,
        "terminal": terminal,
        "db": str(tmp_path / "qts.db"),
        "auth": auth_path,
        "registry": registry_path,
    }


@pytest.fixture()
def run_cli(operator_env):
    from click.testing import CliRunner

    from qts.cli import main

    runner = CliRunner()

    def _run(*args: str):
        return runner.invoke(main, ["demo", *args], catch_exceptions=False)

    return _run


def _register_strategy(registry_path: Path) -> None:
    import fakes_demo_provider as provider_fixture

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


# ------------------------------------------------------------------ Stage 1


def test_connectivity_reports_a_ready_demo_terminal(run_cli, operator_env):
    result = run_cli("connectivity", "--db", operator_env["db"])
    assert result.exit_code == 0, result.output
    assert "readiness passed: True" in result.output
    assert "account: demo=True login=123456 server=Broker-Demo" in result.output
    assert "symbol: XAUUSD -> XAUUSD@ visible=True tradable=True" in result.output
    assert "spread_bps=" in result.output
    assert "STAGE_1_READY: True" in result.output
    # Stage 1 proves the order-check endpoint works and sends nothing.
    assert "'ok': True" in result.output
    assert operator_env["terminal"].requests == []


def test_connectivity_can_write_a_json_report(run_cli, operator_env):
    out = operator_env["tmp"] / "connectivity.json"
    result = run_cli("connectivity", "--db", operator_env["db"], "--json-out", str(out))
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["identity"]["is_demo"] is True
    assert report["symbol_mapping"]["broker_symbol"] == "XAUUSD@"
    assert report["quote"]["fresh"] is True
    assert report["ready_for_stage_1"] is True


# ----------------------------------------------------------- arming and orders


def test_full_operator_flow_arms_and_submits_one_labelled_order(run_cli, operator_env):
    # Stage 1 — pin and confirm the observed DEMO identity.
    pinned = run_cli("connectivity", "--db", operator_env["db"], "--pin")
    assert pinned.exit_code == 0, pinned.output
    assert "identity pin written (PENDING_REVIEW)" in pinned.output

    confirmed = run_cli("connectivity", "--db", operator_env["db"], "--confirm-pin")
    assert confirmed.exit_code == 0, confirmed.output
    assert "pin confirmation: broker identity pin confirmed" in confirmed.output

    # Stage 1 → 2 (each stage re-proves its prerequisites).
    arm1 = run_cli("arm", "--stage", "1", "--db", operator_env["db"], "--confirm", "--risk-ack")
    assert arm1.exit_code == 0, arm1.output
    assert "STAGE_1_CONNECTIVITY" in arm1.output

    arm2 = run_cli("arm", "--stage", "2", "--db", operator_env["db"], "--confirm", "--risk-ack")
    assert arm2.exit_code == 0, arm2.output
    assert "authority: ENABLED permitted=True" in arm2.output
    assert "STAGE_2_MIN_SIZE_ORDER" in arm2.output

    # One order, minimum size, with its stop — only after a strategy is registered.
    no_strategy = run_cli("order", "--side", "BUY", "--stop-loss", "1995.00", "--db", operator_env["db"])
    assert no_strategy.exit_code == 2
    assert "NO_TRADE" in no_strategy.output

    _register_strategy(operator_env["registry"])
    ordered = run_cli(
        "order", "--side", "BUY", "--stop-loss", "1995.00", "--db", operator_env["db"],
        "--rationale", "cli integration test",
    )
    assert ordered.exit_code == 0, ordered.output
    body = json.loads(ordered.output)
    assert body["allowed"] is True
    assert body["broker_order_id"]
    assert len(operator_env["terminal"].requests) == 1

    journal = run_cli("journal", "--db", operator_env["db"])
    assert journal.exit_code == 0, journal.output
    assert "RESEARCH_DEMO_ORDER" in journal.output
    assert "state=FILLED" in journal.output or "state=ACCEPTED" in journal.output


def test_preflight_submits_nothing(run_cli, operator_env):
    _register_strategy(operator_env["registry"])
    result = run_cli("preflight", "--side", "BUY", "--stop-loss", "1995.00", "--db", operator_env["db"])
    assert result.exit_code == 0, result.output
    assert operator_env["terminal"].requests == []


def test_arm_stage_2_refuses_without_explicit_confirmation(run_cli, operator_env):
    run_cli("connectivity", "--db", operator_env["db"], "--pin")
    run_cli("connectivity", "--db", operator_env["db"], "--confirm-pin")
    run_cli("arm", "--stage", "1", "--db", operator_env["db"], "--confirm", "--risk-ack")

    result = run_cli("arm", "--stage", "2", "--db", operator_env["db"])
    assert result.exit_code == 2
    assert "REFUSED" in result.output
    assert '"operator_confirmation": false' in result.output


def test_autonomous_run_halts_when_no_strategy_is_registered(run_cli, operator_env):
    # Arm through the real gates first, so the halt is the research gate and
    # not merely "the stage machine was never started".
    run_cli("connectivity", "--db", operator_env["db"], "--pin")
    run_cli("connectivity", "--db", operator_env["db"], "--confirm-pin")
    run_cli("arm", "--stage", "1", "--db", operator_env["db"], "--confirm", "--risk-ack")
    run_cli("arm", "--stage", "2", "--db", operator_env["db"], "--confirm", "--risk-ack")

    result = run_cli("run", "--dry-run", "--max-iterations", "1", "--db", operator_env["db"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output.split("\nHALTED:")[0])
    assert report["halted"] is True
    assert "NO_TRADE" in (report["halt_reason"] or "")
    assert report["orders_submitted"] == 0
    assert operator_env["terminal"].requests == []


# ------------------------------------------------------------------- journal


def test_journal_export_writes_the_forward_trail(run_cli, operator_env):
    _register_strategy(operator_env["registry"])
    run_cli("connectivity", "--db", operator_env["db"], "--pin")
    run_cli("connectivity", "--db", operator_env["db"], "--confirm-pin")
    run_cli("arm", "--stage", "1", "--db", operator_env["db"], "--confirm", "--risk-ack")
    run_cli("arm", "--stage", "2", "--db", operator_env["db"], "--confirm", "--risk-ack")
    run_cli("order", "--side", "BUY", "--stop-loss", "1995.00", "--db", operator_env["db"])

    export = operator_env["tmp"] / "journal.jsonl"
    result = run_cli("journal", "--db", operator_env["db"], "--export", str(export))
    assert result.exit_code == 0, result.output
    lines = [line for line in export.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["label"] == "RESEARCH_DEMO_ORDER"
    assert row["broker_order_id"]
    assert row["strategy_config_hash"]


# --------------------------------------------------------- kill switch, revoke


def test_kill_switch_halts_the_stage_machine(run_cli, operator_env):
    run_cli("arm", "--stage", "1", "--db", operator_env["db"], "--confirm", "--risk-ack")
    killed = run_cli("kill", "--db", operator_env["db"], "--reason", "cli integration test")
    assert killed.exit_code == 0, killed.output
    assert '"killed": true' in killed.output

    after = run_cli("arm", "--stage", "2", "--db", operator_env["db"], "--confirm", "--risk-ack")
    assert after.exit_code == 2
    assert "REFUSED" in after.output


def test_revoke_disables_execution_and_never_edits_the_artifact(run_cli, operator_env):
    before_bytes = operator_env["auth"].read_bytes()

    result = run_cli("revoke", "--reason", "cli integration test", "--actor", "owner")
    assert result.exit_code == 0, result.output
    assert "revocation written" in result.output
    assert "DISABLED BY POLICY again" in result.output

    # Additive: the artifact is untouched, a sidecar records the revocation.
    assert operator_env["auth"].read_bytes() == before_bytes
    sidecar = operator_env["auth"].with_name(operator_env["auth"].name + ".revocation.json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["reason"] == "cli integration test"

    # Execution is disabled again — the policy, not just a flag.
    status = run_cli("status", "--db", operator_env["db"])
    assert "DISABLED BY POLICY" in status.output

    _register_strategy(operator_env["registry"])
    ordered = run_cli("order", "--side", "BUY", "--stop-loss", "1995.00", "--db", operator_env["db"])
    assert ordered.exit_code == 2
    assert operator_env["terminal"].requests == []
