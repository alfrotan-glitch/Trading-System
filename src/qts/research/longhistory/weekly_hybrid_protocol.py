"""Frozen weekly slow-hybrid experiment: candidates, windows, gates, trials.

Fourth cycle of the 2026-10-17 series: the monthly champion family
(slow long-or-flat trend; slow trend with USD-confirmed shorts) translated
to the weekly timeframe, with a weekly USD index built from the same
pinned Fed H.10 daily FX basket (last daily observation of each W-FRI
week, >= 6 of 8 currencies required on quoted days). Mirrors
:mod:`qts.research.longhistory.weekly_protocol`; inherited gates/costs/
selection unchanged. Mirrored in
``docs/research/preregistration_longhistory_weekly_hybrid_2026-10-17.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import hybrid_protocol as HYB
from qts.research.longhistory import protocol as D
from qts.research.longhistory import weekly_protocol as WK
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-WHYB-2026-10-17"

COST_BASE = D.COST_BASE
COST_STRESS_MULTIPLIERS = D.COST_STRESS_MULTIPLIERS
GATE_DSR_MIN = D.GATE_DSR_MIN
GATE_HOLM_ALPHA = D.GATE_HOLM_ALPHA
GATE_REGIMES_MIN_POSITIVE = D.GATE_REGIMES_MIN_POSITIVE
GATE_WF_MIN_POSITIVE_YEARS = D.GATE_WF_MIN_POSITIVE_YEARS
INITIAL_EQUITY = D.INITIAL_EQUITY
MIN_TRADES_OOS_GATE = D.MIN_TRADES_OOS_GATE
MIN_TRAIN_ROUND_TURNS = D.MIN_TRAIN_ROUND_TURNS

PERIODS_PER_YEAR = WK.PERIODS_PER_YEAR
VOL_BARS = WK.VOL_BARS
REGIME_TREND_BARS = WK.REGIME_TREND_BARS
REGIME_MIN_BARS = WK.REGIME_MIN_BARS

RESEARCH_START = WK.RESEARCH_START
RESEARCH_END = WK.RESEARCH_END
DEV_END = WK.DEV_END
HOLDOUT_START = WK.HOLDOUT_START
WF_TEST_YEARS = WK.WF_TEST_YEARS
REPLICATE_START = WK.REPLICATE_START
REPLICATE_END = WK.REPLICATE_END

#: Configurations evaluated in this cycle's discovery on the 2004-2009
#: weekly partition (enumerated in the preregistration), plus the control.
DISCOVERY_TRIALS = 25
N_TRIALS_INHERITED = HYB.N_TRIALS
N_TRIALS_THIS_CYCLE = DISCOVERY_TRIALS
N_TRIALS = N_TRIALS_INHERITED + N_TRIALS_THIS_CYCLE

_ANN = PERIODS_PER_YEAR
_V = VOL_BARS

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "wv_263952", "wh_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(26, 39, 52), usd_lb=52, vol_n=_V, ann=_ANN),
        "Weekly ensemble 26/39/52 trend; shorts only while USD index rose over 52 weeks",
    ),
    Candidate(
        "wv_132652", "wh_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(13, 26, 52), usd_lb=52, vol_n=_V, ann=_ANN),
        "Weekly ensemble 13/26/52 trend; shorts only while USD index rose over 52 weeks",
    ),
    Candidate(
        "wv_2652", "wh_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(26, 52), usd_lb=52, vol_n=_V, ann=_ANN),
        "Weekly ensemble 26/52 trend; shorts only while USD index rose over 52 weeks",
    ),
    Candidate(
        "wl_263952", "wh_lo", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(26, 39, 52), long_only=True, vol_n=_V, ann=_ANN),
        "Weekly ensemble 26/39/52 majority vote, long-or-flat",
    ),
    Candidate(
        "wl_132652", "wh_lo", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(13, 26, 52), long_only=True, vol_n=_V, ann=_ANN),
        "Weekly ensemble 13/26/52 majority vote, long-or-flat",
    ),
    Candidate(
        "wl_2652", "wh_lo", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(26, 52), long_only=True, vol_n=_V, ann=_ANN),
        "Weekly ensemble 26/52 majority vote, long-or-flat",
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

GATE_BREAK_EVEN_MIN = WK.GATE_BREAK_EVEN_MIN


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
