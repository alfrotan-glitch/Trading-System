"""Pure, deterministic tests of quote-executable, cost-reserved scalp exits."""

from decimal import Decimal

import pytest

from qts.execution.scalp_exit import ScalpExitPlan, decide_scalp_exit


def plan(**changes: str) -> ScalpExitPlan:
    config = {
        "take_profit_net_bps": "5",
        "extra_cost_reserve_bps": "2",
        "max_loss_net_bps": "12",
        "max_spread_bps": "3",
        "max_tick_age_s": "3",
    }
    config.update(changes)
    return ScalpExitPlan.from_mapping(config)


def test_long_exits_only_after_executable_profit_covers_cost_reserve():
    hold = decide_scalp_exit(
        plan(), side="BUY", entry_price="2000", bid="2001", ask="2001.2", tick_age_s="1"
    )
    assert not hold.close
    result = decide_scalp_exit(
        plan(), side="BUY", entry_price="2000", bid="2001.6", ask="2001.8", tick_age_s="1"
    )
    assert result.close and result.reason == "scalp_take_profit"
    assert result.estimated_net_bps == Decimal("6")


def test_short_exits_at_ask_not_bid():
    hold = decide_scalp_exit(
        plan(), side="SELL", entry_price="2000", bid="1998.6", ask="1999.2", tick_age_s="1"
    )
    assert not hold.close
    result = decide_scalp_exit(
        plan(), side="SELL", entry_price="2000", bid="1998.4", ask="1998.6", tick_age_s="1"
    )
    assert result.close and result.reason == "scalp_take_profit"
    assert result.estimated_net_bps == Decimal("5")


def test_soft_loss_exit_can_fire_with_wide_spread():
    result = decide_scalp_exit(
        plan(), side="BUY", entry_price="2000", bid="1996.5", ask="1997.5", tick_age_s="0"
    )
    assert result.close and result.reason == "scalp_max_loss"


def test_wide_spread_blocks_discretionary_profit_exit():
    result = decide_scalp_exit(
        plan(), side="BUY", entry_price="2000", bid="2002", ask="2003", tick_age_s="1"
    )
    assert not result.close and result.reason == "scalp_spread_too_wide"


@pytest.mark.parametrize(
    "age,bid,ask",
    [("5", "2000", "2000.2"), ("0", "NaN", "2000.2"), ("0", "2000.2", "2000.1")],
)
def test_stale_invalid_and_crossed_quotes_refused(age, bid, ask):
    with pytest.raises(ValueError):
        decide_scalp_exit(
            plan(), side="BUY", entry_price="2000", bid=bid, ask=ask, tick_age_s=age
        )


@pytest.mark.parametrize(
    "name,invalid",
    [
        ("take_profit_net_bps", "0"),
        ("extra_cost_reserve_bps", "NaN"),
        ("max_loss_net_bps", "-1"),
        ("max_tick_age_s", "Inf"),
    ],
)
def test_invalid_frozen_thresholds_rejected(name, invalid):
    with pytest.raises(ValueError):
        plan(**{name: invalid})
