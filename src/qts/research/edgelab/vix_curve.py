"""Causal Cboe equity-option volatility curve as a NEW gold research input.

This is a hypothesis engine, not a validated edge. Cboe index closes arrive
in the US afternoon; signal publication is conservatively delayed by one
additional Cboe observation before a gold daily-close order is considered.
Every generated decision is long-or-flat, with fixed trading cadence and
no post-hoc tuning of direction/parameters.

The two directional hypotheses are deliberately both recorded as trials.
A curve signal must beat exposure-matched gold holding after broker costs;
a positive absolute return on a gold bull market does not establish edge.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd


def read_cboe_history(content: str, *, name: str) -> pd.Series:
    """Parse Cboe historical CSV; reject duplicates, zeros and missing closes."""
    lines = content.lstrip("\ufeff").splitlines()
    header = next(
        (i for i, line in enumerate(lines) if line.strip().upper().startswith("DATE,")),
        None,
    )
    if header is None:
        raise ValueError(f"{name}: missing DATE header in Cboe CSV")
    frame = pd.read_csv(io.StringIO("\n".join(lines[header:])))
    frame.columns = [str(x).strip().upper() for x in frame.columns]
    if "DATE" not in frame or "CLOSE" not in frame:
        raise ValueError(f"{name}: expected DATE and CLOSE columns")
    idx = pd.to_datetime(frame["DATE"], errors="coerce", format="mixed", utc=True)
    values = pd.to_numeric(frame["CLOSE"], errors="coerce")
    if bool(idx.isna().any()) or bool(values.isna().any()):
        raise ValueError(f"{name}: invalid dates or closing values")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(idx), name=name)
    if bool(series.index.duplicated().any()) or bool((series <= 0).any()):
        raise ValueError(f"{name}: duplicate dates or nonpositive closing values")
    return series.sort_index()


def curve_frame(vix: pd.Series, vix3m: pd.Series) -> pd.DataFrame:
    """Create only dates where BOTH official indices published a value."""
    a = vix.rename("VIX")
    b = vix3m.rename("VIX3M")
    joined = pd.concat([a, b], axis=1, join="inner").dropna().sort_index()
    if joined.empty or bool((joined <= 0).any().any()):
        raise ValueError("no valid paired VIX and VIX3M observations")
    if bool(joined.index.duplicated().any()):
        raise ValueError("duplicate VIX curve timestamp")
    return joined


def fixed_cadence_signal(
    curve: pd.DataFrame,
    *,
    direction: str,
    smooth_days: int = 20,
    rebalance_days: int = 21,
) -> pd.Series:
    """A priori monthly decisions on a trailing equity-volatility curve.

    'contango' holds gold when VIX3M > VIX; 'backwardation' when VIX3M < VIX.
    Both are separate, predeclared hypotheses. No future curve values are used.
    One EXTRA published Cboe observation is delayed after the decision, as a
    conservative barrier against using a close before it was disseminated.
    """
    if direction not in ("contango", "backwardation"):
        raise ValueError("direction must be contango or backwardation")
    if smooth_days < 2 or rebalance_days < 1:
        raise ValueError("invalid sampling windows")
    ratio = curve["VIX3M"].astype(float) / curve["VIX"].astype(float)
    slope = pd.Series(np.log(ratio.to_numpy(dtype=float)), index=curve.index, name="vix_curve_slope")
    signal = slope.rolling(smooth_days, min_periods=smooth_days).mean()
    sign = 1.0 if direction == "contango" else -1.0
    desired = (signal * sign > 0).astype(float).where(signal.notna())
    decision = desired.copy()
    decision.iloc[:] = np.nan
    decision.iloc[::rebalance_days] = desired.iloc[::rebalance_days]
    # Hold last scheduled decision; then wait one *subsequent* Cboe publication.
    position = decision.ffill().shift(1).fillna(0.0).clip(0.0, 1.0)
    return position.rename(f"vix_curve_{direction}")


def align_to_gold(
    position: pd.Series,
    gold_index: pd.DatetimeIndex,
    *,
    max_age_days: int = 5,
) -> pd.Series:
    """Forward-fill from PAST Cboe dates only, never across stale observations."""
    if max_age_days < 1:
        raise ValueError("max_age_days must be positive")
    idx = pd.DatetimeIndex(gold_index)
    if idx.tz is None:
        raise ValueError("gold index must have an explicit UTC timezone")
    idx = idx.tz_convert("UTC")
    src = position.copy().sort_index()
    src.index = pd.DatetimeIndex(src.index)
    if src.index.tz is None:
        raise ValueError("Cboe index must have an explicit UTC timezone")
    src.index = src.index.tz_convert("UTC")
    src = src[~src.index.duplicated(keep="first")]
    aligned = src.reindex(idx, method="ffill", tolerance=pd.Timedelta(days=max_age_days))
    return pd.Series(aligned.fillna(0.0).to_numpy(dtype=float), index=gold_index, name=position.name)
