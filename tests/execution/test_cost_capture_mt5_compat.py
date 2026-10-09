"""Cost capture against what the REAL MetaTrader5 package actually returns.

The previous tests used plain Python objects. A real terminal returns a tuple
of namedtuples whose members are **numpy scalars**, and whose timestamps are on
the **server's clock**, not UTC. Both facts break naive code:

* ``numpy.int64`` is not a subclass of Python ``int``, so any
  ``isinstance(value, int)`` check silently reports the field as missing — which
  here would mean "the broker charged nothing", the most dangerous possible
  misread.
* This project's own evidence (``tests/test_tick_timestamp_contract.py``)
  records the WMMarkets-Demo server stamping UTC+3. Converting a server stamp
  with ``fromtimestamp(t, tz=UTC)`` puts every deal three hours in the future.

These tests build rows the way MT5 builds them and assert the numbers survive.
"""

from __future__ import annotations

from collections import namedtuple
from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from qts.execution.cost_capture import (
    CostEvidenceStore,
    deal_evidence_from_broker,
    reconcile_round_trip,
)

# The field set of a real MT5 deal record, in the package's own order.
DEAL_FIELDS = ["ticket", "order", "time", "time_msc", "type", "entry", "magic", "position_id", "reason", "profit", "volume", "price", "commission", "swap", "fee", "symbol", "comment", "external_id"]

MT5Deal = namedtuple("MT5Deal", DEAL_FIELDS)

#: WMMarkets-Demo is UTC+3 (see tests/test_tick_timestamp_contract.py).
OFFSET_3H = 10800.0


def mt5_deal(**overrides: object) -> MT5Deal:
    """One deal row, typed exactly as the MetaTrader5 package returns one."""
    defaults: dict[str, object] = {
        "ticket": np.int64(770001),
        "order": np.int64(990001),
        "time": np.int64(1_760_000_000),          # server-basis seconds
        "time_msc": np.int64(1_760_000_000_000),  # server-basis milliseconds
        "type": np.int64(0),                      # DEAL_TYPE_BUY
        "entry": np.int64(0),                     # DEAL_ENTRY_IN
        "magic": np.int64(20250916),
        "position_id": np.int64(770001),
        "reason": np.int64(3),                    # DEAL_REASON_CLIENT
        "profit": np.float64(0.0),
        "volume": np.float64(0.01),
        "price": np.float64(4000.50),
        "commission": np.float64(-0.70),
        "swap": np.float64(0.0),
        "fee": np.float64(-0.10),
        "symbol": "XAUUSD@",
        "comment": "qts7ab3c9d1",
        "external_id": "",
    }
    defaults.update(overrides)
    return MT5Deal(**defaults)


def evidence(deal: MT5Deal, **kwargs: object):
    return deal_evidence_from_broker(deal, canonical_symbol="XAUUSD", **kwargs)


# --------------------------------------------------------------------------- #
# numpy scalars
# --------------------------------------------------------------------------- #


def test_numpy_int_tickets_are_recognised_not_treated_as_missing() -> None:
    """np.int64 is not an `int` subclass; a naive isinstance check loses it."""
    assert not issubclass(np.int64, int), "precondition: numpy ints are not python ints"
    deal = evidence(mt5_deal())
    assert deal.deal_ticket == "770001"
    assert deal.order_ticket == "990001"
    assert deal.position_id == "770001"
    assert deal.is_identified is True


def test_numpy_float_charges_are_captured_exactly() -> None:
    deal = evidence(mt5_deal())
    assert deal.commission == Decimal("-0.70")
    assert deal.swap == Decimal("0.0")
    assert deal.fee == Decimal("-0.10")
    assert deal.volume == Decimal("0.01")
    assert deal.price == Decimal("4000.50")
    assert deal.complete is True
    assert deal.reported_cost == Decimal("0.80")


def test_a_numpy_zero_charge_is_still_a_real_zero() -> None:
    """Distinguishing 0 from missing is the whole point, and numpy must not blur it."""
    zero = evidence(mt5_deal(commission=np.float64(0.0)))
    assert zero.commission == Decimal("0.0")
    assert zero.complete is True
    assert "commission" not in zero.unavailable_fields


