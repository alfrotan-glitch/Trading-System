"""Tests for the fixed opening-range broker assay."""

import numpy as np

from qts.research.xauusd_broker_ml import BrokerBars
from qts.research.xauusd_broker_opening_range import extract_events, make_samples


def _bars(mid: np.ndarray, *, start_minute: int = 0) -> BrokerBars:
    n = len(mid)
    times = (start_minute + np.arange(n, dtype=np.int64)) * 60_000
    return BrokerBars(
        time_msc=times,
        open_bid=mid - 0.05,
        open_ask=mid + 0.05,
        high_mid=mid,
        low_mid=mid,
        close_bid=mid - 0.05,
        close_ask=mid + 0.05,
        mean_spread=np.full(n, 0.1),
    )


def test_opening_range_breakout_and_fade_directions() -> None:
    start = 8 * 60
    mid = np.full(30 + 1 + 30, 2_000.0)
    mid[30] = 2_001.0
    bars = _bars(mid, start_minute=start)
    bars = BrokerBars(
        time_msc=bars.time_msc,
        open_bid=bars.open_bid,
        open_ask=bars.open_ask,
        high_mid=np.where(np.arange(len(mid)) == 30, 2_001.0, 2_000.0),
        low_mid=np.where(np.arange(len(mid)) == 30, 2_000.0, 2_000.0),
        close_bid=bars.close_bid,
        close_ask=bars.close_ask,
        mean_spread=bars.mean_spread,
    )
    events = extract_events(bars)
    assert events.signal_index.tolist() == [30]
    assert events.entry_index.tolist() == [31]
    assert events.exit_index.tolist() == [60]
    assert make_samples(bars, 1).direction.tolist() == [1]
    assert make_samples(bars, -1).direction.tolist() == [-1]


def test_opening_range_rejects_ambiguous_breakout() -> None:
    n = 30 + 1 + 30
    mid = np.full(n, 2_000.0)
    bars = _bars(mid, start_minute=13 * 60 + 30)
    bars = BrokerBars(
        time_msc=bars.time_msc,
        open_bid=bars.open_bid,
        open_ask=bars.open_ask,
        high_mid=np.where(np.arange(n) == 30, 2_001.0, 2_000.0),
        low_mid=np.where(np.arange(n) == 30, 1_999.0, 2_000.0),
        close_bid=bars.close_bid,
        close_ask=bars.close_ask,
        mean_spread=bars.mean_spread,
    )
    events = extract_events(bars)
    assert len(events.signal_index) == 0
    assert events.ambiguous_breakout_count == 1


def test_opening_range_requires_contiguous_bars() -> None:
    n = 30 + 1 + 30
    mid = np.full(n, 2_000.0)
    bars = _bars(mid, start_minute=8 * 60)
    times = bars.time_msc.copy()
    times[20:] += 60_000
    broken = BrokerBars(
        time_msc=times,
        open_bid=bars.open_bid,
        open_ask=bars.open_ask,
        high_mid=bars.high_mid,
        low_mid=bars.low_mid,
        close_bid=bars.close_bid,
        close_ask=bars.close_ask,
        mean_spread=bars.mean_spread,
    )
    events = extract_events(broken)
    assert len(events.signal_index) == 0
    assert events.incomplete_range_count >= 1
