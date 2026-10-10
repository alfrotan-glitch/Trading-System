"""Causal, daily signal families for XAUUSD.

Contract (checked by :mod:`qts.research.longhistory.checks`):

* every value at bar ``t`` depends only on bars ``<= t``;
* a :class:`Plan` written at close ``t`` is executed by the engine at the OPEN
  of bar ``t+1``. No signal can trade at the price that produced it;
* ``target`` is a position STATE (+1 long, -1 short, 0 flat) or NaN for "no
  change"; the engine treats the state as persistent until it changes.

Families (see the pre-registration for the frozen parameter grids):

``tsmom``          time-series momentum, sign of trailing return, monthly rebalance,
                   volatility-targeted size (Moskowitz, Ooi & Pedersen 2012).
``ma_cross``       simple moving-average crossover, stop-and-reverse, optional ATR stop
                   (Brock, Lakonishok & LeBaron 1992).
``donchian``       N-bar channel breakout with M-bar exit channel and ATR stop
                   (Donchian / Turtle-style trend following).
``range_expansion`` volatility expansion: a body larger than k * ATR starts a
                   fixed-horizon trade (Crabel-style volatility breakout, daily proxy).
``nr7``            narrowest-range-of-7 setup with a close-through breakout
                   (Crabel-style volatility contraction, daily proxy).
``trend_gated``    Donchian breakout entries gated by a Kaufman efficiency-ratio
                   trend-strength filter (regime-conditioned trend).
``rsi2``           Connors-style RSI(2) mean reversion, optional SMA(200) trend filter.
``bollinger``      Bollinger(20, 2) mean reversion to the mean. CONTROL, not a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RISK_PER_TRADE = 0.01  # fraction of equity risked to the stop (stop-based sizing)
VOL_TARGET = 0.10  # annualised volatility target (no-stop sizing)
MAX_FRACTION = 1.0  # no leverage: position notional <= equity
VOL_WINDOW = 60


@dataclass(frozen=True)
class Plan:
    target: np.ndarray  # +1 / -1 / 0 state, NaN = no change
    size: np.ndarray  # desired fraction of equity (NaN = not applicable)
    stop_dist: np.ndarray  # price distance to protective stop (NaN = none)
    rebalance: np.ndarray  # bool: resize an open position to ``size``
    family: str
    params: dict[str, float | int | bool | str]

    def __post_init__(self) -> None:
        n = len(self.target)
        for name in ("size", "stop_dist", "rebalance"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"plan field {name} length mismatch")


# --------------------------------------------------------------------------- indicators


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder average true range."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.where(avg_loss != 0.0, 100.0)


def efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    """Kaufman efficiency ratio in [0, 1]: net move over the path length."""
    net = (close - close.shift(n)).abs()
    path = close.diff().abs().rolling(n, min_periods=n).sum()
    return net / path.replace(0.0, np.nan)


def realized_vol(close: pd.Series, n: int = VOL_WINDOW) -> pd.Series:
    """Annualised standard deviation of daily log returns."""
    return np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(TRADING_DAYS)


def month_end(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    last = s.groupby(index.to_period("M")).transform("max")
    return np.asarray(last.values == s.values)


# --------------------------------------------------------------------------- sizing


def size_stop_based(df: pd.DataFrame, stop_mult: float) -> pd.Series:
    """Risk ``RISK_PER_TRADE`` of equity to a stop at ``stop_mult * ATR``, capped."""
    stop_pct = stop_mult * atr(df) / df["close"]
    return (RISK_PER_TRADE / stop_pct.replace(0.0, np.nan)).clip(upper=MAX_FRACTION)


def size_vol_target(df: pd.DataFrame) -> pd.Series:
    vol = realized_vol(df["close"])
    return (VOL_TARGET / vol.replace(0.0, np.nan)).clip(upper=MAX_FRACTION)


# --------------------------------------------------------------------------- state machines


def _state_from_events(
    n: int,
    enter_long: np.ndarray,
    enter_short: np.ndarray,
    exit_long: np.ndarray,
    exit_short: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    """Persistent position state from boolean event arrays (loop: causal by construction)."""
    out = np.zeros(n)
    s = 0.0
    for t in range(n):
        if not valid[t]:
            out[t] = np.nan
            continue
        if enter_long[t]:
            s = 1.0
        elif enter_short[t]:
            s = -1.0
        elif s == 1.0 and exit_long[t] or s == -1.0 and exit_short[t]:
            s = 0.0
        out[t] = s
    return out


def _timed_state(
    n: int,
    enter_long: np.ndarray,
    enter_short: np.ndarray,
    hold: int,
    valid: np.ndarray,
) -> np.ndarray:
    """Fixed-horizon trades: a signal at ``t`` holds for ``hold`` bars, then flat."""
    out = np.zeros(n)
    s = 0.0
    exit_at = -1
    for t in range(n):
        if not valid[t]:
            out[t] = np.nan
            continue
        if enter_long[t]:
            s, exit_at = 1.0, t + hold
        elif enter_short[t]:
            s, exit_at = -1.0, t + hold
        elif t >= exit_at:
            s = 0.0
        out[t] = s
    return out


def _plan(
    df: pd.DataFrame,
    family: str,
    params: dict[str, float | int | bool | str],
    target: np.ndarray,
    size: pd.Series | np.ndarray,
    stop_dist: pd.Series | np.ndarray,
    rebalance: np.ndarray | None = None,
) -> Plan:
    n = len(df)
    reb = np.zeros(n, dtype=bool) if rebalance is None else rebalance.astype(bool)
    return Plan(
        target=np.asarray(target, dtype=float),
        size=np.asarray(size, dtype=float),
        stop_dist=np.asarray(stop_dist, dtype=float),
        rebalance=reb,
        family=family,
        params=params,
    )


# --------------------------------------------------------------------------- families


def tsmom(df: pd.DataFrame, lookback: int) -> Plan:
    """Trailing-return sign, changed only at month-end rebalances, vol-targeted size."""
    close = df["close"]
    trailing = close / close.shift(lookback) - 1.0
    sig = np.sign(trailing.to_numpy())
    me = month_end(pd.DatetimeIndex(df.index))
    target = np.where(me & np.isfinite(sig), sig, np.nan)
    size = size_vol_target(df)
    reb = me
    return _plan(df, "tsmom", {"lookback": lookback}, target, size, np.full(len(df), np.nan), reb)


def ma_cross(df: pd.DataFrame, fast: int, slow: int, stop_mult: float | None) -> Plan:
    f, s = sma(df["close"], fast), sma(df["close"], slow)
    valid = (f.notna() & s.notna()).to_numpy()
    state = np.where(valid, np.where(f > s, 1.0, -1.0), np.nan)
    stop: np.ndarray
    if stop_mult is None:
        size = size_vol_target(df)
        stop = np.full(len(df), np.nan)
    else:
        size = size_stop_based(df, stop_mult)
        stop = (stop_mult * atr(df)).to_numpy()
    return _plan(
        df,
        "ma_cross",
        {"fast": fast, "slow": slow, "stop_atr": float(stop_mult) if stop_mult is not None else 0.0},
        state,
        size,
        stop,
    )


def donchian(
    df: pd.DataFrame,
    entry: int,
    exit_n: int,
    stop_mult: float,
    gate: pd.Series | None = None,
) -> Plan:
    """Channel breakout on closes; exit on an opposite ``exit_n`` channel break."""
    high_n = df["high"].shift(1).rolling(entry, min_periods=entry).max()
    low_n = df["low"].shift(1).rolling(entry, min_periods=entry).min()
    high_m = df["high"].shift(1).rolling(exit_n, min_periods=exit_n).max()
    low_m = df["low"].shift(1).rolling(exit_n, min_periods=exit_n).min()
    close = df["close"]
    up = (close > high_n).to_numpy()
    dn = (close < low_n).to_numpy()
    if gate is not None:
        g = gate.fillna(0.0).to_numpy().astype(bool)
        up = up & g
        dn = dn & g
    ex_l = (close < low_m).to_numpy()
    ex_s = (close > high_m).to_numpy()
    valid = (high_n.notna() & low_m.notna()).to_numpy()
    state = _state_from_events(len(df), up, dn, ex_l, ex_s, valid)
    stop = (stop_mult * atr(df)).to_numpy()
    size = size_stop_based(df, stop_mult)
    params: dict[str, float | int | bool | str] = {
        "entry": entry,
        "exit": exit_n,
        "stop_atr": stop_mult,
        "gated": gate is not None,
    }
    return _plan(df, "donchian" if gate is None else "trend_gated", params, state, size, stop)


def range_expansion(df: pd.DataFrame, k: float, hold: int, stop_mult: float = 2.0) -> Plan:
    """Body larger than ``k * ATR20`` (prior bar) starts a ``hold``-bar trade."""
    prev_atr = atr(df, 20).shift(1)
    body = df["close"] - df["open"]
    up = (body > k * prev_atr).to_numpy()
    dn = (body < -k * prev_atr).to_numpy()
    valid = prev_atr.notna().to_numpy()
    state = _timed_state(len(df), up, dn, hold, valid)
    return _plan(
        df,
        "range_expansion",
        {"k_atr": k, "hold": hold, "stop_atr": stop_mult},
        state,
        size_stop_based(df, stop_mult),
        (stop_mult * atr(df)).to_numpy(),
    )


def nr7(df: pd.DataFrame, hold: int, stop_mult: float = 2.0, window: int = 5) -> Plan:
    """NR7 contraction; a close through the NR7 bar's range within ``window`` bars trades."""
    rng = (df["high"] - df["low"]).to_numpy()
    n = len(df)
    is_nr7 = np.zeros(n, dtype=bool)
    for t in range(6, n):
        if rng[t] <= np.min(rng[t - 6 : t + 1]):
            is_nr7[t] = True
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    up = np.zeros(n, dtype=bool)
    dn = np.zeros(n, dtype=bool)
    hi_lvl = np.nan
    lo_lvl = np.nan
    setup_at = -(10**9)
    for t in range(n):
        if is_nr7[t]:
            hi_lvl, lo_lvl, setup_at = high[t], low[t], t
            continue
        if t - setup_at <= window and t > setup_at:
            if close[t] > hi_lvl:
                up[t] = True
                setup_at = -(10**9)
            elif close[t] < lo_lvl:
                dn[t] = True
                setup_at = -(10**9)
    valid = np.ones(n, dtype=bool)
    valid[:6] = False
    state = _timed_state(n, up, dn, hold, valid)
    return _plan(
        df,
        "nr7",
        {"hold": hold, "stop_atr": stop_mult, "window": window},
        state,
        size_stop_based(df, stop_mult),
        (stop_mult * atr(df)).to_numpy(),
    )


