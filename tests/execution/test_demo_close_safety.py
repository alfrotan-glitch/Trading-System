"""Close-lifecycle safety tests: broker truth and local journal uncertainty fail closed.

Harness contract
----------------
``close_position`` runs against the product's real components because that is
what production requires: before the correlated close deal is consumed the close
path records the *already sent* broker close as a local order
(``engine.om.submit`` / ``update_state``) and restores the persisted journal
position (``engine.portfolio.restore_position``). It also persists the outcome
into the real order journal. An attribute-only stub satisfies the lookups while
silently skipping all of that, so these tests would pass without the product's
local close record ever running.

* engine — built exactly the way ``DemoSession.engine`` builds it, in a
  per-test database (only ``audit`` is None so a unit test cannot write to the
  operator's audit store);
* journal — the real :class:`DemoOrderJournal`, with a real open row produced
  through its own API (``open_order`` → ``mark_submitted`` → ``mark_fill``);
* adapter — a venue double, since the subject here is how the close path reacts
  to what the venue reports.

Two seams are deliberate, and both are *pinned by tests* rather than assumed:

* ``sync_fills`` — the harness adapter is not a live MT5 terminal, so there is
  no broker deal history to poll. Correlation and attribution of real deals are
  covered by ``tests/test_poll_fill_attribution.py``.
* ``reconcile`` — local book vs venue agreement cannot be manufactured without
  that same broker fill stream, so what is asserted here is the close path's
  *use* of the reconciliation barrier: ``_ReconcileSeam`` counts calls and
  ``test_reconciliation_drift_after_close_blocks_success_and_halts`` proves a
  drift report stops the close from being reported as a success. Full
  local↔venue reconciliation lives in ``tests/integration/test_reconciliation.py``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from qts.domain.modes import ExecutionMode
from qts.execution.demo_session import DemoSession
from qts.execution.order_truth import open_demo_journal


@pytest.fixture(autouse=True)
def demo_readiness_pass(monkeypatch):
    monkeypatch.setattr(
        "qts.lifecycle.demo_gate.demo_forward_readiness_report",
        lambda **kwargs: {"passed": True, "blocked_reasons": [], "checks": {}, "required_checks": []},
    )


class _Harness(DemoSession):
    @property
    def mode(self):
        return ExecutionMode.DEMO_EXECUTION

    def _identity_probe(self):
        return {"is_demo": True}

    def _pin_probe(self):
        return {"verified": True}


class _Stage:
    def __init__(self) -> None:
        self.halts: list[str] = []

    def halt(self, *, reason: str, actor: str) -> None:
        self.halts.append(reason)


class _Authority:
    def is_execution_permitted(self, fresh_readiness=None):
        return True, []


class _ReconcileSeam:
    """Controllable reconciliation result for the close-path unit harness.

    Records how many times the close path consulted the barrier (so a test can
    prove the path is still wired to it) and lets a test force a drift report.
    """

    def __init__(self) -> None:
        self.result: dict = {"requires_suspend": False, "drift": "OK", "details": "", "suspended": False}
        self.calls = 0

    def __call__(self) -> dict:
        self.calls += 1
        return dict(self.result)


class _Adapter:
    RETCODE_DONE = 10009
    RETCODE_DONE_PARTIAL = 10010
    RETCODE_PLACED = 10008

    def __init__(self, *, close_result=None, close_exc=None, post_close=None) -> None:
        self._close_result = close_result or {"retcode": self.RETCODE_DONE, "deal": "deal-1", "client_order_id": "close-123-test"}
        self._close_exc = close_exc
        self._positions = [
            {
                "ticket": 123,
                "position_id": 123,
                "volume": "0.01",
                "profit": "1.25",
                "price_current": "2001.00",
            }
        ]
        self._post_close = post_close
        self.close_calls = 0

    def position_details(self):
        if self._post_close is not None and self.close_calls:
            if isinstance(self._post_close, Exception):
                raise self._post_close
            return self._post_close
        return list(self._positions)

    def position_realized_result(self, ticket, *, client_order_id=None):
        return {
            "position_ticket": ticket,
            "deal_count": 2,
            "profit": "0.95",
            "commission": "-0.10",
            "swap": "0.00",
            "fee": "-0.02",
            "net_realized_pnl": "0.83",
            "deal_tickets": ["deal-open", "deal-close"],
        }

    def get_symbol_spec(self, symbol):
        return SimpleNamespace(
            contract_size=Decimal("100"),
            volume_step=Decimal("0.01"),
            tick_size=Decimal("0.01"),
        )

    def close_position(self, ticket, *, volume, comment):
        self.close_calls += 1
        if self._close_exc is not None:
            raise self._close_exc
        if self._post_close == []:
            self._positions = []
        return dict(self._close_result)


def _engine(adapter: _Adapter, db_path: Path):
    """The production execution engine, built the way ``DemoSession.engine`` does."""
    from qts.adapters.matching import MatchingEngine
    from qts.execution.engine import ExecutionEngine, OrderManager
    from qts.execution.idempotency import IdempotencyStore
    from qts.portfolio.portfolio import Portfolio
    from qts.risk.authority import engine_limits_from, resolve_risk_limits_from_settings
    from qts.risk.engine import RiskEngine

    limits = engine_limits_from(resolve_risk_limits_from_settings(ExecutionMode.DEMO_EXECUTION))
    risk = RiskEngine(limits, db_path=db_path, persist_kill=True)
    return ExecutionEngine(
        OrderManager(audit=None, idempotency=IdempotencyStore(db_path=db_path)),
        risk,
        adapter,
        MatchingEngine(),
        Portfolio(initial_balance=Decimal("0")),  # broker equity is authoritative
        audit=None,
        db_path=db_path,
        market_data=None,
    )


def _journal(tmp_path: Path):
    """A real open journal row for an open DEMO position (broker position 123)."""
    journal = open_demo_journal(tmp_path / "close-safety-journal.db")
    journal_id = journal.open_order(
        client_order_id="open-123-test",
        strategy_id="DEMO-XAUUSD-TREND-TSMOM-V1",
        strategy_config_hash="test-config-hash",
        symbol="XAUUSD",
        side="BUY",
        requested_lots=Decimal("0.01"),
        order_request={"order_type": "MARKET"},
        broker_symbol="XAUUSD@",
    )
    journal.mark_submitted(journal_id, broker_order_id="77", broker_position_id="123")
    journal.mark_fill(
        journal_id,
        filled_lots=Decimal("0.01"),
        executed_price=Decimal("2000.00"),
        broker_position_id="123",
    )
    return journal, journal_id


def _session(adapter: _Adapter, *, journal=None, tmp_path: Path):
    obj = object.__new__(_Harness)
    object.__setattr__(obj, "_authority", _Authority())
    object.__setattr__(obj, "_authority_mode", ExecutionMode.DEMO_EXECUTION)
    object.__setattr__(obj, "_adapter", adapter)
    object.__setattr__(obj, "_engine", _engine(adapter, tmp_path / "close-safety.db"))
    object.__setattr__(obj, "_market_data", None)
    object.__setattr__(obj, "stage", _Stage())
    object.__setattr__(obj, "config", SimpleNamespace(actor="close-test", mode="DEMO_EXECUTION", symbol="XAUUSD", symbol_map={}))
    obj.journal = journal if journal is not None else open_demo_journal(tmp_path / "close-safety-journal.db")
    obj.config.terminal_path = None
    obj.config.mt5_module = object()
    # Deliberate harness seam: no live MT5 deal stream exists here, so there is
    # nothing to poll. The close path must still call it and must fail closed
    # when it raises — see tests/test_poll_fill_attribution.py for the fill path.
    obj.sync_fills = lambda client_order_id=None: 0
    obj.reconcile = _ReconcileSeam()
    return obj


def test_unknown_close_retcode_is_ambiguous_and_halts(tmp_path):
    adapter = _Adapter(close_result={"retcode": 99999})
    session = _session(adapter, tmp_path=tmp_path)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert result["success"] is False
    assert "99999" in result["error"]
    assert session.stage.halts
    assert adapter.close_calls == 1


def test_post_close_venue_read_failure_is_ambiguous_and_halts(tmp_path):
    adapter = _Adapter(post_close=ConnectionError("venue read failed"))
    session = _session(adapter, tmp_path=tmp_path)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert result["success"] is False
    assert "post-close venue verification failed" in result["error"]
    assert session.stage.halts


def test_close_transport_exception_is_ambiguous_and_halts(tmp_path):
    adapter = _Adapter(close_exc=TimeoutError("close timeout"))
    session = _session(adapter, tmp_path=tmp_path)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert result["success"] is False
    assert "timeout" in result["error"].lower()
    assert session.stage.halts


def test_venue_closed_without_matching_journal_row_is_ambiguous(tmp_path):
    adapter = _Adapter(post_close=[])
    session = _session(adapter, tmp_path=tmp_path)  # empty journal: no local lifecycle

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert result["success"] is False
    assert "local journal lifecycle could not be matched" in result["error"]
    assert session.stage.halts


def test_local_close_journal_failure_is_ambiguous_and_halts(tmp_path, monkeypatch):
    adapter = _Adapter(post_close=[])
    journal, _journal_id = _journal(tmp_path)
    session = _session(adapter, journal=journal, tmp_path=tmp_path)
    monkeypatch.setattr(
        journal,
        "mark_outcome",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")),
    )

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "AMBIGUOUS"
    assert result["success"] is False
    assert "journal persistence failed" in result["error"]
    assert session.stage.halts


def test_closed_position_journals_broker_realized_pnl_not_preclose_unrealized_profit(tmp_path):
    adapter = _Adapter(post_close=[])
    journal, journal_id = _journal(tmp_path)
    session = _session(adapter, journal=journal, tmp_path=tmp_path)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "CLOSED"
    assert result["success"] is True
    row = journal.get(journal_id)
    assert row["state"] == "CLOSED"
    # Realized P&L comes from the venue's completed deals, never from the
    # pre-close unrealized profit (1.25) reported with the open position.
    assert row["realized_pnl"] == "0.83"
    assert row["fees"] == "-0.12"
    assert json.loads(row["market_state_exit"])["broker_realized"]["deal_count"] == 2
    assert row["realized_pnl"] != "1.25"
    assert session.reconcile.calls == 1


def test_close_registers_the_correlated_local_execution_record(tmp_path):
    """The already-sent broker close is recorded locally before its deal is consumed.

    Without that record the correlated close deal has no local order owner and
    fill attribution must refuse it (see ``poll_live_fills``) — which is exactly
    how a closed position ends up with an unmatched local lifecycle.
    """
    adapter = _Adapter(post_close=[])
    journal, _journal_id = _journal(tmp_path)
    session = _session(adapter, journal=journal, tmp_path=tmp_path)

    result = DemoSession.close_position(session, 123)

    assert result["state"] == "CLOSED"
    recorded = session.engine.om.get("close-123-test")
    assert recorded is not None
    assert recorded.state.value == "ACCEPTED"


def test_reconciliation_drift_after_close_blocks_success_and_halts(tmp_path):
    """A verified-closed venue position is not a *success* while the book is drifted."""
    adapter = _Adapter(post_close=[])
    journal, _journal_id = _journal(tmp_path)
    session = _session(adapter, journal=journal, tmp_path=tmp_path)
    session.reconcile.result = {
        "requires_suspend": True,
        "drift": "MISSING_POSITION",
        "details": "local XAUUSD 0.01 not on venue",
        "suspended": True,
    }

    result = DemoSession.close_position(session, 123)

    assert result["success"] is False
    assert result["reconciliation"]["requires_suspend"] is True
    assert session.stage.halts
    assert any("reconciliation drift" in reason for reason in session.stage.halts)
