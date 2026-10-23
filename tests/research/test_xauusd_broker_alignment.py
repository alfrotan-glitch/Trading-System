"""Tests for fixed multi-timeframe return-sign alignment."""

import numpy as np

from qts.research.xauusd_broker_alignment import make_samples
from qts.research.xauusd_broker_regime import RegimeBars


def test_alignment_requires_all_fixed_horizons_and_next_bar_entry() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, horizon=3)
    assert samples.signal_index.min() == 48
    assert np.all(samples.direction == 1)
    assert np.all(samples.exit_index == samples.signal_index + 3)


def test_alignment_rejects_mixed_horizon_signs() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64)
    mid[65:] = mid[64] - np.arange(1, n - 64, dtype=np.float64) * 50.0
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, horizon=3)
    late = samples.signal_index >= 65
    assert np.any(late)
    assert np.all(samples.direction[late] == -1)
