"""DEMO staged progression: DISABLED → 1 → 2 → 3, HALTED from anywhere."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from qts.execution.demo_journal import DemoOrderJournal, summarize
from qts.lifecycle.demo_stage import (
    ORDER_STAGES,
    DemoStage,
    DemoStageMachine,
    StageTransitionError,
)


@pytest.fixture()
def machine(tmp_path: Path) -> DemoStageMachine:
    return DemoStageMachine(db_path=tmp_path / "qts.db")


def test_starts_disabled_and_orders_are_not_permitted(machine: DemoStageMachine):
    current = machine.current()
    assert current.stage == DemoStage.DISABLED.value
    assert current.stage not in ORDER_STAGES


def test_legal_progression(machine: DemoStageMachine):
    machine.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test", reason="connectivity ok")
    assert machine.current().stage == DemoStage.STAGE_1_CONNECTIVITY.value
    machine.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test", reason="all gates pass")
    assert machine.current().stage in ORDER_STAGES
    machine.advance(DemoStage.STAGE_3_FORWARD_OBSERVATION, actor="test", reason="first order reconciled")
    assert machine.current().stage in ORDER_STAGES


def test_skipping_stage_1_is_refused(machine: DemoStageMachine):
    with pytest.raises(StageTransitionError):
        machine.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test")
    assert machine.current().stage == DemoStage.DISABLED.value


def test_unmet_prerequisites_refuse_and_record(machine: DemoStageMachine):
    with pytest.raises(StageTransitionError):
        machine.advance(
            DemoStage.STAGE_1_CONNECTIVITY,
            actor="test",
            prerequisites={"readiness_passed": True, "account_is_demo": False},
        )
    assert machine.current().stage == DemoStage.DISABLED.value
    # The refusal is durable evidence, not a silent no-op.
    refused = [r for r in machine.history() if not r.allowed]
    assert refused
    assert refused[0].prerequisites["account_is_demo"] is False


def test_unknown_stage_refuses(machine: DemoStageMachine):
    with pytest.raises(StageTransitionError):
        machine.advance("STAGE_9_TELEPORTATION", actor="test")


def test_halt_is_reachable_from_any_stage(machine: DemoStageMachine):
    machine.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test")
    machine.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test")
    record = machine.halt(reason="kill switch", actor="system")
    assert record.stage == DemoStage.HALTED.value
    assert machine.current().stage not in ORDER_STAGES


def test_halt_requires_explicit_rearm(machine: DemoStageMachine):
    machine.halt(reason="test")
    with pytest.raises(StageTransitionError):
        machine.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="test")
    machine.reset_to_disabled(reason="operator acknowledged halt", actor="owner")
    assert machine.current().stage == DemoStage.DISABLED.value


def test_history_is_durable(machine: DemoStageMachine):
    machine.advance(DemoStage.STAGE_1_CONNECTIVITY, actor="a")
    machine.halt(reason="b")
    stages = [r.stage for r in machine.history()]
    assert stages[0] == DemoStage.HALTED.value
    assert DemoStage.STAGE_1_CONNECTIVITY.value in stages


def test_order_stages_are_exactly_two_and_three():
    assert {
        DemoStage.STAGE_2_MIN_SIZE_ORDER.value,
        DemoStage.STAGE_3_FORWARD_OBSERVATION.value,
    } == ORDER_STAGES


# --------------------------------------------------------------------- journal


def test_journal_records_the_full_order_lifecycle(tmp_path: Path):
    journal = DemoOrderJournal(db_path=tmp_path / "qts.db")
    jid = journal.open_order(
        client_order_id="demo-1",
        strategy_id="S1",
        strategy_config_hash="abc123",
        symbol="XAUUSD",
        broker_symbol="XAUUSD@",
        side="BUY",
        requested_lots="0.01",
        requested_price="2000.20",
        stop_loss="1995.00",
        order_request={"symbol": "XAUUSD@", "volume": 0.01},
        market_state_entry={"bid": "2000.00", "ask": "2000.20"},
        authorization_id="DEMO-AUTH-TEST",
    )
    row = journal.get(jid)
    assert row["label"] == "RESEARCH_DEMO_ORDER"

    journal.mark_submitted(jid, broker_order_id="991", broker_position_id="771", broker_retcode="10009")
    journal.mark_fill(
        jid,
        filled_lots="0.01",
        executed_price="2000.25",
        requested_price="2000.20",
        spread_bps=1.0,
    )
    journal.mark_outcome(jid, state="CLOSED", exit_reason="stop", realized_pnl="-1.20")
    journal.mark_reconciled(jid, ok=True, note="no drift")

    row = journal.get(jid)
    assert row["broker_order_id"] == "991"
    assert row["broker_position_id"] == "771"
    assert row["executed_price"] == "2000.25"
    # Slippage is measured against the requested price, in bps.
    expected_bps = float((Decimal("2000.25") - Decimal("2000.20")) / Decimal("2000.20") * Decimal("10000"))
    assert float(row["slippage_bps"]) == pytest.approx(expected_bps, abs=1e-6)
    assert row["spread_bps"] == 1.0
    assert row["realized_pnl"] == "-1.20"
    assert row["exit_reason"] == "stop"
    assert row["reconciled"] == 1
    assert row["latency_ms"] is not None


def test_journal_records_no_trade_signals(tmp_path: Path):
    journal = DemoOrderJournal(db_path=tmp_path / "qts.db")
    journal.record_signal(
        strategy_id="S1",
        strategy_config_hash="abc",
        symbol="XAUUSD",
        decision="NO_TRADE",
        reason="spread too wide",
    )
    journal.record_signal(
        strategy_id="S1", strategy_config_hash="abc", symbol="XAUUSD", decision="SIGNAL", side="BUY"
    )
    with __import__("qts.db", fromlist=["connect"]).connect(journal.db_path) as con:
        rows = con.execute("SELECT decision FROM demo_signal_journal").fetchall()
    assert {r[0] for r in rows} == {"NO_TRADE", "SIGNAL"}


def test_daily_realized_pnl_and_order_counts(tmp_path: Path):
    journal = DemoOrderJournal(db_path=tmp_path / "qts.db")
    jid = journal.open_order(
        client_order_id="demo-2",
        strategy_id="S1",
        strategy_config_hash="abc",
        symbol="XAUUSD",
        side="BUY",
        requested_lots="0.01",
        order_request={},
    )
    journal.mark_outcome(jid, state="CLOSED", realized_pnl="-5")
    assert journal.daily_realized_pnl() == -5
    assert journal.orders_today() == 1


def test_summarize_reports_unreconciled_orders(tmp_path: Path):
    journal = DemoOrderJournal(db_path=tmp_path / "qts.db")
    journal.open_order(
        client_order_id="demo-3",
        strategy_id="S1",
        strategy_config_hash="abc",
        symbol="XAUUSD",
        side="BUY",
        requested_lots="0.01",
        order_request={},
    )
    summary = summarize(journal)
    assert summary.orders == 1
    assert summary.unreconciled == 1


def test_record_fields_capability_report_is_complete():
    fields = DemoOrderJournal.record_fields_available()
    assert fields and all(fields.values())


def test_export_writes_one_line_per_order(tmp_path: Path):
    journal = DemoOrderJournal(db_path=tmp_path / "qts.db")
    journal.open_order(
        client_order_id="demo-4",
        strategy_id="S1",
        strategy_config_hash="abc",
        symbol="XAUUSD",
        side="BUY",
        requested_lots="0.01",
        order_request={},
    )
    out = journal.export_jsonl(tmp_path / "journal.jsonl")
    lines = [line for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert "RESEARCH_DEMO_ORDER" in lines[0]
