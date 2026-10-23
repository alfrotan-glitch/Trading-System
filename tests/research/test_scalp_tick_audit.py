"""First observable stop-touch quote audit: chronology, sides and safety."""

from decimal import Decimal

import numpy as np
import pytest

from qts.research.scalp_tick_audit import TickStopAuditor


def trade(*, start=0, end=0, side="BUY", stop="1998"):
    return {
        "entry_time_msc": start, "exit_time_msc": end, "side": side,
        "stop_price": stop, "entry_price": "2000", "net_bps": "-30",
        "net_bps_if_stop_at_trigger": "-12", "exit_reason": "intrabar_stop_touch_uncertain",
    }


def auditor(trades):
    return TickStopAuditor(
        trades, exit_slippage_bps=Decimal("0.5"),
        round_trip_commission_bps=Decimal("1"),
    )


def test_first_long_stop_crossing_is_raw_bid_not_minimum_bar_bid():
    a = auditor([trade()])
    a.consume(np.array([100, 200]), np.array([2000, 1999]), np.array([2000.2, 1999.2]))
    a.consume(np.array([300, 350, 61000]), np.array([1997, 1996, 1998]),
              np.array([1997.2, 1996.2, 1998.2]))
    data = a.report()
    assert data["stops_with_observed_first_touch"] == 1
    assert data["mean_first_touch_quote_net_bps_on_matched_stops"] < -12
    assert data["orders_submitted"] == 0 and data["LIVE"] == "LOCKED"


def test_short_uses_executable_ask():
    a = auditor([trade(side="SELL", stop="2002")])
    a.consume(np.array([50, 70]), np.array([2000, 2001]), np.array([2000.5, 2002.2]))
    assert a.report()["stops_with_observed_first_touch"] == 1


def test_reject_crossed_quotes_and_reordered_parts():
    a = auditor([trade()])
    a.consume(np.array([100, 200]), np.array([2000, 2000]), np.array([2000.2, 2000.2]))
    with pytest.raises(ValueError, match="order changed"):
        a.consume(np.array([199]), np.array([1999]), np.array([1999.2]))
    with pytest.raises(ValueError, match="bid/ask"):
        auditor([]).consume(np.array([1]), np.array([2001]), np.array([2000]))


def test_missing_quote_does_not_create_a_stop_fill():
    a = auditor([trade()])
    a.consume(np.array([100, 200, 60200]), np.array([2000, 2000, 2000]),
              np.array([2000.2, 2000.2, 2000.2]))
    assert a.report()["missing_stop_touches"] == 1
    assert a.report()["mean_first_touch_quote_net_bps_on_matched_stops"] is None


def test_refuse_overlapping_stop_windows():
    with pytest.raises(ValueError, match="overlapping"):
        auditor([trade(start=0, end=60000), trade(start=60000, end=120000)])


def test_ignore_non_stop_trades():
    t = trade()
    t["exit_reason"] = "scalp_take_profit"
    assert auditor([t]).report()["stop_trades_in_bar_replay"] == 0
