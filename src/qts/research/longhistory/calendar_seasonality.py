"""Fixed annual gold-demand calendar signal for the frozen 2026-10 screen."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import Plan

ACTIVE_MONTHS = (1, 2, 3, 8, 9)


def calendar_seasonal_plan(base_sizer: Plan, index: pd.DatetimeIndex) -> Plan:
    """Long in the frozen seasonal months of the *next* monthly bar.

    The source plan contributes only its inherited 12-month volatility size,
    protective-stop array and monthly rebalance schedule. The target uses a
    fixed calendar mask and contains no price-return or future feature values.
    """
    if not isinstance(index, pd.DatetimeIndex) or index.hasnans or index.has_duplicates:
        raise ValueError("calendar-seasonality index must be a clean DatetimeIndex")
    if not index.is_monotonic_increasing:
        raise ValueError("calendar-seasonality index must be increasing")

    size = np.asarray(base_sizer.size, dtype=float).copy()
    if size.shape != (len(index),):
        raise ValueError("volatility-size array must match the calendar index")
    target = np.zeros(len(index), dtype=float)
    if len(index) > 1:
        next_months = index[1:].month
        target[:-1] = np.isin(next_months, ACTIVE_MONTHS).astype(float)

    valid_size = np.isfinite(size)
    target[~valid_size] = np.nan
    size[~valid_size] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(base_sizer.stop_dist, dtype=float).copy(),
        rebalance=np.asarray(base_sizer.rebalance, dtype=bool).copy(),
        family="fixed_calendar_seasonality_long_only",
        params={
            "active_calendar_months": ",".join(str(month) for month in ACTIVE_MONTHS),
            "target_timing": "calendar month of next monthly bar",
            "sizing": "inherited 12-month realized volatility target from ts9_lo",
            "long_only": True,
        },
    )
