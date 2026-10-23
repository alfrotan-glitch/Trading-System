"""Tests for the corrected compressed-range broker assay."""

import numpy as np

from qts.research.xauusd_broker_compression import (
    CompressionBars,
    aggregate_complete_fifteen_minute,
    make_samples,
)
from qts.research.xauusd_broker_ml import BrokerBars


def test_aggregate_complete_fifteen_minute_requires_full_groups() -> None:
    n = 31
    times = np.arange(n, dtype=np.int64) * 60_000
    mid = np.full(n, 2_000.0)
    bars = BrokerBars(times, mid - 0.05, mid + 0.05, mid + 0.1, mid - 0.1, mid - 0.05, mid + 0.05, np.full(n, 0.1))
    result = aggregate_complete_fifteen_minute(bars)
    assert result.time_msc.tolist() == [0, 900_000]
    assert result.high_mid.tolist() == [2_000.1, 2_000.1]


def test_compression_breakout_uses_quiet_state_and_next_bar_entry() -> None:
    n = 330
    time = np.arange(n, dtype=np.int64) * 900_000
    mid = np.full(n, 2_000.0)
    high = np.full(n, 2_002.0)
    low = np.full(n, 1_998.0)
    high[256:288] = 2_000.5
    low[256:288] = 1_999.5
    mid[288] = 2_003.0
    high[288] = 2_003.0
    low[288] = 2_000.0
    bars = CompressionBars(time, mid - 0.05, mid + 0.05, high, low, mid - 0.05, mid + 0.05)
    samples = make_samples(bars, horizon=8)
    assert samples.signal_index.tolist() == [288]
    assert samples.exit_index.tolist() == [296]
    assert samples.direction.tolist() == [1]


def test_compression_breakout_does_not_signal_without_compression() -> None:
    n = 330
    time = np.arange(n, dtype=np.int64) * 900_000
    mid = np.full(n, 2_000.0)
    high = np.full(n, 2_002.0)
    low = np.full(n, 1_998.0)
    mid[288] = 2_003.0
    high[288] = 2_003.0
    low[288] = 2_000.0
    bars = CompressionBars(time, mid - 0.05, mid + 0.05, high, low, mid - 0.05, mid + 0.05)
    assert len(make_samples(bars, horizon=8).signal_index) == 0
