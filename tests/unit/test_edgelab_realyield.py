"""Rolling real-yield residual: the regression identity and the sign convention.

The load-bearing test is the first one: the rolling-sums implementation must give
exactly the coefficients a fresh OLS fit gives on the same window. If it does not,
every result from this family is computed on a different model than the one
described in the docstring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import realyield as R


def _series(n: int = 400, seed: int = 4):
    idx = pd.bdate_range("2010-01-01", periods=n, tz="UTC")
    rng = np.random.default_rng(seed)
    x = pd.Series(np.linspace(2.0, 0.5, n) + rng.normal(0, 0.1, n), index=idx)
    y = pd.Series(3.0 - 0.4 * x.to_numpy() + rng.normal(0, 0.05, n), index=idx)
    return y, x


def test_rolling_z_matches_a_fresh_ols_fit():
    y, x = _series()
    z = R.rolling_ols_z(y, x, window=60)
    t = 250
    yy = y.iloc[t - 59 : t + 1].to_numpy()
    xx = x.iloc[t - 59 : t + 1].to_numpy()
    X = np.column_stack([np.ones(len(xx)), xx])
    coef = np.linalg.lstsq(X, yy, rcond=None)[0]
    resid = yy - X @ coef
    expected = resid[-1] / np.std(resid, ddof=2)
    assert z.iloc[t] == pytest.approx(expected, rel=1e-8)


def test_rolling_z_is_nan_before_a_full_window():
    y, x = _series(200)
    z = R.rolling_ols_z(y, x, window=60)
    assert z.iloc[:59].isna().all()
    assert z.iloc[59:].notna().all()


def test_rolling_z_rejects_a_mismatched_index():
    y, x = _series(100)
    with pytest.raises(ValueError, match="share an index"):
        R.rolling_ols_z(y, x.iloc[:-1], window=30)


def test_signal_is_short_when_gold_is_rich():
    """A gold series rising far above its fitted value must produce a short."""
    idx = pd.bdate_range("2010-01-01", periods=400, tz="UTC")
    ry = pd.Series(np.linspace(2.0, 2.0, 400), index=idx)  # constant -> degenerate
    ry = pd.Series(np.linspace(2.0, 0.0, 400), index=idx)
    close = pd.Series(np.exp(np.linspace(7.0, 8.5, 400)), index=idx)  # gold rallies hard
    bars = pd.DataFrame({"close": close}, index=idx)
    sig = R.residual_signal(bars, ry, window=120)
    assert sig.iloc[-1] <= 0.0


def test_long_only_signal_never_goes_short():
    idx = pd.bdate_range("2010-01-01", periods=400, tz="UTC")
    ry = pd.Series(np.linspace(2.0, 0.0, 400), index=idx)
    bars = pd.DataFrame({"close": np.exp(np.linspace(7.0, 8.5, 400))}, index=idx)
    sig = R.residual_signal(bars, ry, window=120, long_only=True)
    assert (sig >= 0.0).all() and (sig <= 1.0).all()


def test_discrete_signal_takes_only_three_values():
    idx = pd.bdate_range("2010-01-01", periods=400, tz="UTC")
    rng = np.random.default_rng(2)
    ry = pd.Series(rng.normal(1.0, 0.3, 400), index=idx)
    bars = pd.DataFrame({"close": np.exp(np.cumsum(rng.normal(0, 0.01, 400)))}, index=idx)
    sig = R.residual_signal(bars, ry, window=100, discrete=True)
    assert set(np.unique(sig)) <= {-1.0, 0.0, 1.0}


def test_signal_aligns_naive_yield_index_to_utc_bars():
    idx = pd.bdate_range("2010-01-01", periods=400, tz="UTC")
    ry = pd.Series(np.linspace(2.0, 0.0, 400), index=idx.tz_localize(None))
    rng = np.random.default_rng(7)
    bars = pd.DataFrame({"close": np.exp(np.cumsum(rng.normal(0, 0.01, 400)))}, index=idx)
    sig = R.residual_signal(bars, ry, window=100)
    assert len(sig) == len(bars)
    assert sig.notna().all()
