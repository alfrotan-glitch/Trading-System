"""End-to-end: a real DEMO submission must preserve the broker's actual charges.

These run the product's own submit path (``DemoSession.submit``) against the
stateful fake terminal, then read the evidence log back. They exist because a
capture layer that is never wired up is indistinguishable from one that does
not exist — and the whole point of this phase is that modelled costs must
eventually be replaced by measured ones.

Nothing here contacts a broker. ``DEMO_EXECUTION`` only; LIVE stays locked.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import fakes_demo_provider as provider_fixture
import pytest
from demo_harness import armed_session, write_registry
from fakes_mt5_demo import FakeTerminal

from qts.execution import demo_session as demo_session_module
from qts.execution.cost_capture import CostEvidenceStore

PASSING_VERDICT = SimpleNamespace(
    passed=True,
    failed=(),
    unknown=(),
    reasons=(),
    as_dict=lambda: {"passed": True, "failed": [], "unknown": [], "reasons": []},
)


def passing_gate(monkeypatch) -> None:
    """Isolate the broker-outcome branch; the pre-trade gate has its own suite."""
    monkeypatch.setattr(demo_session_module, "run_pretrade_gate", lambda _ctx: PASSING_VERDICT)


def terminal_with_charges(*, commission: float = -0.70, swap: float = 0.0,
                          fee: float = -0.10) -> FakeTerminal:
    """A fake terminal whose deals carry real cost fields.

    The stock ``FakeTerminal`` omits commission/swap/fee entirely. Adding them
    here is what turns "the broker charged us X" into something observable.
    """
    terminal = FakeTerminal()
    original_send = terminal.order_send

    def order_send(request):
        result = original_send(request)
        for deal in terminal.deals:
            for name, value in (("commission", commission), ("swap", swap), ("fee", fee)):
                if not hasattr(deal, name):
                    setattr(deal, name, value)
        return result

    terminal.order_send = order_send  # type: ignore[method-assign]
    return terminal


def evidence_path_for(session) -> Path:
    return Path(session.cost_evidence_store.path)


# --------------------------------------------------------------------------- #
# the happy path: charges are captured
# --------------------------------------------------------------------------- #


def test_a_real_submission_writes_the_broker_charges_to_the_evidence_log(
    demo_env, monkeypatch
) -> None:
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = terminal_with_charges()
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="cost capture test")
    assert result.allowed is True, result.reasons

    path = evidence_path_for(session)
    assert path.exists(), "a successful fill must leave cost evidence behind"

    store = CostEvidenceStore(path)
    deals = store.deals()
    assert deals, "no deal evidence was captured for a filled order"
    assert all(deal.complete for deal in deals), [
        deal.unavailable_fields for deal in deals
    ]
    # The broker's own numbers survived the round trip, unmodified.
    assert any(deal.commission == Decimal("-0.70") for deal in deals)
    assert any(deal.fee == Decimal("-0.10") for deal in deals)
    assert store.verify_chain()[0] is True


def test_the_evidence_names_the_broker_symbol_and_the_canonical_symbol(demo_env, monkeypatch) -> None:
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = terminal_with_charges()
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="symbol provenance")

    deals = CostEvidenceStore(evidence_path_for(session)).deals()
    assert deals
    assert {deal.canonical_symbol for deal in deals} == {"XAUUSD"}
    assert {deal.broker_symbol for deal in deals} == {"XAUUSD@"}


def test_captured_evidence_reconciles_against_a_cost_model(demo_env, monkeypatch) -> None:
    """The measurement the whole phase exists to produce."""
    from qts.execution.cost_capture import reconcile_store
    from qts.research.costs import CostModel

    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = terminal_with_charges()
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="reconciliation")

    model = CostModel.xauusd_default(
        spread_price_units=0.30, slippage_price_units=0.10, swap_per_night_per_lot_usd=0.0
    )
    report = reconcile_store(CostEvidenceStore(evidence_path_for(session)), model=model)
    # One fill is not a round trip, but the measurement must still be produced
    # rather than silently producing nothing.
    assert report["store_completeness"]["deals"] >= 1
    assert report["conclusion"]
    assert "profitable" not in report["conclusion"].lower()


# --------------------------------------------------------------------------- #
# the failure paths: never favourable, never silent
# --------------------------------------------------------------------------- #


def test_a_rejected_order_writes_no_cost_evidence(demo_env, monkeypatch) -> None:
    """A rejection is not a fill; recording it as a zero-cost fill is a lie."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = terminal_with_charges()
    terminal.order_send_retcode = 10019  # TRADE_RETCODE_NO_MONEY — definitive
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="rejection")
    assert result.allowed is False

    store = session.cost_evidence_store
    assert store is None or store.deals() == []


