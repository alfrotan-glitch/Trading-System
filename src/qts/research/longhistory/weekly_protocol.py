"""Frozen weekly ensemble experiment: candidates, windows, gates, trials.

The weekly timeframe (W-FRI bars resampled from the BaseMax complete-day
daily series) was never evaluated by any parent cycle: daily was cost-
limited and monthly was sample-limited (G6). Weekly is the intermediate
frequency. Windows, costs, gates and the selection rule mirror the daily
protocol via :mod:`qts.research.longhistory.ensemble_protocol`'s parent
chain. Mirrored in
``docs/research/preregistration_longhistory_weekly_2026-10-17.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import ensemble_protocol as ENS
from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import protocol as D
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-W1-2026-10-17"

COST_BASE = D.COST_BASE
COST_STRESS_MULTIPLIERS = D.COST_STRESS_MULTIPLIERS
GATE_DSR_MIN = D.GATE_DSR_MIN
GATE_HOLM_ALPHA = D.GATE_HOLM_ALPHA
GATE_REGIMES_MIN_POSITIVE = D.GATE_REGIMES_MIN_POSITIVE
GATE_WF_MIN_POSITIVE_YEARS = D.GATE_WF_MIN_POSITIVE_YEARS
INITIAL_EQUITY = D.INITIAL_EQUITY
MIN_TRADES_OOS_GATE = D.MIN_TRADES_OOS_GATE
MIN_TRAIN_ROUND_TURNS = D.MIN_TRAIN_ROUND_TURNS

# ----------------------------------------------------------------- calendar
PERIODS_PER_YEAR = 52
VOL_BARS = 26
#: Regime labels: 52-week trend and the expanding volatility median.
REGIME_TREND_BARS = 52
REGIME_MIN_BARS = 52

# ----------------------------------------------------------------- windows
RESEARCH_START = "2004-06-11"
RESEARCH_END = "2025-02-28"
DEV_END = "2019-12-31"
HOLDOUT_START = "2020-01-01"
WF_TEST_YEARS = tuple(range(2010, 2020))
REPLICATE_START = "2025-08-06"
REPLICATE_END = "2026-09-16"

# ----------------------------------------------------------------- trials
#: Configurations evaluated in this cycle's discovery on the 2004-2009
#: pre-walk-forward weekly partition, enumerated in the preregistration
#: discovery ledger, plus the registered Bollinger control.
DISCOVERY_TRIALS = 44
#: Cumulative count through LH-XAUUSD-ENS-2026-10-17 (this cycle runs
#: after the monthly ensemble cycle in the same research series because
#: the evaluation calendars overlap).
N_TRIALS_INHERITED = ENS.N_TRIALS
N_TRIALS_THIS_CYCLE = DISCOVERY_TRIALS
N_TRIALS = N_TRIALS_INHERITED + N_TRIALS_THIS_CYCLE

# ----------------------------------------------------------------- candidates
_ANN = PERIODS_PER_YEAR
_V = VOL_BARS

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "w_e132652_ls", "wk_ens", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(13, 26, 52), vol_n=_V, ann=_ANN),
        "Weekly ensemble TSMOM 13/26/52-week majority vote, long-short",
    ),
    Candidate(
        "w_e4132652_ls", "wk_ens", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(4, 13, 26, 52), vol_n=_V, ann=_ANN),
        "Weekly ensemble TSMOM 4/13/26/52-week majority vote, long-short",
    ),
    Candidate(
        "w_e4132652_ls_gr", "wk_ens", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(4, 13, 26, 52), graded=True, vol_n=_V, ann=_ANN),
        "Weekly ensemble TSMOM 4/13/26/52 long-short, size scaled by vote share",
    ),
    Candidate(
        "w_max13_52_ls", "wk_trend", "CANDIDATE",
        partial(ES.ma_trend, fast=13, slow=52, vol_n=_V, ann=_ANN),
        "Weekly SMA 13/52 cross state, long-short, vol-targeted (no stop)",
    ),
    Candidate(
        "w_sma52_ls", "wk_trend", "CANDIDATE",
        partial(ES.sma_trend, n=52, vol_n=_V, ann=_ANN),
        "Weekly close vs 52-week SMA state, long-short, vol-targeted",
    ),
    Candidate(
        "w_don26_ls", "wk_trend", "CANDIDATE",
        partial(ES.donchian_trend, n=26, vol_n=_V, ann=_ANN),
        "Weekly 26-week close breakout state, long-short, vol-targeted",
    ),
    Candidate(
        "w_max13_52_lo", "wk_longonly", "CANDIDATE",
        partial(ES.ma_trend, fast=13, slow=52, long_only=True, vol_n=_V, ann=_ANN),
        "Weekly SMA 13/52 cross state, long-or-flat, vol-targeted (no stop)",
    ),
    Candidate(
        "w_sma52_lo", "wk_longonly", "CANDIDATE",
        partial(ES.sma_trend, n=52, long_only=True, vol_n=_V, ann=_ANN),
        "Weekly close vs 52-week SMA state, long-or-flat, vol-targeted",
    ),
    Candidate(
        "w_e4132652_lo", "wk_longonly", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(4, 13, 26, 52), long_only=True, vol_n=_V, ann=_ANN),
        "Weekly ensemble TSMOM 4/13/26/52, long-or-flat (shorts clipped to flat)",
    ),
    Candidate(
        "w_boll20_2", "wk_reversion", "CONTROL",
        partial(ES.bollinger_control, vol_n=_V, ann=_ANN),
        "CONTROL: 20-week two-sigma mean-reversion state; exists to be falsified",
    ),
)

FAMILY_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE")
)
CONTROL_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(c.group for c in CANDIDATES if c.role == "CONTROL")
)

GATE_BREAK_EVEN_MIN = 2.0


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
