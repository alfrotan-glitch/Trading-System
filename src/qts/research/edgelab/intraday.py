"""Session-clock strategies: the information that lives in *when* you hold gold.

Every family tested so far asked "which direction?" on a daily or monthly clock.
This one asks a different question: inside a 24-hour day, does gold earn its
return at particular hours? That is a materially different information set — the
time of day is known in advance and costs nothing to condition on, so a real
session effect is not something that can be overfitted away by parameter search
the way a price pattern can.

The economics, stated before any result was read:

* **Overnight drift.** Gold's marginal buyer is Asian physical demand, which
  trades in the East Asian session. Western futures positioning unwinds into the
  New York close. If the "overnight" window carries a positive drift and the
  Western session carries offsetting noise, then flat-by-day/long-by-night beats
  buy-and-hold per unit of risk — with the same gross exposure to the metal and
  roughly a third of the time at risk.
* **Intraday reversal of the overnight move.** Overnight moves are thinner and
  more sentiment-driven than the New York session, where the marginal price-setter
  is a deep futures book. A reversal during the following session is the classic
  liquidity-provision story.
* **Intraday momentum into the close**, the "market intraday momentum" result
  documented for equity indices: the first half-hour return predicts the last
  half-hour return. Gold's version is the overnight → late-New-York momentum.
* **Opening-range breakout.** The Asian range is a liquidity reservoir; London
  and New York price discovery frequently resolves it. This is the one hypothesis
  here that needs a genuine intraday state machine rather than a fixed window.

Conventions that matter for honesty:

* All times are **UTC hours**, half-open ``[start, end)``, and may wrap midnight.
  DST is deliberately not modelled: the London/NY boundary moves by an hour twice
  a year, which is a source of noise for a session effect, not a source of alpha.
  Ignoring it makes results slightly worse, never better.
* Signals are evaluated on bar closes. ``run_vector`` then shifts the position by
  one bar, so a decision taken at the close of ``t`` cannot earn the move into
  ``t``. The breakout state machine is path-dependent and is written as an
  explicit loop for exactly that reason — a vectorised shortcut is how a
  look-ahead bug gets in.
* The 21:00-22:00 UTC hour is the COMEX maintenance halt and is almost absent
  from the data (314 bars in 21 years). Windows that span it simply hold through
  the gap; the position is unchanged and no return is credited.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- clocks

#: Session windows in UTC hours, half-open ``[start, end)``.
SESSIONS: dict[str, tuple[int, int]] = {
    # Tokyo/Shanghai hours plus the pre-London lull. Gold's physical bid.
    "asia": (22, 6),
    # London price discovery.
    "london": (7, 12),
    # The COMEX floor session plus the equity cash session that dominates gold.
    "newyork": (12, 20),
    # Everything that is not the Western sessions.
    "overnight": (21, 6),
}


def _dt_index(bars: pd.DataFrame) -> pd.DatetimeIndex:
    """The bar index as a ``DatetimeIndex``.

    ``DataFrame.index`` is typed as a generic ``Index`` so every ``.hour`` /
    ``.date`` access fails a type check even though the runtime type is always a
    ``DatetimeIndex``. Asserting it once keeps the signal code readable.
    """
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must be indexed by a DatetimeIndex")
    return bars.index


def hour_mask(index: pd.DatetimeIndex, start: int, end: int) -> pd.Series:
    """Boolean mask for the UTC hours in ``[start, end)``, wrapping past midnight."""
    if not 0 <= start < 24 or not 0 <= end <= 24:
        raise ValueError("hours must be in [0, 24]")
    if start == end:
        raise ValueError("empty window")
    hours = index.hour
    inside = (hours >= start) & (hours < end) if start < end else (hours >= start) | (hours < end)
    return pd.Series(inside, index=index)


def within_window(bars: pd.DataFrame, start: int, end: int) -> pd.Series:
    """Position of 1.0 throughout a clock window, 0.0 outside it."""
    return hour_mask(_dt_index(bars), start, end).astype(float)


# --------------------------------------------------------------------------- session stats


def window_return_per_day(bars: pd.DataFrame, start: int, end: int) -> pd.Series:
    """Compounded return earned inside ``[start, end)`` on each calendar day.

    Uses close-to-close returns of the bars *inside* the window, so the overnight
    move from the previous session's last bar into the window's first bar is not
    credited to the window. Exposed so the descriptive statistics behind a
    hypothesis can be checked independently of any backtest.
    """
    mask = hour_mask(_dt_index(bars), start, end)
    r = bars["close"].pct_change()
    r = r.where(mask)
    return (1.0 + r.fillna(0.0)).groupby(np.asarray(_dt_index(bars).date)).prod() - 1.0


def daily_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Aggregate M15 bars to calendar days (UTC)."""
    b = bars.copy()
    b.index = _dt_index(bars)
    if b.index.tz is None:
        b.index = b.index.tz_localize("UTC")
    g = b.resample("1D")
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    return out.dropna(subset=["close"])


