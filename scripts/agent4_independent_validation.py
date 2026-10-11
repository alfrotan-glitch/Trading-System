#!/usr/bin/env python3
"""Agent 4 — independent validation of the frozen long-history XAUUSD studies.

Mandate (QTS multi-agent protocol, Agent 4): independently review the candidate
strategies and their evidence; check for look-ahead bias, selection bias,
overfitting and multiple-testing effects; re-run chronological validation and
walk-forward checks; stress execution costs; and recommend PASS / FAIL /
INSUFFICIENT EVIDENCE against the pre-registered acceptance gates.

What this script does — and deliberately does NOT do:

* It RE-IMPLEMENTS the execution engine, ALL signal families of both studies
  (daily: tsmom, ma_cross, donchian, range expansion, nr7, trend-gated Donchian,
  RSI(2), bollinger control; M15: ma_cross, donchian, range expansion, session
  breakout), the selection rule, the regime labels and the statistics from the
  pre-registrations (``docs/research/preregistration_longhistory_2026-10-10.md``
  and ``docs/research/preregistration_longhistory_m15_2026-10-10.md``) WITHOUT
  importing ``qts.research.longhistory``. The only shared inputs are the
  processed, SHA-256-pinned CSVs rebuilt by the committed fetch/build scripts.
* It re-derives every headline number of both final evidence files
  (daily ``LH-XAUUSD-D1-2026-10-10``, intraday ``LH-XAUUSD-M15-2026-10-10``)
  and compares them against the committed evidence.
* It runs robustness diagnostics on the FROZEN selections only: fill-lag
  sensitivity (bar-stamp convention), chronological year-by-year stability,
  holdout halves, a cost grid, an all-days (no completeness filter) run and
  overnight-hold accounting. Nothing here re-tunes, re-selects or improves any
  candidate, and the 2020-2025 holdout is never used to change a definition.
* It performs no broker interaction of any kind and changes no runtime state.

Usage::

    python scripts/agent4_independent_validation.py            # full run
    python scripts/agent4_independent_validation.py --quick    # engine cross-check only

Writes ``data/evidence/longhistory/agent4_validation.json``. The report is
``docs/audit/agent4_independent_validation_2026-10-11.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE = REPO_ROOT / "data" / "evidence" / "longhistory" / "agent4_validation.json"
DAILY_FINAL = REPO_ROOT / "data" / "evidence" / "longhistory" / "research_final.json"
INTRADAY_FINAL = REPO_ROOT / "data" / "evidence" / "longhistory" / "intraday_research_final.json"

# ------------------------------------------------------------------ constants (prereg)

INITIAL_EQUITY = 10_000.0
RISK_PER_TRADE = 0.01
VOL_TARGET = 0.10
MAX_FRACTION = 1.0
OUNCES_PER_LOT = 100.0
SPREAD_BPS = 3.0
SLIPPAGE_BPS = 1.0
COMMISSION_USD_PER_LOT_SIDE = 7.0
RESEARCH_START = "2004-06-11"
RESEARCH_END = "2025-02-28"
DEV_END = "2019-12-31"
HOLDOUT_START = "2020-01-01"
WF_YEARS = tuple(range(2010, 2020))
MIN_TRAIN_ROUND_TURNS = 20
MIN_TRADES_OOS_GATE = 100
GATE_WF_MIN_POSITIVE_YEARS = 6
GATE_HOLM_ALPHA = 0.05
GATE_DSR_MIN = 0.95
GATE_REGIMES_MIN_POSITIVE = 3

DAILY_PPY = 252
DAILY_VOL_WINDOW = 60  # 60 trading days, as the daily protocol's VOL_WINDOW
M15_BARS_PER_DAY = 92
M15_PPY = M15_BARS_PER_DAY * 252
M15_VOL_BARS = 60 * M15_BARS_PER_DAY
M15_REGIME_BARS = 252 * M15_BARS_PER_DAY
SESSION_ROLL_HOURS = 2
MIN_BARS_PER_DAY = 40
REPLICATE_START = "2025-08-06"
REPLICATE_END = "2026-09-16"


def side_rate(price: float, mult: float = 1.0) -> float:
    """Per-side cost as a fraction of traded notional (prereg §4)."""
    return mult * (
        SPREAD_BPS / 2.0 / 1e4 + SLIPPAGE_BPS / 1e4 + COMMISSION_USD_PER_LOT_SIDE / (OUNCES_PER_LOT * price)
    )


# ------------------------------------------------------------------ independent engine


@dataclass
class XTrade:
    direction: int
    entry_bar: int
    exit_bar: int
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    gross_usd: float
    cost_usd: float
    stopped: bool
    forced: bool
    entry_frac: float = 0.0

    @property
    def net_usd(self) -> float:
        return self.gross_usd - self.cost_usd


@dataclass
class XRun:
    times: pd.DatetimeIndex
    equity: np.ndarray
    trades: list[XTrade] = field(default_factory=list)
    initial_equity: float = INITIAL_EQUITY
    turnover: float = 0.0
    cost_usd: float = 0.0
    gross_usd: float = 0.0

    @property
    def returns(self) -> np.ndarray:
        prev = np.concatenate([[self.initial_equity], self.equity[:-1]])
        return self.equity / prev - 1.0

    @property
    def net_usd(self) -> float:
        return float(self.equity[-1] - self.initial_equity) if len(self.equity) else 0.0


def xrun(
    bars: pd.DataFrame,
    target: np.ndarray,
    size: np.ndarray,
    stop_dist: np.ndarray,
    i0: int,
    i1: int,
    mult: float = 1.0,
    lag_bars: int = 0,
    rebalance: np.ndarray | None = None,
) -> XRun:
    """Independent bar-loop engine, written from prereg §3 ('Execution model').

    Event order per bar (all fills conservative):
      1. an open position marks from the previous close to this open;
      2. the decision taken at the close of the previous bar fills at THIS open;
      3. the protective stop is checked against this bar's range and fills at
         the stop level, or at the open when the open gapped through it;
         same-direction re-entry is then blocked until the state changes;
      4. the position marks from open to close;
      5. at the final bar an open position force-closes at the close.

    ``lag_bars`` adds extra execution delay (robustness diagnostic only).
    """
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    n = i1 - i0
    equity = np.empty(n)
    times = pd.DatetimeIndex(bars.index[i0:i1])

    E = INITIAL_EQUITY
    pos = 0
    frac = 0.0
    blocked = 0
    stop_px = math.nan
    entry_i = -1
    entry_px = math.nan
    tr_gross = 0.0
    tr_cost = 0.0
    trades: list[XTrade] = []
    turnover = 0.0
    cost_total = 0.0
    gross_total = 0.0
    reb_flags = None if rebalance is None else np.asarray(rebalance, dtype=bool)
    pending: tuple[float, float, float, bool] | None = None
    prev_close = math.nan

    def close_trade(j: int, px: float, stopped: bool, forced: bool) -> None:
        nonlocal tr_gross, tr_cost, pos, frac, stop_px, entry_i
        trades.append(
            XTrade(
                pos, entry_i, j, times[entry_i - i0], times[j - i0], entry_px, px, tr_gross, tr_cost, stopped, forced, frac
            )
        )
        tr_gross = 0.0
        tr_cost = 0.0
        pos = 0
        frac = 0.0
        stop_px = math.nan
        entry_i = -1

    for i in range(i0, i1):
        op, hi, low, cl = o[i], h[i], lo[i], c[i]
        # 1. gap mark
        if pos != 0 and i > i0:
            pnl = pos * frac * E * (op / prev_close - 1.0)
            E += pnl
            tr_gross += pnl
            gross_total += pnl
        # 2. previous close's decision fills at this open
        if pending is not None:
            tgt, sz, sd, reb = pending
            if math.isfinite(tgt):
                if tgt != blocked:
                    blocked = 0
                if tgt != pos:
                    if pos != 0:
                        cost = frac * E * side_rate(op, mult)
                        E -= cost
                        tr_cost += cost
                        cost_total += cost
                        turnover += frac
                        close_trade(i, op, stopped=False, forced=False)
                    if tgt != 0 and tgt != blocked and math.isfinite(sz) and sz > 0:
                        f = min(float(sz), MAX_FRACTION)
                        cost = f * E * side_rate(op, mult)
                        E -= cost
                        pos = int(tgt)
                        frac = f
                        entry_px = op
                        entry_i = i
                        stop_px = op - pos * sd if math.isfinite(sd) else math.nan
                        tr_gross = 0.0
                        tr_cost = cost
                        cost_total += cost
                        turnover += f
                        blocked = 0
                elif reb and pos != 0 and math.isfinite(sz):
                    # calendar rebalance: resize the open position to ``size``
                    new_f = min(float(sz), MAX_FRACTION)
                    delta = new_f - frac
                    if abs(delta) > 1e-12:
                        cost = abs(delta) * E * side_rate(op, mult)
                        E -= cost
                        tr_cost += cost
                        cost_total += cost
                        turnover += abs(delta)
                        frac = new_f
        # 3. stop against this bar's range
        if pos != 0 and math.isfinite(stop_px):
            hit = (pos > 0 and low <= stop_px) or (pos < 0 and hi >= stop_px)
            if hit:
                x = min(op, stop_px) if pos > 0 else max(op, stop_px)
                pnl = pos * frac * E * (x / op - 1.0)
                E += pnl
                tr_gross += pnl
                gross_total += pnl
                cost = frac * E * side_rate(x, mult)
                E -= cost
                tr_cost += cost
                cost_total += cost
                turnover += frac
                blocked = pos
                close_trade(i, x, stopped=True, forced=False)
        # 4. open->close mark
        if pos != 0:
            pnl = pos * frac * E * (cl / op - 1.0)
            E += pnl
            tr_gross += pnl
            gross_total += pnl
        # 5. force close at the end of the window
        if i == i1 - 1 and pos != 0:
            cost = frac * E * side_rate(cl, mult)
            E -= cost
            tr_cost += cost
            cost_total += cost
            turnover += frac
            close_trade(i, cl, stopped=False, forced=True)
        equity[i - i0] = E
        prev_close = cl
        # 6. decision for the next bar, from this close (optionally lagged)
        j = i - lag_bars
        if i + 1 < i1 and j >= 0:
            reb = bool(reb_flags[j]) if reb_flags is not None else False
            pending = (float(target[j]), float(size[j]), float(stop_dist[j]), reb)
        else:
            pending = None

    return XRun(times, equity, trades, INITIAL_EQUITY, turnover, cost_total, gross_total)


def window_bounds(index: pd.DatetimeIndex, start: str, end: str) -> tuple[int, int]:
    """Half-open [i0, i1) of bars stamped within [start, end] inclusive."""
    i0 = int(index.searchsorted(pd.Timestamp(start), side="left"))
    i1 = int(index.searchsorted(pd.Timestamp(end) + pd.Timedelta(days=1), side="left"))
    return i0, i1


# ------------------------------------------------------------------ independent signals


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def atr14(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def realized_vol(close: pd.Series, n: int, ann: float) -> pd.Series:
    return np.log(close).diff().rolling(n, min_periods=n).std() * math.sqrt(ann)


def size_stop(stop_mult: float, df: pd.DataFrame) -> pd.Series:
    stop_pct = stop_mult * atr14(df) / df["close"]
    return (RISK_PER_TRADE / stop_pct.replace(0.0, np.nan)).clip(upper=MAX_FRACTION)


def size_volt(close: pd.Series, n: int, ann: float) -> pd.Series:
    return (VOL_TARGET / realized_vol(close, n, ann).replace(0.0, np.nan)).clip(upper=MAX_FRACTION)


@dataclass
class XPlan:
    target: np.ndarray
    size: np.ndarray
    stop: np.ndarray
    cid: str
    rebalance: np.ndarray | None = None  # bool flags: resize an open position to ``size``


def x_ma_cross(df: pd.DataFrame, fast: int, slow: int, stop_mult: float | None, ann: float, vol_n: int) -> XPlan:
    f, s = sma(df["close"], fast), sma(df["close"], slow)
    valid = (f.notna() & s.notna()).to_numpy()
    state = np.where(valid, np.where(f > s, 1.0, -1.0), np.nan)
    if stop_mult is None:
        size = size_volt(df["close"], vol_n, ann).to_numpy()
        stop = np.full(len(df), np.nan)
    else:
        size = size_stop(stop_mult, df).to_numpy()
        stop = (stop_mult * atr14(df)).to_numpy()
    return XPlan(state, size, stop, f"ma_{fast}_{slow}_{stop_mult}")


def x_donchian(df: pd.DataFrame, entry: int, exit_n: int, stop_mult: float, gate: np.ndarray | None = None) -> XPlan:
    hi_n = df["high"].shift(1).rolling(entry, min_periods=entry).max()
    lo_n = df["low"].shift(1).rolling(entry, min_periods=entry).min()
    hi_m = df["high"].shift(1).rolling(exit_n, min_periods=exit_n).max()
    lo_m = df["low"].shift(1).rolling(exit_n, min_periods=exit_n).min()
    cl = df["close"]
    up = (cl > hi_n).to_numpy()
    dn = (cl < lo_n).to_numpy()
    if gate is not None:
        up = up & gate
        dn = dn & gate
    ex_l = (cl < lo_m).to_numpy()
    ex_s = (cl > hi_m).to_numpy()
    valid = (hi_n.notna() & lo_m.notna()).to_numpy()
    n = len(df)
    state = np.zeros(n)
    s = 0.0
    for t in range(n):
        if not valid[t]:
            state[t] = np.nan
            continue
        if up[t]:
            s = 1.0
        elif dn[t]:
            s = -1.0
        elif (s == 1.0 and ex_l[t]) or (s == -1.0 and ex_s[t]):
            s = 0.0
        state[t] = s
    return XPlan(state, size_stop(stop_mult, df).to_numpy(), (stop_mult * atr14(df)).to_numpy(), f"don_{entry}_{exit_n}")


def x_range_expansion(df: pd.DataFrame, k: float, hold: int, stop_mult: float = 2.0) -> XPlan:
    prev_atr = atr14(df, 20).shift(1)
    body = df["close"] - df["open"]
    up = (body > k * prev_atr).to_numpy()
    dn = (body < -k * prev_atr).to_numpy()
    valid = prev_atr.notna().to_numpy()
    n = len(df)
    state = np.zeros(n)
    s = 0.0
    exit_at = -1
    for t in range(n):
        if not valid[t]:
            state[t] = np.nan
            continue
        if up[t]:
            s, exit_at = 1.0, t + hold
        elif dn[t]:
            s, exit_at = -1.0, t + hold
        elif t >= exit_at:
            s = 0.0
        state[t] = s
    return XPlan(state, size_stop(stop_mult, df).to_numpy(), (stop_mult * atr14(df)).to_numpy(), f"rexp_{k}_{hold}")


def x_session_breakout(df: pd.DataFrame, buffer_atr: float) -> XPlan:
    """Asian-range breakout, from prereg M15 §5 (session_brk rows)."""
    idx = pd.DatetimeIndex(df.index)
    n = len(df)
    hour = np.asarray(idx.hour)
    day = pd.DatetimeIndex(idx + pd.Timedelta(hours=SESSION_ROLL_HOURS)).normalize()
    in_asia = (hour >= 0) & (hour < 7)
    asia_hi = pd.Series(np.where(in_asia, df["high"].to_numpy(float), np.nan), index=day).groupby(level=0).max()
    asia_lo = pd.Series(np.where(in_asia, df["low"].to_numpy(float), np.nan), index=day).groupby(level=0).min()
    asia_n = pd.Series(in_asia.astype(int), index=day).groupby(level=0).sum()
    rng_hi = asia_hi.reindex(day).to_numpy(float)
    rng_lo = asia_lo.reindex(day).to_numpy(float)
    rng_n = asia_n.reindex(day).to_numpy(float)
    ok = np.isfinite(rng_hi) & np.isfinite(rng_lo) & (rng_n >= 8)
    close = df["close"].to_numpy(float)
    a = atr14(df).to_numpy(float)
    warm = np.isfinite(a)
    target = np.full(n, np.nan)
    stop = np.full(n, np.nan)
    size = np.full(n, np.nan)
    state = 0.0
    for t in range(n):
        if not warm[t]:
            continue
        hh = hour[t]
        if hh < 7 or hh >= 19:
            state = 0.0
        elif state == 0.0 and ok[t] and hh < 16:
            buf = buffer_atr * a[t]
            if close[t] > rng_hi[t] + buf:
                state = 1.0
                stop[t] = close[t] - rng_lo[t]
            elif close[t] < rng_lo[t] - buf:
                state = -1.0
                stop[t] = rng_hi[t] - close[t]
            if state != 0.0:
                sd = stop[t]
                size[t] = min(MAX_FRACTION, RISK_PER_TRADE / (sd / close[t])) if sd > 0 else np.nan
        target[t] = state
    return XPlan(target, size, stop, f"sess_{buffer_atr}")


def x_buy_hold(bars: pd.DataFrame, i0: int, i1: int, mult: float = 1.0) -> XRun:
    """Reference baseline: long 1.0x from the window's first open.

    Mirrors the pre-registered baseline: the decision sits on the bar before the
    window and the anchor bar's flat equity is dropped, so returns start at the
    window's first bar.
    """
    n = len(bars)
    target = np.full(n, np.nan)
    size = np.full(n, np.nan)
    stop = np.full(n, np.nan)
    anchor = i0 - 1 if i0 >= 1 else 0
    target[anchor] = 1.0
    size[anchor] = 1.0
    run = xrun(bars, target, size, stop, anchor, i1, mult)
    if i0 >= 1:
        return XRun(
            run.times[1:],
            run.equity[1:],
            run.trades,
            run.initial_equity,
            run.turnover,
            run.cost_usd,
            run.gross_usd,
        )
    return run


# ------------------------------------------------------------------ daily-only families


def month_end_flags(index: pd.DatetimeIndex) -> np.ndarray:
    """True on the last bar of each calendar month (knowable only ex post; the
    decision written on that bar fills at the NEXT open, by which time the flag
    is true -- the same calendar exemption the repo's truncation check uses)."""
    s = pd.Series(pd.DatetimeIndex(index), index=pd.DatetimeIndex(index))
    last = s.groupby(pd.DatetimeIndex(index).to_period("M")).transform("max")
    return np.asarray(last.values == s.values)


def x_tsmom(df: pd.DataFrame, lookback: int) -> XPlan:
    """Sign of trailing return, changed at month ends, vol-targeted size."""
    close = df["close"]
    trailing = close / close.shift(lookback) - 1.0
    sig = np.sign(trailing.to_numpy())
    me = month_end_flags(pd.DatetimeIndex(df.index))
    target = np.where(me & np.isfinite(sig), sig, np.nan)
    size = size_volt(close, DAILY_VOL_WINDOW, DAILY_PPY).to_numpy()
    return XPlan(target, size, np.full(len(df), np.nan), f"tsmom_L{lookback}", rebalance=me)


def _wilder_rsi(close: pd.Series, n: int) -> np.ndarray:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.where(avg_loss != 0.0, 100.0).to_numpy()


def x_rsi2(df: pd.DataFrame, threshold: float, trend_filter: bool, time_exit: int = 5) -> XPlan:
    """Connors RSI(2): buy oversold (optionally above SMA200), exit above SMA(5) or on time."""
    close = df["close"]
    r = _wilder_rsi(close, 2)
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
        ok_long = (not trend_filter) or (np.isfinite(s200[t]) and c[t] > s200[t])
        ok_short = (not trend_filter) or (np.isfinite(s200[t]) and c[t] < s200[t])
        if s == 0.0:
            if r[t] < threshold and ok_long:
                s, entry_t = 1.0, t
            elif r[t] > 100.0 - threshold and ok_short:
                s, entry_t = -1.0, t
        elif (s == 1.0 and (c[t] > s5[t] or t - entry_t >= time_exit)) or (
            s == -1.0 and (c[t] < s5[t] or t - entry_t >= time_exit)
        ):
            s = 0.0
        state[t] = s
    return XPlan(state, size_volt(close, DAILY_VOL_WINDOW, DAILY_PPY).to_numpy(), np.full(n, np.nan), f"rsi2_{threshold}")


def x_nr7(df: pd.DataFrame, hold: int, stop_mult: float = 2.0, window: int = 5) -> XPlan:
    """Narrowest-range-of-7 setup; close through its range within ``window`` bars trades."""
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
    hi_lvl = math.nan
    lo_lvl = math.nan
    setup_at = -(10**9)
    for t in range(n):
        if is_nr7[t]:
            hi_lvl, lo_lvl, setup_at = high[t], low[t], t
            continue
        if 0 < t - setup_at <= window:
            if close[t] > hi_lvl:
                up[t] = True
                setup_at = -(10**9)
            elif close[t] < lo_lvl:
                dn[t] = True
                setup_at = -(10**9)
    valid = np.ones(n, dtype=bool)
    valid[:6] = False
    state = np.zeros(n)
    s = 0.0
    exit_at = -1
    for t in range(n):
        if not valid[t]:
            state[t] = np.nan
            continue
        if up[t]:
            s, exit_at = 1.0, t + hold
        elif dn[t]:
            s, exit_at = -1.0, t + hold
        elif t >= exit_at:
            s = 0.0
        state[t] = s
    return XPlan(state, size_stop(stop_mult, df).to_numpy(), (stop_mult * atr14(df)).to_numpy(), f"nr7_{hold}")


def x_bollinger(df: pd.DataFrame, n_: int = 20, k: float = 2.0) -> XPlan:
    """CONTROL: fade band excursions, exit at the mean. Falsification benchmark only."""
    close = df["close"]
    mid = sma(close, n_)
    sd = close.rolling(n_, min_periods=n_).std()
    upper = (mid + k * sd).to_numpy()
    lower = (mid - k * sd).to_numpy()
    m = mid.to_numpy()
    c = close.to_numpy()
    nn = len(df)
    state = np.zeros(nn)
    s = 0.0
    for t in range(nn):
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
    return XPlan(state, size_volt(close, DAILY_VOL_WINDOW, DAILY_PPY).to_numpy(), np.full(nn, np.nan), "bollinger_control")


def x_efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    net = (close - close.shift(n)).abs()
    path = close.diff().abs().rolling(n, min_periods=n).sum()
    return net / path.replace(0.0, np.nan)


def x_gated_donchian(df: pd.DataFrame, threshold: float) -> XPlan:
    """Donchian 55/20 with a Kaufman efficiency-ratio(60) entry gate (daily trend_gated)."""
    gate = (x_efficiency_ratio(df["close"], 60) >= threshold).astype(float).fillna(0.0).to_numpy().astype(bool)
    plan = x_donchian(df, 55, 20, 3.0, gate=gate)
    return XPlan(plan.target, plan.size, plan.stop, f"gated_er60_{threshold}", plan.rebalance)


# ------------------------------------------------------------------ independent stats


def xsharpe(r: np.ndarray, ppy: float) -> float:
    r = np.asarray(r, float)
    if r.size < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd == 0.0 or not math.isfinite(sd):
        return 0.0
    return float(np.mean(r) / sd * math.sqrt(ppy))


def xmaxdd(equity: np.ndarray, initial: float) -> float:
    e = np.concatenate([[initial], np.asarray(equity, float)])
    peak = np.maximum.accumulate(e)
    return float(np.min(e / peak - 1.0))


def xblock_bootstrap(r: np.ndarray, stat: Any, n_boot: int, block: int, seed: int) -> np.ndarray:
    """Circular block bootstrap (keeps short-range dependence)."""
    r = np.asarray(r, float)
    n = r.size
    if n < 2:
        return np.zeros(n_boot)
    block = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    out = np.empty(n_boot)
    offs = np.arange(block)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = ((starts[:, None] + offs[None, :]) % n).ravel()[:n]
        out[b] = stat(r[idx])
    return out


def xholm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj: dict[str, float] = {}
    running = 0.0
    for rank, (k, p) in enumerate(items):
        val = min(1.0, (m - rank) * p)
        running = max(running, val)
        adj[k] = running
    return adj


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Acklam's rational approximation to the normal inverse CDF."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


EULER_GAMMA = 0.5772156649015329


def xdsr(returns: np.ndarray, n_trials: int, ppy: float) -> dict[str, float]:
    """Deflated Sharpe ratio, from Bailey & Lopez de Prado (2014), implemented fresh.

    PSR(SR*) = Phi( (SR - SR*) * sqrt(n-1) / sqrt(1 - g3*SR + (g4-1)/4*SR^2) )
    with per-period SR; benchmark SR0 = E[max of N null Sharpes].
    """
    r = np.asarray(returns, float)
    n = int(r.size)
    sr_ann = xsharpe(r, ppy)
    if n < 30 or n_trials < 1:
        return {"dsr": math.nan, "sharpe_annual": sr_ann, "n": n, "n_trials": n_trials}
    sr = sr_ann / math.sqrt(ppy)  # per-period
    sd = float(np.std(r, ddof=1))
    g3 = float(np.mean(((r - r.mean()) / sd) ** 3)) if sd > 0 else 0.0
    g4 = float(np.mean(((r - r.mean()) / sd) ** 4)) if sd > 0 else 3.0
    # expected max of N standard normals (Lopez de Prado, DSRToolbox)
    if n_trials <= 1:
        sr0 = 0.0
    else:
        em = (1.0 - EULER_GAMMA) * _norm_ppf(1.0 - 1.0 / n_trials) + EULER_GAMMA * _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
        sr0 = em / math.sqrt(n - 1)  # per-period benchmark under the null
    denom = math.sqrt(max(1e-12, 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr))
    z = (sr - sr0) * math.sqrt(n - 1) / denom
    return {"dsr": _norm_cdf(z), "sharpe_annual": sr_ann, "n": n, "n_trials": n_trials}


# ------------------------------------------------------------------ data loading


def trading_day(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.DatetimeIndex(index) + pd.Timedelta(hours=SESSION_ROLL_HOURS)).normalize()


def load_m15(name: str, complete_days_only: bool = True) -> pd.DataFrame:
    raw = pd.read_csv(PROCESSED / name)
    index = pd.to_datetime(raw["time"], utc=True).dt.tz_convert(None)
    frame = raw[["open", "high", "low", "close", "volume"]].astype(float)
    frame.index = pd.DatetimeIndex(index, name="stamp")
    if complete_days_only:
        labels = trading_day(frame.index)
        counts = pd.Series(1, index=labels).groupby(level=0).sum()
        complete = counts[counts >= MIN_BARS_PER_DAY].index
        frame = frame.loc[np.asarray(labels.isin(complete))]
    if frame.index.duplicated().any():
        raise SystemExit(f"duplicate stamps in {name}")
    return frame


def load_daily(name: str) -> pd.DataFrame:
    raw = pd.read_csv(PROCESSED / name)
    index = pd.to_datetime(raw["time"], utc=True).dt.tz_convert(None).dt.normalize()
    frame = raw[["open", "high", "low", "close", "volume"]].astype(float)
    frame.index = pd.DatetimeIndex(index, name="day")
    return frame[~frame.index.duplicated()]


# ------------------------------------------------------------------ candidate grids

# M15 grid (preregistration_longhistory_m15 §5); (cid, group, builder-partial)


def m15_plans(df: pd.DataFrame) -> dict[str, XPlan]:
    plans: dict[str, XPlan] = {}
    for f_, s_, st_ in [(16, 64, None), (16, 64, 3.0), (32, 128, None), (32, 128, 3.0), (64, 256, None), (64, 256, 3.0)]:
        tag = "nostop" if st_ is None else "atr3"
        plans[f"ma_{f_}_{s_}_{tag}"] = x_ma_cross(df, f_, s_, st_, M15_PPY, M15_VOL_BARS)
    for e_, x_, st_ in [(96, 48, 2.0), (96, 48, 3.0), (384, 192, 3.0)]:
        plans[f"donchian_{e_}_{x_}_atr{int(st_)}"] = x_donchian(df, e_, x_, st_)
    plans["rexp_k10_h4"] = x_range_expansion(df, 1.0, 4)
    plans["rexp_k10_h16"] = x_range_expansion(df, 1.0, 16)
    plans["session_brk_b0"] = x_session_breakout(df, 0.0)
    plans["session_brk_b025"] = x_session_breakout(df, 0.25)
    return plans


M15_GROUPS: dict[str, list[str]] = {
    "ma_cross": ["ma_16_64_nostop", "ma_16_64_atr3", "ma_32_128_nostop", "ma_32_128_atr3", "ma_64_256_nostop", "ma_64_256_atr3"],
    "donchian": ["donchian_96_48_atr2", "donchian_96_48_atr3", "donchian_384_192_atr3"],
    "volatility_expansion": ["rexp_k10_h4", "rexp_k10_h16"],
    "session_breakout": ["session_brk_b0", "session_brk_b025"],
}


# ------------------------------------------------------------------ protocol re-runs


def select_group(
    df: pd.DataFrame,
    plans: dict[str, XPlan],
    cids: list[str],
    train_start: str,
    train_end: str,
    ppy: float = M15_PPY,
) -> dict[str, Any]:
    """Prereg §6: highest training-window net Sharpe at base cost, >=20 turns, ties earlier."""
    a, b = window_bounds(df.index, train_start, train_end)
    best: tuple[float, str] | None = None
    table = []
    for cid in cids:
        p = plans[cid]
        run = xrun(df, p.target, p.size, p.stop, a, b, rebalance=p.rebalance)
        sr = xsharpe(run.returns, ppy)
        turns = len(run.trades)
        table.append({"cid": cid, "train_sharpe": round(sr, 4), "train_round_turns": turns})
        if turns >= MIN_TRAIN_ROUND_TURNS and (best is None or sr > best[0] + 1e-12):
            best = (sr, cid)
    return {"cid": best[1] if best else None, "table": table}


PPY_OF: dict[str, float] = {"m15": M15_PPY, "daily": DAILY_PPY}


def run_frozen_m15(df: pd.DataFrame, plans: dict[str, XPlan], quick: bool) -> dict[str, Any]:
    """Re-derive the M15 study: holdout selection, holdout runs, WF folds."""
    out: dict[str, Any] = {"holdout": {}, "walk_forward": {}, "selection": {}}
    # holdout selection: train through DEV_END
    sel: dict[str, Any] = {}
    for group, cids in M15_GROUPS.items():
        sel[group] = select_group(df, plans, cids, RESEARCH_START, DEV_END)
    out["selection"] = {g: s["cid"] for g, s in sel.items()}
    a, b = window_bounds(df.index, HOLDOUT_START, RESEARCH_END)
    for group, s in sel.items():
        cid = s["cid"]
        p = plans[cid]
        rec: dict[str, Any] = {"cid": cid}
        for label, mult in [("base", 1.0), ("x2", 2.0), ("x3", 3.0), ("zero", 0.0)]:
            run = xrun(df, p.target, p.size, p.stop, a, b, mult=mult)
            rec[label] = summarize_xrun(run, M15_PPY)
        rec["break_even"] = x_break_even(df, p, a, b)
        out["holdout"][group] = rec
    # walk-forward
    folds: list[dict[str, Any]] = []
    for year in WF_YEARS:
        fsel = {}
        for group, cids in M15_GROUPS.items():
            fsel[group] = select_group(df, plans, cids, RESEARCH_START, f"{year - 1}-12-31")
        ta, tb = window_bounds(df.index, f"{year}-01-01", f"{year}-12-31")
        rec: dict[str, Any] = {"year": year, "groups": {}}
        for group, s in fsel.items():
            if s["cid"] is None:
                rec["groups"][group] = {"cid": None, "net_usd": 0.0, "round_turns": 0}
                continue
            p = plans[s["cid"]]
            run = xrun(df, p.target, p.size, p.stop, ta, tb)
            rec["groups"][group] = {
                "cid": s["cid"],
                "net_usd": round(run.net_usd, 2),
                "round_turns": len(run.trades),
                "sharpe": round(xsharpe(run.returns, M15_PPY), 4),
            }
        folds.append(rec)
        if quick and year >= 2012:
            break
    out["walk_forward"] = folds
    return out


def summarize_xrun(run: XRun, ppy: float) -> dict[str, Any]:
    nets = np.array([t.net_usd for t in run.trades], float)
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    years = max(len(run.times), 1) / ppy
    return {
        "net_usd": round(run.net_usd, 2),
        "gross_usd": round(run.gross_usd, 2),
        "cost_usd": round(run.cost_usd, 2),
        "sharpe": round(xsharpe(run.returns, ppy), 4),
        "max_drawdown": round(xmaxdd(run.equity, run.initial_equity), 4),
        "round_turns": len(run.trades),
        "win_rate": round(float(wins.size / nets.size), 4) if nets.size else 0.0,
        "expectancy_usd": round(float(nets.mean()), 4) if nets.size else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 4) if losses.size and losses.sum() < 0 else None,
        "turnover_per_year": round(run.turnover / years, 3) if years else 0.0,
        "mean_bars_held": round(float(np.mean([t.exit_bar - t.entry_bar for t in run.trades])), 2) if run.trades else 0.0,
        "final_equity": round(float(run.equity[-1]), 2) if len(run.equity) else INITIAL_EQUITY,
    }


