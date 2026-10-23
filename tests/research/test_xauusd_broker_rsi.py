"""Tests for fixed RSI(2) oscillator research."""

import numpy as np

from qts.research.xauusd_broker_regime import RegimeBars
from qts.research.xauusd_broker_rsi import make_samples


def test_rsi_extreme_is_faded_with_next_bar_entry() -> None:
    n = 40
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64) * 0.01
    mid[0:3] = [2_000.0, 1_999.0, 1_998.0]
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, horizon=6)
    assert samples.signal_index.min() == 2
    assert samples.direction[0] == 1
    assert samples.exit_index[0] == 8


def test_rsi_has_no_signal_when_prior_changes_are_zero() -> None:
    n = 40
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = np.full(n, 2_000.0)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    assert len(make_samples(bars, horizon=6).signal_index) == 0
