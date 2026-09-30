"""Failure-mode and concurrency tests for DEMO execution.

A trading system is judged by what it does when things break, not when they
work. Every test here injects a failure — an ambiguous broker retcode, a
definitive rejection, a disconnect, a stale in-flight order, a concurrent
caller, a kill switch raised by another process — and asserts the system
**fails closed**: no duplicate economic action, no fabricated fill, no trading
on an unknown state, and a durable record that says what happened.

The terminal is the stateful fake from ``tests/fakes_mt5_demo.py``; nothing
here contacts a broker.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import fakes_demo_provider as provider_fixture
from demo_harness import armed_session, write_registry
from fakes_mt5_demo import FakeTerminal

from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot
from qts.execution.demo_session import DemoSession, DemoSessionConfig

# --------------------------------------------------------------- broker faults


def test_ambiguous_retcode_suspends_and_sends_no_second_order(demo_env):
    """A broker timeout is an UNKNOWN state: refuse, record, never retry blindly."""

    terminal = FakeTerminal()
    terminal.order_send_retcode = 10012  # TRADE_RETCODE_TIMEOUT — ambiguous
    session = armed_session(demo_env["tmp"], terminal)

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="failure-mode test")
    assert result.allowed is False
    assert result.state in ("REJECTED", "NO_TRADE")

    row = session.journal.list_orders()[0]
    assert row["state"] == "REJECTED"
    assert "10012" in (row["broker_retcode"] or "") or "timeout" in (row["exit_reason"] or "").lower()

    # The engine suspended on the ambiguous state — the next attempt is refused
    # by the gate rather than silently re-sending the order.
    assert getattr(session.engine, "is_suspended", False) is True
    second = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert second.allowed is False
    assert len(terminal.requests) == 1, "an ambiguous result must never trigger a resend"


def test_definitive_rejection_is_recorded_and_not_retried(demo_env):
    terminal = FakeTerminal()
    terminal.order_send_retcode = 10006  # TRADE_RETCODE_REJECT — definitive
    session = armed_session(demo_env["tmp"], terminal)

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert result.allowed is False
    row = session.journal.list_orders()[0]
    assert row["state"] == "REJECTED"
    assert row["broker_retcode"] == "10006" or "rejected" in (row["exit_reason"] or "").lower()
    # One attempt, one record — no retry loop against a definitive refusal.
    assert len(terminal.requests) == 1
    assert terminal.positions == []


def test_broker_disconnect_during_the_loop_halts_it(demo_env):
    """If the broker disappears, the loop stops — it must not keep trading blind."""

    class FlakyTerminal(FakeTerminal):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = 0

        def positions_get(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 2:
                raise ConnectionError("terminal disconnected")
            return super().positions_get(*args, **kwargs)

    terminal = FlakyTerminal()
    session = armed_session(demo_env["tmp"], terminal, stage=stage3())

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=6, poll_interval_s=0, actor="test")
    )
    assert report.halted is True
    reason = (report.halt_reason or "").lower()
    assert "reconcil" in reason or "disconnect" in reason or "suspend" in reason


def stage3():
    from qts.lifecycle.demo_stage import DemoStage

    return DemoStage.STAGE_3_FORWARD_OBSERVATION


# ------------------------------------------------------------------ restart


def test_restart_with_a_broker_only_position_refuses_to_trade(demo_env):
    """After a crash the broker may hold a position we never journaled.

    That is an unknown state: reconciliation must say so and orders must stop,
    instead of opening a second position against the same exposure cap.
    """
    terminal = FakeTerminal(
        open_positions=[
            SimpleNamespace(
                ticket=555_001,
                symbol="XAUUSD@",
                volume=0.01,
                type=0,
                price_open=2000.20,
                price_current=2000.10,
                sl=1995.0,
                tp=2010.2,
                profit=-1.0,
                swap=0.0,
                comment="orphaned-by-crash",
                time=time.time() - 60,
                magic=20250916,
            )
        ]
    )
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    reconciliation = session.reconcile()

    assert reconciliation["requires_suspend"] is True
    assert reconciliation["drift"] in ("UNKNOWN_POSITION", "MISSING_POSITION")

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert result.allowed is False
    assert terminal.requests == [], "no order may be sent while broker state is unreconciled"


def test_stale_inflight_row_is_failed_not_blocking_forever(demo_env):
    """A row abandoned mid-submission (process died) must not wedge the system."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = armed_session(demo_env["tmp"], terminal)

    # Simulate a process that died between claiming the slot and the broker call.
    from qts.db import connect

    stuck = session.journal.open_order(
        client_order_id="demo-stale-1",
        strategy_id="TEST-PREREG-01",
        strategy_config_hash="x",
        symbol="XAUUSD",
        side="BUY",
        requested_lots=Decimal("0.01"),
        order_request={"symbol": "XAUUSD@"},
    )
    stale_at = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    with connect(demo_env["db"]) as con:
        con.execute(
            "UPDATE demo_order_journal SET requested_at=?, created_at=?, updated_at=? WHERE journal_id=?",
            (stale_at, stale_at, stale_at, stuck),
        )
        con.commit()

    # A fresh start (restart after the crash) fails the abandoned submission.
    DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=Path(demo_env["db"]),
            actor="restarted-process",
            mt5_module=terminal,
        )
    )
    rows = [r for r in session.journal.list_orders() if r["client_order_id"] == "demo-stale-1"]
    assert rows and rows[0]["state"] == "REJECTED"
    assert "abandoned" in (rows[0]["exit_reason"] or "")

    # And the session can still trade: the abandoned row no longer holds the slot.
    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="after recovery")
    assert result.allowed is True, result.reasons
    assert len(terminal.requests) == 1


