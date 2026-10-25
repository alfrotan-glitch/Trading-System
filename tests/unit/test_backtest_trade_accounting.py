"""Economic trade counts and profit factor MUST come from completed trades.

A fill is not a trade; entering, partially exiting, or flipping a position
does not magically create several independent historical wins.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from qts.backtest.trade_accounting import summarize_completed_trades


def fill(side, qty, price, fee=0, symbol="XAUUSD", contract=100):
    return {
        "side": side,
        "qty": str(qty),
        "price": str(price),
        "fee": str(fee),
        "symbol": symbol,
        "contract_size": str(contract),
    }


def test_empty_data_cannot_manufacture_a_trade_or_pf():
    x = summarize_completed_trades([])
    assert x.fill_count == 0
    assert x.completed_net_usd == ()
    assert x.profit_factor == 0
    assert x.incomplete_position_count == 0


def test_entry_fill_alone_is_not_a_completed_trade():
    x = summarize_completed_trades([fill("BUY", ".1", "2000", "0.2")])
    assert x.fill_count == 1
    assert x.completed_net_usd == ()
    assert x.incomplete_position_count == 1
    assert x.open_entry_fees_usd == Decimal("0.2")


def test_two_fills_create_one_net_trade_not_two_wins():
    x = summarize_completed_trades([
        fill("BUY", "1", "2000", 1),
        fill("SELL", "1", "2002", 2),
    ])
    assert x.fill_count == 2
    assert x.completed_net_usd == (Decimal("197"),)
    assert x.incomplete_position_count == 0
    assert x.profit_factor == float("inf")


def test_long_partial_exit_is_one_completed_position_when_flat():
    x = summarize_completed_trades([
        fill("BUY", "1", "100", 1),
        fill("SELL", ".4", "110", ".4"),
        fill("SELL", ".6", "90", ".6"),
    ])
    # +400 - 600 - opening fee 1 - closing fees 1 = -202.
    assert x.fill_count == 3
    assert x.completed_net_usd == (Decimal("-202"),)
    assert x.incomplete_position_count == 0


def test_incomplete_partial_position_cannot_claim_a_winning_trade():
    x = summarize_completed_trades([
        fill("BUY", "1", "100", 1),
        fill("SELL", ".4", "110", ".4"),
    ])
    assert x.completed_net_usd == ()
    assert x.incomplete_position_count == 1
    assert x.realized_partial_close_pnl_usd == Decimal("399.2")
    assert x.open_entry_fees_usd == Decimal(".6")


def test_weighted_average_cost_of_adds_is_used():
    x = summarize_completed_trades([
        fill("BUY", "1", "100", 1),
        fill("BUY", "1", "110", 1),
        fill("SELL", "2", "120", 2),
    ])
    # 2 lots at 105 avg -> 2 * 100 * 15 = 3000; fees = 4
    assert x.completed_net_usd == (Decimal("2996"),)


def test_short_round_trip_is_symmetric():
    x = summarize_completed_trades([
        fill("SELL", ".2", "2100", ".2"),
        fill("BUY", ".2", "2090", ".3"),
    ])
    assert x.completed_net_usd == (Decimal("199.5"),)


def test_flip_splits_fee_and_books_two_round_trips():
    x = summarize_completed_trades([
        fill("BUY", "1", "100", 1),
        fill("SELL", "2", "110", 2),
        fill("BUY", "1", "100", 1),
    ])
    assert x.fill_count == 3
    assert x.completed_net_usd == (Decimal("998"), Decimal("998"))
    assert x.incomplete_position_count == 0


def test_profit_factor_uses_completed_position_usd_not_bar_returns():
    x = summarize_completed_trades([
        fill("BUY", "1", "100"),
        fill("SELL", "1", "101"),  # +100
        fill("BUY", "1", "100"),
        fill("SELL", "1", "98"),  # -200
        fill("BUY", "1", "100"),
        fill("SELL", "1", "103"),  # +300
    ])
    assert len(x.completed_net_usd) == 3
    assert x.profit_factor == pytest.approx(2.0)


def test_multiple_instruments_do_not_share_cost_basis():
    x = summarize_completed_trades([
        fill("BUY", "1", "100", symbol="XAUUSD"),
        fill("BUY", "1", "200", symbol="OTHER", contract=1),
        fill("SELL", "1", "101", symbol="XAUUSD"),
    ])
    assert x.completed_net_usd == (Decimal("100"),)
    assert x.incomplete_position_count == 1


@pytest.mark.parametrize("field,bad", [
    ("side", "WAIT"),
    ("qty", "0"),
    ("qty", "-1"),
    ("price", "nan"),
    ("fee", "-1"),
    ("contract_size", "0"),
    ("symbol", ""),
])
def test_invalid_fills_fail_closed(field, bad):
    x = fill("BUY", "1", "100")
    x[field] = bad
    with pytest.raises(ValueError):
        summarize_completed_trades([x])


def test_mid_position_contract_change_rejected():
    with pytest.raises(ValueError, match="contract size changed"):
        summarize_completed_trades([
            fill("BUY", 1, 100, contract=100),
            fill("SELL", 1, 101, contract=10),
        ])
