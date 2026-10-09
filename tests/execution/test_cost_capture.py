"""Actual (broker-reported) execution cost capture and reconciliation.

Why these tests exist
---------------------
The system's edge case rests on cost numbers. If a modelled cost is ever
quietly substituted for a measured one — or if a broker field the venue never
sent is read as a zero — then every backtest, every drawdown limit and every
"net of costs" claim becomes unfalsifiable. These tests pin the behaviour that
prevents that:

* a field the broker did not send is UNAVAILABLE, never 0;
* an unavailable component makes the total incomplete, never smaller;
* a deal that cannot be identified is rejected rather than recorded twice;
* a replayed event (reconnect) is deduplicated, not double-counted;
* a charge that arrives late marks the earlier total as revised.

The class ``BrokerDeal`` deliberately mimics MT5's numpy structured row: it is
attribute-only, and an absent field raises ``AttributeError`` on access. That
is the failure mode the extractors have to survive.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from qts.execution.cost_capture import (
    CostEvidenceStore,
    DealEvidence,
    deal_evidence_from_broker,
    reconcile_fill,
    reconcile_round_trip,
    reconcile_store,
    submit_evidence_from_request,
)
from qts.research.costs import CostModel

CONTRACT_SIZE = 100.0


class BrokerDeal:
    """An MT5-style row: attribute access, no keys, absent means absent."""

    def __init__(self, **fields: object) -> None:
        for key, value in fields.items():
            setattr(self, key, value)

    def _asdict(self) -> dict[str, object]:
        return dict(vars(self))


def full_deal(
    *,
    ticket: int = 1001,
    order: int = 501,
    position_id: int = 77,
    side_type: int = 0,
    entry: int = 0,
    volume: str = "0.01",
    price: str = "4000.50",
    profit: str = "0.00",
    commission: str = "-0.70",
    swap: str = "0.00",
    fee: str = "-0.10",
    time_msc: int = 1_760_000_000_000,
    symbol: str = "XAUUSD@",
    **extra: object,
) -> BrokerDeal:
    return BrokerDeal(
        ticket=ticket,
        order=order,
        position_id=position_id,
        symbol=symbol,
        type=side_type,
        entry=entry,
        volume=volume,
        price=price,
        profit=profit,
        commission=commission,
        swap=swap,
        fee=fee,
        time=1_760_000_000,
        time_msc=time_msc,
        comment="qts-abc123",
        **extra,
    )


def evidence(
    deal: BrokerDeal,
    *,
    spread_points: int | None = 30,
    requested_price: str | None = None,
    account_currency: str | None = "USD",
) -> DealEvidence:
    return deal_evidence_from_broker(
        deal,
        canonical_symbol="XAUUSD",
        client_order_id="demo-1",
        spread_points=spread_points,
        requested_price=requested_price,
        account_currency=account_currency,
    )


def flat_model(spread: str = "0.20", slippage: str = "0.05") -> CostModel:
    """A round-turn model: spread 0.20 price units, slippage 0.05 per fill.

    ``CostModel`` evaluates in floats, so it is constructed with floats. Per
    fill that is spread 0.20 * 100 * 0.01 / 2 = 0.10 plus slippage
    0.05 * 100 * 0.01 = 0.05, i.e. 0.15.
    """
    return CostModel.xauusd_default(
        spread_price_units=float(spread),
        slippage_price_units=float(slippage),
        swap_per_night_per_lot_usd=0.0,
    )


@pytest.fixture
def store(tmp_path: Path) -> CostEvidenceStore:
    return CostEvidenceStore(tmp_path / "cost_evidence.jsonl")


# --------------------------------------------------------------------------- #
# 1. Capture: preserve reality, distinguish unavailable from zero
# --------------------------------------------------------------------------- #


def test_a_complete_deal_reports_its_charges_as_a_positive_cost() -> None:
    deal = evidence(full_deal())
    assert deal.complete is True
    assert deal.unavailable_fields == ()
    # MT5 signs charges negatively; cost is the money out, so it is positive.
    assert deal.reported_charges == Decimal("-0.80")
    assert deal.reported_cost == Decimal("0.80")
    assert deal.net_pnl == Decimal("-0.80")


def test_a_missing_commission_is_unavailable_and_not_zero() -> None:
    """The central invariant: absence must never read as 'free'."""
    deal = evidence(_without("commission"))
    assert "commission" in deal.unavailable_fields
    assert deal.commission is None
    # A partial total would be a SMALLER number that looks better than truth.
    assert deal.reported_charges is None
    assert deal.reported_cost is None
    assert deal.net_pnl is None
    assert deal.complete is False


def _without(*names: str) -> BrokerDeal:
    row = full_deal()
    for name in names:
        if hasattr(row, name):
            delattr(row, name)
    return row


def test_a_genuine_zero_commission_is_distinguishable_from_a_missing_one() -> None:
    zero = evidence(full_deal(commission="0.00"))
    missing = evidence(_without("commission"))
    assert zero.commission == Decimal("0")
    assert zero.complete is True
    assert missing.commission is None
    assert missing.complete is False


def test_every_required_field_absence_is_recorded_individually() -> None:
    for field in ("volume", "price", "profit", "commission", "swap", "fee"):
        deal = evidence(_without(field))
        assert field in deal.unavailable_fields, field
        assert deal.complete is False


def test_unparseable_and_nonsense_values_are_unavailable_not_zero() -> None:
    deal = evidence(full_deal(commission="n/a", swap="", fee=None))
    assert "commission" in deal.unavailable_fields
    assert "swap" in deal.unavailable_fields
    assert deal.reported_cost is None


def test_the_raw_broker_record_is_preserved_verbatim() -> None:
    deal = evidence(full_deal())
    assert deal.raw["ticket"] == 1001
    assert deal.raw["symbol"] == "XAUUSD@"
    assert deal.source == "mt5.history_deals_get"
    assert deal.canonical_symbol == "XAUUSD"
    assert deal.broker_symbol == "XAUUSD@"


def test_deal_time_comes_from_the_broker_stamp_not_the_local_clock() -> None:
    deal = evidence(full_deal(time_msc=1_760_000_000_000))
    assert deal.time_msc == 1_760_000_000_000
    assert deal.time_iso is not None and deal.time_iso.startswith("2025-")


def test_submit_evidence_preserves_requested_versus_executed_prices() -> None:
    submit = submit_evidence_from_request(
        client_order_id="demo-1",
        canonical_symbol="XAUUSD",
        broker_symbol="XAUUSD@",
        side="BUY",
        requested_volume=Decimal("0.01"),
        requested_price=Decimal("4000.00"),
        order_type="MARKET",
        bid=Decimal("4000.00"),
        ask=Decimal("4000.30"),
        spread_points=30,
        account_currency="USD",
    )
    assert submit.requested_price == Decimal("4000.00")
    assert submit.bid == Decimal("4000.00")
    assert submit.ask == Decimal("4000.30")
    assert submit.unavailable_fields == ()
    assert submit.identity_key() == "submit:demo-1"


# --------------------------------------------------------------------------- #
# 2. Store: append-only, deduplicated, tamper-evident
# --------------------------------------------------------------------------- #


def test_append_then_replay_is_a_duplicate_not_a_second_record(store: CostEvidenceStore) -> None:
    first, outcome1 = store.append(evidence(full_deal()))
    assert outcome1 == "appended" and first is not None
    second, outcome2 = store.append(evidence(full_deal()))
    assert outcome2 == "duplicate" and second is None
    assert store.completeness_report()["deals"] == 1
    assert store.completeness_report()["duplicates_skipped"] == 1


def test_a_deal_without_a_ticket_is_rejected_rather_than_recorded(store: CostEvidenceStore) -> None:
    """Unticketed deals cannot be deduplicated, so storing one risks inflation."""
    record, outcome = store.append(evidence(_without("ticket")))
    assert outcome == "rejected_unidentified"
    assert record is None
    assert store.completeness_report()["deals"] == 0


def test_the_hash_chain_verifies_and_detects_tampering(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1)))
    store.append(evidence(full_deal(ticket=2)))
    assert store.verify_chain()[0] is True

    lines = store.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["commission"] = "0.00"  # make the fill look free
    lines[0] = json.dumps(tampered)
    store.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert lines, "the log must not be empty for this test to mean anything"

    fresh = CostEvidenceStore(store.path)
    ok, problems = fresh.verify_chain()
    assert ok is False
    assert problems, "tampering must be reported with a reason"


def test_a_truncated_log_is_detected_not_ignored(store: CostEvidenceStore) -> None:
    """A hash chain alone cannot see a missing tail; the head file can."""
    store.append(evidence(full_deal(ticket=1)))
    store.append(evidence(full_deal(ticket=2)))
    lines = store.path.read_text(encoding="utf-8").splitlines()
    store.path.write_text(lines[0] + "\n", encoding="utf-8")
    fresh = CostEvidenceStore(store.path)
    ok, problems = fresh.verify_chain()
    assert ok is False and problems
    assert fresh.completeness_report()["truncated"] is True


def test_the_store_reopens_and_continues_the_chain(store: CostEvidenceStore) -> None:
    """Restart safety: a new process must extend the log, not restart it."""
    store.append(evidence(full_deal(ticket=1)))
    reopened = CostEvidenceStore(store.path)
    assert reopened.verify_chain()[0] is True
    record, outcome = reopened.append(evidence(full_deal(ticket=2)))
    assert outcome == "appended"
    assert reopened.verify_chain()[0] is True
    assert reopened.completeness_report()["deals"] == 2


def test_a_malformed_line_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    path.write_text("this is not json\n", encoding="utf-8")
    store = CostEvidenceStore(path)
    report = store.completeness_report()
    assert report["malformed_lines"], "a corrupt line must never pass as clean"


def test_completeness_report_counts_unavailable_fields_separately(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1)))
    store.append(evidence(_without("commission") if False else BrokerDeal(
        **{k: v for k, v in full_deal(ticket=2).__dict__.items() if k != "commission"}
    )))
    report = store.completeness_report()
    assert report["complete_deals"] == 1
    assert report["incomplete_deals"] == 1
    assert report["unavailable_field_counts"] == {"commission": 1}


# --------------------------------------------------------------------------- #
# 3. Reconciliation: modelled vs actual
# --------------------------------------------------------------------------- #


def test_a_complete_fill_reconciles_to_a_signed_delta() -> None:
    deal = evidence(full_deal(commission="-0.70", swap="0.00", fee="-0.10"))
    fill = reconcile_fill(
        deal,
        model=flat_model(spread="0.20"),
        contract_size=CONTRACT_SIZE,
        requested_price=Decimal("4000.00"),
    )
    assert fill.complete is True
    # Half the round-turn spread (0.20 * 100 * 0.01 / 2 = 0.10) plus one fill of
    # slippage (0.05 * 100 * 0.01 = 0.05).
    assert fill.modelled_cost == pytest.approx(Decimal("0.15"))
    # reported 0.80 + slippage (0.50 * 100 * 0.01 = 0.50) = 1.30
    assert fill.observed_cost == pytest.approx(Decimal("1.30"))
    # Positive delta = the model UNDER-charged, i.e. reality was worse.
    assert fill.delta == pytest.approx(Decimal("1.15"))
    assert fill.delta is not None and fill.delta > 0


def test_slippage_is_signed_adverse_for_both_sides() -> None:
    buy = evidence(full_deal(side_type=0, price="4000.50"), requested_price="4000.00")
    sell = evidence(full_deal(side_type=1, price="3999.50"), requested_price="4000.00")
    buy_fill = reconcile_fill(buy, contract_size=CONTRACT_SIZE)
    sell_fill = reconcile_fill(sell, contract_size=CONTRACT_SIZE)
    # Both executed 0.50 worse than requested, so both are POSITIVE costs.
    assert buy_fill.slippage_price == pytest.approx(Decimal("0.50"))
    assert sell_fill.slippage_price == pytest.approx(Decimal("0.50"))
    assert buy_fill.slippage_cost == pytest.approx(Decimal("0.50"))
    assert sell_fill.slippage_cost == pytest.approx(Decimal("0.50"))


def test_favourable_slippage_is_negative_not_clipped_to_zero() -> None:
    deal = evidence(full_deal(side_type=0, price="3999.50"), requested_price="4000.00")
    fill = reconcile_fill(deal, contract_size=CONTRACT_SIZE)
    assert fill.slippage_price == pytest.approx(Decimal("-0.50"))


def test_unmeasurable_slippage_is_excluded_from_the_total_and_named() -> None:
    """Without a requested price the total is partial — and says so."""
    deal = evidence(full_deal())  # no requested price
    fill = reconcile_fill(deal, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert fill.slippage_cost is None
    assert "slippage" in fill.unmeasurable_components
    # The charges we CAN see are still totalled, rather than reported as nothing.
    assert fill.observed_cost == pytest.approx(Decimal("0.80"))
    # …but the comparison is not trustworthy, so it is not marked complete.
    assert fill.complete is False
    assert any("not included in the observed total" in note for note in fill.notes)


def test_a_requested_price_captured_with_the_deal_is_used_for_slippage() -> None:
    deal = evidence(full_deal(price="4000.50"), requested_price="4000.00")
    fill = reconcile_fill(deal, contract_size=CONTRACT_SIZE)
    assert fill.slippage_cost == pytest.approx(Decimal("0.50"))


def test_missing_charges_produce_no_comparison_at_all() -> None:
    row = BrokerDeal(**{k: v for k, v in full_deal().__dict__.items() if k != "swap"})
    deal = evidence(row)
    fill = reconcile_fill(deal, model=flat_model(), contract_size=CONTRACT_SIZE,
                          requested_price=Decimal("4000.00"))
    assert fill.reported_cost is None
    assert fill.delta is None
    assert fill.complete is False
    assert any("UNAVAILABLE, not zero" in note for note in fill.notes)


def test_currency_conversion_is_explicit_or_the_amount_stays_unconverted() -> None:
    """MT5 reports in the deposit currency; silently calling it USD is a lie."""
    deal = evidence(full_deal(), account_currency="EUR")
    fill = reconcile_fill(deal, contract_size=CONTRACT_SIZE)
    assert fill.currency == "EUR"
    assert fill.converted is False
    assert any("EUR" in note for note in fill.notes)

    converted = reconcile_fill(
        deal,
        contract_size=CONTRACT_SIZE,
        fx_rate=Decimal("1.08"),
        fx_source="ECB reference rate 2026-10-09",
    )
    assert converted.converted is True
    assert converted.currency == "USD"
    assert converted.observed_cost == pytest.approx(Decimal("0.80") * Decimal("1.08"))


def test_a_round_trip_sums_entry_and_exit_charges() -> None:
    entry = evidence(full_deal(ticket=1, entry=0, side_type=0, commission="-0.70", swap="0.00", fee="-0.10"))
    exit_ = evidence(full_deal(ticket=2, entry=1, side_type=1, commission="-0.70", swap="-1.20", fee="-0.10"))
    trip = reconcile_round_trip([entry, exit_], position_id="77")
    assert trip.deal_count == 2
    assert trip.observed_total == pytest.approx(Decimal("2.80"))
    assert trip.revised is False


def test_a_delayed_swap_marks_the_earlier_total_as_revised() -> None:
    """The classic late charge: it must invalidate the first measurement."""
    entry = evidence(full_deal(ticket=1, entry=0))
    exit_ = evidence(full_deal(ticket=2, entry=1))
    first = reconcile_round_trip([entry, exit_], position_id="77")
    assert first.revised is False

    late_swap = evidence(full_deal(ticket=3, entry=2, volume="0.00", price="0.00",
                                   profit="0.00", commission="0.00", swap="-2.50", fee="0.00"))
    second = reconcile_round_trip(
        [entry, exit_, late_swap], position_id="77", previously_reconciled_deal_count=2
    )
    assert second.deal_count == 3
    assert second.revised is True
    assert any("arrived after this round trip was first reconciled" in n for n in second.notes)
    assert second.observed_total == pytest.approx((first.observed_total or Decimal("0")) + Decimal("2.50"))


def test_a_financing_only_posting_is_named_as_such() -> None:
    swap_only = evidence(full_deal(ticket=1, volume="0.00", price="0.00", swap="-1.20"))
    trip = reconcile_round_trip([swap_only], position_id="77")
    assert any("financing-only" in note for note in trip.notes)


def test_deals_without_a_position_cannot_be_attributed() -> None:
    orphan = evidence(_without("position_id"))
    trip = reconcile_round_trip([orphan], position_id=None)
    assert trip.position_id is None
    assert any("cannot be attributed" in n for n in trip.notes)


# --------------------------------------------------------------------------- #
# 4. Whole-store reconciliation and its conclusions
# --------------------------------------------------------------------------- #


def test_no_evidence_yields_no_claim(store: CostEvidenceStore) -> None:
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert report["conclusion"].startswith("NO_EVIDENCE")
    assert report["complete_round_trips"] == 0


def test_incomplete_evidence_refuses_to_draw_a_conclusion(store: CostEvidenceStore) -> None:
    row = BrokerDeal(**{k: v for k, v in full_deal().__dict__.items() if k != "commission"})
    store.append(evidence(row))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert report["conclusion"].startswith("INCOMPLETE")
    assert "commission" in report["conclusion"]
    assert report["complete_round_trips"] == 0
    assert report["total_delta_usd"] is None


def test_a_tampered_log_is_reported_as_unreliable(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1)))
    lines = store.path.read_text(encoding="utf-8").splitlines()
    bad = json.loads(lines[0])
    bad["commission"] = "0.00"
    store.path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    report = reconcile_store(CostEvidenceStore(store.path), model=flat_model(),
                             contract_size=CONTRACT_SIZE)
    assert report["conclusion"].startswith("EVIDENCE_UNRELIABLE")


def test_a_measured_round_trip_still_refuses_to_claim_an_edge(store: CostEvidenceStore) -> None:
    """Even a perfect cost measurement is not evidence of profitability."""
    store.append(evidence(full_deal(ticket=1, entry=0), requested_price="4000.00"))
    store.append(evidence(full_deal(ticket=2, entry=1), requested_price="4005.00"))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert report["complete_round_trips"] == 1
    assert report["conclusion"].startswith("MEASURED")
    assert "not evidence of a trading edge" in report["conclusion"]
    # The guard is explicit so a future reader cannot widen it by accident.
    assert "profitable" not in report["conclusion"].lower()


def test_reality_being_worse_than_the_model_is_counted_prominently(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1, entry=0, commission="-5.00"), requested_price="4000.00"))
    store.append(evidence(full_deal(ticket=2, entry=1, commission="-5.00"), requested_price="4005.00"))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert report["round_trips_where_reality_was_worse"] == 1
    assert report["total_delta_usd"] is not None
    assert Decimal(report["total_delta_usd"]) > 0


def test_incomplete_and_complete_round_trips_are_reported_side_by_side(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1, entry=0, position_id=77), requested_price="4000.00"))
    store.append(evidence(full_deal(ticket=2, entry=1, position_id=77), requested_price="4005.00"))
    broken = BrokerDeal(**{k: v for k, v in full_deal(ticket=3, position_id=88).__dict__.items()
                           if k != "fee"})
    store.append(evidence(broken))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert report["complete_round_trips"] == 1
    assert report["incomplete_round_trips"] == 1
    assert report["positions"] == 2
    # A complete trip exists, so the conclusion is MEASURED — but the incomplete
    # one is still counted and visible, not hidden behind the good result.
    assert report["conclusion"].startswith("MEASURED")


def test_partial_fills_are_recorded_separately_and_summed(store: CostEvidenceStore) -> None:
    """A partial fill is several deals on one order; each is its own evidence."""
    for ticket, volume in ((1, "0.01"), (2, "0.02")):
        store.append(evidence(full_deal(ticket=ticket, order=501, position_id=77, volume=volume)))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    trip = next(t for t in report["round_trips"])
    assert trip["deal_count"] == 2
    assert len(trip["fills"]) == 2


def test_a_rejected_order_produces_no_cost_evidence(store: CostEvidenceStore) -> None:
    """A rejection is not a fill, and must not be recorded as a zero-cost one."""
    assert store.completeness_report()["deals"] == 0
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert report["conclusion"].startswith("NO_EVIDENCE")


def test_reconnect_replay_does_not_inflate_the_measurement(store: CostEvidenceStore) -> None:
    """The restart-safety requirement, end to end."""
    for _ in range(3):  # terminal reconnects and replays the same history
        store.append(evidence(full_deal(ticket=1, entry=0), requested_price="4000.00"))
        store.append(evidence(full_deal(ticket=2, entry=1), requested_price="4005.00"))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert store.completeness_report()["deals"] == 2
    assert store.completeness_report()["duplicates_skipped"] == 4
    assert report["complete_round_trips"] == 1
    assert store.verify_chain()[0] is True


def test_prior_counts_make_late_charges_detectable_across_restarts(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1, entry=0), requested_price="4000.00"))
    store.append(evidence(full_deal(ticket=2, entry=1), requested_price="4005.00"))
    before = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert before["revised_round_trips"] == []

    prior = {t["position_id"]: t["deal_count"] for t in before["round_trips"]}
    store.append(evidence(full_deal(ticket=3, entry=2, volume="0.00", price="0.00",
                                    profit="0.00", commission="0.00", swap="-2.50", fee="0.00")))
    after = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE,
                            prior_deal_counts=prior)
    assert after["revised_round_trips"] == ["77"]


def test_the_report_is_json_serialisable(store: CostEvidenceStore) -> None:
    store.append(evidence(full_deal(ticket=1, entry=0)))
    store.append(evidence(full_deal(ticket=2, entry=1)))
    report = reconcile_store(store, model=flat_model(), contract_size=CONTRACT_SIZE)
    assert json.loads(json.dumps(report))["schema"] == "qts.cost_reconciliation.v1"
