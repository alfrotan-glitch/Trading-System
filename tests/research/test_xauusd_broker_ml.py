"""Tests for the fixed quote-only broker ML research engine."""

import numpy as np

from qts.research.xauusd_broker_ml import BrokerBars, build_features, make_samples


def _bars(n: int = 100) -> BrokerBars:
    time = np.arange(n, dtype=np.int64) * 60_000
    mid = 2_000.0 + np.arange(n, dtype=np.float64) * 0.1
    return BrokerBars(
        time_msc=time,
        open_bid=mid - 0.05,
        open_ask=mid + 0.05,
        high_mid=mid + 0.1,
        low_mid=mid - 0.1,
        close_bid=mid - 0.05,
        close_ask=mid + 0.05,
        mean_spread=np.full(n, 0.1),
    )


def test_features_are_unavailable_before_fixed_warmup() -> None:
    features, valid = build_features(_bars())
    assert features.shape == (100, 9)
    assert not valid[:60].any()
    assert valid[60:].all()


def test_samples_use_one_bar_latency_and_exact_horizon() -> None:
    samples = make_samples(_bars(), 5)
    assert samples.signal_index[0] >= 60
    assert np.all(samples.entry_index == samples.signal_index + 1)
    assert np.all(samples.exit_index == samples.signal_index + 5)
    assert np.all(samples.pnl_long > 0.0)


def test_samples_exclude_internal_minute_gaps() -> None:
    bars = _bars()
    bars.time_msc[75:] += 60_000
    samples = make_samples(bars, 5)
    assert not np.any((samples.signal_index <= 74) & (samples.exit_index >= 75))
