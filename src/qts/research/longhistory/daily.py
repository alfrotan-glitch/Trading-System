"""Trading-day aggregation for UTC 15-minute bars.

Convention (fixed, pre-registered in
``docs/research/preregistration_longhistory_2026-10-10.md``):

* A trading day rolls at 22:00 UTC, the usual CFD rollover. A bar stamped
  22:00 UTC therefore opens the next trading day. Concretely the day label is
  ``(utc + 2h).normalize()``.
* Daily open = first bar open of the day, high/low = extremes, close = last
  bar close, volume = summed volume.
* A day with fewer than ``min_bars`` 15-minute bars is PARTIAL. It is kept in
  the coverage accounting but excluded from strategy evaluation, so a
  half-session can never generate a signal or a fill.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from qts.research.longhistory.sources import OHLC_COLUMNS

SESSION_ROLL_HOURS = 2  # (utc + 2h).normalize() == trading day rolling at 22:00 UTC
DEFAULT_MIN_BARS = 40  # ~10 hours of 15-minute bars


@dataclass(frozen=True)
class DailyCoverage:
    days_total: int
    days_complete: int
    days_partial: int
    partial_share: float
    median_bars_per_day: float


def trading_day_label(utc_index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    shifted = pd.DatetimeIndex(utc_index) + pd.Timedelta(hours=SESSION_ROLL_HOURS)
    return pd.DatetimeIndex(shifted.normalize(), name="day")


def to_daily(bars_utc: pd.DataFrame, min_bars: int = DEFAULT_MIN_BARS) -> tuple[pd.DataFrame, DailyCoverage]:
    """Aggregate 15-minute UTC bars to trading-day bars.

    Returns the complete-day frame (``open, high, low, close, volume, n_bars``)
    and a coverage summary that counts partial days.
    """
    if bars_utc.empty:
        raise ValueError("no bars to aggregate")
    labels = trading_day_label(pd.DatetimeIndex(bars_utc.index))
    grouped = bars_utc.groupby(labels, sort=True)
    daily = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    daily["n_bars"] = grouped.size()
    complete = daily[daily["n_bars"] >= min_bars].copy()
    partial = int((daily["n_bars"] < min_bars).sum())
    coverage = DailyCoverage(
        days_total=int(len(daily)),
        days_complete=int(len(complete)),
        days_partial=partial,
        partial_share=float(partial / len(daily)) if len(daily) else 0.0,
        median_bars_per_day=float(daily["n_bars"].median()),
    )
    return complete[OHLC_COLUMNS + ["n_bars"]], coverage


def restrict(daily: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """Inclusive calendar restriction on the day index."""
    out = daily
    if start is not None:
        out = out.loc[pd.Timestamp(start) :]
    if end is not None:
        out = out.loc[: pd.Timestamp(end)]
    return out