# ---------------------------------------------------------------- concurrency


def test_two_concurrent_submissions_send_exactly_one_order(demo_env):
    """The classic check-then-act race — both callers pass the gate, one trades."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = armed_session(demo_env["tmp"], terminal)

    barrier = threading.Barrier(2)
    results: list = []

    def worker() -> None:
        barrier.wait()  # both threads reach the submission together
        results.append(session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="race"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert len(results) == 2
    allowed = [r for r in results if r.allowed]
    refused = [r for r in results if not r.allowed]
    assert len(allowed) == 1, "exactly one order may reach the broker"
    assert len(refused) == 1
    assert any("in flight" in r or "duplicate" in r for r in refused[0].reasons)
    assert len(terminal.requests) == 1
    assert len(session.journal.list_orders()) == 1


def test_a_second_order_inside_the_minimum_interval_is_refused(demo_env):
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = armed_session(demo_env["tmp"], terminal)

    first = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert first.allowed is True
    second = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert second.allowed is False
    assert any("duplicate" in r or "interval" in r for r in second.reasons)
    assert len(terminal.requests) == 1


# -------------------------------------------------------------- kill switch


def test_a_kill_switch_raised_by_another_process_is_honoured(demo_env):
    """Durable means durable: a fresh process with no in-memory state obeys it."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    first = armed_session(demo_env["tmp"], terminal)
    killed = first.raise_kill_switch("raised by another process")
    assert killed["killed"] is True

    # A brand-new session: nothing in memory, only the durable state.
    other = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=Path(demo_env["db"]),
            actor="other-process",
            mt5_module=terminal,
        )
    )
    result = other.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert result.allowed is False
    assert result.verdict["checks"]["kill_switch_functional"]["status"] == "FAIL"
    assert terminal.requests == []


def test_kill_switch_survives_a_stage_that_would_otherwise_allow_orders(demo_env):
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = armed_session(demo_env["tmp"], terminal, stage=stage3())
    session.raise_kill_switch("halt for maintenance")

    report = run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=2, poll_interval_s=0, actor="test")
    )
    assert report.halted is True
    assert report.orders_submitted == 0


