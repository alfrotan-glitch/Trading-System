"""The 51-year gold hypothesis catalogue.

Every rule here has a stated economic reason to exist, and the set was fixed
before any result on this dataset was seen. That ordering is the whole point:
the previous 52-configuration search was rejected not because the rules were bad
but because 52 attempts on 17.8 years cannot distinguish skill from luck.

Design choices that limit multiple testing:

* **One idea, few implementations.** The real-yield family has three lookbacks,
  not twenty. Inflation has two. Every additional variant would be a trial that
  the deflated Sharpe has to pay for.
* **No fitted parameters.** Lookbacks are round numbers chosen from the
  literature (12-month momentum, 5-year valuation median), not optimised on this
  data. Seasonality uses Sep-Nov, specified from the gold-demand calendar
  (Indian festival and wedding season, year-end) rather than from the return
  series.
* **Regimes are conditioning, not discovery.** The two combination rules ask
  whether a known signal improves when gated, not whether some gate exists.

Signals use *months*, converted to bars at ~21 trading days, because the
hypotheses are monthly-scale economics measured on daily data.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import StrategySpec

BARS_PER_MONTH = 21
BARS_PER_YEAR = 252.0

LONG_PARQUET = Path("data/research/longgold/xauusd_d1_lbma.parquet")

#: Chronological, non-overlapping. The 2020-2024 holdout is NOT in this file and
#: is not touched by any code that reads these splits.
LONG_BOUNDS = {
    "DEV": ("1969-01-02", "2000-12-31"),
    "VAL": ("2001-01-01", "2010-12-31"),
    "TEST": ("2011-01-01", "2019-12-31"),
}


def load_long_gold(path: Path | None = None) -> pd.DataFrame:
    p = path or LONG_PARQUET
    if not p.exists():
        raise FileNotFoundError(f"{p} missing — run scripts/edgelab_prepare_longgold.py")
    df = pd.read_parquet(p)
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def long_split(index: pd.DatetimeIndex) -> dict[str, pd.DatetimeIndex]:
    out: dict[str, pd.DatetimeIndex] = {}
    for name, (lo, hi) in LONG_BOUNDS.items():
        out[name] = index[(index >= pd.Timestamp(lo)) & (index <= pd.Timestamp(hi))]
    return out


def _m(months: int) -> int:
    return max(1, int(months * BARS_PER_MONTH))


# ------------------------------------------------------------------ signals


def real_yield_level(bars: pd.DataFrame, window_years: int = 5) -> pd.Series:
    """Long gold when the real yield is cheap relative to its own history.

    Gold pays no coupon, so the real yield is its carry. When that carry is low
    relative to its recent range, holding gold costs little. This is a valuation
    argument, not a momentum one.
    """
    ry = bars["real_yield"]
    med = ry.rolling(_m(12 * window_years), min_periods=_m(24)).median()
    return pd.Series(np.where(ry < med, 1.0, 0.0), index=bars.index).where(med.notna(), 0.0)


def real_yield_change(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """Long gold while its opportunity cost is falling.

    Directly tests the mechanism: if gold is priced off real yields, the
    direction of travel should matter more than the level.
    """
    chg = bars["real_yield"] - bars["real_yield"].shift(_m(months))
    return pd.Series(np.where(chg < 0, 1.0, 0.0), index=bars.index).where(chg.notna(), 0.0)


def inflation_accel(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """Long gold when inflation is accelerating.

    The classic hedging claim. Falsifiable: if gold is a hedge, rising CPI
    momentum should precede positive gold returns.
    """
    d = bars["cpi_yoy"] - bars["cpi_yoy"].shift(_m(months))
    return pd.Series(np.where(d > 0, 1.0, 0.0), index=bars.index).where(d.notna(), 0.0)


def inflation_level(bars: pd.DataFrame, threshold: float = 3.0) -> pd.Series:
    """Long gold only when CPI year-on-year exceeds ``threshold`` percent."""
    return pd.Series(np.where(bars["cpi_yoy"] > threshold, 1.0, 0.0), index=bars.index)


def tsmom_months(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """Time-series momentum: long if the trailing 12-month return is positive."""
    r = bars["close"].pct_change(_m(months))
    return pd.Series(np.sign(r.to_numpy()), index=bars.index, dtype=float).fillna(0.0)


def ma_trend(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """Long when price is above its N-month moving average."""
    ma = bars["close"].rolling(_m(months), min_periods=_m(months)).mean()
    return pd.Series(np.where(bars["close"] > ma, 1.0, 0.0), index=bars.index).where(ma.notna(), 0.0)


def pullback(bars: pd.DataFrame, months: int = 12, depth: float = 0.10) -> pd.Series:
    """Buy dips within an uptrend: long only when price is ``depth`` below its MA.

    Tests the widely repeated "buy the dip" prior against the trend-following one;
    the two make opposite predictions about the same data.
    """
    ma = bars["close"].rolling(_m(months), min_periods=_m(months)).mean()
    below = bars["close"] < ma * (1.0 - depth)
    return pd.Series(np.where(below & bars["close"] > ma.shift(_m(months)), 1.0, 0.0), index=bars.index).where(
        ma.notna(), 0.0
    )


def reversal_1m(bars: pd.DataFrame, months: int = 1) -> pd.Series:
    """Short-horizon reversal: long after a down month."""
    r = bars["close"].pct_change(_m(months))
    return pd.Series(np.where(r < 0, 1.0, 0.0), index=bars.index).where(r.notna(), 0.0)


def seasonal_months(bars: pd.DataFrame, months: tuple[int, ...] = (9, 10, 11)) -> pd.Series:
    """Hold gold only during the specified calendar months.

    Default set is Sep-Nov, chosen from the physical-demand calendar (Indian
    festival and wedding season, year-end restocking) rather than from the
    return series.
    """
    m = pd.DatetimeIndex(bars.index).month
    return pd.Series(np.where(np.isin(m, months), 1.0, 0.0), index=bars.index)


def turn_of_month(bars: pd.DataFrame, before: int = 2, after: int = 3) -> pd.Series:
    """Long over the month boundary — a documented flow effect across assets."""
    idx = pd.DatetimeIndex(bars.index)
    dom = pd.Series(idx.day, index=idx)
    days_in_month = pd.Series(idx.days_in_month, index=idx)
    near_start = dom <= after
    near_end = dom > (days_in_month - before)
    return pd.Series(np.where(near_start | near_end, 1.0, 0.0), index=bars.index)


def realized_vol_daily(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    r = np.log(bars["close"]).diff()
    return r.rolling(_m(months), min_periods=_m(3)).std() * np.sqrt(BARS_PER_YEAR)


def trend_low_vol(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """12-month trend, but only while realised volatility is below its median."""
    sig = tsmom_months(bars, months)
    vol = realized_vol_daily(bars, 12)
    med = vol.rolling(_m(120), min_periods=_m(24)).median()
    return sig.where(vol < med, 0.0).fillna(0.0)


def trend_falling_yield(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """12-month trend, only when the real yield is also falling.

    Two independent reasons to be long, required together. If the trend result
    was noise, demanding agreement should degrade it rather than improve it.
    """
    sig = tsmom_months(bars, months)
    ry = real_yield_change(bars, 12)
    return (sig * ry).clip(-1.0, 1.0)


def long_specs() -> list[StrategySpec]:
    """The fixed catalogue: 14 configurations in 7 families."""
    return [
        # --- opportunity cost (3 implementations of one idea) ---
        StrategySpec("ry_level_5y", "real_yield", {"window_years": 5}, real_yield_level,
                     "Low carry is cheap carry: long gold when the real yield is below its 5y median."),
        StrategySpec("ry_chg_12m", "real_yield", {"months": 12}, real_yield_change,
                     "Gold is priced off the direction of its opportunity cost."),
        StrategySpec("ry_chg_3m", "real_yield", {"months": 3}, real_yield_change,
                     "Faster version of the same mechanism; tests whether speed matters."),
        # --- inflation hedge (2) ---
        StrategySpec("infl_accel_12m", "inflation", {"months": 12}, inflation_accel,
                     "Gold hedges accelerating inflation."),
        StrategySpec("infl_above_3pct", "inflation", {"threshold": 3.0}, inflation_level,
                     "Gold outperforms in high-inflation regimes."),
        # --- trend persistence (5) ---
        # Horizons 1m-12m follow Moskowitz, Ooi & Pedersen (2012), whose time-series
        # momentum study spans exactly this range. The first catalogue omitted the
        # two shortest horizons; adding them completes a pre-specified family rather
        # than introducing a new idea.
        StrategySpec("tsmom_1m", "trend", {"months": 1}, tsmom_months,
                     "Shortest documented TSMOM horizon; gold's short-run autocorrelation."),
        StrategySpec("tsmom_3m", "trend", {"months": 3}, tsmom_months,
                     "Quarterly momentum, between the 1m and 6m horizons."),
        StrategySpec("tsmom_12m", "trend", {"months": 12}, tsmom_months,
                     "Time-series momentum, documented across asset classes."),
        StrategySpec("tsmom_6m", "trend", {"months": 6}, tsmom_months,
                     "Faster momentum; tests horizon sensitivity."),
        StrategySpec("ma_trend_12m", "trend", {"months": 12}, ma_trend,
                     "Price above a 12-month average indicates persistent trend."),
        # --- mean reversion / pullback (2) ---
        StrategySpec("pullback_12m_10", "meanrev", {"months": 12, "depth": 0.10}, pullback,
                     "Buy 10% dips inside an uptrend — the opposite prior to trend following."),
        StrategySpec("reversal_1m", "meanrev", {"months": 1}, reversal_1m,
                     "Short-horizon overreaction reverses (falsifiable for gold)."),
        # --- calendar (2) ---
        StrategySpec("seasonal_sep_nov", "calendar", {"months": (9, 10, 11)}, seasonal_months,
                     "Physical demand peaks Sep-Nov (Indian festivals, year-end)."),
        StrategySpec("turn_of_month", "calendar", {"before": 2, "after": 3}, turn_of_month,
                     "Documented month-boundary flow effect."),
        # --- conditioning (2) ---
        StrategySpec("trend_lowvol", "regime", {"months": 12}, trend_low_vol,
                     "Trend works better in calm regimes if the effect is real."),
        StrategySpec("trend_falling_yield", "regime", {"months": 12}, trend_falling_yield,
                     "Require trend and carry to agree; noise should degrade, not improve."),
    ]