def rsi2(df: pd.DataFrame, threshold: float, trend_filter: bool, time_exit: int = 5) -> Plan:
    """Connors RSI(2): buy oversold pullbacks (optionally above SMA200), exit above SMA(5)."""
    close = df["close"]
    r = rsi(close, 2).to_numpy()
    s5 = sma(close, 5).to_numpy()
    s200 = sma(close, 200).to_numpy()
    c = close.to_numpy()
    n = len(df)
    state = np.zeros(n)
    s = 0.0
    entry_t = -1
    for t in range(n):
        if not np.isfinite(r[t]) or not np.isfinite(s5[t]):
            state[t] = np.nan
            continue
        trend_ok_long = (not trend_filter) or (np.isfinite(s200[t]) and c[t] > s200[t])
        trend_ok_short = (not trend_filter) or (np.isfinite(s200[t]) and c[t] < s200[t])
        if s == 0.0:
            if r[t] < threshold and trend_ok_long:
                s, entry_t = 1.0, t
            elif r[t] > 100.0 - threshold and trend_ok_short:
                s, entry_t = -1.0, t
        elif (
            s == 1.0
            and (c[t] > s5[t] or t - entry_t >= time_exit)
            or s == -1.0
            and (c[t] < s5[t] or t - entry_t >= time_exit)
        ):
            s = 0.0
        state[t] = s
    return _plan(
        df,
        "rsi2",
        {"threshold": threshold, "trend_filter": trend_filter, "time_exit": time_exit},
        state,
        size_vol_target(df),
        np.full(n, np.nan),
    )


def bollinger(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> Plan:
    """CONTROL: fade band excursions, exit at the mean. Falsification benchmark only."""
    close = df["close"]
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    upper = (mid + k * sd).to_numpy()
    lower = (mid - k * sd).to_numpy()
    m = mid.to_numpy()
    c = close.to_numpy()
    size_n = len(df)
    state = np.zeros(size_n)
    s = 0.0
    for t in range(size_n):
        if not np.isfinite(m[t]):
            state[t] = np.nan
            continue
        if s == 0.0:
            if c[t] < lower[t]:
                s = 1.0
            elif c[t] > upper[t]:
                s = -1.0
        elif s == 1.0 and c[t] >= m[t] or s == -1.0 and c[t] <= m[t]:
            s = 0.0
        state[t] = s
    return _plan(df, "bollinger_control", {"n": n, "k": k}, state, size_vol_target(df), np.full(size_n, np.nan))


def efficiency_gate(df: pd.DataFrame, n: int, threshold: float) -> pd.Series:
    """Boolean gate: trend strength (efficiency ratio) at or above ``threshold``."""
    return (efficiency_ratio(df["close"], n) >= threshold).astype(float)
