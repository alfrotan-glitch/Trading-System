"""Signal library for XAUUSD edge research.

Every function here returns a position series indexed like ``bars`` where the value
at ``t`` is decided from information available **at the close of bar t** and is held
from ``open[t]`` to ``open[t+1]``. Nothing may reference ``t+1`` or later.

Families are deliberately heterogeneous: trend/TSMOM, breakout, mean reversion,
session effects, and volatility-regime overlays. A family that fails is recorded,
not quietly retuned.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.edgelab import atr, ema, realized_vol


def _dt_index(bars: pd.DataFrame) -> pd.DatetimeIndex:
    """Bars are always timestamp-indexed; this keeps pandas-stubs honest."""
    return pd.DatetimeIndex(bars.index)


def _bars_per_day(bars: pd.DataFrame) -> float:
    """Median bars per calendar day actually present (gold trades ~5 days/week)."""
    if len(bars) < 100:
        return 96.0
    days = bars.groupby(pd.Index(bars.index).normalize()).size()
    return float(max(1.0, days.median()))


# ------------------------------------------------------------------ trend / TSMOM


def tsmom(bars: pd.DataFrame, lookback_days: int = 20, vol_target: float | None = None) -> pd.Series:
    """Time-series momentum: long if the trailing return is positive, short if negative.

    ``vol_target`` (e.g. 0.15 annualised) scales exposure by realised volatility so
    the risk per unit of signal is stable across gold's very different volatility
    regimes (2008, 2011-13, 2020).
    """
    bpd = _bars_per_day(bars)
    n = max(1, int(lookback_days * bpd))
    ret = bars["close"].pct_change(n)
    sig = pd.Series(np.sign(ret.to_numpy()), index=bars.index, dtype=float)
    if vol_target is not None:
        rv = realized_vol(bars["close"], n=max(20, int(20 * bpd)))
        scale = (vol_target / rv).clip(upper=1.0)
        sig = sig * scale
    return sig


def ma_cross(bars: pd.DataFrame, fast_days: int = 20, slow_days: int = 100) -> pd.Series:
    bpd = _bars_per_day(bars)
    f = ema(bars["close"], max(2, int(fast_days * bpd)))
    s = ema(bars["close"], max(3, int(slow_days * bpd)))
    return pd.Series(np.sign((f - s).to_numpy()), index=bars.index, dtype=float)


def donchian(bars: pd.DataFrame, entry_days: int = 20, exit_days: int = 10) -> pd.Series:
    """Classic turtle-style breakout with a shorter exit channel."""
    bpd = _bars_per_day(bars)
    hi = bars["high"].rolling(max(2, int(entry_days * bpd)), min_periods=2).max()
    lo = bars["low"].rolling(max(2, int(entry_days * bpd)), min_periods=2).min()
    exit_hi = bars["high"].rolling(max(2, int(exit_days * bpd)), min_periods=2).max()
    exit_lo = bars["low"].rolling(max(2, int(exit_days * bpd)), min_periods=2).min()
    close = bars["close"]
    # Shift channels by one bar: the breakout level must be known before the bar.
    hi, lo = hi.shift(1), lo.shift(1)
    exit_hi, exit_lo = exit_hi.shift(1), exit_lo.shift(1)
    state = 0.0
    c = close.to_numpy()
    hi_v, lo_v = hi.to_numpy(), lo.to_numpy()
    eh, el = exit_hi.to_numpy(), exit_lo.to_numpy()
    out = np.zeros(len(c))
    for i in range(len(c)):
        if np.isnan(hi_v[i]) or np.isnan(lo_v[i]):
            out[i] = 0.0
            continue
        if state == 0.0:
            if c[i] > hi_v[i]:
                state = 1.0
            elif c[i] < lo_v[i]:
                state = -1.0
        elif (state > 0 and c[i] < el[i]) or (state < 0 and c[i] > eh[i]):
            state = 0.0
        out[i] = state
    return pd.Series(out, index=bars.index)


def ma_slope(bars: pd.DataFrame, n_days: int = 50) -> pd.Series:
    """Trend strength from the slope of a long moving average, normalised by ATR."""
    bpd = _bars_per_day(bars)
    n = max(2, int(n_days * bpd))
    ma = ema(bars["close"], n)
    slope = ma.diff(int(max(1, bpd)))
    a = atr(bars, max(5, int(14 * bpd / 96) if bpd > 20 else 14))
    z = (slope / (a + 1e-12)).clip(-0.5, 0.5) * 2.0
    return z.clip(-1, 1)


# ---------------------------------------------------------------------- breakout


def volatility_breakout(bars: pd.DataFrame, k: float = 1.0, lookback: int = 20) -> pd.Series:
    """Long when price closes above the prior close + k*ATR, short below.

    Enters on expansion, exits when momentum decays (price crosses back through the
    mid of the recent range).
    """
    a = atr(bars, max(5, lookback))
    close = bars["close"]
    anchor = close.shift(1)
    up = anchor + k * a
    dn = anchor - k * a
    c = close.to_numpy()
    u, d = up.to_numpy(), dn.to_numpy()
    mid = close.rolling(max(2, lookback), min_periods=2).mean().to_numpy()
    out = np.zeros(len(c))
    state = 0.0
    for i in range(len(c)):
        if np.isnan(u[i]) or np.isnan(mid[i]):
            out[i] = 0.0
            continue
        if state == 0.0:
            if c[i] > u[i]:
                state = 1.0
            elif c[i] < d[i]:
                state = -1.0
        elif (state > 0 and c[i] < mid[i]) or (state < 0 and c[i] > mid[i]):
            state = 0.0
        out[i] = state
    return pd.Series(out, index=bars.index)


def opening_range_breakout(
    bars: pd.DataFrame,
    range_minutes: int = 60,
    session_start_hour: int = 7,
    hold_minutes: int = 240,
) -> pd.Series:
    """London-open range breakout.

    The range is built from the first ``range_minutes`` after ``session_start_hour``
    UTC, then a close outside it opens a position that is flat by
    ``session_start_hour + hold_minutes``. Positions are only held inside the window.
    """
    idx = _dt_index(bars)
    minute_of_day = idx.hour * 60 + idx.minute
    start = session_start_hour * 60
    in_range = (minute_of_day >= start) & (minute_of_day < start + range_minutes)
    in_window = (minute_of_day >= start + range_minutes) & (minute_of_day < start + hold_minutes)

    day = pd.Series(idx.normalize(), index=idx)
    hi = bars["high"].where(in_range).groupby(day).transform("max")
    lo = bars["low"].where(in_range).groupby(day).transform("min")
    # The range is only known after the range window closes.
    hi = hi.where(in_window).ffill().where(in_window)
    lo = lo.where(in_window).ffill().where(in_window)
    close = bars["close"]
    sig = pd.Series(0.0, index=idx)
    long_ = (close > hi).astype(float)
    short_ = (close < lo).astype(float)
    sig = (long_ - short_).where(in_window, 0.0)
    # Hold a direction within the window once triggered; re-evaluated each bar, so
    # a close back inside the range exits.
    return sig.ffill().where(in_window, 0.0).fillna(0.0)


# ---------------------------------------------------------------- mean reversion


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    roll_dn = down.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = roll_up / roll_dn.replace(0.0, np.nan)
    return 100 - 100 / (1 + rs)


def rsi_reversion(
    bars: pd.DataFrame,
    n: int = 14,
    low: float = 30.0,
    high: float = 70.0,
    trend_filter_days: int | None = None,
) -> pd.Series:
    """Buy oversold / sell overbought, optionally only with the long-term trend."""
    r = rsi(bars["close"], n)
    sig = pd.Series(0.0, index=bars.index)
    sig[r < low] = 1.0
    sig[r > high] = -1.0
    if trend_filter_days:
        bpd = _bars_per_day(bars)
        trend = np.sign(bars["close"] - ema(bars["close"], max(5, int(trend_filter_days * bpd))))
        sig = sig.where(sig == trend, 0.0)
    # Exit on the mid-line: hold until RSI crosses 50.
    state = 0.0
    out = np.zeros(len(sig))
    rv = r.to_numpy()
    sv = sig.to_numpy()
    for i in range(len(rv)):
        if state == 0.0 and sv[i] != 0.0:
            state = sv[i]
        elif (state > 0 and rv[i] >= 50) or (state < 0 and rv[i] <= 50):
            state = 0.0
        out[i] = state
    return pd.Series(out, index=bars.index)


def bollinger_reversion(bars: pd.DataFrame, n: int = 40, k: float = 2.0, regime_max_vol: float | None = None) -> pd.Series:
    """Fade k-sigma moves, optionally only in low-volatility regimes."""
    close = bars["close"]
    ma = close.rolling(n, min_periods=n).mean()
    sd = close.rolling(n, min_periods=n).std()
    z = (close - ma) / sd.replace(0.0, np.nan)
    sig = pd.Series(0.0, index=bars.index)
    sig[z < -k] = 1.0
    sig[z > k] = -1.0
    if regime_max_vol is not None:
        bpd = int(_bars_per_day(bars))
        rv = realized_vol(close, n=max(20, 20 * bpd // 96))
        sig = sig.where(rv < regime_max_vol, 0.0)
    # Exit when z returns to 0.
    out = np.zeros(len(sig))
    zv = z.to_numpy()
    sv = sig.to_numpy()
    state = 0.0
    for i in range(len(zv)):
        if state == 0.0 and sv[i] != 0.0:
            state = sv[i]
        elif (state > 0 and zv[i] >= 0) or (state < 0 and zv[i] <= 0):
            state = 0.0
        out[i] = state
    return pd.Series(out, index=bars.index)


# ------------------------------------------------------------- session / seasonality


def session_bias(
    bars: pd.DataFrame,
    long_hours: tuple[int, ...] = (13, 14, 15),
    short_hours: tuple[int, ...] = (),
) -> pd.Series:
    """Static session exposure — tests whether particular UTC hours carry drift."""
    h = _dt_index(bars).hour
    sig = pd.Series(0.0, index=bars.index)
    sig[np.isin(h, long_hours)] = 1.0
    sig[np.isin(h, short_hours)] = -1.0
    return sig


def day_of_week(bars: pd.DataFrame, long_days: tuple[int, ...] = (0,), short_days: tuple[int, ...] = (4,)) -> pd.Series:
    d = _dt_index(bars).dayofweek
    sig = pd.Series(0.0, index=bars.index)
    sig[np.isin(d, long_days)] = 1.0
    sig[np.isin(d, short_days)] = -1.0
    return sig


def overnight(bars: pd.DataFrame, entry_hour: int = 20, exit_hour: int = 6) -> pd.Series:
    """Hold the overnight session only (roll/close-to-open drift)."""
    h = _dt_index(bars).hour
    on = (h >= entry_hour) | (h < exit_hour)
    return pd.Series(np.where(on, 1.0, 0.0), index=bars.index)


def vol_managed_long(
    bars: pd.DataFrame,
    target_vol: float = 0.15,
    lookback_days: int = 20,
    max_exposure: float = 1.0,
) -> pd.Series:
    """Long-only gold sized inversely to realised volatility.

    Gold's risk is strongly autocorrelated: 2008-2013 and 2020 were 2-3x the
    volatility of 2017. Holding a constant notional therefore holds a wildly
    varying amount of risk. Scaling by ``target_vol / realised_vol`` keeps the risk
    budget steady, which is a documented improvement across asset classes
    (Moreira & Muir 2017). It is *risk timing*, not return forecasting — whether it
    earns alpha over static exposure is an empirical question this harness answers,
    not an assumption.

    ``lookback_days`` must be long enough to estimate sigma but short enough to
    react; 20-60 days is the usual range.
    """
    close = bars["close"]
    bpd = _bars_per_day(bars)
    rv = realized_vol(close, n=max(20, int(lookback_days * bpd)))
    scale = (target_vol / rv.replace(0.0, np.nan)).clip(upper=max_exposure)
    return pd.Series(np.clip(scale.to_numpy(), 0.0, max_exposure), index=bars.index).fillna(0.0)


# ------------------------------------------------------------------------ overlays


def regime_filter(signal: pd.Series, bars: pd.DataFrame, max_vol: float | None = None, min_vol: float | None = None) -> pd.Series:
    """Gate a signal by realised-volatility regime."""
    bpd = int(_bars_per_day(bars))
    rv = realized_vol(bars["close"], n=max(20, 20 * bpd // 96))
    out = signal.copy()
    if max_vol is not None:
        out = out.where(rv <= max_vol, 0.0)
    if min_vol is not None:
        out = out.where(rv >= min_vol, 0.0)
    return out
