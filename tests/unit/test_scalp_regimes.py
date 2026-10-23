"""Causal regime scalp entry and registration-neutral provider checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.research.demo_scalp_provider import AnticipatoryScalpProvider, RegimeScalpProvider
from qts.research.scalp_regimes import (
    early_entry_still_has_room,
    propose_anticipatory_entry,
    propose_scalp_entry,
)


def test_uptrend_pullback_and_downtrend_pullback_proposals():
    up = [Decimal("2000") + Decimal("0.25") * i for i in range(32)]
    up += [Decimal("2007.0"), Decimal("2006.6"), Decimal("2006.9")]
    down = [Decimal("2010") - Decimal("0.25") * i for i in range(32)]
    down += [Decimal("2002.8"), Decimal("2003.3"), Decimal("2003.0")]
    long = propose_scalp_entry(up)
    short = propose_scalp_entry(down)
    assert long is not None and (long.side, long.regime, long.family) == (
        "BUY", "UP", "trend_pullback"
    )
    assert short is not None and (short.side, short.regime, short.family) == (
        "SELL", "DOWN", "trend_pullback"
    )


def test_range_fades_in_both_directions_and_avoids_flat():
    oscillation = [Decimal("2000") + Decimal("0.5") * (i % 4) for i in range(31)]
    low = [Decimal("2000"), *oscillation, Decimal("2000"), Decimal("2000.20")]
    high = [Decimal("2000"), *oscillation, Decimal("2001.5"), Decimal("2001.30")]
    buy, sell = propose_scalp_entry(low), propose_scalp_entry(high)
    assert buy is not None and (buy.side, buy.family) == ("BUY", "range_fade")
    assert sell is not None and (sell.side, sell.family) == ("SELL", "range_fade")
    assert propose_scalp_entry([Decimal("2000")] * 40) is None


def test_scalp_provider_fails_closed_on_gapped_history():
    provider = RegimeScalpProvider()
    t = datetime(2026, 10, 22, tzinfo=UTC)
    bars = [(t, Decimal("2000")), (t + timedelta(minutes=2), Decimal("2001"))]
    assert provider.seed_completed_bars(bars)["accepted"] is False


def test_scalp_provider_only_consumes_completed_bars_and_checks_costs():
    provider = RegimeScalpProvider()
    first = datetime(2026, 10, 22, tzinfo=UTC)
    prices = [Decimal("2000") + Decimal("1.5") * i for i in range(49)]
    prices[-2] = prices[-3] - Decimal("1.5")
    prices[-1] = prices[-2] - Decimal("1.5")
    seeded = provider.seed_completed_bars([
        (first + timedelta(minutes=i), price) for i, price in enumerate(prices)
    ], source="unit completed minute bars")
    assert seeded["accepted"] is True
    tick = prices[-1] + Decimal("2.0")
    def market(minute: int):
        return {
            "bid": str(tick - Decimal("0.1")),
            "ask": str(tick + Decimal("0.1")),
            "age_s": 0,
            "spread_bps": 1,
            "event_time": (first + timedelta(minutes=minute, seconds=1)).isoformat(),
            "timestamp_basis": "measured-fresh-tick",
        }
    assert provider.generate(market(49)) is None  # forming bar
    first_result = provider.generate(market(50))  # prior minute now confirmed
    assert first_result is not None
    assert first_result.side == "BUY"
    assert first_result.stop_loss < tick
    assert "Unvalidated" in first_result.rationale
    assert provider.generate(market(50)) is None  # no duplicate signal


def test_anticipatory_setup_exists_before_confirmed_breakout():
    # A synthetic pre-breakout squeeze: the last bar has NOT crossed the
    # preceding channel high, but shows directional pressure near it.
    prices = [Decimal(2002 + (3 if i % 2 else -3)) for i in range(25)]
    prices += [Decimal(v) for v in (
        "2003.6", "2003.65", "2003.62", "2003.66", "2003.60",
        "2003.63", "2003.64", "2003.66", "2003.72",
    )]
    assert len(prices) == 34
    assert prices[-1] < max(prices[-21:-1])
    early = propose_anticipatory_entry(prices)
    assert early is not None
    assert (early.side, early.family, early.regime) == (
        "BUY", "pre_breakout", "COMPRESSION"
    )
    assert propose_scalp_entry(prices) is None
    # Changing unseen future bars cannot affect the prefix decision.
    extended = prices + [Decimal("2040"), Decimal("1980")]
    assert propose_anticipatory_entry(extended[:34]) == early

    down = [Decimal("4000") - price for price in prices]
    short = propose_anticipatory_entry(down)
    assert short is not None and short.side == "SELL"


def test_anticipatory_refuses_chase_and_flat_or_bad_price():
    prices = [Decimal(2002 + (3 if i % 2 else -3)) for i in range(25)]
    prices += [Decimal(v) for v in (
        "2003.6", "2003.65", "2003.62", "2003.66", "2003.60",
        "2003.63", "2003.64", "2003.66", "2005.9",
    )]
    assert propose_anticipatory_entry(prices) is None  # beyond old high
    assert propose_anticipatory_entry([Decimal("2000")] * 40) is None
    assert propose_anticipatory_entry([Decimal("NaN")] * 40) is None
    assert propose_anticipatory_entry(prices[:33]) is None


def test_anticipant_provider_has_distinct_strategy_identity():
    early = AnticipatoryScalpProvider()
    ordinary = RegimeScalpProvider()
    assert early.strategy_id != ordinary.strategy_id
    assert early.requires_registered_scalp_exit is True


def test_early_entry_does_not_chase_a_confirmed_breakout_at_execution_time():
    prices = [Decimal(2002 + (3 if i % 2 else -3)) for i in range(25)]
    prices += [Decimal(v) for v in (
        "2003.6", "2003.65", "2003.62", "2003.66", "2003.60",
        "2003.63", "2003.64", "2003.66", "2003.72",
    )]
    idea = propose_anticipatory_entry(prices)
    assert idea is not None and idea.boundary_price == Decimal("2005")
    assert early_entry_still_has_room(
        idea, bid=Decimal("2003.9"), ask=Decimal("2004.1"),
        reserve_bps=Decimal("2"), margin_bps=Decimal("1"),
    )
    assert not early_entry_still_has_room(
        idea, bid=Decimal("2005.1"), ask=Decimal("2005.3"),
        reserve_bps=Decimal("2"), margin_bps=Decimal("1"),
    )
