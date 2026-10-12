"""Frozen intraday (M15) experiment: candidates, calendar and multiple-testing count.

Mirrors the daily :mod:`protocol` attribute names so the same runner can execute
either protocol. Windows, costs, gates and the selection rule are re-exported
from the daily protocol, so they cannot drift. Only the calendar, the candidate
set and the trial count differ. Mirrored in
``docs/research/preregistration_longhistory_m15_2026-10-10.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import intraday_signals as IS
from qts.research.longhistory import protocol as D
from qts.research.longhistory import signals as G
from qts.research.longhistory.protocol import Candidate

# Shared with the daily protocol: windows, costs, gates and selection are not part of
# this cycle's changes. Assigned explicitly (not imported as bare re-exports) so the
# sharing is visible to readers and to linters.
COST_BASE = D.COST_BASE
COST_STRESS_MULTIPLIERS = D.COST_STRESS_MULTIPLIERS
DEV_END = D.DEV_END
GATE_DSR_MIN = D.GATE_DSR_MIN
GATE_HOLM_ALPHA = D.GATE_HOLM_ALPHA
GATE_REGIMES_MIN_POSITIVE = D.GATE_REGIMES_MIN_POSITIVE
GATE_WF_MIN_POSITIVE_YEARS = D.GATE_WF_MIN_POSITIVE_YEARS
HOLDOUT_START = D.HOLDOUT_START
INITIAL_EQUITY = D.INITIAL_EQUITY
MIN_TRADES_OOS_GATE = D.MIN_TRADES_OOS_GATE
MIN_TRAIN_ROUND_TURNS = D.MIN_TRAIN_ROUND_TURNS
REPLICATE_END = D.REPLICATE_END
REPLICATE_START = D.REPLICATE_START
RESEARCH_END = D.RESEARCH_END
RESEARCH_START = D.RESEARCH_START
WF_TEST_YEARS = D.WF_TEST_YEARS

PREREG_ID = "LH-XAUUSD-M15-2026-10-10"

# ----------------------------------------------------------------- calendar
#: Complete trading days carry 92 bars of 15 minutes (measured on the research
#: series: median and maximum of complete days; see the data-quality evidence).
BARS_PER_DAY = 92
TRADING_DAYS_PER_YEAR = 252
PERIODS_PER_YEAR = BARS_PER_DAY * TRADING_DAYS_PER_YEAR
#: Volatility window: 60 trading days, expressed in bars (as the daily 60-day window).
VOL_BARS = 60 * BARS_PER_DAY
#: Regime labels: 12-month trend and the expanding volatility median, in bars.
REGIME_TREND_BARS = TRADING_DAYS_PER_YEAR * BARS_PER_DAY
REGIME_MIN_BARS = TRADING_DAYS_PER_YEAR * BARS_PER_DAY

# ----------------------------------------------------------------- candidates
#: Bar-count windows: 16 bars = 4 h, 32 = 8 h, 64 = 16 h, 96 = 1 trading day,
#: 128 = 32 h, 192 = 2 trading days, 256 = 2.8 trading days, 384 = 4 trading days.
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "ma_16_64_nostop",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=16, slow=64, stop_mult=None, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "SMA 16/64 bars stop-and-reverse, no stop, vol-targeted",
    ),
    Candidate(
        "ma_16_64_atr3",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=16, slow=64, stop_mult=3.0, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "SMA 16/64 bars stop-and-reverse, 3 ATR(14) stop",
    ),
    Candidate(
        "ma_32_128_nostop",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=32, slow=128, stop_mult=None, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "SMA 32/128 bars stop-and-reverse, no stop, vol-targeted",
    ),
    Candidate(
        "ma_32_128_atr3",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=32, slow=128, stop_mult=3.0, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "SMA 32/128 bars stop-and-reverse, 3 ATR(14) stop",
    ),
    Candidate(
        "ma_64_256_nostop",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=64, slow=256, stop_mult=None, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "SMA 64/256 bars stop-and-reverse, no stop, vol-targeted",
    ),
    Candidate(
        "ma_64_256_atr3",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=64, slow=256, stop_mult=3.0, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "SMA 64/256 bars stop-and-reverse, 3 ATR(14) stop",
    ),
    Candidate(
        "donchian_96_48_atr2",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=96, exit_n=48, stop_mult=2.0),
        "96-bar breakout, 48-bar exit, 2 ATR stop",
    ),
    Candidate(
        "donchian_96_48_atr3",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=96, exit_n=48, stop_mult=3.0),
        "96-bar breakout, 48-bar exit, 3 ATR stop",
    ),
    Candidate(
        "donchian_384_192_atr3",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=384, exit_n=192, stop_mult=3.0),
        "384-bar breakout, 192-bar exit, 3 ATR stop",
    ),
    Candidate(
        "rexp_k10_h4",
        "volatility_expansion",
        "CANDIDATE",
        partial(G.range_expansion, k=1.0, hold=4),
        "bar body > 1.0 ATR20 starts a 4-bar (1 h) trade",
    ),
    Candidate(
        "rexp_k10_h16",
        "volatility_expansion",
        "CANDIDATE",
        partial(G.range_expansion, k=1.0, hold=16),
        "bar body > 1.0 ATR20 starts a 16-bar (4 h) trade",
    ),
    Candidate(
        "session_brk_b0",
        "session_breakout",
        "CANDIDATE",
        partial(IS.session_breakout, buffer_atr=0.0),
        "Asian-range (00-07 UTC) breakout, entries to 16 UTC, flat 19 UTC, opposite-range stop",
    ),
    Candidate(
        "session_brk_b025",
        "session_breakout",
        "CANDIDATE",
        partial(IS.session_breakout, buffer_atr=0.25),
        "as session_brk_b0, entry requires a 0.25 ATR buffer beyond the range",
    ),
    Candidate(
        "bollinger_20_2_control",
        "bollinger_control",
        "CONTROL",
        partial(G.bollinger, n=20, k=2.0, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "Bollinger(20 bars, 2) fade to mean. Falsification control, never a candidate",
    ),
)

#: Configurations evaluated in THIS cycle (candidates plus control).
N_TRIALS_THIS_CYCLE = len(CANDIDATES)
#: Every configuration evaluated on the same research series, across both cycles
#: (daily 26 + intraday 14). Used for the deflated Sharpe, the conservative choice.
N_TRIALS = D.N_TRIALS + N_TRIALS_THIS_CYCLE
FAMILY_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE"))


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
