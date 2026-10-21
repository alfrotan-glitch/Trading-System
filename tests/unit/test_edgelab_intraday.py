"""Session-clock signals and the HAC alpha they are judged with.

The load-bearing tests here are the ones that would have caught a real defect:

* the breakout state machine must not look ahead — moving a price in the future
  may not change a position taken in the past;
* ``hac_alpha`` must recover a known intercept and must refuse to report one
  against a constant benchmark.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import hac_alpha
from qts.research.edgelab import intraday as I


def synthetic_bars(days: int = 40, seed: int = 7) -> pd.DataFrame:
    """M15 bars on a realistic clock: 22:00-20:45 with the 21:00 halt missing."""
    idx = []
    for d in pd.date_range("2024-01-01", periods=days, freq="1D", tz="UTC"):
        for hour in list(range(0, 21)) + [22, 23]:
            for minute in (0, 15, 30, 45):
                idx.append(d + pd.Timedelta(hours=hour, minutes=minute))
    index = pd.DatetimeIndex(sorted(idx))
    rng = np.random.default_rng(seed)
    # A random walk keeps prices varying, which several statistics depend on.
    close = 2000.0 * np.exp(np.cumsum(rng.normal(0, 0.001, len(index))))
    return pd.DataFrame(
        {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1.0},
        index=index,
    )


def test_hour_mask_wraps_midnight():
    idx = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
    mask = I.hour_mask(idx, 22, 6)
    assert bool(mask.loc[idx[23]]) is True  # 23:00 inside
    assert bool(mask.loc[idx[0]]) is True  # 00:00 inside
    assert bool(mask.loc[idx[5]]) is True  # 05:00 inside
    assert bool(mask.loc[idx[6]]) is False  # 06:00 excluded
    assert bool(mask.loc[idx[12]]) is False  # midday outside


def test_hour_mask_rejects_empty_window():
    idx = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    with pytest.raises(ValueError):
        I.hour_mask(idx, 7, 7)


def test_hold_window_is_flat_outside_and_never_short():
    bars = synthetic_bars()
    pos = I.hold_window(bars, 22, 6)
    inside = I.hour_mask(bars.index, 22, 6)
    assert set(np.unique(pos)) <= {0.0, 1.0}
    assert np.array_equal(pos.to_numpy(dtype=float), inside.to_numpy(dtype=float))


def test_breakout_does_not_look_ahead():
    """Changing a future bar must not change a position already taken."""
    bars = synthetic_bars(days=20)
    pos = I.opening_range_breakout(bars, range_start=22, range_end=7, trade_end=20, buffer_bps=0.0)
    cut = len(bars) // 2
    mutated = bars.copy()
    mutated.iloc[cut + 5 :, mutated.columns.get_loc("close")] *= 1.05
    pos2 = I.opening_range_breakout(mutated, range_start=22, range_end=7, trade_end=20, buffer_bps=0.0)
    # Positions decided strictly before the first mutated bar are identical.
    assert pos.iloc[: cut + 5].equals(pos2.iloc[: cut + 5])


def test_breakout_only_trades_after_the_range_forms():
    bars = synthetic_bars(days=20)
    pos = I.opening_range_breakout(bars, range_start=22, range_end=7, trade_end=20)
    assert (pos[I.hour_mask(bars.index, 22, 7).to_numpy()] == 0.0).all()


def test_overnight_reversal_uses_only_prior_days_move():
    bars = synthetic_bars(days=30)
    pos = I.overnight_reversal(bars, start=22, end=6, day_start=12, day_end=20)
    day = I.hour_mask(bars.index, 12, 20)
    # Every non-zero reversal position sits inside the day session and is a sign.
    assert set(np.unique(pos[day.to_numpy()])) <= {-1.0, 0.0, 1.0}
    assert (pos[~day.to_numpy()] == 0.0).all()



def test_overnight_momentum_never_reads_tonights_future_prices():
    """A mutation after 22:00 cannot change a decision made at 19:00."""
    bars = synthetic_bars(days=8)
    base = I.overnight_momentum_close(bars)
    day = pd.Timestamp("2024-01-05", tz="UTC")
    before_evening = (bars.index >= day) & (bars.index < day + pd.Timedelta(hours=22))
    later = (bars.index >= day + pd.Timedelta(hours=22)) & (
        bars.index < day + pd.Timedelta(days=1)
    )
    changed = bars.copy()
    changed.loc[later, "close"] *= 1.6
    after = I.overnight_momentum_close(changed)
    assert base.loc[before_evening].equals(after.loc[before_evening])


def test_overnight_reversal_and_momentum_use_last_completed_session():
    """22:00 on Monday belongs to Tuesday's completed morning session."""
    idx = pd.to_datetime(
        [
            "2024-01-01T22:00:00Z",
            "2024-01-02T05:45:00Z",
            "2024-01-02T12:00:00Z",
            "2024-01-02T19:00:00Z",
            "2024-01-02T22:00:00Z",
            "2024-01-02T23:45:00Z",
        ],
        utc=True,
    )
    bars = pd.DataFrame({"close": [100.0, 105.0, 105.0, 105.0, 70.0, 70.0]}, index=idx)
    momentum = I.overnight_momentum_close(bars)
    reversal = I.overnight_reversal(bars)
    assert momentum.loc[pd.Timestamp("2024-01-02T19:00:00Z")] == 1.0
    assert reversal.loc[pd.Timestamp("2024-01-02T12:00:00Z")] == -1.0


