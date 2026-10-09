"""Fills are not trades. Pairing them is what makes expectancy measurable.

The canonical edge evidence recorded ``net_exp 0.0000 pf 0.00`` because nothing
converted the backtest's fills into round turns. These tests pin the pairing
(FIFO, direction flips close, remainder stays open) and the split between
frictionless P&L and the cost the simulation actually charged.
"""

from __future__ import annotations

import pytest

from qts.research.trade_ledger import (
    OpenLot,
    round_turns_from_fills,
    to_trade_records,
)


def _fill(side: str, qty: str | float, price: str | float, mid: str | float, time: str, fee: str | float = "0"):
    return {"side": side, "qty": str(qty), "price": str(price), "bar_open": str(mid), "time": time, "fee": str(fee)}


# -------------------------------------------------------------------- pairing


def test_a_buy_then_a_sell_produces_one_round_turn():
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.10", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2010.10", "2010.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    assert ledger.trades == 1
    assert not ledger.open_lots
    t = ledger.round_turns[0]
    # frictionless: (2010 - 2000) * 0.1 * 100 = +100
    assert t.gross_pnl_usd == pytest.approx(100.0)
    # realized at filled prices: (2010.10 - 2000.10) * 0.1 * 100 = +100
    assert t.realized_pnl_usd == pytest.approx(100.0)
    assert t.measured_cost_usd == pytest.approx(0.0)
    assert t.side == "BUY"


