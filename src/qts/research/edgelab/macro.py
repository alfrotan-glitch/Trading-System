"""Macro conditioning for XAUUSD: real yields.

Price-derived signals on gold have now failed twice, independently (§20-22 of the
project control log and the Edge Lab run of 2026-10-20). The next honest question
is whether *different* information helps. The single most defensible prior for
gold is the real yield: gold pays no coupon, so its opportunity cost is the
inflation-adjusted Treasury yield, and the two are strongly negatively correlated
over long horizons.

The series is FRED ``DFII10`` — 10-Year Treasury Inflation-Indexed Security,
constant maturity, daily. It is US government data, redistributed by FRED, and is
used here only as a conditioning variable.

Timing rules, which matter more than the signal:

* FRED timestamps ``DFII10`` to the observation date, but the value is not
  published until after that day's close. A signal for the close of day ``t``
  therefore uses ``t-1``'s value. ``align_to_bars`` shifts by one business day and
  the code refuses to build a signal from a series it cannot prove is lagged.
* Gold and Treasury holiday calendars differ. Gaps are forward-filled, which is
  honest here: a missing yield on a US holiday carries no new information, whereas
  dropping the bar would silently shift the alignment.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DFII10_PARQUET = Path("data/research/macro/dfii10_daily.parquet")


def load_dfii10(path: Path | None = None) -> pd.Series:
    """Load the real-yield series as a naive-date-indexed float Series."""
    p = path or DFII10_PARQUET
    if not p.exists():
        raise FileNotFoundError(
            f"{p} missing — run scripts/edgelab_prepare_macro.py first"
        )
    df = pd.read_parquet(p)
    s = df.iloc[:, 0] if isinstance(df, pd.DataFrame) else df
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s.astype(float).sort_index()


def align_to_bars(bars: pd.DataFrame, series: pd.Series, lag_days: int = 1) -> pd.Series:
    """Align a daily macro series to bar timestamps, lagged to avoid look-ahead.

    ``lag_days`` is a *business*-day lag applied before reindexing, so the value
    attached to bar ``t`` was published strictly before ``t``.
    """
    if lag_days < 1:
        raise ValueError(
            "lag_days must be >= 1: a same-day real yield is not knowable at the close"
        )
    idx = pd.DatetimeIndex(bars.index)
    dates = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    dates = dates.normalize()
    shifted = series.copy()
    # Shift on the macro series' own business calendar, then forward-fill onto the
    # distinct calendar dates and map back per bar. Intraday bars repeat a date many
    # times, and reindexing onto a duplicated axis raises.
    shifted.index = shifted.index + pd.offsets.BDay(lag_days)
    unique_dates = pd.DatetimeIndex(dates.unique())
    aligned = shifted.reindex(shifted.index.union(unique_dates)).ffill().reindex(unique_dates)
    per_bar = aligned.to_numpy()[unique_dates.get_indexer(dates)]
    return pd.Series(per_bar, index=bars.index, dtype=float)


def real_yield_momentum(bars: pd.DataFrame, lookback_days: int = 60, allow_short: bool = True) -> pd.Series:
    """Long gold while the real yield is falling, short while it is rising.

    The economic claim is narrow and falsifiable: the *change* in the real yield
    carries information about gold's next move. If the sign is right today and
    wrong out of sample, the claim is false.
    """
    if "dfii10" not in bars.columns:
        raise ValueError("bars must carry a 'dfii10' column — run attach_macro() first")
    y = bars["dfii10"]
    change = y - y.shift(lookback_days)
    sig = pd.Series(-np.sign(change.to_numpy()), index=bars.index, dtype=float)
    if not allow_short:
        sig = sig.clip(lower=0.0)
    return sig.fillna(0.0)


def attach_macro(bars: pd.DataFrame, path: Path | None = None, lag_days: int = 1) -> pd.DataFrame:
    """Return a copy of ``bars`` carrying the lagged real yield."""
    out = bars.copy()
    out["dfii10"] = align_to_bars(bars, load_dfii10(path), lag_days=lag_days)
    return out