def test_the_raw_record_preserves_a_namedtuple_deal_including_numpy_values() -> None:
    deal = evidence(mt5_deal())
    assert deal.raw["symbol"] == "XAUUSD@"
    assert deal.raw["comment"] == "qts7ab3c9d1"
    # numpy ints are stringified for JSON rather than silently dropped.
    assert str(deal.raw["ticket"]) == "770001"
    assert isinstance(deal.raw, dict) and deal.raw


def test_a_real_mt5_tuple_of_deals_is_walked_in_order() -> None:
    rows = (mt5_deal(ticket=np.int64(1)), mt5_deal(ticket=np.int64(2)))
    assert len(rows) == 2  # MT5 returns a tuple, not a list
    tickets = [evidence(r).deal_ticket for r in rows]
    assert tickets == ["1", "2"]


# --------------------------------------------------------------------------- #
# server-basis timestamps
# --------------------------------------------------------------------------- #


def test_a_server_stamp_is_not_called_utc_when_no_offset_is_supplied() -> None:
    """The failure this file exists for: 1760000000 is NOT that UTC instant."""
    deal = evidence(mt5_deal())
    assert deal.server_utc_offset_s is None
    assert deal.time_iso is None, "no offset supplied, so no UTC time may be claimed"
    assert deal.time_basis == "broker-basis-only"
    assert deal.time_iso_broker is not None
    # The raw broker stamp is preserved whatever happens to the rendering.
    assert deal.time_msc == 1_760_000_000_000


def test_the_measured_offset_produces_true_utc() -> None:
    """UTC+3 server: subtracting 3h is what turns a server stamp into UTC."""
    deal = evidence(mt5_deal(), server_utc_offset_s=OFFSET_3H)
    assert deal.time_basis == "utc-corrected"
    assert deal.server_utc_offset_s == OFFSET_3H
    assert deal.time_iso is not None
    broker = datetime.fromisoformat(str(deal.time_iso_broker))
    utc = datetime.fromisoformat(str(deal.time_iso))
    assert (broker - utc).total_seconds() == pytest.approx(OFFSET_3H)


def test_the_two_bases_are_labelled_so_they_cannot_be_confused() -> None:
    deal = evidence(mt5_deal(), server_utc_offset_s=OFFSET_3H)
    assert deal.time_iso != deal.time_iso_broker
    assert deal.time_basis == "utc-corrected"


def test_a_negative_offset_is_applied_in_the_right_direction() -> None:
    """A UTC-5 server: UTC must be LATER than the server stamp."""
    deal = evidence(mt5_deal(), server_utc_offset_s=-18000.0)
    broker = datetime.fromisoformat(str(deal.time_iso_broker))
    utc = datetime.fromisoformat(str(deal.time_iso))
    assert (utc - broker).total_seconds() == Decimal("18000.0")


def test_a_round_trip_warns_when_its_times_are_not_utc() -> None:
    entry = evidence(mt5_deal(ticket=np.int64(1)))
    exit_ = evidence(mt5_deal(ticket=np.int64(2), entry=np.int64(1)))
    trip = reconcile_round_trip([entry, exit_], position_id="770001")
    assert any("NOT UTC" in note for note in trip.notes)
    # Ordering still works: both bases are monotonic in the same instant.
    assert trip.last_deal_time is not None


def test_a_round_trip_with_utc_times_carries_no_warning() -> None:
    entry = evidence(mt5_deal(ticket=np.int64(1)), server_utc_offset_s=OFFSET_3H)
    exit_ = evidence(mt5_deal(ticket=np.int64(2), entry=np.int64(1)), server_utc_offset_s=OFFSET_3H)
    trip = reconcile_round_trip([entry, exit_], position_id="770001")
    assert not any("NOT UTC" in note for note in trip.notes)


# --------------------------------------------------------------------------- #
# real deal shapes
# --------------------------------------------------------------------------- #


