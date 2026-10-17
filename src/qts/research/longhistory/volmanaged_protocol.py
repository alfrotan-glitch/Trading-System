"""Frozen monthly volatility-managed trend experiment (Wave 5).

Fifth cycle of the 2026-10-17 series. The signal (champion slow trends)
is unchanged; only the *sizing volatility window* changes: position
size is set from fast 3- or 6-month realised volatility instead of
12-month, de-risking sooner when volatility expands (Barroso &
Santa-Clara-style volatility management in window form). Chosen on the
<=1989 discovery partition only; drawdown-brake variants were evaluated
there and rejected. Windows, costs, gates G1-G9 and the selection rule
are inherited unchanged. Mirrored in
``docs/research/preregistration_longhistory_volmanaged_2026-10-17.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import protocol as D
from qts.research.longhistory import weekly_hybrid_protocol as _WH
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-VOLM-2026-10-17"

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
DISCOVERY_TRIALS = 23
#: Cumulative through LH-XAUUSD-WHYB-2026-10-17 (weekly hybrid cycle).
N_TRIALS_INHERITED = _WH.N_TRIALS
N_TRIALS_THIS_CYCLE = DISCOVERY_TRIALS
N_TRIALS = N_TRIALS_INHERITED + N_TRIALS_THIS_CYCLE

_ANN = PERIODS_PER_YEAR
_V = VOL_BARS

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "veto9_fv3", "vm_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(9,), usd_lb=12, vol_n=_V, ann=_ANN, sizing_vol_n=3),
        "9-month USD-veto trend, size from 3-month realised vol (fast de-risking)",
    ),
    Candidate(
        "veto9_fv6", "vm_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(9,), usd_lb=12, vol_n=_V, ann=_ANN, sizing_vol_n=6),
        "9-month USD-veto trend, size from 6-month realised vol",
    ),
    Candidate(
        "veto12_fv3", "vm_veto", "CANDIDATE",
        partial(ES.ensemble_usd_veto, lookbacks=(12,), usd_lb=12, vol_n=_V, ann=_ANN, sizing_vol_n=3),
        "12-month USD-veto trend, size from 3-month realised vol",
    ),
    Candidate(
        "lo9_fv3", "vm_lo", "CANDIDATE",
        partial(ES.tsmom_single, lookback=9, long_only=True, vol_n=_V, ann=_ANN, sizing_vol_n=3),
        "9-month long-or-flat trend, size from 3-month realised vol",
    ),
    Candidate(
        "lo9_fv6", "vm_lo", "CANDIDATE",
        partial(ES.tsmom_single, lookback=9, long_only=True, vol_n=_V, ann=_ANN, sizing_vol_n=6),
        "9-month long-or-flat trend, size from 6-month realised vol",
    ),
    Candidate(
        "lo12_fv3", "vm_lo", "CANDIDATE",
        partial(ES.tsmom_single, lookback=12, long_only=True, vol_n=_V, ann=_ANN, sizing_vol_n=3),
        "12-month long-or-flat trend, size from 3-month realised vol",
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
