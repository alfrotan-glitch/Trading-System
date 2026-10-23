"""Tests for fixed Bollinger mean-reversion research."""

import numpy as np

from qts.research.xauusd_broker_bollinger import make_samples
from qts.research.xauusd_broker_regime import RegimeBars


def test_bollinger_extreme_is_faded_with_next_bar_entry() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64) * 0.01
    mid[48] = 1_980.0
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, horizon=6)
    assert samples.signal_index.min() == 48
    assert samples.direction[0] == 1
    assert samples.exit_index[0] == 54


def test_bollinger_has_no_signal_when_prior_scale_is_zero() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = np.full(n, 2_000.0)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    assert len(make_samples(bars, horizon=6).signal_index) == 0