def test_incomplete_overnight_session_is_not_a_signal():
    idx = pd.to_datetime(
        ["2024-01-02T04:00:00Z", "2024-01-02T05:45:00Z", "2024-01-02T19:00:00Z"],
        utc=True,
    )
    bars = pd.DataFrame({"close": [100.0, 105.0, 105.0]}, index=idx)
    assert I.overnight_momentum_close(bars).iloc[-1] == 0.0


def test_breakout_range_preserves_previous_evening_across_midnight():
    """The Asian range contains BOTH the evening and next morning bars."""
    idx = pd.to_datetime(
        [
            "2024-01-01T22:00:00Z",
            "2024-01-01T23:45:00Z",
            "2024-01-02T00:00:00Z",
            "2024-01-02T06:45:00Z",
            "2024-01-02T07:00:00Z",
        ],
        utc=True,
    )
    bars = pd.DataFrame({"close": [110.0, 110.0, 100.0, 100.0, 105.0]}, index=idx)
    positions = I.opening_range_breakout(bars)
    assert positions.iloc[-1] == 0.0  # 105 is still INSIDE the true 100..110 range



def test_window_return_per_day_matches_compounding_within_completed_night():
    bars = synthetic_bars(days=10)
    idx = bars.index
    session_end = pd.Timestamp("2024-01-04", tz="UTC")
    inside = I.hour_mask(idx, 22, 6).to_numpy()
    previous_inside = np.concatenate(([False], inside[:-1]))
    seconds = idx.to_series().diff().dt.total_seconds().to_numpy()
    completed_session = (idx >= session_end - pd.Timedelta(hours=2)) & (
        idx < session_end + pd.Timedelta(hours=6)
    )
    earned = inside & previous_inside & (seconds <= 900.0) & completed_session
    expected = (1 + bars["close"].pct_change().to_numpy()[earned]).prod() - 1
    result = I.window_return_per_day(bars, 22, 6)
    assert result.loc[session_end] == pytest.approx(expected)


def test_window_return_per_day_excludes_reopening_gap_and_groups_across_midnight():
    idx = pd.to_datetime(
        [
            "2024-01-01T20:45:00Z",
            "2024-01-01T22:00:00Z",
            "2024-01-01T22:15:00Z",
            "2024-01-01T22:30:00Z",
            "2024-01-01T22:45:00Z",
            "2024-01-02T00:00:00Z",
            "2024-01-02T00:15:00Z",
        ],
        utc=True,
    )
    bars = pd.DataFrame({"close": [100.0, 120.0, 121.0, 122.0, 123.0, 125.0, 126.0]}, index=idx)
    result = I.window_return_per_day(bars, 22, 6)
    # Price 100 -> 120 was the reopening gap and 123 -> 125 is an
    # unobserved 75-minute interval. Neither is a fillable window return.
    expected = (123.0 / 120.0) * (126.0 / 125.0) - 1.0
    assert result.loc[pd.Timestamp("2024-01-02", tz="UTC")] == pytest.approx(expected)



def test_hac_alpha_recovers_a_known_intercept():
    rng = np.random.default_rng(11)
    n = 2500
    bench = pd.Series(rng.normal(0, 0.01, n))
    truth = 0.0003
    strat = truth + 0.5 * bench + pd.Series(rng.normal(0, 0.004, n))
    out = hac_alpha(strat, bench, 252, lags=5)
    assert out["alpha_per_bar"] == pytest.approx(truth, abs=2e-4)
    assert out["beta"] == pytest.approx(0.5, abs=0.05)
    assert out["n_obs"] == n


def test_hac_alpha_refuses_a_constant_benchmark():
    strat = pd.Series(np.random.default_rng(3).normal(0, 0.01, 400))
    bench = pd.Series(np.zeros(400))
    with pytest.raises(ValueError, match="zero variance"):
        hac_alpha(strat, bench, 252)


def test_hac_alpha_requires_enough_observations():
    with pytest.raises(ValueError, match="at least"):
        hac_alpha(pd.Series([0.01, 0.02, 0.0]), pd.Series([0.01, -0.01, 0.02]), 252, lags=5)
