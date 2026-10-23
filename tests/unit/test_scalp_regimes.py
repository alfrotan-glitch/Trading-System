"""Causal regime scalp entry and registration-neutral provider checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.research.demo_scalp_provider import RegimeScalpProvider
from qts.research.scalp_regimes import propose_scalp_entry


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
            "timestamp_basis": "MEASURED",
        }
    assert provider.generate(market(49)) is None  # forming bar
    first_result = provider.generate(market(50))  # prior minute now confirmed
    assert first_result is not None
    assert first_result.side == "BUY"
    assert first_result.stop_loss < tick
    assert "Unvalidated" in first_result.rationale
    assert provider.generate(market(50)) is None  # no duplicate signal
