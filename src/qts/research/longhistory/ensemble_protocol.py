"""Frozen monthly ensemble experiment: candidates, windows, gates, trials.

Mirrors :mod:`qts.research.longhistory.monthly_protocol` so the shared
runner executes this cycle unchanged. Costs, gates and the selection rule
are re-exported by explicit assignment from the daily protocol. Only the
calendar stays monthly; the candidate set (multi-horizon ensemble,
MA/breakout trend, long-only trend), the signal module and the trial
count differ. Mirrored in
``docs/research/preregistration_longhistory_ensemble_2026-10-17.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import protocol as D
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-ENS-2026-10-17"

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
PERIODS_PER_YEAR = MON.PERIODS_PER_YEAR
VOL_BARS = MON.VOL_BARS
REGIME_TREND_BARS = MON.REGIME_TREND_BARS
REGIME_MIN_BARS = MON.REGIME_MIN_BARS

# ----------------------------------------------------------------- windows
RESEARCH_START = MON.RESEARCH_START
RESEARCH_END = MON.RESEARCH_END
DEV_END = MON.DEV_END
HOLDOUT_START = MON.HOLDOUT_START
WF_TEST_YEARS = MON.WF_TEST_YEARS
REPLICATE_START = MON.REPLICATE_START
REPLICATE_END = MON.REPLICATE_END

# ----------------------------------------------------------------- trials
#: Configurations evaluated in this cycle's discovery on the <=1989 monthly
#: partition (1973-1983 selection / 1984-1989 test), enumerated in the
#: preregistration discovery ledger, plus the re-registered Bollinger
#: control. Every one counts, frozen or not.
DISCOVERY_TRIALS = 77
#: Cumulative count through LH-XAUUSD-MON-2026-10-15 (50 parent + 22 monthly).
N_TRIALS_INHERITED = MON.N_TRIALS
N_TRIALS_THIS_CYCLE = DISCOVERY_TRIALS
N_TRIALS = N_TRIALS_INHERITED + N_TRIALS_THIS_CYCLE

# ----------------------------------------------------------------- candidates
_ANN = PERIODS_PER_YEAR
_V = VOL_BARS

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "e248_ls", "ens_fast", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(2, 4, 8), vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 2/4/8-month majority vote, long-short, vol-targeted",
    ),
    Candidate(
        "e248_ls_graded", "ens_fast", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(2, 4, 8), graded=True, vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 2/4/8 long-short, size scaled by vote share",
    ),
    Candidate(
        "e612_ls", "ens_multi", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(6, 12), vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 6/12-month majority vote, long-short",
    ),
    Candidate(
        "e3612_ls", "ens_multi", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(3, 6, 12), vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 3/6/12-month majority vote, long-short",
    ),
    Candidate(
        "e13612_ls", "ens_multi", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(1, 3, 6, 12), vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 1/3/6/12-month majority vote, long-short",
    ),
    Candidate(
        "e248_usdveto", "usd_conditioned", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(2, 4, 8), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 2/4/8; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "e13612_usdveto", "usd_conditioned", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(1, 3, 6, 12), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 1/3/6/12; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "e248_usdagree", "usd_conditioned", "CANDIDATE",
        partial(ES.ensemble_usd_agreement, lookbacks=(2, 4, 8), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 2/4/8 traded only when the 12-month USD move agrees, else flat",
    ),
    Candidate(
        "e1312_ls", "ens_fast", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(1, 3, 12), vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 1/3/12-month majority vote, long-short",
    ),
    Candidate(
        "e248_lo", "long_only", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(2, 4, 8), long_only=True, vol_n=_V, ann=_ANN),
        "Ensemble TSMOM 2/4/8, long-or-flat (shorts clipped to flat)",
    ),
    Candidate(
        "max3_12_lo", "long_only", "CANDIDATE",
        partial(ES.ma_trend, fast=3, slow=12, long_only=True, vol_n=_V, ann=_ANN),
        "SMA 3/12 cross state, long-or-flat, vol-targeted (no stop)",
    ),
    Candidate(
        "ts9_lo", "long_only", "CANDIDATE",
        partial(ES.tsmom_single, lookback=9, long_only=True, vol_n=_V, ann=_ANN),
        "9-month TSMOM sign, long-or-flat, vol-targeted",
    ),
    Candidate(
        "m_boll20_2", "monthly_reversion", "CONTROL",
        partial(ES.bollinger_control, vol_n=_V, ann=_ANN),
        "CONTROL: 20-month two-sigma mean-reversion state; exists to be falsified",
    ),
)

FAMILY_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE")
)
CONTROL_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(c.group for c in CANDIDATES if c.role == "CONTROL")
)

GATE_BREAK_EVEN_MIN = MON.GATE_BREAK_EVEN_MIN
GATE_FINANCING_CHARGED_POSITIVE = MON.GATE_FINANCING_CHARGED_POSITIVE
FINANCING_BPS_PER_DAY = MON.FINANCING_BPS_PER_DAY
COST_FINANCING = MON.COST_FINANCING
SWAP_USD_PER_LOT_ROLLOVER = MON.SWAP_USD_PER_LOT_ROLLOVER


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