# --------------------------------------------------------------------------- strategies


def hold_window(bars: pd.DataFrame, start: int = 22, end: int = 6) -> pd.Series:
    """Long only inside the clock window — the pure session-exposure bet."""
    return within_window(bars, start, end)


def overnight_reversal(bars: pd.DataFrame, start: int = 22, end: int = 6, day_start: int = 12, day_end: int = 20) -> pd.Series:
    """Fade the previous overnight move during the Western session.

    The overnight leg is measured from the last bar before ``day_end`` on the
    previous day to the last bar before ``day_start`` today — information that is
    fully known when the day session opens.
    """
    idx = _dt_index(bars)
    close = bars["close"]
    # Last close of the overnight window, per day, then reindexed onto every bar.
    night = hour_mask(idx, start, end)
    night_close = close.where(night).groupby(idx.date).last()
    night_open = close.where(night).groupby(idx.date).first()
    move = (night_close / night_open - 1.0).shift(1)  # yesterday's overnight move
    move_by_bar = pd.Series(idx.date, index=idx).map(move)
    in_day = hour_mask(idx, day_start, day_end).astype(bool).to_numpy()
    sig = np.where(in_day, -np.sign(move_by_bar.to_numpy(dtype=float)), 0.0)
    return pd.Series(np.nan_to_num(sig), index=idx, dtype=float)


def overnight_momentum_close(
    bars: pd.DataFrame,
    start: int = 22,
    end: int = 6,
    entry_hour: int = 19,
    exit_hour: int = 21,
) -> pd.Series:
    """Trade the last stretch of the New York session in the overnight direction.

    ``entry_hour``..``exit_hour`` is held with the sign of the overnight move that
    ended earlier the same day. Nothing here uses a price observed after the
    position is set.
    """
    idx = _dt_index(bars)
    close = bars["close"]
    night = hour_mask(idx, start, end)
    night_close = close.where(night).groupby(idx.date).last()
    night_open = close.where(night).groupby(idx.date).first()
    move = (night_close / night_open - 1.0)
    move_by_bar = pd.Series(idx.date, index=idx).map(move)
    in_window = hour_mask(idx, entry_hour, exit_hour).astype(bool).to_numpy()
    sig = np.where(in_window, np.sign(move_by_bar.to_numpy(dtype=float)), 0.0)
    return pd.Series(np.nan_to_num(sig), index=idx, dtype=float)


def opening_range_breakout(
    bars: pd.DataFrame,
    range_start: int = 22,
    range_end: int = 7,
    trade_end: int = 20,
    buffer_bps: float = 0.0,
    allow_short: bool = True,
) -> pd.Series:
    """Break out of the Asian range during the European/American session.

    Path-dependent by nature, so this is an explicit per-bar loop. State at bar
    ``t`` uses only bars up to and including ``t``:

    1. Before ``range_end`` the range is still forming and the position is flat.
    2. Once trading opens, a close above ``range_high * (1 + buffer)`` goes long
       and a close below ``range_low * (1 - buffer)`` goes short.
    3. The first break of the day wins; the opposite side does not re-enter.
    4. Everything is flat from ``trade_end`` until the next range.
    """
    idx = _dt_index(bars)
    close = bars["close"].to_numpy(dtype=float)
    day = np.asarray(idx.date)
    in_range = hour_mask(idx, range_start, range_end).to_numpy()
    in_trade = hour_mask(idx, range_end, trade_end).to_numpy()

    pos = np.zeros(len(idx), dtype=float)
    cur_day = None
    hi = -np.inf
    lo = np.inf
    state = 0.0
    for i in range(len(idx)):
        d = day[i]
        if d != cur_day:
            cur_day, hi, lo, state = d, -np.inf, np.inf, 0.0
        if in_range[i]:
            hi = max(hi, close[i])
            lo = min(lo, close[i])
            state = 0.0
            pos[i] = 0.0
        elif in_trade[i] and np.isfinite(hi):
            if state == 0.0:
                if close[i] > hi * (1.0 + buffer_bps / 1e4):
                    state = 1.0
                elif allow_short and close[i] < lo * (1.0 - buffer_bps / 1e4):
                    state = -1.0
            pos[i] = state
        else:
            state = 0.0
    return pd.Series(pos, index=idx, dtype=float)