def x_break_even(df: pd.DataFrame, p: XPlan, a: int, b: int, hi: float = 50.0) -> dict[str, Any]:
    if xrun(df, p.target, p.size, p.stop, a, b, mult=0.0, rebalance=p.rebalance).net_usd <= 0:
        return {"value": 0.0, "status": "NEGATIVE_EVEN_AT_ZERO_COST"}
    if xrun(df, p.target, p.size, p.stop, a, b, mult=hi, rebalance=p.rebalance).net_usd > 0:
        return {"value": hi, "status": f"POSITIVE_AT_{hi:g}X"}
    lo_m, hi_m = 0.0, hi
    for _ in range(30):
        mid = 0.5 * (lo_m + hi_m)
        if xrun(df, p.target, p.size, p.stop, a, b, mult=mid, rebalance=p.rebalance).net_usd > 0:
            lo_m = mid
        else:
            hi_m = mid
    return {"value": round(0.5 * (lo_m + hi_m), 4), "status": "CROSSES_ZERO"}


# ------------------------------------------------------------------ daily study verification


def daily_plans(df: pd.DataFrame) -> dict[str, XPlan]:
    """The frozen daily candidate grid (preregistration_longhistory §4-5)."""
    plans: dict[str, XPlan] = {}
    for lb in (63, 126, 252):
        plans[f"tsmom_L{lb}"] = x_tsmom(df, lb)
    for f_, s_ in ((20, 100), (20, 200), (50, 200)):
        for st_ in (None, 3.0):
            tag = "nostop" if st_ is None else "atr3"
            plans[f"ma_{f_}_{s_}_{tag}"] = x_ma_cross(df, f_, s_, st_, DAILY_PPY, DAILY_VOL_WINDOW)
    for e_, x_ in ((20, 10), (55, 20)):
        for st_ in (2.0, 3.0):
            plans[f"donchian_{e_}_{x_}_atr{int(st_)}"] = x_donchian(df, e_, x_, st_)
    for k_, tag in ((0.5, "k05"), (1.0, "k10")):
        for h_ in (1, 3):
            plans[f"rexp_{tag}_h{h_}"] = x_range_expansion(df, k_, h_)
    for h_ in (3, 5):
        plans[f"nr7_h{h_}"] = x_nr7(df, h_)
    for th, tag in ((0.25, "025"), (0.35, "035")):
        plans[f"gated_er60_{tag}"] = x_gated_donchian(df, th)
    for th, tag in ((5.0, "t5"), (10.0, "t10")):
        for filt, ftag in ((False, "nofilter"), (True, "sma200")):
            plans[f"rsi2_{tag}_{ftag}"] = x_rsi2(df, th, filt)
    plans["bollinger_20_2_control"] = x_bollinger(df, 20, 2.0)
    return plans


