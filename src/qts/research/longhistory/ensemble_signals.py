"""Ensemble / long-only trend signal families (monthly + weekly cycles).

Every builder expects an OHLC frame (``open, high, low, close``; extra
columns such as the monthly ``usd`` index are ignored) and follows the
shared :mod:`qts.research.longhistory.signals` contract:

* every value at bar ``t`` depends only on bars ``<= t``;
* a :class:`~qts.research.longhistory.signals.Plan` written at close ``t``
  executes at the open of bar ``t+1``;
* ``target`` is a position STATE (+1 long, -1 short, 0 flat) or NaN for
  "no change"; NaN is forced wherever the vol-target size is undefined so
  the engine can never close a position it cannot re-enter;
* sizing is the inherited 10% annualised vol target, capped at 1.0x.
  ``graded`` ensemble variants scale that size by the vote share
  ``|sum of horizon signs| / n_horizons`` — a position-size choice, never
  a fractional target, so the target domain stays {-1, 0, +1}.

Families (frozen in the LH-XAUUSD-ENS / LH-XAUUSD-W1 preregistrations):

``ensemble_tsmom``  sign of the summed trailing-return signs across
                    several lookbacks (Moskowitz et al. multi-horizon
                    time-series momentum, majority-vote form).
``tsmom_single``    one trailing-return sign (ensemble control member).
``sma_trend``       close above/below its SMA (state form).
``ma_trend``        fast SMA above/below slow SMA (state form, vol sized).
``donchian_trend``  close breakout through the prior-N-bar extremes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import MAX_FRACTION, VOL_TARGET, Plan, _plan, bollinger, realized_vol

REQUIRED_COLUMNS = ("open", "high", "low", "close")


def _validate_frame(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"frame missing columns: {', '.join(missing)}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans or df.index.has_duplicates:
        raise ValueError("frame must have a clean DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError("frame index must be increasing")
    prices = df[list(REQUIRED_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0.0).any():
        raise ValueError("frame OHLC columns must be finite and positive")


def vol_size(df: pd.DataFrame, vol_n: int, ann: int) -> pd.Series:
    """Annualised volatility-target fraction, capped at no-leverage (1.0)."""
    vol = realized_vol(df["close"], vol_n, ann)
    return (VOL_TARGET / vol.replace(0.0, np.nan)).clip(upper=MAX_FRACTION)


def _finish(
    df: pd.DataFrame,
    family: str,
    params: dict[str, float | int | bool | str],
    target: np.ndarray,
    size: pd.Series,
) -> Plan:
    sz = size.to_numpy(dtype=float)
    out = np.asarray(target, dtype=float).copy()
    out[~np.isfinite(sz)] = np.nan
    return _plan(df, family, params, out, size, np.full(len(df), np.nan), np.ones(len(df), dtype=bool))


def _clip_long_only(target: np.ndarray, long_only: bool) -> np.ndarray:
    return np.clip(target, 0.0, None) if long_only else target


def tsmom_single(
    df: pd.DataFrame,
    lookback: int,
    *,
    long_only: bool = False,
    vol_n: int,
    ann: int,
) -> Plan:
    """Trailing-return sign at one lookback, vol-targeted."""
    _validate_frame(df)
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    target = np.sign((df["close"] / df["close"].shift(lookback) - 1.0).to_numpy())
    target = _clip_long_only(target, long_only)
    return _finish(
        df, "tsmom_single", {"lookback": lookback, "long_only": long_only, "vol_n": vol_n, "ann": ann},
        target, vol_size(df, vol_n, ann),
    )


def ensemble_tsmom(
    df: pd.DataFrame,
    lookbacks: tuple[int, ...],
    *,
    long_only: bool = False,
    graded: bool = False,
    vol_n: int,
    ann: int,
) -> Plan:
    """Majority-vote trailing-return ensemble across ``lookbacks``.

    Target is the sign of the summed per-horizon signs (flat on an exact
    tie). With ``graded=True`` the vol-target size is additionally scaled
    by the winning vote share, so split votes take smaller positions.
    """
    _validate_frame(df)
    if not lookbacks or any(lb < 1 for lb in lookbacks):
        raise ValueError("lookbacks must be a non-empty tuple of integers >= 1")
    votes = np.sum(
        [np.sign((df["close"] / df["close"].shift(lb) - 1.0).to_numpy()) for lb in lookbacks], axis=0
    )
    target = _clip_long_only(np.sign(votes), long_only)
    size = vol_size(df, vol_n, ann)
    if graded:
        size = size * (np.abs(votes) / len(lookbacks))
    params: dict[str, float | int | bool | str] = {
        "lookbacks": ",".join(str(lb) for lb in lookbacks),
        "long_only": long_only,
        "graded": graded,
        "vol_n": vol_n,
        "ann": ann,
    }
    return _finish(df, "ensemble_tsmom", params, target, size)

def bollinger_control(df: pd.DataFrame, *, vol_n: int, ann: int) -> Plan:
    """CONTROL: 20-bar two-sigma mean reversion, target masked to sized bars."""
    _validate_frame(df)
    plan = bollinger(df, n=20, k=2.0, ann=ann, vol_n=vol_n)
    size = pd.Series(np.asarray(plan.size, dtype=float), index=df.index)
    return _finish(df, plan.family, dict(plan.params), np.asarray(plan.target, dtype=float), size)

def _usd_change(df: pd.DataFrame, usd_lb: int) -> np.ndarray:
    if "usd" not in df.columns:
        raise ValueError("USD-conditioned builders require the monthly 'usd' column")
    if usd_lb < 1:
        raise ValueError("usd_lb must be >= 1")
    return (df["usd"] / df["usd"].shift(usd_lb) - 1.0).to_numpy()


def _ensemble_votes(df: pd.DataFrame, lookbacks: tuple[int, ...]) -> np.ndarray:
    if not lookbacks or any(lb < 1 for lb in lookbacks):
        raise ValueError("lookbacks must be a non-empty tuple of integers >= 1")
    return np.sum(
        [np.sign((df["close"] / df["close"].shift(lb) - 1.0).to_numpy()) for lb in lookbacks], axis=0
    )


def ensemble_usd_veto(
    df: pd.DataFrame,
    lookbacks: tuple[int, ...],
    *,
    usd_lb: int = 12,
    vol_n: int,
    ann: int,
) -> Plan:
    """Ensemble trend; shorts only while the USD index rose over ``usd_lb`` bars."""
    _validate_frame(df)
    votes = _ensemble_votes(df, lookbacks)
    trend = np.sign(votes)
    usd_up = _usd_change(df, usd_lb) > 0.0
    target = np.where(trend > 0, 1.0, np.where(trend < 0, np.where(usd_up, -1.0, 0.0), 0.0))
    params: dict[str, float | int | bool | str] = {
        "lookbacks": ",".join(str(lb) for lb in lookbacks), "usd_lb": usd_lb, "vol_n": vol_n, "ann": ann,
    }
    return _finish(df, "ensemble_usd_veto", params, target, vol_size(df, vol_n, ann))


def ensemble_usd_agreement(
    df: pd.DataFrame,
    lookbacks: tuple[int, ...],
    *,
    usd_lb: int = 12,
    vol_n: int,
    ann: int,
) -> Plan:
    """Ensemble trend traded only when the USD index agrees (flat otherwise)."""
    _validate_frame(df)
    votes = _ensemble_votes(df, lookbacks)
    trend = np.sign(votes)
    usd_up = _usd_change(df, usd_lb) > 0.0
    target = np.where((trend > 0) & (~usd_up), 1.0, np.where((trend < 0) & usd_up, -1.0, 0.0))
    params: dict[str, float | int | bool | str] = {
        "lookbacks": ",".join(str(lb) for lb in lookbacks), "usd_lb": usd_lb, "vol_n": vol_n, "ann": ann,
    }
    return _finish(df, "ensemble_usd_agreement", params, target, vol_size(df, vol_n, ann))


def sma_trend(
    df: pd.DataFrame,
    n: int,
    *,
    long_only: bool = False,
    vol_n: int,
    ann: int,
) -> Plan:
    """Close above its ``n``-bar SMA = long state, below = short (or flat)."""
    _validate_frame(df)
    if n < 2:
        raise ValueError("n must be >= 2")
    sma_n = df["close"].rolling(n, min_periods=n).mean()
    target = np.where(df["close"] > sma_n, 1.0, -1.0)
    target = _clip_long_only(np.asarray(target, dtype=float), long_only)
    return _finish(
        df, "sma_trend", {"n": n, "long_only": long_only, "vol_n": vol_n, "ann": ann},
        target, vol_size(df, vol_n, ann),
    )


def ma_trend(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    *,
    long_only: bool = False,
    vol_n: int,
    ann: int,
) -> Plan:
    """Fast SMA above slow SMA = long state, below = short (or flat)."""
    _validate_frame(df)
    if fast < 1 or slow <= fast:
        raise ValueError("require 1 <= fast < slow")
    f = df["close"].rolling(fast, min_periods=fast).mean()
    s = df["close"].rolling(slow, min_periods=slow).mean()
    target = _clip_long_only(np.where(f > s, 1.0, -1.0).astype(float), long_only)
    return _finish(
        df, "ma_trend", {"fast": fast, "slow": slow, "long_only": long_only, "vol_n": vol_n, "ann": ann},
        target, vol_size(df, vol_n, ann),
    )


def donchian_trend(
    df: pd.DataFrame,
    n: int,
    *,
    long_only: bool = False,
    vol_n: int,
    ann: int,
) -> Plan:
    """Close through the prior-``n``-bar high/low sets the persistent state."""
    _validate_frame(df)
    if n < 2:
        raise ValueError("n must be >= 2")
    high_n = df["close"].shift(1).rolling(n, min_periods=n).max().to_numpy()
    low_n = df["close"].shift(1).rolling(n, min_periods=n).min().to_numpy()
    close = df["close"].to_numpy()
    state = np.zeros(len(df))
    s = 0.0
    for t in range(len(df)):
        if not np.isfinite(high_n[t]) or not np.isfinite(low_n[t]):
            state[t] = np.nan
            continue
        if close[t] > high_n[t]:
            s = 1.0
        elif close[t] < low_n[t]:
            s = -1.0
        state[t] = s
    state = _clip_long_only(state, long_only)
    return _finish(
        df, "donchian_trend", {"n": n, "long_only": long_only, "vol_n": vol_n, "ann": ann},
        state, vol_size(df, vol_n, ann),
    )
