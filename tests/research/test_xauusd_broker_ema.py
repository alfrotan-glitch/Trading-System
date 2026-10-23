"""Tests for fixed EMA trend-state research."""

import numpy as np

from qts.research.xauusd_broker_ema import make_samples
from qts.research.xauusd_broker_regime import RegimeBars


def test_ema_trend_state_uses_causal_slow_warmup() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64) * 0.01
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, horizon=6)
    assert samples.signal_index.min() == 47
    assert samples.direction[0] == 1
    assert samples.exit_index[0] == 53


def test_ema_has_no_signal_when_prices_are_constant() -> None:
    n = 80
    time = np.arange(n, dtype=np.int64) * 300_000
    mid = np.full(n, 2_000.0)
    bars = RegimeBars(time, mid - 0.05, mid + 0.05, mid - 0.05, mid + 0.05)
    assert len(make_samples(bars, horizon=6).signal_index) == 0
