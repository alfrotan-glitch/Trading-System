"""Market-regime classification for the allocation layer.

Why this module exists
----------------------
The programme has 21 researched signals and no way to say *when* any of them should
be allowed to trade. This module answers that with a small, causal, pre-registered
classifier: trend versus range, and normal versus stressed volatility. It is
deliberately not fitted — the thresholds are round numbers fixed before any
evaluation, because a regime engine tuned on the same returns it later filters is
just another way to overfit.

Everything here is causal
-------------------------
Every quantity at bar ``t`` uses only bars up to and including ``t``. The vol
percentile uses a *trailing* window rank, never a full-sample quantile. (The older
``qts.regime.detector.VolatilityRegimeDetector`` computes its threshold from the
whole sample, which is look-ahead; it is fixed in the same change.)

The no-trade state
------------------
``allow_trade`` is False in the top percentile of volatility — conditions where a
retail spread widens, stops slip, and the measured cost model stops being
conservative. That is a risk statement, not an alpha statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd


class MarketRegime(StrEnum):
    """Coarse, tradable states. Deliberately few — more states, more overfitting."""

    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RegimeConfig:
    """Thresholds fixed a priori; see the module docstring."""

    trend_window: int = 63
    trend_quantile: float = 0.70
    vol_window: int = 21
    vol_rank_window: int = 504
    high_vol_quantile: float = 0.80
    no_trade_quantile: float = 0.95

    def __post_init__(self) -> None:
        if self.trend_window < 5 or self.vol_window < 2:
            raise ValueError("windows too short to be meaningful")
        if not 0.5 < self.high_vol_quantile < self.no_trade_quantile <= 1.0:
            raise ValueError("quantiles must satisfy 0.5 < high < no_trade <= 1")
        if not 0.5 <= self.trend_quantile <= 0.95:
            raise ValueError("trend_quantile must be in [0.5, 0.95]")


def realized_vol(close: pd.Series, window: int) -> pd.Series:
    """Annualised trailing volatility of daily close-to-close returns."""
    r = close.astype(float).pct_change()
    return (r.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(252.0)).rename("realized_vol")


def efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    """Kaufman efficiency ratio: net move over the sum of absolute moves.

    1.0 is a straight line, 0.0 is pure noise. This is a *directionless* measure of
    trend strength, so it does not double-count the direction that
    :func:`classify` reads separately from the price change.
    """
    c = close.astype(float)
    net = (c - c.shift(window)).abs()
    path = c.diff().abs().rolling(window, min_periods=window).sum()
    er = (net / path.replace(0.0, np.nan)).clip(0.0, 1.0)
    return er.rename("efficiency_ratio")


def trailing_percentile(s: pd.Series, window: int) -> pd.Series:
    """Percentile rank of the current value within its own trailing window.

    This is the causal replacement for ``np.quantile(s, q)`` over the full sample.
    Uses ``raw=True`` so a 500-day window over 13k bars stays fast.
    """

    def _last_rank(arr: np.ndarray) -> float:
        cur = arr[-1]
        if not np.isfinite(cur):
            return np.nan
        valid = arr[np.isfinite(arr)]
        if valid.size < 2:
            return np.nan
        return float((valid < cur).sum() + 0.5 * (valid == cur).sum()) / float(valid.size)

    return s.rolling(window, min_periods=max(20, window // 5)).apply(_last_rank, raw=True).rename("percentile")


def classify(bars: pd.DataFrame, config: RegimeConfig | None = None) -> pd.DataFrame:
    """Label every bar with a regime and a trade-permission flag.

    Returns a frame indexed like ``bars`` with ``regime``, ``efficiency_ratio``,
    ``realized_vol``, ``vol_percentile`` and ``allow_trade``.
    """
    cfg = config or RegimeConfig()
    close = bars["close"].astype(float)
    er = efficiency_ratio(close, cfg.trend_window)
    vol = realized_vol(close, cfg.vol_window)
    vol_pct = trailing_percentile(vol, cfg.vol_rank_window)
    drift = close.pct_change(cfg.trend_window)

    # Self-calibrating, causal trend threshold. A fixed efficiency ratio (an
    # earlier version used 0.30) does not transfer across assets or decades: on gold
    # it labelled only 2.5% of bars as trending, which would have made every trend
    # rule permanently ineligible — a broken policy dressed up as a conservative
    # one. Ranking the efficiency ratio inside its own trailing window gives a
    # stable ~30% share without ever consulting future returns.
    er_pct = trailing_percentile(er, cfg.vol_rank_window)
    trending = (er_pct >= cfg.trend_quantile) & drift.notna()
    regime = np.where(
        vol_pct >= cfg.high_vol_quantile,
        MarketRegime.HIGH_VOL.value,
        np.where(trending & (drift > 0), MarketRegime.TREND_UP.value, np.where(trending, MarketRegime.TREND_DOWN.value, MarketRegime.RANGE.value)),
    )
    out = pd.DataFrame(
        {
            "regime": regime,
            "efficiency_ratio": er,
            "trend_percentile": er_pct,
            "realized_vol": vol,
            "vol_percentile": vol_pct,
            "allow_trade": (vol_pct < cfg.no_trade_quantile) & vol_pct.notna(),
        },
        index=bars.index,
    )
    out.loc[vol_pct.isna() | er.isna(), "regime"] = MarketRegime.UNKNOWN.value
    out.loc[out["regime"] == MarketRegime.UNKNOWN.value, "allow_trade"] = False
    return out


def regime_summary(regimes: pd.DataFrame) -> pd.DataFrame:
    """Share of bars and the realised vol in each state — for reporting, not fitting."""
    g = regimes.groupby("regime", observed=True)
    return pd.DataFrame(
        {
            "bars": g.size(),
            "share": g.size() / len(regimes),
            "mean_vol": g["realized_vol"].mean(),
            "tradable_share": g["allow_trade"].mean(),
        }
    ).sort_values("share", ascending=False)
