"""Broker outcome contract: what happened, what is UNKNOWN, and how UNKNOWN ends.

Forensic origin — order ``demo-20260928T140630-884971d1e6`` on WMMarkets-Demo:

    MT5 order_send returned None: (-2, 'Invalid "comment" argument')

The client library refused to marshal the request. Nothing was transmitted, the
broker never saw an order, and the account was untouched. QTS recorded
AMBIGUOUS, wrote a durable reconciliation suspension, and refused every later
order — and no product path could resolve it, because reconciliation compares
the in-memory order map with the venue and a restarted process has an empty
map. A local string-length bug took the trading system down permanently.

These tests pin the three properties that make that impossible:

1. a request the broker never received is a deterministic REJECTION;
2. a request that MIGHT have been received stays AMBIGUOUS and keeps the
   system suspended (fail-closed is not weakened anywhere here);
3. an AMBIGUOUS order is resolved by BROKER EVIDENCE, in both directions —
   proven-not-executed clears, proven-executed is adopted and never duplicated.

No test mocks the lifecycle away: every one drives the real DemoSession, the
real durable stores and the real recovery transition. No broker order is ever
submitted to a real terminal.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo_harness import armed_session  # noqa: E402
from fakes_mt5_demo import FakeTerminal  # noqa: E402

pytest_plugins = ["demo_harness"]


# --------------------------------------------------------------------- fakes
class RefusingTerminal(FakeTerminal):
    """``order_send`` returns None with a configurable client error code.

    Reproduces the real failure shape: MetaTrader5 signals a refused or lost
    call by returning ``None``, and the only discriminator is ``last_error()``.
    """

    def __init__(self, error: tuple[int, str], **kw: Any) -> None:
        super().__init__(**kw)
        self._error = error
        self.send_attempts = 0

    def order_send(self, request):
        self.send_attempts += 1
        self.requests.append(dict(request))
        return None

    def last_error(self):
        return self._error


class EvidenceTerminal(FakeTerminal):
    """A live terminal used only to answer 'did this order execute?'."""

    def __init__(self, *, deals: list[Any] | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self._history = list(deals or [])

    def history_deals_get(self, *args, **kwargs):
        return list(self._history)


class BlindTerminal(FakeTerminal):
    """Connected, but its deal history cannot be read."""

    def history_deals_get(self, *args, **kwargs):
        return None  # MT5 signals failure with None, not an empty tuple


def _suspend_via_broker_ambiguity(session) -> None:
    """Drive the session into a durable AMBIGUOUS suspension through real code."""
    engine = session.engine
    engine._suspended = True
    engine._suspend_reason = "ambiguous broker state demo-test: outcome unknown"
    engine._persist_reconcile_suspend(True, engine._suspend_reason)


def _journal_row(session, client_order_id: str, state: str) -> int:
    from decimal import Decimal

    journal_id = session.journal.open_order(
        client_order_id=client_order_id,
        strategy_id="DEMO-EXECPROBE-XAUUSD-V1",
        strategy_config_hash="deadbeef",
        symbol="XAUUSD",
        broker_symbol="XAUUSD@",
        side="BUY",
        requested_lots=Decimal("0.01"),
        order_request={"symbol": "XAUUSD@", "volume": 0.01},
    )
    if state != "NEW":
        session.journal.mark_outcome(journal_id, state=state, exit_reason="outcome never observed")
    return journal_id


# ------------------------------------------------- 1. classification contract
def test_a_request_the_broker_never_received_is_rejected_not_ambiguous(demo_env, tmp_path):
    """THE regression. ``(-2, 'Invalid "comment" argument')`` is local."""
    from qts.adapters.broker_outcome import BrokerRequestRejected
    from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

    terminal = RefusingTerminal((-2, 'Invalid "comment" argument'))
    session = armed_session(tmp_path, terminal)
    adapter = session.adapter

    intent = OrderIntent(
        client_order_id="demo-20260928T140630-884971d1e6",
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity="0.01",
        order_type=OrderType.MARKET,
        strategy_id="DEMO-EXECPROBE-XAUUSD-V1",
    )
    with pytest.raises(BrokerRequestRejected) as excinfo:
        adapter.submit(intent)

    message = str(excinfo.value)
    assert "NOT TRANSMITTED" in message
    assert "-2" in message
    # The verdict must carry its own justification for the audit trail.
    assert "nothing was marshalled or sent" in message


def test_a_lost_reply_stays_unknown_and_fails_closed(demo_env, tmp_path):
    """The other direction: a timeout MIGHT have reached the broker."""
    from qts.adapters.broker_outcome import BrokerOutcomeUnknown
    from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

    terminal = RefusingTerminal((-10005, "IPC timeout"))
    session = armed_session(tmp_path, terminal)

    intent = OrderIntent(
        client_order_id="demo-unknown-outcome",
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity="0.01",
        order_type=OrderType.MARKET,
        strategy_id="DEMO-EXECPROBE-XAUUSD-V1",
    )
    with pytest.raises(BrokerOutcomeUnknown) as excinfo:
        session.adapter.submit(intent)
    assert "OUTCOME UNKNOWN" in str(excinfo.value)


def test_an_unrecognised_error_code_is_treated_as_unknown(demo_env, tmp_path):
    """Fail closed by default: only an allowlisted code proves non-transmission."""
    from qts.adapters.broker_outcome import classify_send_failure

    assert classify_send_failure((-99999, "brand new code")).is_unknown is True
    assert classify_send_failure(None).is_unknown is True
    assert classify_send_failure((-2, 'Invalid "comment" argument')).is_unknown is False


def test_the_engine_classifies_by_evidence_not_by_error_text(demo_env, tmp_path):
    """A definitive rejection whose text says 'connection' must not suspend.

    The old classifier substring-matched the exception message, so a broker
    rejection reading "no connection to trade server" became AMBIGUOUS and
    durably suspended trading.
    """
    from qts.adapters.broker_outcome import BrokerRequestRejected
    from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

    terminal = FakeTerminal()
    session = armed_session(tmp_path, terminal)
    engine = session.engine

    def rejecting_submit(intent):
        raise BrokerRequestRejected("MT5 rejected retcode 10031: no connection to trade server")

    # Everything about the broker stays real except the verdict under test.
    engine.broker.submit = rejecting_submit
    intent = OrderIntent(
        client_order_id="demo-definitive-reject",
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity="0.01",
        order_type=OrderType.MARKET,
        strategy_id="DEMO-EXECPROBE-XAUUSD-V1",
    )
    engine.submit_intent(intent)

    from qts.execution.engine import load_reconcile_suspension

    durable = load_reconcile_suspension(session.db_path)
    assert durable.suspended is False, (
        "a rejection the broker itself answered must never create a durable suspension"
    )


# ------------------------------------------------ 2. one canonical request
def test_submit_sends_exactly_what_the_dry_run_builder_produced(demo_env, tmp_path):
    """One construction. The preview must equal the request actually sent."""
    from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

    terminal = FakeTerminal()
    session = armed_session(tmp_path, terminal)
    adapter = session.adapter

    intent = OrderIntent(
        client_order_id="demo-one-builder",
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity="0.01",
        order_type=OrderType.MARKET,
        strategy_id="DEMO-EXECPROBE-XAUUSD-V1",
    )
    preview = adapter.build_broker_request(intent)
    adapter.submit(intent)

    assert terminal.requests, "no request was sent"
    sent = terminal.requests[-1]
    assert sent == preview, f"preview and sent request diverged:\npreview={preview}\nsent={sent}"


def test_the_request_contract_refuses_the_comment_that_caused_the_incident():
    """A 31-char client_order_id as comment is refused before any send."""
    from qts.adapters.broker_outcome import BrokerRequestRejected
    from qts.adapters.mt5_adapter import validate_broker_request

    base = {
        "action": 1,
        "symbol": "XAUUSD@",
        "volume": 0.01,
        "type": 0,
        "type_filling": 1,
        "type_time": 0,
        "magic": 20250916,
        "comment": "demo-20260928T140630-884971d1e6",  # the real 31-char id
    }
    with pytest.raises(BrokerRequestRejected) as excinfo:
        validate_broker_request(base, max_comment=16)
    assert "comment" in str(excinfo.value)
    assert "31 chars" in str(excinfo.value)

    # and the contract catches the other shapes MT5 refuses
    for field, bad in [
        ("symbol", ""),
        ("volume", 0.0),
        ("comment", 'say "hi"'),
        ("type", None),
        ("price", float("nan")),
    ]:
        broken = {**base, "comment": "qtsdeadbeef", field: bad}
        with pytest.raises(BrokerRequestRejected):
            validate_broker_request(broken, max_comment=16)


# --------------------------------------- 3. unknown outcomes end with evidence
def test_broker_evidence_that_nothing_executed_resolves_the_ambiguity(demo_env, tmp_path):
    """The dead end gets an exit — and only on a definite broker answer."""
    terminal = EvidenceTerminal(deals=[])
    session = armed_session(tmp_path, terminal)
    _journal_row(session, "demo-never-executed", "AMBIGUOUS")
    _suspend_via_broker_ambiguity(session)

    before = session.durable_suspension_state()
    assert "reconciliation_suspension" in before["active_ids"]

    outcome = session.resume_from_suspension(
        reason="broker confirmed no execution for the ambiguous order", actor="test"
    )

    assert outcome["recovered"] is True, outcome
    assert outcome["unresolved_executions"]["all_resolved"] is True
    assert len(outcome["unresolved_executions"]["resolved"]) == 1
    assert "never executed" in outcome["unresolved_executions"]["resolved"][0]["detail"]

    row = session.journal.get_by_client_order_id("demo-never-executed")
    assert row["state"] == "REJECTED"
    assert "broker evidence" in row["exit_reason"]
    assert session.durable_suspension_state()["active_blockers"] == []
    # Recovery clears blockers; it does not promote the stage machine.
    assert outcome["stage"]["stage"] == before["stage"]["stage"]


def test_an_order_that_did_execute_is_adopted_and_never_duplicated(demo_env, tmp_path):
    """Evidence of execution must be adopted, not cleared away."""
    deal = SimpleNamespace(
        ticket=778899,
        order=990123,
        symbol="XAUUSD@",
        volume=0.01,
        price=2000.10,
        profit=0.0,
        type=0,
        time=1_700_000_000,
        comment="",  # filled in below with the mapped comment
    )
    terminal = EvidenceTerminal(deals=[deal])
    session = armed_session(tmp_path, terminal)
    _journal_row(session, "demo-did-execute", "AMBIGUOUS")
    # The adapter maps client_order_id -> MT5 comment; the deal carries that.
    from qts.adapters.mt5_adapter import mt5_comment_for

    deal.comment = mt5_comment_for("demo-did-execute")
    session.adapter._store_comment_map("demo-did-execute", deal.comment)
    _suspend_via_broker_ambiguity(session)

    outcome = session.resume_from_suspension(reason="checking the ambiguous order", actor="test")

    assert outcome["recovered"] is False, "an order that reached the broker must not be cleared away"
    assert outcome["unresolved_executions"]["executed"], outcome["unresolved_executions"]
    evidence = outcome["unresolved_executions"]["executed"][0]["evidence"]
    assert "778899" in evidence["deals"]

    row = session.journal.get_by_client_order_id("demo-did-execute")
    assert row["state"] == "FILLED"
    assert "DID reach the broker" in row["exit_reason"]
    # Still suspended, and no order was ever re-sent.
    assert session.durable_suspension_state()["active_blockers"]
    assert terminal.requests == []


def test_an_unreadable_broker_history_resolves_nothing(demo_env, tmp_path):
    """Absence of evidence is not evidence of absence."""
    terminal = BlindTerminal()
    session = armed_session(tmp_path, terminal)
    _journal_row(session, "demo-unverifiable", "AMBIGUOUS")
    _suspend_via_broker_ambiguity(session)

    outcome = session.resume_from_suspension(reason="attempting recovery", actor="test")

    assert outcome["recovered"] is False
    resolution = outcome["unresolved_executions"]
    assert resolution["unverifiable"], resolution
    assert "fail closed" in resolution["unverifiable"][0]["detail"]
    row = session.journal.get_by_client_order_id("demo-unverifiable")
    assert row["state"] == "AMBIGUOUS", "an unverifiable order must keep its unknown state"
    assert session.durable_suspension_state()["active_blockers"]


def test_resolution_keeps_the_journal_and_the_duplicate_guard_in_step(demo_env, tmp_path):
    """Two stores hold the outcome; a resolution must update both."""
    from qts.execution.idempotency import IdempotencyStore

    terminal = EvidenceTerminal(deals=[])
    session = armed_session(tmp_path, terminal)
    _journal_row(session, "demo-two-stores", "AMBIGUOUS")
    store = IdempotencyStore(db_path=session.db_path)
    store.record("demo-two-stores", "AMBIGUOUS")
    assert store.is_ambiguous("demo-two-stores") is True
    _suspend_via_broker_ambiguity(session)

    session.resume_from_suspension(reason="resolving against the broker", actor="test")

    assert session.journal.get_by_client_order_id("demo-two-stores")["state"] == "REJECTED"
    assert IdempotencyStore(db_path=session.db_path).is_ambiguous("demo-two-stores") is False, (
        "the duplicate guard still reports AMBIGUOUS while the journal says resolved"
    )


def test_an_in_flight_submission_is_unresolved_too(demo_env, tmp_path):
    """A process that died mid-order leaves SUBMITTED, which is also UNKNOWN."""
    terminal = EvidenceTerminal(deals=[])
    session = armed_session(tmp_path, terminal)
    journal_id = _journal_row(session, "demo-in-flight", "NEW")
    session.journal.mark_submitted(journal_id, broker_order_id="1")
    assert [r["client_order_id"] for r in session.unresolved_executions()] == ["demo-in-flight"]

    report = session.resolve_unresolved_executions(actor="test")
    assert report["resolved"], report
    assert session.journal.get_by_client_order_id("demo-in-flight")["state"] == "REJECTED"


# ------------------------------------------------------- 4. API truthfulness
def test_the_resume_api_reports_failed_predicates_and_never_fakes_success(demo_env, tmp_path):
    """200 must mean recovered; a refusal must name the predicate that failed."""
    terminal = BlindTerminal()
    session = armed_session(tmp_path, terminal)
    _journal_row(session, "demo-api-unverifiable", "AMBIGUOUS")
    _suspend_via_broker_ambiguity(session)

    refused = session.resume_from_suspension(reason="operator attempt", actor="api:guide")
    assert refused["recovered"] is False
    assert "unresolved_executions_resolved" in refused["failed_predicates"]
    assert refused["active_blockers"], "a refusal must say what is still blocking"
    assert refused["changed"] is False, "a refused recovery must not mutate durable state"

    # ...and the same call succeeds once the broker can answer, with the
    # predicate list empty. Same transition, no second code path.
    session._adapter = None
    session._engine = None
    session.config.mt5_module = EvidenceTerminal(deals=[])
    session._mt5 = session.config.mt5_module
    recovered = session.resume_from_suspension(reason="broker now reachable", actor="api:guide")
    assert recovered["recovered"] is True, recovered
    assert recovered["failed_predicates"] == []
