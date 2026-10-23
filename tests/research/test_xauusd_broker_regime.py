"""Tests for the fixed volatility-regime broker assay."""

import numpy as np

from qts.research.xauusd_broker_regime import RegimeBars, aggregate_complete_five_minute, make_samples


def _minute_bars(n: int = 15):
    time = np.arange(n, dtype=np.int64) * 60_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64)
    return type(
        "MinuteBars",
        (),
        {
            "time_msc": time,
            "open_bid": mid - 0.05,
            "open_ask": mid + 0.05,
            "close_bid": mid - 0.05,
            "close_ask": mid + 0.05,
        },
    )()


def test_aggregation_discards_incomplete_groups() -> None:
    bars = _minute_bars()
    result = aggregate_complete_five_minute(bars)
    assert len(result.time_msc) == 3


def test_samples_require_fixed_warmup_and_quote_sides() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    steps = np.full(n, 0.1, dtype=np.float64)
    steps[49:61] = 2.0
    mid = 2_000.0 + np.cumsum(steps)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars)
    assert samples.signal_index.min() >= 60
    assert np.all(samples.exit_index == samples.signal_index + 3)
