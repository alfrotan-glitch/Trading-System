import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from qts.research.demo_trend_tsmom import TrendTimeSeriesMomentum


def _quote(t: datetime, price: str) -> dict:
    return {
        "symbol": "XAUUSD",
        "bid": Decimal(price),
        "ask": Decimal(price) + Decimal("0.10"),
        "spread_bps": 1.0,
        "age_s": 0.5,
        "event_time": t.isoformat(),
    }


def test_strategy_evaluates_only_completed_15m_bars():
    strategy = TrendTimeSeriesMomentum()
    raise AssertionError("PROBE_CODE_HASH=" + hashlib.sha256(Path("src/qts/research/demo_trend_tsmom.py").read_bytes()).hexdigest())
    t0 = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)

    assert strategy.generate(_quote(t0, "4000")) is None
    assert len(strategy._prices) == 0

    # More ticks inside the same bar must not advance EMA history.
    assert strategy.generate(_quote(t0 + timedelta(minutes=5), "4005")) is None
    assert strategy.generate(_quote(t0 + timedelta(minutes=14, seconds=59), "4010")) is None
    assert len(strategy._prices) == 0

    # The first tick of the next bar closes the previous bar exactly once.
    assert strategy.generate(_quote(t0 + timedelta(minutes=15), "4015")) is None
    assert len(strategy._prices) == 1

    # More ticks in the new bar do not create another completed bar.
    assert strategy.generate(_quote(t0 + timedelta(minutes=15, seconds=30), "4020")) is None
    assert len(strategy._prices) == 1


def test_strategy_signal_ids_are_bar_based_not_tick_based():
    strategy = TrendTimeSeriesMomentum(
        {
            **strategy_params(),
            "fast_ema": 2,
            "slow_ema": 3,
        }
    )
    t0 = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)

    # Seed four completed bars with an uptrend so the crossover can be observed.
    prices = ["4000", "3990", "4000", "4020", "4050"]
    for i, price in enumerate(prices):
        strategy.generate(_quote(t0 + timedelta(minutes=15 * i), price))

    # The signal, if produced, is tied to the completed-bar boundary.
    signal = strategy.generate(_quote(t0 + timedelta(minutes=15 * len(prices)), "4060"))
    if signal is not None:
        assert signal.signal_id.startswith("tsmom-")
        assert "T08:00:00+00:00" not in signal.signal_id
        assert signal.signal_id.endswith(":00+00:00")


def strategy_params() -> dict:
    return {
        "fast_ema": 12,
        "slow_ema": 48,
        "min_cross_gap_bps": 0.0,
        "stop_distance_price": 3.0,
        "max_hold_seconds": 14400,
        "max_tick_age_s": 5.0,
        "bar_timeframe_minutes": 15,
        "lots": 0.01,
        "require_spread_within_policy": True,
        "comment": "RESEARCH_DEMO_ORDER trend benchmark",
    }
