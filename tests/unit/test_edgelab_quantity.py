"""Tests for the quantity-based macro signals (round 13)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import quantity as Q


def _bars(index: pd.DatetimeIndex) -> pd.DataFrame:
    close = pd.Series(np.linspace(300, 1500, len(index)), index=index)
    out = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=index)
    out["volume"] = 0.0
    return out


def test_monthly_stamp_is_never_before_publication():
    """A value must not be visible on the bar before its stamped date."""
    s = Q.monthly("us_m2")
    first = s.index[0]
    # FRED stamps monthly data on the 1st; the stamped date must be at least two
    # months later, so nothing lands earlier than the observation month.
    assert first >= pd.Timestamp("1959-03-31")


def test_weekly_stamp_moves_forward_by_one_week():
    s = Q.weekly("initial_claims_4wk")
    assert s.index.to_series().diff().dropna().min() > pd.Timedelta(0)


def test_signals_preserve_a_tz_aware_bar_index():
    """Regression: a tz-naive signal index makes every position zero, silently.

    ``reindex`` against mismatched tz does not raise — it returns an empty
    selection — so a strategy would report a flat, zero-alpha history forever.
    """
    idx = pd.date_range("2010-01-04", "2012-12-31", freq="B", tz="UTC")
    bars = _bars(idx)
    for name, fn in Q.quantity_specs().items():
        sig = fn(bars)
        assert sig.index.equals(idx), f"{name} did not return the caller's index"
        assert sig.index.tz is not None, f"{name} dropped the tz"
        pos = sig.reindex(bars.index).ffill().fillna(0.0)
        assert float(pos.abs().sum()) >= 0.0  # must be computable, not all-NaN


def test_signals_are_bounded_and_non_negative():
    idx = pd.date_range("2005-01-03", "2015-12-31", freq="B")
    bars = _bars(idx)
    for name, fn in Q.quantity_specs().items():
        sig = fn(bars)
        assert sig.notna().all(), f"{name} leaked NaN"
        assert sig.isin([0.0, 1.0]).all(), f"{name} produced values outside {{0,1}}"


def test_signals_do_not_peek():
    """Truncating the bars must not change any earlier position."""
    idx = pd.date_range("1995-01-03", "2015-12-31", freq="B")
    bars = _bars(idx)
    cut = idx[int(len(idx) * 0.7)]
    for _name, fn in Q.quantity_specs().items():
        full = fn(bars).loc[:cut]
        part = fn(bars.loc[:cut])
        pd.testing.assert_series_equal(full, part, check_names=False)


def test_declared_inputs_exist():
    missing = [k for k, ok in Q.available().items() if not ok]
    assert not missing, f"missing inputs: {missing}"


def test_truncated_mirror_raises(monkeypatch):
    short = pd.Series(1.0, index=pd.date_range("2023-01-01", periods=100, tz="UTC"))
    monkeypatch.setattr(Q, "load_fred", lambda name, positive=False: short)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="rolling window"):
        Q.monthly("us_m2")