def test_a_claim_against_a_locked_database_refuses_instead_of_guessing(demo_env):
    """Another process holds the write lock → unknown state → refuse, do not insert."""
    from qts.db import connect, immediate
    from qts.execution.demo_journal import DemoOrderJournal

    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    armed_session(demo_env["tmp"], terminal)
    journal = DemoOrderJournal(db_path=demo_env["db"])

    claim_kwargs = {
        "client_order_id": "demo-locked-1",
        "strategy_id": "TEST-PREREG-01",
        "strategy_config_hash": "x",
        "symbol": "XAUUSD",
        "side": "BUY",
        "order_request": {"symbol": "XAUUSD@"},
        "requested_lots": Decimal("0.01"),
    }

    # Simulate another process (or a crashed one) holding the write lock.
    with immediate(demo_env["db"]) as con:
        con.execute("INSERT INTO demo_order_journal (label, client_order_id, state, created_at, updated_at)"
                    " VALUES ('RESEARCH_DEMO_ORDER','demo-other','NEW',?,?)", (_now_iso(), _now_iso()))
        journal_id, reason = journal.claim_order_slot(**claim_kwargs, timeout_s=0.2)
        assert journal_id is None
        assert "could not be claimed atomically" in reason

    # Release the other process's in-flight row, then claim honestly.
    with connect(demo_env["db"]) as con:
        con.execute(
            "UPDATE demo_order_journal SET state='REJECTED', exit_reason='test cleanup' WHERE client_order_id='demo-other'"
        )
        con.commit()

    # Once the lock is released the slot can be claimed honestly.
    journal_id, reason = journal.claim_order_slot(**claim_kwargs, timeout_s=1.0)
    assert journal_id is not None, reason


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def test_cold_start_rebuilds_local_state_from_broker_deals(demo_env):
    """A fresh process starts with an empty portfolio — that is not drift.

    Without this, restarting after a fill makes the broker's legitimate
    position look like ``UNKNOWN_POSITION``, which suspends trading and blocks
    the operator until a manual reconcile.
    """
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    session = armed_session(demo_env["tmp"], terminal)

    first = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="before restart")
    assert first.allowed is True, first.reasons
    assert len(terminal.positions) == 1

    # A brand-new process: same database and terminal, empty in-memory state.
    restarted = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=Path(demo_env["db"]),
            actor="restarted-process",
            mt5_module=terminal,
        )
    )
    assert restarted.engine.portfolio.positions == {}, "a cold process must start empty"

    reconciliation = restarted.reconcile()
    assert reconciliation["requires_suspend"] is False, reconciliation
    assert reconciliation["drift"] == "NONE"
    assert len(restarted.engine.portfolio.positions) == 1, "state is rebuilt from broker deals"


def test_a_process_in_any_other_mode_cannot_use_the_demo_order_path(demo_env, monkeypatch):
    """The DEMO path exists only in DEMO_EXECUTION — and never in LIVE.

    A ``DemoSession`` object must not be enough: its mode is resolved from the
    process, so if the mode changes (or was never set) everything is refused
    with a legible reason even though the session is fully armed. This is the
    end-to-end version of ``LIVE = LOCKED``: with authorization, pin, stage and
    registry all in place, the mode alone decides.
    """
    monkeypatch.setenv("QTS_MODE", "demo_execution")
    terminal = FakeTerminal()
    session = armed_session(demo_env["tmp"], terminal)
    assert session.authority.current().execution_permitted is True

    for mode in ("DEVELOPMENT", "PAPER", "SHADOW", "DEMO_FORWARD", "LIVE"):
        monkeypatch.setenv("QTS_MODE", mode)
        assert str(session.mode) == mode
        assert session.policy.enabled is False, f"{mode}: the DEMO policy must be disabled"
        # The authority is re-resolved for the current mode, so a permission
        # granted under DEMO_EXECUTION does not survive the change.
        assert session.authority.current().execution_permitted is False

        result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="mode test")
        assert result.allowed is False, f"{mode}: submission must be refused"
        assert "mode_is_demo_execution" in (result.verdict or {}).get("failed", [])
        assert terminal.requests == [], f"{mode}: no broker request may be sent"

        # The autopilot stops rather than looping on a refusal it cannot fix.
        report = run_autopilot(
            session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="test")
        )
        assert report.orders_submitted == 0
        assert terminal.requests == []


def test_demo_session_reports_the_mode_it_is_actually_running_in(demo_env, monkeypatch):
    """An explicitly requested mode is honoured — including a refused one.

    Constructing a DEMO session with ``mode="LIVE"`` must not quietly fall back
    to the DEMO path: the session reports LIVE, the policy is disabled and no
    arming or submission can succeed.
    """
    monkeypatch.setenv("QTS_MODE", "demo_execution")  # the process would allow DEMO
    terminal = FakeTerminal()
    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=demo_env["tmp"] / "qts.db",
            actor="test",
            mt5_module=terminal,
            mode="LIVE",  # an explicit request overrides the environment
        )
    )
    assert str(session.mode) == "LIVE"
    assert session.policy.enabled is False  # LIVE = LOCKED, no artifact can permit it

    decision = session.authority.enable(readiness={}, confirmed=True, risk_ack=True)
    assert decision.execution_permitted is False
    assert any("LIVE" in r for r in decision.reasons)

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"))
    assert result.allowed is False
    assert "mode_is_demo_execution" in (result.verdict or {}).get("failed", [])
    assert terminal.requests == []