DAILY_GROUPS: dict[str, list[str]] = {
    "tsmom": ["tsmom_L63", "tsmom_L126", "tsmom_L252"],
    "ma_cross": [
        "ma_20_100_nostop", "ma_20_100_atr3", "ma_20_200_nostop", "ma_20_200_atr3", "ma_50_200_nostop", "ma_50_200_atr3",
    ],
    "donchian": ["donchian_20_10_atr2", "donchian_20_10_atr3", "donchian_55_20_atr2", "donchian_55_20_atr3"],
    "volatility_expansion": ["rexp_k05_h1", "rexp_k05_h3", "rexp_k10_h1", "rexp_k10_h3", "nr7_h3", "nr7_h5"],
    "trend_gated": ["gated_er60_025", "gated_er60_035"],
    "mean_reversion": ["rsi2_t5_nofilter", "rsi2_t5_sma200", "rsi2_t10_nofilter", "rsi2_t10_sma200"],
}


def regime_labels_x(df: pd.DataFrame, trend_bars: int, vol_bars: int, ann: float, min_bars: int) -> pd.Series:
    """Causal mechanical regimes: 12-month trend sign x vol vs expanding median."""
    close = df["close"]
    trend = np.sign(close / close.shift(trend_bars) - 1.0)
    vol = realized_vol(close, vol_bars, ann)
    vol_med = vol.expanding(min_periods=min_bars).median()
    hi = vol > vol_med
    names = np.where(trend > 0, "UP", "DOWN") + np.where(hi, "_HIVOL", "_LOWVOL")
    labels = pd.Series(names, index=df.index, dtype=object)
    labels[trend.isna() | vol_med.isna()] = None
    return labels


