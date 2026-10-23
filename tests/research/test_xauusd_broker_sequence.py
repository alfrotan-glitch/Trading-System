"""Tests for the fixed three-bar sequence broker assay."""

import numpy as np

from qts.research.xauusd_broker_regime import RegimeBars
from qts.research.xauusd_broker_sequence import make_samples


def test_sequence_direction_mapping_and_horizon() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    steps = np.ones(n, dtype=np.float64)
    mid = 2_000.0 + np.cumsum(steps)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    continuation = make_samples(bars, 1)
    fade = make_samples(bars, -1)
    assert continuation.signal_index.min() >= 3
    assert np.all(continuation.exit_index == continuation.signal_index + 3)
    assert np.all(continuation.direction == 1)
    assert np.all(fade.direction == -1)


def test_sequence_requires_contiguous_history() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    time[40:] += 300_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, 1)
    assert not np.any((samples.signal_index <= 40) & (samples.exit_index >= 40))
