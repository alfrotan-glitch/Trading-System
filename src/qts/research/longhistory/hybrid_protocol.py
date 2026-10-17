"""Frozen monthly slow-hybrid experiment: candidates, windows, gates, trials.

Third cycle of the 2026-10-17 ensemble series. The monthly ensemble cycle
found the repository's strongest evaluation window in slow long-or-flat
trend (``ts9_lo``: Sharpe 0.837, DSR 0.929 at N=149) and its least-bad
1990s walk-forward in USD-conditioned trend. This cycle freezes the
asymmetric combination — slow trend whose longs are unconditioned and
whose shorts require 12-month USD agreement (veto form), the full-
agreement form, and the slow long-or-flat controls — at slow horizons
(9, 6/9/12, 4/9/12 months) chosen on the ≤1989 discovery partition only.
Mirrors :mod:`qts.research.longhistory.ensemble_protocol`; gates, costs,
windows and the selection rule are inherited unchanged. Mirrored in
``docs/research/preregistration_longhistory_hybrid_2026-10-17.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import ensemble_protocol as ENS
from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import protocol as D
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-HYB-2026-10-17"

COST_BASE = D.COST_BASE
COST_STRESS_MULTIPLIERS = D.COST_STRESS_MULTIPLIERS
GATE_DSR_MIN = D.GATE_DSR_MIN
GATE_HOLM_ALPHA = D.GATE_HOLM_ALPHA
GATE_REGIMES_MIN_POSITIVE = D.GATE_REGIMES_MIN_POSITIVE
GATE_WF_MIN_POSITIVE_YEARS = D.GATE_WF_MIN_POSITIVE_YEARS
INITIAL_EQUITY = D.INITIAL_EQUITY
MIN_TRADES_OOS_GATE = D.MIN_TRADES_OOS_GATE
MIN_TRAIN_ROUND_TURNS = D.MIN_TRAIN_ROUND_TURNS

PERIODS_PER_YEAR = MON.PERIODS_PER_YEAR
VOL_BARS = MON.VOL_BARS
REGIME_TREND_BARS = MON.REGIME_TREND_BARS
REGIME_MIN_BARS = MON.REGIME_MIN_BARS

RESEARCH_START = MON.RESEARCH_START
RESEARCH_END = MON.RESEARCH_END
DEV_END = MON.DEV_END
HOLDOUT_START = MON.HOLDOUT_START
WF_TEST_YEARS = MON.WF_TEST_YEARS
REPLICATE_START = MON.REPLICATE_START
REPLICATE_END = MON.REPLICATE_END

#: Configurations evaluated in this cycle's discovery on the <=1989 monthly
#: partition (enumerated in the preregistration), plus the control.
DISCOVERY_TRIALS = 44
#: Cumulative through LH-XAUUSD-W1-2026-10-17 (weekly cycle).
from qts.research.longhistory import weekly_protocol as _WK  # noqa: E402

N_TRIALS_INHERITED = _WK.N_TRIALS
N_TRIALS_THIS_CYCLE = DISCOVERY_TRIALS
N_TRIALS = N_TRIALS_INHERITED + N_TRIALS_THIS_CYCLE

_ANN = PERIODS_PER_YEAR
_V = VOL_BARS

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "veto9", "hyb_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(9,), usd_lb=12, vol_n=_V, ann=_ANN),
        "9-month trend; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "veto6912", "hyb_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(6, 9, 12), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble 6/9/12 trend; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "veto4912", "hyb_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(4, 9, 12), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble 4/9/12 trend; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "agree9", "hyb_agree", "CANDIDATE",
        partial(ES.ensemble_usd_agreement, lookbacks=(9,), usd_lb=12, vol_n=_V, ann=_ANN),
        "9-month trend only when the 12-month USD move agrees, else flat",
    ),
    Candidate(
        "agree6912", "hyb_agree", "CANDIDATE",
        partial(ES.ensemble_usd_agreement, lookbacks=(6, 9, 12), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble 6/9/12 trend only when the 12-month USD move agrees, else flat",
    ),
    Candidate(
        "agree4912", "hyb_agree", "CANDIDATE",
        partial(ES.ensemble_usd_agreement, lookbacks=(4, 9, 12), usd_lb=12, vol_n=_V, ann=_ANN),
        "Ensemble 4/9/12 trend only when the 12-month USD move agrees, else flat",
    ),
    Candidate(
        "ts9_lo", "hyb_lo", "CANDIDATE",
        partial(ES.tsmom_single, lookback=9, long_only=True, vol_n=_V, ann=_ANN),
        "9-month TSMOM sign, long-or-flat (re-registered control member)",
    ),
    Candidate(
        "lo6912", "hyb_lo", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(6, 9, 12), long_only=True, vol_n=_V, ann=_ANN),
        "Ensemble 6/9/12 majority vote, long-or-flat",
    ),
    Candidate(
        "lo4912", "hyb_lo", "CANDIDATE",
        partial(ES.ensemble_tsmom, lookbacks=(4, 9, 12), long_only=True, vol_n=_V, ann=_ANN),
        "Ensemble 4/9/12 majority vote, long-or-flat",
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