def attribute_regimes(stamps: list, pnls: list, labels: pd.Series) -> dict[str, dict[str, float | int]]:
    days = np.concatenate([np.asarray(d) for d in stamps]) if stamps else np.array([], dtype="datetime64[ns]")
    pnl = np.concatenate([np.asarray(x) for x in pnls]) if pnls else np.array([])
    aligned = labels.reindex(pd.DatetimeIndex(days)).to_numpy() if len(days) else np.array([], dtype=object)
    out: dict[str, dict[str, float | int]] = {}
    for regime in ("UP_HIVOL", "UP_LOWVOL", "DOWN_HIVOL", "DOWN_LOWVOL"):
        mask = np.asarray(aligned == regime, dtype=bool)
        out[regime] = {
            "days": int(mask.sum()),
            "net_usd": round(float(pnl[mask].sum()), 2) if mask.any() else 0.0,
        }
    return out


def run_pnl_series(run: XRun) -> tuple[np.ndarray, np.ndarray]:
    eq = np.concatenate([[run.initial_equity], run.equity])
    return np.asarray(run.times), np.diff(eq)


def verify_regimes(
    df: pd.DataFrame,
    plans: dict[str, XPlan],
    groups: dict[str, list[str]],
    sel: dict[str, Any],
    committed: dict[str, Any],
    labels: pd.Series,
    ppy: float,
    tag: str,
) -> list[dict[str, Any]]:
    """Independently re-derive the G7 regime attribution (WF composite + holdout)."""
    out: list[dict[str, Any]] = []
    a, b = window_bounds(df.index, HOLDOUT_START, RESEARCH_END)
    for group in groups:
        if group not in sel or sel[group] is None:
            continue
        stamps: list[np.ndarray] = []
        pnls: list[np.ndarray] = []
        for year in WF_YEARS:
            fsel = select_group(df, plans, groups[group], RESEARCH_START, f"{year - 1}-12-31", ppy=ppy)
            if fsel["cid"] is None:
                continue
            p = plans[fsel["cid"]]
            ta, tb = window_bounds(df.index, f"{year}-01-01", f"{year}-12-31")
            r = xrun(df, p.target, p.size, p.stop, ta, tb, rebalance=p.rebalance)
            s_, v_ = run_pnl_series(r)
            stamps.append(s_)
            pnls.append(v_)
        p = plans[sel[group]]
        r = xrun(df, p.target, p.size, p.stop, a, b, rebalance=p.rebalance)
        s_, v_ = run_pnl_series(r)
        stamps.append(s_)
        pnls.append(v_)
        mine = attribute_regimes(stamps, pnls, labels)
        theirs = committed["gates"][group]["regimes_oos"]
        for regime in mine:
            out.append(compare(f"{tag}_regimes[{group}][{regime}].days", mine[regime]["days"], theirs[regime]["days"], 0))
            out.append(compare(f"{tag}_regimes[{group}][{regime}].net", mine[regime]["net_usd"], theirs[regime]["net_usd"], 0.02))
    return out


