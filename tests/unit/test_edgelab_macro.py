"""Macro alignment must be lagged, or every result built on it is fiction.

A real yield is published after the close of its observation date. Attaching the
same date's value to that date's bar would let a signal trade on a number that did
not exist yet — the single easiest way to manufacture a spectacular backtest.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qts.research.edgelab.macro import align_to_bars, real_yield_momentum


def _bars(n: int = 10, start: str = "2020-01-06") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n, tz="UTC")
    return pd.DataFrame({"close": 100.0, "open": 100.0, "high": 100.0, "low": 100.0}, index=idx)


def test_zero_lag_is_refused():
    """Same-day macro data is not knowable at the close; refuse to pretend it is."""
    bars = _bars()
    series = pd.Series(1.0, index=pd.bdate_range("2020-01-01", periods=20))
    with pytest.raises(ValueError, match="lag_days"):
        align_to_bars(bars, series, lag_days=0)


def test_alignment_uses_the_previous_business_day():
    """A jump on date D must not appear on D's own bar."""
    bars = _bars(n=6, start="2020-01-06")  # Mon 6th .. Mon 13th
    idx = pd.bdate_range("2020-01-01", periods=12)
    series = pd.Series(0.0, index=idx)
    jump_day = pd.Timestamp("2020-01-08")
    series.loc[jump_day:] = 1.0

    aligned = align_to_bars(bars, series, lag_days=1)
    on_jump_day = aligned.loc[pd.Timestamp("2020-01-08", tz="UTC")]
    after = aligned.loc[pd.Timestamp("2020-01-09", tz="UTC")]
    assert on_jump_day == 0.0, "the jump leaked into its own bar — look-ahead"
    assert after == 1.0, "the lag is too long: the value never arrives"


def test_intraday_bars_repeated_dates_align():
    """Many bars share a calendar date; the lookup must not reindex a duplicated axis."""
    idx = pd.date_range("2020-01-06", periods=96, freq="15min", tz="UTC")
    bars = pd.DataFrame({"close": 100.0}, index=idx)
    series = pd.Series(1.5, index=pd.bdate_range("2020-01-01", periods=10))
    aligned = align_to_bars(bars, series, lag_days=1)
    assert len(aligned) == len(bars)
    assert aligned.notna().all()
    assert (aligned == 1.5).all()


def test_real_yield_momentum_requires_macro_columns():
    with pytest.raises(ValueError, match="dfii10"):
        real_yield_momentum(_bars())


def test_real_yield_momentum_goes_long_when_yields_fall():
    """Direction check: falling real yields mean long gold, and vice versa."""
    bars = _bars(n=8)
    y = pd.Series([2.0, 1.9, 1.8, 1.7, 1.9, 2.0, 2.1, 2.2], index=bars.index)
    bars = bars.assign(dfii10=y)
    sig = real_yield_momentum(bars, lookback_days=2, allow_short=True)
    assert sig.iloc[3] == 1.0, "yield fell over the window, so the position should be long"
    assert sig.iloc[-1] == -1.0, "yield rose over the window, so the position should be short"


def test_long_only_never_shorts():
    bars = _bars(n=8)
    y = pd.Series([2.0, 1.9, 1.8, 1.7, 1.9, 2.0, 2.1, 2.2], index=bars.index)
    bars = bars.assign(dfii10=y)
    sig = real_yield_momentum(bars, lookback_days=2, allow_short=False)
    assert (sig >= 0).all()
    assert sig.max() == 1.0
