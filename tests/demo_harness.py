"""Shared harness for DEMO execution integration tests.

Provides one hermetic environment builder (``demo_env``) and one
``armed_session`` helper so the wiring, loop, CLI and failure-mode tests all
arm the system the same way: authorization → identity pin + owner confirmation
→ fresh readiness → durable authority → staged arming. Everything durable
(DB, audit log, kill-switch self test, identity pin) lands in ``tmp_path``.

This harness never weakens a gate: ``armed_session`` goes through the real
authority and stage machine, and fails the test if any gate refuses.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from qts.execution import demo_session as demo_session_module
from qts.lifecycle.demo_authorization import document_fingerprint
from qts.lifecycle.demo_stage import DemoStage

DEFAULT_AUTHORIZATION_ID = "DEMO-AUTH-INTEGRATION"


def authorization_doc(authorization_id: str = DEFAULT_AUTHORIZATION_ID) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": authorization_id,
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "integration test",
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


def write_authorization(path: Path, doc: dict[str, Any] | None = None) -> Path:
    path.write_text(json.dumps(doc or authorization_doc(), indent=2), encoding="utf-8")
    return path


def registry_doc(entry: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": "qts.demo_forward_registry.v1",
        "research_integrity": {
            "optimization_allowed": False,
            "no_forward_fitting": True,
            "hypothesis_preregistered": True,
        },
        "entries": [entry] if entry else [],
    }


def write_registry(path: Path, entry: dict[str, Any] | None = None) -> Path:
    path.write_text(json.dumps(registry_doc(entry), indent=2), encoding="utf-8")
    os.environ["QTS_DEMO_REGISTRY"] = str(path)
    return path


@pytest.fixture()
def demo_env(tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """Isolated operator environment — every durable side effect in tmp_path."""
    auth = write_authorization(tmp_path / "authorization.json")
    registry = tmp_path / "registry.json"
    write_registry(registry, None)
    setup = tmp_path / "setup.json"
    setup.write_text(
        json.dumps({"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}}), encoding="utf-8"
    )

    monkeypatch.setenv("QTS_MODE", "demo_execution")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(auth))
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    monkeypatch.setenv("QTS_SETUP_FILE", str(setup))
    monkeypatch.setattr(demo_session_module, "SELF_TEST_DB", tmp_path / "selftest.db")

    from qts.observability import audit as audit_module

    real_audit = audit_module.SqliteAuditLog
    monkeypatch.setattr(
        audit_module,
        "SqliteAuditLog",
        lambda *a, **k: real_audit(db_path=tmp_path / "audit.db", jsonl_path=tmp_path / "audit.jsonl"),
    )
    return {
        "tmp": tmp_path,
        "auth": auth,
        "registry": registry,
        "setup": setup,
        "db": str(tmp_path / "qts.db"),
    }


def armed_session(
    tmp_path: Path,
    terminal: Any,
    *,
    stage: DemoStage = DemoStage.STAGE_2_MIN_SIZE_ORDER,
    register_strategy: bool = True,
) -> Any:
    """Build a session wired to ``terminal`` and armed through the real gates."""
    from qts.execution.demo_identity import confirm_pin, write_pin
    from qts.execution.demo_session import DemoSession, DemoSessionConfig
    from qts.lifecycle.demo_authority import readiness_age_seconds
    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    if register_strategy:
        import fakes_demo_provider as provider_fixture

        write_registry(Path(tmp_path) / "registry.json", provider_fixture.registry_entry())

    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=Path(tmp_path) / "qts.db",
            actor="integration-test",
            mt5_module=terminal,
        )
    )
    write_pin(session.adapter.broker_identity(), actor="integration-test")
    assert confirm_pin(actor="owner")[0] is True

    report = session.connectivity_report()
    session.stage.advance(
        DemoStage.STAGE_1_CONNECTIVITY,
        actor="integration-test",
        reason="harness arming",
        prerequisites={
            "readiness_passed": bool(report["readiness"]["passed"]),
            "account_is_demo": report["identity"]["is_demo"] is True,
            "symbol_ok": bool(report["symbol_mapping"]["ok"]),
            "quote_fresh": bool(report["quote"]["fresh"]),
        },
    )
    readiness = demo_forward_readiness_report(
        mt5_module=terminal, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"}
    )
    decision = session.authority.enable(
        readiness=readiness,
        confirmed=True,
        risk_ack=True,
        readiness_age_s=readiness_age_seconds(readiness),
        actor="integration-test",
    )
    assert decision.execution_permitted is True, decision.reasons

    if stage in (DemoStage.STAGE_2_MIN_SIZE_ORDER, DemoStage.STAGE_3_FORWARD_OBSERVATION):
        session.stage.advance(
            DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="integration-test", reason="harness arming"
        )
    if stage is DemoStage.STAGE_3_FORWARD_OBSERVATION:
        session.stage.advance(
            DemoStage.STAGE_3_FORWARD_OBSERVATION, actor="integration-test", reason="harness arming"
        )
    session.reconcile()
    return session
