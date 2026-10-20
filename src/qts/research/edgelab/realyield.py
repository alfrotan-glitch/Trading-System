"""Gold priced against the real yield: mispricing, not momentum.

Every macro rule tested so far — in rounds 3, 5, 6 and 8 — asks about the
**direction of travel** of a driver. This one asks a different question: given
where the real yield is *right now*, is gold expensive or cheap relative to its
own recent relationship with that yield?

The economics: gold is a zero-coupon real asset, so the 10-year TIPS yield is
its carrying cost. Over a window long enough to average out noise, ``log gold``
should be approximately linear in the real yield with a negative slope. When gold
trades above that fitted line it is expensive and should underperform; below it,
cheap. Trading the residual is a mean-reversion bet on a *relationship*, which is
a materially different information use from betting on a driver's direction.

Two honest caveats, stated before any result is read:

* **The relationship broke down after 2022.** Real yields rose sharply while gold
  also rose, which the 2003-2021 data would call impossible. A rolling regression
  adapts slowly and will spend that period on the wrong side. That is a real risk
  to this family, not a nuance.
* **Rolling OLS is a fitting procedure inside a backtest.** Because the window is
  fixed at 252 days and the signal formula is fixed before running, the
  in-sample fit at each date uses only past data — but the *choice* of window is
  a trial and is counted as one.

The regression is computed from rolling sums rather than by re-fitting 5,000
regressions, which gives identical coefficients at a fraction of the cost. The
identity is exercised by a test against ``numpy.linalg.lstsq``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_ols_z(y: pd.Series, x: pd.Series, window: int = 252) -> pd.Series:
    """Z-score of ``y`` against its rolling OLS fit on ``x``.

    Coefficients at date ``t`` use observations ``t-window+1 .. t``. The value is
    therefore knowable at ``t`` and, when used as a signal, is shifted by the
    backtest engine before it earns anything. Returns NaN until a full window is
    available and wherever the regression is degenerate.
    """
    if window < 3:
        raise ValueError("window must be at least 3")
    if not y.index.equals(x.index):
        raise ValueError("y and x must share an index")
    n = float(window)
    s_x = x.rolling(window, min_periods=window).sum()
    s_xx = (x * x).rolling(window, min_periods=window).sum()
    s_y = y.rolling(window, min_periods=window).sum()
    s_xy = (x * y).rolling(window, min_periods=window).sum()
    denom = n * s_xx - s_x * s_x
    # A constant regressor makes the slope unidentified; NaN rather than a guess.
    if (denom.abs() < 1e-12).any():
        denom = denom.where(denom.abs() >= 1e-12)
    slope = (n * s_xy - s_x * s_y) / denom
    intercept = (s_y - slope * s_x) / n
    resid = y - (intercept + slope * x)
    # Residual scale must come from *this window's* fit, not from the rolling
    # standard deviation of the residual series (whose earlier entries were
    # produced by different coefficients). Expanding the sum of squared residuals
    # in terms of the same rolling sums gives that exactly:
    #   SSR = Syy - 2a*Sy - 2b*Sxy + n*a^2 + 2ab*Sx + b^2*Sxx
    s_yy = (y * y).rolling(window, min_periods=window).sum()
    ssr = s_yy - 2.0 * intercept * s_y - 2.0 * slope * s_xy + n * intercept**2 + 2.0 * intercept * slope * s_x + slope**2 * s_xx
    sd = np.sqrt(ssr.clip(lower=0.0) / (n - 2.0))
    z = resid / sd.replace(0.0, np.nan)
    return z.rename("z")


def residual_signal(
    bars: pd.DataFrame,
    real_yield: pd.Series,
    window: int = 252,
    long_only: bool = False,
    discrete: bool = False,
) -> pd.Series:
    """Position in [-1, 1] from the real-yield residual.

    ``z > 0`` means gold is above its fitted value — rich — so the position is
    negative. ``long_only`` clips the short side to zero, which is the only form
    a spot-only product can trade; ``discrete`` trades the sign at full size
    instead of scaling continuously, and is included because continuous sizing
    quietly assumes you can trade any fraction of a position.
    """
    if "close" not in bars.columns:
        raise ValueError("bars must carry 'close'")
    idx = pd.DatetimeIndex(bars.index)
    ry = real_yield.copy()
    ry.index = pd.DatetimeIndex(ry.index)
    if ry.index.tz is None:
        ry.index = ry.index.tz_localize("UTC")
    ry = ry.sort_index()
    ry = ry[~ry.index.duplicated(keep="first")]
    aligned = ry.reindex(ry.index.union(idx)).ffill().reindex(idx)
    logp = np.log(bars["close"].astype(float))
    logp_s = pd.Series(np.asarray(logp, dtype=float), index=idx)
    aligned_s = pd.Series(np.asarray(aligned, dtype=float), index=idx)
    z = rolling_ols_z(logp_s, aligned_s, window)
    raw: pd.Series = pd.Series(-z.to_numpy(), index=idx, dtype=float)
    if discrete:
        raw = pd.Series(np.sign(raw.to_numpy()), index=idx, dtype=float)
    # A spot-only product can be long or flat, never short, so the long-only
    # variant clips instead of inverting — and it must clip the top too, or a
    # |z| > 1 would request leverage the product cannot take.
    raw = raw.clip(0.0, 1.0) if long_only else raw.clip(-1.0, 1.0)
    return raw.fillna(0.0)
