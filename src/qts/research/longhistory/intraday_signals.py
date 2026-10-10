"""Intraday (M15) signal family that has no daily analogue.

Only the session-range breakout is defined here. The other intraday families
reuse the bar-based builders in :mod:`qts.research.longhistory.signals` with
bar-count parameters (see ``intraday_protocol``). TSMOM and RSI(2) are not
carried over: their definitions depend on calendar rebalances or on an SMA
measured in days, so a bar-count version would be a different strategy.

Session-range breakout, all times UTC, trading day per :mod:`daily`
(rolls at 22:00 UTC):

* range: highest high and lowest low of the 00:00-07:00 bars of the trading
  day. It is complete by the 07:00 bar, so no decision inside the window can
  see a later bar;
* entry: between 07:00 and 16:00 a bar close above ``range_high + buffer*ATR``
  opens a long at the next open (a close below ``range_low - buffer*ATR`` opens
  a short). The stop is the opposite range boundary, and it is sized by
  ``RISK_PER_TRADE`` over that distance;
* one trade per session: once a direction has traded (or been stopped), the
  state persists until the flat rule, so the engine's re-entry block stops a
  same-day re-entry;
* flat rule: any decision bar at or after 19:00 UTC, and any bar before 07:00,
  is flat. Positions therefore never run through the 22:00 rollover.

Contract is the same as the other families (see :mod:`signals`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory.daily import trading_day_label
from qts.research.longhistory.signals import MAX_FRACTION, RISK_PER_TRADE, Plan, _plan, atr

ASIA_START_HOUR = 0
ASIA_END_HOUR = 7  # exclusive: range bars are 00:00..06:45
ENTRY_END_HOUR = 16  # exclusive: no new entries from 16:00
FLAT_FROM_HOUR = 19  # decision bars at or after 19:00 are flat (exit at 20:00 open)
MIN_RANGE_BARS = 8  # at least 2 hours of range bars, else no trade that day
ATR_BARS = 14


def session_breakout(df: pd.DataFrame, buffer_atr: float) -> Plan:
    """Trade the first close outside the Asian range, flat by 19:00 UTC."""
    idx = pd.DatetimeIndex(df.index)
    n = len(df)
    hour = np.asarray(idx.hour)
    day = trading_day_label(idx)

    in_asia = (hour >= ASIA_START_HOUR) & (hour < ASIA_END_HOUR)
    asia = pd.DataFrame(
        {
            "day": np.asarray(day),
            "high": np.where(in_asia, df["high"].to_numpy(dtype=float), np.nan),
            "low": np.where(in_asia, df["low"].to_numpy(dtype=float), np.nan),
            "n": in_asia.astype(int),
        },
        index=idx,
    )
    g = asia.groupby("day")
    rng_hi = g["high"].max().reindex(np.asarray(day)).to_numpy(dtype=float)
    rng_lo = g["low"].min().reindex(np.asarray(day)).to_numpy(dtype=float)
    rng_n = g["n"].sum().reindex(np.asarray(day)).to_numpy(dtype=float)
    ok_range = np.isfinite(rng_hi) & np.isfinite(rng_lo) & (rng_n >= MIN_RANGE_BARS)

    close = df["close"].to_numpy(dtype=float)
    a = atr(df, ATR_BARS).to_numpy(dtype=float)
    warm = np.isfinite(a)

    target = np.full(n, np.nan)
    stop_dist = np.full(n, np.nan)
    size = np.full(n, np.nan)
    state = 0.0
    for t in range(n):
        if not warm[t]:
            continue  # NaN = no change; the engine is flat anyway before warm-up
        h = hour[t]
        if h < ASIA_END_HOUR or h >= FLAT_FROM_HOUR:
            state = 0.0
        elif state == 0.0 and ok_range[t] and h < ENTRY_END_HOUR:
            buf = buffer_atr * a[t]
            if close[t] > rng_hi[t] + buf:
                state = 1.0
                stop_dist[t] = close[t] - rng_lo[t]
            elif close[t] < rng_lo[t] - buf:
                state = -1.0
                stop_dist[t] = rng_hi[t] - close[t]
            if state != 0.0:
                sd = stop_dist[t]
                size[t] = min(MAX_FRACTION, RISK_PER_TRADE / (sd / close[t])) if sd > 0 else np.nan
        target[t] = state
    params: dict[str, float | int | bool | str] = {
        "buffer_atr": buffer_atr,
        "range_utc": "00:00-07:00",
        "entry_utc": "07:00-16:00",
        "flat_from_utc": "19:00",
    }
    # stop_dist is only read by the engine on entry bars; size likewise. Other bars carry NaN.
    return _plan(df, "session_breakout", params, target, size, stop_dist)