def run_daily_checks(daily: pd.DataFrame, committed: dict[str, Any], quick: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Full independent verification of the daily study LH-XAUUSD-D1-2026-10-10."""
    checks: list[dict[str, Any]] = []
    plans = daily_plans(daily)
    a, b = window_bounds(daily.index, HOLDOUT_START, RESEARCH_END)
    sel: dict[str, Any] = {}
    for group, cids in DAILY_GROUPS.items():
        s = select_group(daily, plans, cids, RESEARCH_START, DEV_END, ppy=DAILY_PPY)
        sel[group] = s["cid"]
        checks.append(compare(f"daily_holdout_selection[{group}]", s["cid"], committed["holdout_selection_summary"][group], 0))
    for group, cid in sel.items():
        if cid is None:
            continue
        p = plans[cid]
        run = xrun(daily, p.target, p.size, p.stop, a, b, rebalance=p.rebalance)
        summ = summarize_xrun(run, DAILY_PPY)
        theirs = committed["holdout"]["groups"][group]["base"]
        for k, tol in [
            ("net_usd", 0.001), ("sharpe", 0.01), ("round_turns", 0), ("max_drawdown", 0.01),
            ("cost_usd", 0.005), ("gross_usd", 0.005),
        ]:
            checks.append(compare(f"daily_holdout[{group}].{k}", summ[k], theirs[k], tol))
        for m_ in (2.0, 3.0):
            r2 = xrun(daily, p.target, p.size, p.stop, a, b, mult=m_, rebalance=p.rebalance)
            checks.append(compare(f"daily_holdout[{group}].net@{m_}x", round(r2.net_usd, 2), committed["holdout"]["groups"][group]["stress"][f"{m_:g}x"]["net_usd"], 0.001))
        be = x_break_even(daily, p, a, b)
        checks.append(compare(f"daily_holdout[{group}].break_even", be["value"], committed["holdout"]["groups"][group]["break_even_multiplier"]["value"], 0.02))
    # buy-and-hold
    bh = x_buy_hold(daily, a, b)
    sb = summarize_xrun(bh, DAILY_PPY)
    tb = committed["benchmarks"]["buy_and_hold_long"]["holdout"]
    for k, tol in [("net_usd", 0.001), ("sharpe", 0.01), ("max_drawdown", 0.01)]:
        checks.append(compare(f"daily_buyhold.{k}", sb[k], tb[k], tol))
    # walk-forward folds
    if not quick:
        for fold in committed["walk_forward"]["folds"]:
            year = fold["year"]
            for group, cids in DAILY_GROUPS.items():
                fsel = select_group(daily, plans, cids, RESEARCH_START, f"{year - 1}-12-31", ppy=DAILY_PPY)
                theirs = fold["selection"][group]
                checks.append(compare(f"daily_wf[{year}].sel[{group}]", fsel["cid"], theirs["cid"], 0))
                if fsel["cid"] is None:
                    continue
                p = plans[fsel["cid"]]
                ta, tb2 = window_bounds(daily.index, f"{year}-01-01", f"{year}-12-31")
                run = xrun(daily, p.target, p.size, p.stop, ta, tb2, rebalance=p.rebalance)
                checks.append(compare(f"daily_wf[{year}].net[{group}]", round(run.net_usd, 2), theirs["net_usd"], 0.001))
                checks.append(compare(f"daily_wf[{year}].turns[{group}]", len(run.trades), theirs["round_turns"], 0))
        # regime re-derivation (G7) for the daily study
        labels = regime_labels_x(daily, 252, DAILY_VOL_WINDOW, DAILY_PPY, 252)
        checks.extend(verify_regimes(daily, plans, DAILY_GROUPS, sel, committed, labels, DAILY_PPY, "daily"))
    return checks, sel


# ------------------------------------------------------------------ comparison helpers


def compare(label: str, mine: Any, theirs: Any, tol: float) -> dict[str, Any]:
    if isinstance(mine, float) and isinstance(theirs, float):
        ok = abs(mine - theirs) <= tol * max(1.0, abs(theirs))
    else:
        ok = mine == theirs
    return {"item": label, "mine": mine, "theirs": theirs, "match": bool(ok)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="engine cross-check only (short WF)")
    args = parser.parse_args()

    if not (PROCESSED / "xauusd_basemax_utc_15m_20040611_20250228.csv").exists():
        raise SystemExit("processed series missing: run fetch_longhistory_sources.py + build_longhistory_dataset.py")

    m15 = load_m15("xauusd_basemax_utc_15m_20040611_20250228.csv")
    labels = trading_day(m15.index)
    m15 = m15.loc[np.asarray(labels <= pd.Timestamp(RESEARCH_END))]
    evidence = {"generated_at": datetime.now(UTC).isoformat(), "agent": "Agent 4 — independent validation", "checks": []}
    checks = evidence["checks"]

    print(f"research bars (independent load): {len(m15)}  ({m15.index[0]} → {m15.index[-1]})")
    committed = json.loads(INTRADAY_FINAL.read_text())

    # ---- 1. engine cross-check: M15 holdout ------------------------------------
    plans = m15_plans(m15)
    a, b = window_bounds(m15.index, HOLDOUT_START, RESEARCH_END)
    ho_sel_mine: dict[str, str | None] = {}
    for group, cids in M15_GROUPS.items():
        s = select_group(m15, plans, cids, RESEARCH_START, DEV_END)
        ho_sel_mine[group] = s["cid"]
        theirs_cid = committed["holdout_selection_summary"][group]
        checks.append(compare(f"m15_holdout_selection[{group}]", s["cid"], theirs_cid, 0))
    evidence["m15_holdout_selection"] = ho_sel_mine

    for group, cid in ho_sel_mine.items():
        if cid is None:
            continue
        p = plans[cid]
        run = xrun(m15, p.target, p.size, p.stop, a, b)
        summ = summarize_xrun(run, M15_PPY)
        theirs = committed["holdout"]["groups"][group]["base"]
        for k, tol in [
            ("net_usd", 0.001),
            ("sharpe", 0.01),
            ("round_turns", 0),
            ("max_drawdown", 0.01),
            ("cost_usd", 0.005),
            ("gross_usd", 0.005),
        ]:
            checks.append(compare(f"m15_holdout[{group}].{k}", summ[k], theirs[k], tol))
        # cost stresses and break-even
        for m_ in (2.0, 3.0):
            r2 = xrun(m15, p.target, p.size, p.stop, a, b, mult=m_)
            checks.append(compare(f"m15_holdout[{group}].net@{m_}x", round(r2.net_usd, 2), committed["holdout"]["groups"][group]["stress"][f"{m_:g}x"]["net_usd"], 0.001))
        be = x_break_even(m15, p, a, b)
        checks.append(compare(f"m15_holdout[{group}].break_even", be["value"], committed["holdout"]["groups"][group]["break_even_multiplier"]["value"], 0.02))
        # zero cost
        r0 = xrun(m15, p.target, p.size, p.stop, a, b, mult=0.0)
        checks.append(compare(f"m15_holdout[{group}].zero_cost_net", round(r0.net_usd, 2), committed["holdout"]["groups"][group]["gross_zero_cost_usd"], 0.001))

    # ---- 2. walk-forward cross-check -------------------------------------------
    if not args.quick:
        for fold in committed["walk_forward"]["folds"]:
            year = fold["year"]
            # recompute this fold
            fsel = {}
            for group, cids in M15_GROUPS.items():
                fsel[group] = select_group(m15, plans, cids, RESEARCH_START, f"{year - 1}-12-31")
            ta, tb = window_bounds(m15.index, f"{year}-01-01", f"{year}-12-31")
            for group, s in fsel.items():
                theirs = fold["selection"][group]
                checks.append(compare(f"m15_wf[{year}].sel[{group}]", s["cid"], theirs["cid"], 0))
                if s["cid"] is None:
                    continue
                p = plans[s["cid"]]
                run = xrun(m15, p.target, p.size, p.stop, ta, tb)
                checks.append(compare(f"m15_wf[{year}].net[{group}]", round(run.net_usd, 2), theirs["net_usd"], 0.001))
                checks.append(compare(f"m15_wf[{year}].turns[{group}]", len(run.trades), theirs["round_turns"], 0))
            print(f"  wf {year} checked")

    # ---- 3. buy-and-hold baseline ----------------------------------------------
    bh = x_buy_hold(m15, a, b)
    summ = summarize_xrun(bh, M15_PPY)
    theirs = committed["benchmarks"]["buy_and_hold_long"]["holdout"]
    for k, tol in [("net_usd", 0.001), ("sharpe", 0.01), ("max_drawdown", 0.01)]:
        checks.append(compare(f"m15_buyhold.{k}", summ[k], theirs[k], tol))

    # ---- 4. replicate cross-check (Dukascopy M15) -------------------------------
    rep = load_m15("xauusd_dukascopy_utc_15m_20250806_20260916.csv")
    ra, rb = window_bounds(pd.DatetimeIndex(rep.index), REPLICATE_START, REPLICATE_END)
    for group, cid in ho_sel_mine.items():
        if cid is None:
            continue
        pr = m15_plans(rep)[cid]
        run = xrun(rep, pr.target, pr.size, pr.stop, ra, rb)
        theirs = committed["replicate"][group]
        if theirs.get("status") == "EVALUATED":
            checks.append(compare(f"m15_replicate[{group}].net", round(run.net_usd, 2), theirs["net_usd"], 0.001))
            checks.append(compare(f"m15_replicate[{group}].turns", len(run.trades), theirs["round_turns"], 0))

    # ---- 4b. daily study: full independent verification -------------------------
    daily_sel: dict[str, Any] = {}
    if (PROCESSED / "xauusd_basemax_utc_daily_research.csv").exists():
        daily = load_daily("xauusd_basemax_utc_daily_research.csv")
        dcom = json.loads(DAILY_FINAL.read_text())
        daily_checks, daily_sel = run_daily_checks(daily, dcom, args.quick)
        checks.extend(daily_checks)
        if not args.quick and (PROCESSED / "xauusd_dukascopy_utc_daily_replicate.csv").exists():
            rep_d = load_daily("xauusd_dukascopy_utc_daily_replicate.csv")
            dplans = daily_plans(rep_d)
            ra2, rb2 = window_bounds(rep_d.index, REPLICATE_START, REPLICATE_END)
            for group, cid in daily_sel.items():
                if cid is None:
                    continue
                pr = dplans[cid]
                first_valid = int(np.argmax(np.isfinite(pr.target))) if np.isfinite(pr.target).any() else len(pr.target)
                theirs = dcom["replicate"][group]
                if first_valid > 0.25 * len(rep_d):
                    checks.append(compare(f"daily_replicate[{group}].status", "NOT_EVALUABLE_INSUFFICIENT_WARMUP", theirs["status"], 0))
                    continue
                checks.append(compare(f"daily_replicate[{group}].status", "EVALUATED", theirs["status"], 0))
                rr = xrun(rep_d, pr.target, pr.size, pr.stop, ra2, rb2, rebalance=pr.rebalance)
                checks.append(compare(f"daily_replicate[{group}].net", round(rr.net_usd, 2), theirs["net_usd"], 0.001))
                checks.append(compare(f"daily_replicate[{group}].turns", len(rr.trades), theirs["round_turns"], 0))
        evidence["daily_holdout_selection"] = daily_sel
        print(f"  daily study checked ({len(daily_checks)} checks)")

    # ---- 5. DSR / Holm / sign-randomisation statistical layer --------------------
    if not args.quick:
        stats_checks = statistical_layer(m15, plans, ho_sel_mine, committed)
        checks.extend(stats_checks)
        # M15 regime re-derivation (G7)
        m15_labels = regime_labels_x(m15, M15_REGIME_BARS, M15_VOL_BARS, M15_PPY, M15_REGIME_BARS)
        checks.extend(verify_regimes(m15, plans, M15_GROUPS, ho_sel_mine, committed, m15_labels, M15_PPY, "m15"))

    # ---- 6. diagnostics ---------------------------------------------------------
    diag = diagnostics(m15, plans, ho_sel_mine, args.quick)
    evidence["diagnostics"] = diag

    n_match = sum(1 for c in checks if c["match"])
    evidence["cross_checks"] = checks
    evidence["cross_check_summary"] = {"total": len(checks), "matched": n_match, "mismatched": len(checks) - n_match}
    for c in checks:
        if not c["match"]:
            print(f"  MISMATCH {c['item']}: mine={c['mine']} theirs={c['theirs']}")
    print(f"cross-checks: {n_match}/{len(checks)} matched")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {EVIDENCE.relative_to(REPO_ROOT)}")
    return 0


def statistical_layer(df: pd.DataFrame, plans: dict[str, XPlan], sel: dict[str, Any], committed: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-derive the statistical layer: WF composite Sharpe, DSR, Holm, sign null."""
    out: list[dict[str, Any]] = []
    ppy = M15_PPY
    combined: dict[str, list[np.ndarray]] = {g: [] for g in M15_GROUPS}
    for year in WF_YEARS:
        ta, tb = window_bounds(df.index, f"{year}-01-01", f"{year}-12-31")
        for group in M15_GROUPS:
            # frozen per-year selection recomputed identically to the runner:
            fsel = select_group(df, plans, M15_GROUPS[group], RESEARCH_START, f"{year - 1}-12-31")
            if fsel["cid"] is None:
                continue
            p = plans[fsel["cid"]]
            combined[group].append(xrun(df, p.target, p.size, p.stop, ta, tb).returns)
    a, b = window_bounds(df.index, HOLDOUT_START, RESEARCH_END)
    pvals: dict[str, float] = {}
    for group, cid in sel.items():
        if cid is None:
            continue
        p = plans[cid]
        ho = xrun(df, p.target, p.size, p.stop, a, b)
        combined[group].append(ho.returns)
        # WF summary
        wf_rets = list(combined[group][:-1])
        wf_join = np.concatenate(wf_rets) if wf_rets else np.array([])
        theirs_wf = committed["walk_forward"]["summary"][group]
        out.append(compare(f"m15_wf_summary[{group}].sharpe", round(xsharpe(wf_join, ppy), 4), theirs_wf["wf_sharpe"], 0.02))
        # one-sided bootstrap p (own implementation, own seed -> tolerance)
        r = ho.returns
        observed = float(np.mean(r))
        centred = r - observed
        dist = xblock_bootstrap(centred, lambda x: float(np.mean(x)), 2000, 20, 1234)
        p_mine = float(np.mean(dist >= observed))
        pvals[group] = p_mine
        out.append(compare(f"m15_holdout[{group}].p_one_sided", round(p_mine, 4), committed["holdout"]["groups"][group]["p_mean_positive_one_sided"], 0.05))
        # sign randomisation (own seed -> tolerance)
        trades = [t for t in ho.trades if t.direction != 0]
        dirs = np.array([t.direction for t in trades], float)
        gross = np.array([t.gross_usd for t in trades], float)
        costs = np.array([t.cost_usd for t in trades], float)
        unsigned = gross * dirs
        obs = float(gross.sum() - costs.sum())
        rng = np.random.default_rng(99)
        signs = rng.choice([-1.0, 1.0], size=(3000, len(trades)))
        nulls = (signs * unsigned).sum(axis=1) - costs.sum()
        p_sign = float(np.mean(nulls >= obs))
        out.append(compare(f"m15_holdout[{group}].p_sign_randomisation", round(p_sign, 4), committed["holdout"]["groups"][group]["sign_randomisation"]["p_value"], 0.05))
    holm = xholm(pvals)
    theirs_holm = {g: committed["holdout"]["groups"][g]["holm_adjusted_p"] for g in pvals}
    for g in pvals:
        out.append(compare(f"m15_holm[{g}]", round(holm[g], 4), theirs_holm[g], 0.1))
    # DSR on combined OOS series
    for group in pvals:
        oos = np.concatenate(combined[group])
        dsr = xdsr(oos, 40, ppy)
        out.append(compare(f"m15_dsr[{group}]", round(dsr["dsr"], 4), committed["gates"][group]["dsr"], 0.05))
        dsr100 = xdsr(oos, 100, ppy)
        out.append(compare(f"m15_dsr_N100_gt_gate[{group}]", bool(dsr100["dsr"] >= GATE_DSR_MIN), False, 0))
    # gate arithmetic verification from the committed evidence itself
    for group, rec in committed["gates"].items():
        if not isinstance(rec, dict) or "checks" not in rec:
            continue
        ho_rec = committed["holdout"]["groups"][group]
        g1 = ho_rec["base"]["net_usd"] > 0 and ho_rec["base"]["sharpe"] > 0
        g2 = ho_rec["stress"]["2x"]["net_usd"] > 0
        wfs = committed["walk_forward"]["summary"][group]
        g3 = wfs["wf_sharpe"] > 0 and wfs["wf_positive_years"] >= GATE_WF_MIN_POSITIVE_YEARS
        g4 = ho_rec["holm_adjusted_p"] <= GATE_HOLM_ALPHA
        g5 = rec["dsr"] >= GATE_DSR_MIN
        g6 = rec["oos_round_turns"] >= MIN_TRADES_OOS_GATE
        g7 = all(v["days"] > 0 for v in rec["regimes_oos"].values()) and rec["positive_regimes"] >= GATE_REGIMES_MIN_POSITIVE
        mine_checks = [g1, g2, g3, g4, g5, g6, g7]
        keys = sorted(rec["checks"])
        theirs_checks = [rec["checks"][k] == "PASS" for k in keys]
        out.append(compare(f"m15_gate_arithmetic[{group}]", mine_checks, theirs_checks, 0))
    return out


def diagnostics(df: pd.DataFrame, plans: dict[str, XPlan], sel: dict[str, Any], quick: bool) -> dict[str, Any]:
    """Robustness diagnostics on the FROZEN selections. No re-selection, no tuning."""
    out: dict[str, Any] = {}
    a, b = window_bounds(df.index, HOLDOUT_START, RESEARCH_END)
    for group, cid in sel.items():
        if cid is None:
            continue
        p = plans[cid]
        rec: dict[str, Any] = {"cid": cid}

        # (a) fill-lag sensitivity: act one bar later (bar-stamp convention stress)
        lagged = xrun(df, p.target, p.size, p.stop, a, b, lag_bars=1)
        rec["holdout_lag1"] = summarize_xrun(lagged, M15_PPY)

        # (b) chronological stability: one continuous run 2004->2025, per-year P&L
        full = xrun(df, p.target, p.size, p.stop, 0, len(df))
        eq = np.concatenate([[INITIAL_EQUITY], full.equity])
        pnl = np.diff(eq)
        pnl_years = np.asarray(pd.DatetimeIndex(full.times).year)
        year_pnl = {}
        for y in sorted(set(pnl_years)):
            year_pnl[str(y)] = round(float(pnl[pnl_years == y].sum()), 2)
        rec["full_run_yearly_pnl"] = year_pnl
        rec["full_run_summary"] = summarize_xrun(full, M15_PPY)

        # (c) holdout halves
        for name, (s_, e_) in {
            "half1_2020_2022H1": ("2020-01-01", "2022-06-30"),
            "half2_2022H2_2025": ("2022-07-01", RESEARCH_END),
        }.items():
            ha, hb = window_bounds(df.index, s_, e_)
            rec[name] = summarize_xrun(xrun(df, p.target, p.size, p.stop, ha, hb), M15_PPY)

        # (d) cost grid + break-even
        rec["cost_grid"] = {}
        for m_ in (0.5, 1.0, 1.5, 2.0, 3.0):
            rec["cost_grid"][f"{m_}x"] = round(xrun(df, p.target, p.size, p.stop, a, b, mult=m_).net_usd, 2)
        rec["break_even"] = x_break_even(df, p, a, b)

        # (e) trade-level diagnostics: overnight holds (financing is assumed 0)
        run = xrun(df, p.target, p.size, p.stop, a, b)
        rec["holdout_base"] = summarize_xrun(run, M15_PPY)
        entry_days = trading_day(run.times[[t.entry_bar - a for t in run.trades]])
        exit_days = trading_day(run.times[[t.exit_bar - a for t in run.trades]])
        rec["overnight_trades"] = int(np.sum(np.asarray(exit_days) != np.asarray(entry_days)))
        # nights held per trade, for an unmodeled-financing sensitivity:
        # XAUUSD retail swap is typically negative on BOTH sides; at
        # -3.5 USD per lot (100 oz) per night the drag is nights x lots x 3.5.
        nights = np.zeros(len(run.trades))
        for k_, t_ in enumerate(run.trades):
            e_d = trading_day(run.times[[t_.entry_bar - a]])[0]
            x_d = trading_day(run.times[[t_.exit_bar - a]])[0]
            nights[k_] = max(0.0, (x_d - e_d).days)
        # traded lots at entry: (entry_frac * equity) / (100 oz * price), equity ~= initial
        est_lots = np.array(
            [t_.entry_frac * INITIAL_EQUITY / (100.0 * t_.entry_price) if t_.entry_price > 0 else 0.0 for t_ in run.trades]
        )
        rec["total_nights_held"] = float(nights.sum())
        rec["unmodeled_swap_drag_usd_at_3.5_per_lot_night"] = round(float((nights * est_lots * 3.5).sum()), 2)
        rec["stop_exit_share"] = round(float(np.mean([t.stopped for t in run.trades])), 4) if run.trades else 0.0
        out[group] = rec
        print(f"  diagnostics {group}: lag1 net {rec['holdout_lag1']['net_usd']}, break-even {rec['break_even']['value']}x")

    # (f) complete-day filter sensitivity: rerun frozen selections on ALL days
    if not quick:
        alldays = load_m15("xauusd_basemax_utc_15m_20040611_20250228.csv", complete_days_only=False)
        lbl = trading_day(pd.DatetimeIndex(alldays.index))
        alldays = alldays.loc[np.asarray(lbl <= pd.Timestamp(RESEARCH_END))]
        n_partial = len(alldays) - len(df)
        aa, bb = window_bounds(pd.DatetimeIndex(alldays.index), HOLDOUT_START, RESEARCH_END)
        sens: dict[str, Any] = {"partial_bars_excluded_by_filter": n_partial}
        for _group, cid in sel.items():
            if cid is None:
                continue
            pr = m15_plans(alldays)[cid]
            sens[cid] = summarize_xrun(xrun(alldays, pr.target, pr.size, pr.stop, aa, bb), M15_PPY)
        out["complete_day_filter_sensitivity"] = sens

    return out


if __name__ == "__main__":
    sys.exit(main())
