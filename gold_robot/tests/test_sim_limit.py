import pytest

from gold_robot.research.sim_limit import LimitPlan, Tick, replay


def buy(**kwargs):
    return LimitPlan(1, 3000, 2998, 3002, 10, 100, **kwargs)


def sell(**kwargs):
    return LimitPlan(-1, 3000, 3002, 2998, 10, 100, **kwargs)


def test_buy_touch_uses_ask_not_bid():
    result = replay(buy(), [Tick(20, 2999, 3000.4), Tick(30, 2999, 3000.1)])
    assert result.outcome == "pending_unfilled"


def test_buy_target_executable_bid_and_fees():
    result = replay(buy(), [Tick(20, 2999.7, 3000), Tick(30, 3001.95, 3002.15), Tick(40, 3002, 3002.2)])
    assert result.outcome == "target"
    assert result.net_usd == pytest.approx(1.9)


def test_stop_gap_uses_worse_quote_and_slippage():
    result = replay(buy(), [Tick(20, 2999.8, 3000), Tick(30, 2996, 2996.2)])
    assert result.outcome == "stop"
    assert result.net_usd == pytest.approx(-4.2)


def test_sell_uses_bid_to_fill_and_ask_to_exit():
    result = replay(sell(), [Tick(20, 3000.2, 3000.4), Tick(30, 2997.8, 2998.2), Tick(40, 2997.7, 2998)])
    assert result.outcome == "target"


def test_expiry_exact_timestamp_does_not_fill():
    assert replay(buy(), [Tick(100, 2999.8, 3000)]).outcome == "pending_unfilled"


def test_decision_tick_never_fills():
    assert replay(buy(), [Tick(10, 2999, 2999.5)]).outcome == "pending_unfilled"


def test_unsorted_and_crossed_quote_rejected():
    with pytest.raises(ValueError):
        replay(buy(), [Tick(20, 2999.8, 3000), Tick(20, 2999.9, 3000.1)])
    with pytest.raises(ValueError):
        replay(buy(), [Tick(20, 3000, 2999.9)])


def test_open_at_end_not_counted_as_profit():
    x = replay(buy(), [Tick(20, 2999.8, 3000)])
    assert x.outcome == "open_at_end" and x.net_usd == 0


def test_timeout_at_executable_quote():
    x = replay(buy(max_hold_ms=10), [Tick(20, 2999.8, 3000), Tick(30, 3000.2, 3000.4)])
    assert x.outcome == "timeout" and x.net_usd == pytest.approx(0.1)