def test_a_closing_deal_carries_the_overnight_swap() -> None:
    close = evidence(
        mt5_deal(
            ticket=np.int64(770002),
            entry=np.int64(1),      # DEAL_ENTRY_OUT
            type=np.int64(1),       # DEAL_TYPE_SELL
            swap=np.float64(-1.20),
            profit=np.float64(5.00),
        ),
        server_utc_offset_s=OFFSET_3H,
    )
    assert close.side == "SELL"
    assert close.profit == Decimal("5.00")
    assert close.net_pnl == Decimal(5.00) - Decimal("0.70") - Decimal("1.20") - Decimal("0.10")
    assert close.reported_cost == Decimal("2.00")


def test_a_swap_only_posting_has_zero_volume_and_is_not_a_fill() -> None:
    posting = evidence(mt5_deal(volume=np.float64(0.0), price=np.float64(0.0),
                                swap=np.float64(-2.50), commission=np.float64(0.0),
                                fee=np.float64(0.0), profit=np.float64(0.0)))
    assert posting.is_swap_only is True
    assert posting.reported_cost == Decimal("2.50")


def test_non_trading_deal_types_have_no_side_and_are_not_marked_incomplete() -> None:
    """Balance/credit deals (type >= 2) have no BUY/SELL — that is a fact, not a gap."""
    balance = evidence(mt5_deal(type=np.int64(2), volume=np.float64(0.0),
                                price=np.float64(0.0), profit=np.float64(100.0)))
    assert balance.side is None
    assert "type" not in balance.unavailable_fields
    assert balance.complete is True


def test_commission_charged_as_a_positive_number_is_preserved_not_flipped() -> None:
    """Some brokers sign charges positively. Preserve the sign; never assume."""
    deal = evidence(mt5_deal(commission=np.float64(0.70), swap=np.float64(0.0),
                             fee=np.float64(0.0)))
    assert deal.commission == Decimal("0.70")
    assert deal.reported_charges == Decimal("0.70")
    # A positive net charge is a CREDIT, so the "cost" is negative. That is the
    # honest reading of the broker's number; forcing it positive would hide a
    # sign-convention disagreement behind a plausible-looking cost.
    assert deal.reported_cost == Decimal("-0.70")


# --------------------------------------------------------------------------- #
# persistence round trip with real types
# --------------------------------------------------------------------------- #


def test_numpy_derived_evidence_survives_disk_and_stays_reconcilable(tmp_path) -> None:
    store = CostEvidenceStore(tmp_path / "e.jsonl")
    entry = evidence(mt5_deal(ticket=np.int64(1)), server_utc_offset_s=OFFSET_3H)
    exit_ = evidence(mt5_deal(ticket=np.int64(2), entry=np.int64(1), type=np.int64(1),
                              swap=np.float64(-1.20), profit=np.float64(5.0)),
                     server_utc_offset_s=OFFSET_3H)
    store.append(entry)
    store.append(exit_)

    reloaded = CostEvidenceStore(store.path)
    deals = reloaded.deals()
    assert len(deals) == 2
    assert all(d.time_basis == "utc-corrected" for d in deals)
    assert all(d.server_utc_offset_s == OFFSET_3H for d in deals)
    assert all(d.complete for d in deals)
    assert reloaded.verify_chain()[0] is True


def test_captured_timestamps_are_not_in_the_future_on_a_utc_plus_3_server() -> None:
    """The exact regression: an uncorrected UTC+3 stamp reads 3h from now."""
    # A UTC+3 server reports "now" as now + 3h. That is the stamp MT5 returns.
    now_msc = int(datetime.now(UTC).timestamp() * 1000) + int(OFFSET_3H * 1000)
    deal = mt5_deal(time_msc=np.int64(now_msc))
    corrected = evidence(deal, server_utc_offset_s=OFFSET_3H)
    assert corrected.time_iso is not None
    assert datetime.fromisoformat(str(corrected.time_iso)) <= datetime.now(UTC)

    uncorrected_stamp = datetime.fromisoformat(str(corrected.time_iso_broker))
    assert (uncorrected_stamp - datetime.now(UTC)).total_seconds() > 2 * 3600, (
        "precondition: without the offset this stamp really is ~3h in the future"
    )