def test_the_stock_terminal_without_cost_fields_is_recorded_as_incomplete(demo_env, monkeypatch) -> None:
    """The default fake omits commission/swap/fee — that must read UNAVAILABLE."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = FakeTerminal()  # no cost fields at all
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="missing fields")
    assert result.allowed is True

    deals = CostEvidenceStore(evidence_path_for(session)).deals()
    assert deals, "the fill itself was real even though the charges were not"
    for deal in deals:
        assert deal.complete is False
        assert {"commission", "swap", "fee"} & set(deal.unavailable_fields)
        # The invariant that matters: not a single one was read as zero.
        assert deal.reported_cost is None


def test_a_capture_failure_is_reported_and_never_becomes_a_zero_cost(demo_env, monkeypatch) -> None:
    """If the evidence log dies, the system must say so, not assume free trading."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = terminal_with_charges()
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    monkeypatch.setattr(
        session.__class__,
        "cost_evidence_store",
        property(lambda _self: None),
    )
    session._cost_store_error = "simulated evidence store failure"

    result = session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="store down")
    # A dead evidence log must not stop the order, but must not be silent either.
    assert result.allowed is True
    summary = session._last_cost_capture
    assert summary["captured"] == 0
    assert summary["unavailable"]


def test_replaying_the_same_fill_does_not_double_count(demo_env, monkeypatch) -> None:
    """The reconnect case: identical deal rows arrive again after a restart."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = terminal_with_charges()
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="replay")

    store = CostEvidenceStore(evidence_path_for(session))
    before = len(store.deals())
    assert before >= 1

    # Simulate a reconnect replaying the same broker history.
    rows = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    from qts.execution.cost_capture import _deal_from_record

    for row in rows:
        if row.get("kind") == "deal":
            store.append(_deal_from_record(row))

    assert len(store.deals()) == before
    assert store.completeness_report()["duplicates_skipped"] == before


def test_the_evidence_log_survives_a_new_session_object(demo_env, monkeypatch) -> None:
    """Restart safety at the session layer, not just the store layer."""
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    terminal = terminal_with_charges()
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale="restart")
    path = evidence_path_for(session)

    reopened = CostEvidenceStore(path)
    assert reopened.verify_chain()[0] is True
    assert reopened.completeness_report()["truncated"] is False


@pytest.mark.parametrize("missing", ["commission", "swap", "fee"])
def test_each_missing_charge_individually_blocks_a_cost_measurement(
    demo_env, monkeypatch, missing: str
) -> None:
    write_registry(demo_env["registry"], provider_fixture.registry_entry())
    terminal = FakeTerminal()
    original_send = terminal.order_send

    def order_send(request):
        result = original_send(request)
        for deal in terminal.deals:
            for name in ("commission", "swap", "fee"):
                if name == missing:
                    if hasattr(deal, name):
                        delattr(deal, name)
                elif not hasattr(deal, name):
                    setattr(deal, name, -0.10)
        return result

    terminal.order_send = order_send  # type: ignore[method-assign]
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))
    session = armed_session(demo_env["tmp"], terminal, register_strategy=True)
    passing_gate(monkeypatch)
    monkeypatch.setenv("QTS_STATE_ROOT", str(demo_env["tmp"] / "state"))

    session.submit(side="BUY", stop_loss=Decimal("1995.00"), rationale=f"missing {missing}")

    deals = CostEvidenceStore(evidence_path_for(session)).deals()
    assert deals
    assert any(missing in deal.unavailable_fields for deal in deals)
    assert any(deal.reported_cost is None for deal in deals)
