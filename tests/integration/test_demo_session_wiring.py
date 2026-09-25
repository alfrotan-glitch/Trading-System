"""Integration wiring test for the DEMO execution session (fake terminal).

No broker is contacted and no order is sent. A deterministic fake
``MetaTrader5`` module stands in for the Windows terminal so the whole wiring
can be exercised in CI: authorization → identity → symbol → quote → order-check
→ full pre-trade gate (every required safeguard, contract check and registered-policy limit) → refusal.

The point of this file is the *shape of the refusal*: with a healthy DEMO
terminal and a valid authorization, every market/identity/control safeguard
passes and the only remaining blocker is research integrity — **no strategy is
registered, so the system returns NO_TRADE**. That is exactly the contract
documented in
``docs/demo_execution_authorization_and_safety_2026-09-23.md``.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from qts.db import connect
from qts.execution.demo_session import DemoSession, DemoSessionConfig
from qts.lifecycle.demo_authorization import document_fingerprint
from qts.lifecycle.demo_stage import DemoStage

# ------------------------------------------------------------------ fake MT5


def _fake_mt5(*, trade_mode: int = 0, symbol: str = "XAUUSD@", tick_age_s: float = 1.0, spread: float = 0.20):
    """A minimal but honest-shaped MetaTrader5 stand-in."""
    account = SimpleNamespace(
        login=123456,
        server="Broker-Demo",
        company="Example Brokers Ltd",
        name="Research Demo",
        trade_mode=trade_mode,
        trade_allowed=True,
        trade_expert=True,
        currency="USD",
        leverage=100,
        balance=10_000.0,
        equity=10_000.0,
        margin=0.0,
        margin_free=10_000.0,
    )
    symbol_info = SimpleNamespace(
        trade_contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        digits=2,
        point=0.01,
        tick_size=0.01,
        trade_mode=4,
        filling_mode=1,
        execution_mode=2,
        stops_level=0,
        freeze_level=0,
    )
    now_s = time.time() - tick_age_s

    def _tick():
        bid = 2000.00
        ask = round(bid + spread, 2)
        return SimpleNamespace(
            time=int(now_s),
            time_msc=int(now_s * 1000),
            bid=bid,
            ask=ask,
            last=bid,
            volume=1,
            flags=6,
            volume_real=1.0,
        )

    def _order_check(request):
        return SimpleNamespace(retcode=0, comment="Done", balance=10_000.0, equity=10_000.0, margin=17.0)

    def _order_send(request):
        raise AssertionError("no order may be sent from this test")

    return SimpleNamespace(
        initialize=lambda **kwargs: True,
        shutdown=lambda: None,
        last_error=lambda: (1, "No error"),
        terminal_info=lambda: SimpleNamespace(connected=True, company="Example Brokers Ltd", build=4000),
        account_info=lambda: account,
        symbol_info=lambda name: symbol_info if name == symbol else None,
        symbol_select=lambda name, enable: name == symbol,
        symbol_info_tick=lambda name: _tick() if name == symbol else None,
        copy_rates_from_pos=lambda name, tf, start, count: None,
        order_check=_order_check,
        order_send=_order_send,
        positions_get=lambda **kwargs: (),
        orders_get=lambda **kwargs: (),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        TRADE_ACTION_DEAL=1,
        TRADE_ACTION_PENDING=5,
        TRADE_ACTION_REMOVE=6,
        ORDER_FILLING_FOK=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_RETURN=2,
        ORDER_TIME_GTC=0,
        TIMEFRAME_M1=1,
    )


@pytest.fixture()
def authorization(tmp_path: Path, monkeypatch):
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
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(path))
    # The DEMO session resolves its mode from the process: the DEMO order path
    # exists only in DEMO_EXECUTION, never by virtue of a DEMO session object.
    monkeypatch.setenv("QTS_MODE", "demo_execution")

    # Registry: explicitly empty — no strategy has passed the research gates.
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
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry))
    return path


def _session(tmp_path: Path, **mt5_kwargs) -> DemoSession:
    return DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=tmp_path / "qts.db",
            actor="integration-test",
            mt5_module=_fake_mt5(**mt5_kwargs),
        )
    )


# ---------------------------------------------------------------------- tests


def test_stage_1_connectivity_passes_on_a_healthy_demo_terminal(tmp_path: Path, authorization):
    session = _session(tmp_path)
    report = session.connectivity_report()

    assert report["identity"]["is_demo"] is True
    assert report["identity"]["login"] == 123456
    assert report["identity"]["server"] == "Broker-Demo"
    assert report["symbol_mapping"]["canonical"] == "XAUUSD"
    assert report["symbol_mapping"]["broker_symbol"] == "XAUUSD@"
    assert report["symbol_mapping"]["tradable"] is True
    assert report["quote"]["fresh"] is True
    assert report["quote"]["spread_bps"] == pytest.approx(1.0, abs=0.05)
    assert report["order_check"]["ok"] is True
    assert report["policy"]["policy"] == "ENABLED_AUTHORIZED"
    assert report["ready_for_stage_1"] is True


def test_connectivity_refuses_a_real_account(tmp_path: Path, authorization):
    session = _session(tmp_path, trade_mode=2)
    report = session.connectivity_report()
    assert report["identity"]["is_demo"] is False
    assert report["identity"]["account_type"] == "REAL"
    assert report["ready_for_stage_1"] is False


def test_preflight_passes_market_controls_and_blocks_on_no_registered_strategy(tmp_path: Path, authorization):
    """The wiring works; research integrity is the only remaining blocker."""
    session = _session(tmp_path)
    session.stage.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test", reason="wiring test")
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test", reason="wiring test")

    out = session.preflight(side="BUY", stop_loss=Decimal("1995.00"))
    checks = out["verdict"]["checks"]

    # Market, identity, symbol, kill switch, recording: all resolved.
    for name in (
        "account_is_demo",
        "broker_identity_verified",
        "symbol_mapping_canonical",
        "market_data_fresh",
        "spread_available",
        "order_size_within_hard_max",
        "stop_loss_present",
        "kill_switch_functional",
        "execution_record_fields",
        "risk_limits_resolved",
    ):
        assert name in checks, name
        assert checks[name]["status"] in ("PASS", "FAIL"), (name, checks[name])

    # The order is still refused — and the reason is the missing strategy.
    assert out["verdict"]["passed"] is False
    assert "strategy_registered_frozen" in out["verdict"]["failed"]
    assert "NO_TRADE" in checks["strategy_registered_frozen"]["detail"]


def test_submit_refuses_and_records_a_no_trade_signal(tmp_path: Path, authorization):
    session = _session(tmp_path)
    session.stage.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test")
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test")

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="wiring test")
    assert result.allowed is False
    assert result.state == "NO_TRADE"

    with connect(session.db_path) as con:
        rows = con.execute("SELECT decision, reason FROM demo_signal_journal").fetchall()
    assert rows and rows[0][0] == "NO_TRADE"
    assert "registry" in (rows[0][1] or "").lower() or "strategy" in (rows[0][1] or "").lower()
    # No broker order was created.
    assert session.journal.list_orders() == []


def test_submit_is_refused_outside_order_stages_even_with_a_healthy_terminal(tmp_path: Path, authorization):
    session = _session(tmp_path)
    assert session.stage.current().stage == DemoStage.DISABLED.value
    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert result.allowed is False
    assert result.verdict["checks"]["stage_allows_order"]["status"] == "FAIL"


def test_autopilot_halts_immediately_when_no_strategy_is_registered(tmp_path: Path, authorization):
    from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot

    session = _session(tmp_path)
    session.stage.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test")
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test")
    report = run_autopilot(session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, actor="test"))
    assert report.halted is True
    assert "NO_TRADE" in (report.halt_reason or "")
    assert report.orders_submitted == 0


def test_autopilot_halts_on_an_active_kill_switch(tmp_path: Path, authorization):
    from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot

    session = _session(tmp_path)
    session.stage.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test")
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test")
    out = session.raise_kill_switch("integration test halt")
    assert out["killed"] is True
    report = run_autopilot(session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, actor="test"))
    assert report.halted is True
    # A raised kill switch halts the stage machine, so the loop stops on the
    # stage check — the durable flag is the authoritative fact either way.
    assert session.kill_switch_state()["killed"] is True
    assert session.stage.current().stage == DemoStage.HALTED.value
    assert report.orders_submitted == 0


def test_kill_switch_halts_the_stage_machine(tmp_path: Path, authorization):
    session = _session(tmp_path)
    session.stage.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test")
    out = session.raise_kill_switch("integration halt")
    assert out["killed"] is True
    assert session.stage.current().stage == DemoStage.HALTED.value


def test_after_arming_the_only_remaining_blocker_is_the_missing_strategy(tmp_path: Path, authorization, monkeypatch):
    """End-to-end proof that the binding constraint is research, not plumbing.

    With a healthy DEMO terminal, a valid authorization, a confirmed identity
    pin, a clean reconciliation, the durable authority enabled and the stage
    armed, every operational safeguard passes — and the order is still refused
    for exactly one reason: no strategy has passed the research gates.
    """
    from decimal import Decimal

    from qts.execution.demo_identity import confirm_pin, write_pin
    from qts.lifecycle.demo_authority import readiness_age_seconds
    from qts.lifecycle.demo_gate import demo_forward_readiness_report
    from qts.lifecycle.demo_stage import DemoStage

    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    session = _session(tmp_path)

    # Owner pins and confirms the observed DEMO identity.
    write_pin(session.adapter.broker_identity(), actor="test")
    assert confirm_pin(actor="owner")[0] is True

    # Stage 1 with its real prerequisites.
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

    # Fresh readiness → durable authority enablement.
    rpt = demo_forward_readiness_report(
        mt5_module=session.config.mt5_module, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"}
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
    session.reconcile()

    out = session.preflight(side="BUY", stop_loss=Decimal("1995.00"))
    verdict = out["verdict"]
    assert verdict["unknown"] == []
    assert verdict["failed"] == ["strategy_registered_frozen"]
    assert "NO_TRADE" in verdict["checks"]["strategy_registered_frozen"]["detail"]