def test_measured_cost_separates_the_frictionless_pnl_from_the_filled_pnl():
    """Half-spread + slippage on each fill is the cost the simulation took."""
    ledger = round_turns_from_fills(
        [
            # buy filled 0.10 above mid, sell filled 0.10 below mid
            _fill("BUY", "0.1", "2000.10", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2009.90", "2010.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    t = ledger.round_turns[0]
    assert t.gross_pnl_usd == pytest.approx(100.0)
    assert t.realized_pnl_usd == pytest.approx(98.0)  # (2009.90-2000.10)*10
    assert t.measured_cost_usd == pytest.approx(2.0)


def test_fees_reduce_realized_pnl():
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00", fee="1.00"),
            _fill("SELL", "0.1", "2000.00", "2000.00", "2026-01-05T12:00:00+00:00", fee="1.00"),
        ]
    )
    t = ledger.round_turns[0]
    assert t.gross_pnl_usd == pytest.approx(0.0)
    assert t.fees_usd == pytest.approx(1.0)  # closing fee attributed to the round turn
    assert t.realized_pnl_usd == pytest.approx(-1.0)


def test_short_round_turns_are_signed_correctly():
    ledger = round_turns_from_fills(
        [
            _fill("SELL", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("BUY", "0.1", "1990.00", "1990.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    t = ledger.round_turns[0]
    assert t.side == "SELL"
    # price fell 10 while short -> +10 * 0.1 * 100 = +100
    assert t.gross_pnl_usd == pytest.approx(100.0)


def test_pairing_is_fifo_not_average_cost():
    """Two lots opened at different prices close oldest-first."""
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("BUY", "0.1", "2020.00", "2020.00", "2026-01-05T11:00:00+00:00"),
            _fill("SELL", "0.1", "2010.00", "2010.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    assert ledger.trades == 1
    # FIFO closes the 2000 lot: (2010-2000)*10 = +100, not (2010-2010)*10 = 0
    assert ledger.round_turns[0].gross_pnl_usd == pytest.approx(100.0)
    assert len(ledger.open_lots) == 1
    assert ledger.open_lots[0].price == pytest.approx(2020.0)


def test_a_direction_flip_closes_then_opens_the_remainder():
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.3", "2010.00", "2010.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    assert ledger.trades == 1  # only the 0.1 long was closed
    assert len(ledger.open_lots) == 1
    short = ledger.open_lots[0]
    assert short.side == "SELL"
    assert short.lots == pytest.approx(0.2)


def test_partial_closes_split_proportionally():
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.2", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2010.00", "2010.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    assert ledger.trades == 1
    assert ledger.round_turns[0].lots == pytest.approx(0.1)
    assert ledger.round_turns[0].gross_pnl_usd == pytest.approx(100.0)
    assert ledger.open_lots[0].lots == pytest.approx(0.1)


def test_an_unclosed_position_is_never_reported_as_a_trade():
    ledger = round_turns_from_fills([_fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00")])
    assert ledger.trades == 0
    assert ledger.gross_pnl_usd == 0.0
    assert len(ledger.open_lots) == 1


# ------------------------------------------------------------- holding period


def test_nights_held_counts_calendar_nights():
    intraday = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2000.00", "2000.00", "2026-01-05T22:00:00+00:00"),
        ]
    )
    assert intraday.round_turns[0].nights_held == 0.0

    overnight = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2000.00", "2000.00", "2026-01-08T10:00:00+00:00"),
        ]
    )
    assert overnight.round_turns[0].nights_held == 3.0


# ------------------------------------------------------------------ integrity


def test_unparseable_fills_are_counted_not_silently_dropped():
    """A ledger that quietly dropped a fill would understate cost."""
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.00", "2000.00", "2026-01-05T10:00:00+00:00"),
            {"side": "SIDEWAYS", "qty": "abc", "price": None},
            "not even a dict",
        ]
    )
    assert ledger.unparseable_fills == 2
    assert any("could not be parsed" in r for r in ledger.reasons)


def test_a_missing_reference_price_is_flagged_not_hidden():
    """Without a mid, measured cost is structurally zero — say so."""
    ledger = round_turns_from_fills(
        [
            {"side": "BUY", "qty": "0.1", "price": "2000.00", "time": "2026-01-05T10:00:00+00:00"},
            {"side": "SELL", "qty": "0.1", "price": "2010.00", "time": "2026-01-05T12:00:00+00:00"},
        ]
    )
    assert ledger.trades == 1
    assert ledger.round_turns[0].measured_cost_usd == pytest.approx(0.0)
    assert any("no reference price" in r for r in ledger.reasons)


def test_non_positive_contract_size_is_refused():
    with pytest.raises(ValueError):
        round_turns_from_fills([], contract_size=0)


def test_empty_fill_stream_produces_an_empty_ledger():
    ledger = round_turns_from_fills([])
    assert ledger.trades == 0
    assert ledger.as_dict()["trades"] == 0


# ------------------------------------------------------- cost-model bridging


def test_trade_records_carry_the_frictionless_pnl():
    """Feeding realized (already-costed) P&L to a cost model would double-charge."""
    from qts.research.costs import CostModel, decompose_costs

    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.10", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2009.90", "2010.00", "2026-01-05T12:00:00+00:00"),
        ]
    )
    records = to_trade_records(ledger)
    assert len(records) == 1
    # The record carries gross (100.0), not the already-costed 98.0.
    assert records[0].gross_pnl_usd == pytest.approx(100.0)
    assert records[0].nights_held == 0.0

    model = CostModel.xauusd_default(
        spread_price_units=0.30, slippage_price_units=0.10, swap_per_night_per_lot_usd=0.0
    )
    dec = decompose_costs(records, model)
    assert dec.gross_pnl_usd == pytest.approx(100.0)
    assert dec.cost_usd == pytest.approx(5.0)
    assert dec.net_pnl_usd == pytest.approx(95.0)


def test_ledger_totals_aggregate_round_turns():
    ledger = round_turns_from_fills(
        [
            _fill("BUY", "0.1", "2000.10", "2000.00", "2026-01-05T10:00:00+00:00"),
            _fill("SELL", "0.1", "2009.90", "2010.00", "2026-01-05T12:00:00+00:00"),
            # short: sold 0.10 below mid, bought back 0.10 above mid
            _fill("SELL", "0.1", "1999.90", "2000.00", "2026-01-06T10:00:00+00:00"),
            _fill("BUY", "0.1", "2000.10", "2000.00", "2026-01-06T12:00:00+00:00"),
        ]
    )
    assert ledger.trades == 2
    assert ledger.measured_cost_usd == pytest.approx(4.0)  # 2.00 per round turn
    assert ledger.gross_pnl_usd == pytest.approx(100.0)
    assert ledger.realized_pnl_usd == pytest.approx(96.0)


def test_open_lot_is_serialisable():
    lot = OpenLot(side="BUY", lots=0.1, price=2000.0, mid=2000.0, opened_at="2026-01-05T10:00:00+00:00")
    assert lot.as_dict()["side"] == "BUY"
