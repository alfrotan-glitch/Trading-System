"""Frozen monthly signal families for the long-history XAUUSD monthly cycle.

Every builder expects the monthly research frame::

    columns: open, high, low, close, usd
    index  : month-end timestamps (UTC), one row per calendar month

Contract (identical to :mod:`qts.research.longhistory.signals`):

* every value at bar ``t`` depends only on bars ``<= t`` (and on the USD
  index, which is itself computed from Federal Reserve daily quotes whose
  last observation of month ``t`` is known at month ``t`` end);
* a :class:`~qts.research.longhistory.signals.Plan` written at close ``t``
  executes at the open of bar ``t+1``. On this series the month's single
  observation is its monthly average price, so an execution at the next
  bar's open is the preregistered uniform-across-the-month (TWAP) fill at
  that average — no price is ever invented;
* ``target`` is a position STATE (+1 long, -1 short, 0 flat) or NaN for "no
  change"; NaN is forced whenever the vol-target size is not yet defined so
  the engine can never close a position it cannot re-enter.

Families (frozen in ``docs/research/preregistration_longhistory_monthly_*.md``):

``gold_tsmom``     trailing gold-return sign, monthly vol-targeted rebalance.
``usd_veto``       gold-trend longs always; gold-trend shorts only while the
                   equal-weight USD index rose over the prior ``usd_lb``
                   months (debasement veto).
``usd_agreement``  long only when gold trend and dollar-weakening agree,
                   short only when gold trend down and dollar-strengthening
                   agree, otherwise flat.
``bollinger``      CONTROL (fades two-sigma band excursions; falsification
                   benchmark only).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import (
    MAX_FRACTION,
    VOL_TARGET,
    Plan,
    _plan,
    bollinger,
    realized_vol,
)

MONTHS_PER_YEAR = 12
VOL_MONTHS = 12
REQUIRED_COLUMNS = ("open", "high", "low", "close", "usd")


def _validate_frame(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"monthly frame missing columns: {', '.join(missing)}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans or df.index.has_duplicates:
        raise ValueError("monthly frame must have a clean DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError("monthly frame index must be increasing")
    prices = df[list(REQUIRED_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0.0).any():
        raise ValueError("monthly frame columns must be finite and positive")


def monthly_vol_size(
    df: pd.DataFrame,
    vol_n: int = VOL_MONTHS,
    ann: int = MONTHS_PER_YEAR,
    target_vol: float = VOL_TARGET,
) -> pd.Series:
    """Annualised volatility-target fraction, capped at no-leverage (1.0)."""
    vol = realized_vol(df["close"], vol_n, ann)
    return (target_vol / vol.replace(0.0, np.nan)).clip(upper=MAX_FRACTION)


def _mask_target_by_size(target: np.ndarray, size: pd.Series) -> np.ndarray:
    """No finite target where the size is undefined (no forced flat churn)."""
    sz = size.to_numpy(dtype=float)
    out = np.asarray(target, dtype=float).copy()
    out[~np.isfinite(sz)] = np.nan
    return out


def gold_tsmom(
    df: pd.DataFrame,
    lookback: int,
    vol_n: int = VOL_MONTHS,
    ann: int = MONTHS_PER_YEAR,
) -> Plan:
    """Trailing gold-return sign with monthly vol-targeted rebalance."""
    _validate_frame(df)
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    close = df["close"]
    trailing = close / close.shift(lookback) - 1.0
    target = _mask_target_by_size(np.sign(trailing.to_numpy()), monthly_vol_size(df, vol_n, ann))
    size = monthly_vol_size(df, vol_n, ann)
    rebalance = np.ones(len(df), dtype=bool)
    return _plan(
        df,
        "gold_tsmom",
        {"lookback": lookback, "vol_n": vol_n, "ann": ann},
        target,
        size,
        np.full(len(df), np.nan),
        rebalance,
    )


def usd_veto_tsmom(
    df: pd.DataFrame,
    gold_lb: int,
    usd_lb: int,
    vol_n: int = VOL_MONTHS,
    ann: int = MONTHS_PER_YEAR,
) -> Plan:
    """Gold trend, with shorts vetoed unless the USD index rose over ``usd_lb`` months.

    Longs follow the gold trend unconditionally (gold's long-run ascent means a
    gold-trend long needs no external confirmation). Gold-trend shorts execute
    only while the dollar also strengthened over the same macro horizon; a
    gold downtrend inside a weakening dollar (a debasement backdrop) goes flat
    instead of short.
    """
    _validate_frame(df)
    if gold_lb < 1 or usd_lb < 1:
        raise ValueError("lookbacks must be >= 1")
    gold_trend = np.sign((df["close"] / df["close"].shift(gold_lb) - 1.0).to_numpy())
    usd_strengthening = (df["usd"] / df["usd"].shift(usd_lb) - 1.0).to_numpy() > 0.0
    target = np.where(
        gold_trend > 0,
        1.0,
        np.where(gold_trend < 0, np.where(usd_strengthening, -1.0, 0.0), 0.0),
    )
    size = monthly_vol_size(df, vol_n, ann)
    target = _mask_target_by_size(target, size)
    rebalance = np.ones(len(df), dtype=bool)
    return _plan(
        df,
        "usd_veto",
        {"gold_lb": gold_lb, "usd_lb": usd_lb, "vol_n": vol_n, "ann": ann},
        target,
        size,
        np.full(len(df), np.nan),
        rebalance,
    )


def usd_agreement(
    df: pd.DataFrame,
    gold_lb: int,
    usd_lb: int,
    vol_n: int = VOL_MONTHS,
    ann: int = MONTHS_PER_YEAR,
) -> Plan:
    """Dual-signal agreement: trade only when gold trend and dollar agree.

    Gold-trend sign combined with the sign of dollar-weakening (negative USD
    index return). Opposing signs flatten (no position); either sign at zero
    flattens.
    """
    _validate_frame(df)
    if gold_lb < 1 or usd_lb < 1:
        raise ValueError("lookbacks must be >= 1")
    gold_sign = np.sign((df["close"] / df["close"].shift(gold_lb) - 1.0).to_numpy())
    usd_weakening_sign = -np.sign((df["usd"] / df["usd"].shift(usd_lb) - 1.0).to_numpy())
    combined = gold_sign + usd_weakening_sign
    target = np.sign(combined)
    target[(gold_sign * usd_weakening_sign) < 0.0] = 0.0
    size = monthly_vol_size(df, vol_n, ann)
    target = _mask_target_by_size(target, size)
    rebalance = np.ones(len(df), dtype=bool)
    return _plan(
        df,
        "usd_agreement",
        {"gold_lb": gold_lb, "usd_lb": usd_lb, "vol_n": vol_n, "ann": ann},
        target,
        size,
        np.full(len(df), np.nan),
        rebalance,
    )


def control_bollinger(
    df: pd.DataFrame,
    n: int = 20,
    k: float = 2.0,
    vol_n: int = VOL_MONTHS,
    ann: int = MONTHS_PER_YEAR,
) -> Plan:
    """CONTROL: monthly two-sigma mean-reversion state (falsification only)."""
    _validate_frame(df)
    plan = bollinger(df, n=n, k=k, ann=ann, vol_n=vol_n)
    # Mask the control's target wherever its own size is undefined.
    target = _mask_target_by_size(plan.target, pd.Series(plan.size, index=df.index))
    return _plan(
        df,
        plan.family,
        dict(plan.params),
        target,
        plan.size,
        plan.stop_dist,
        plan.rebalance,
    )
