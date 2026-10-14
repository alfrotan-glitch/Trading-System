"""Frozen calendar-seasonality experiment: candidates, windows, gates, trial count.

Mirrors :mod:`qts.research.longhistory.intraday_protocol` (which mirrors the
daily protocol) so the same runner executes this cycle too. Windows, costs,
gates and the selection rule are re-exported by explicit assignment from the
parent protocols, so they cannot drift. Only the candidates, the group set and
the trial count differ. Mirrored in
``docs/research/preregistration_longhistory_seasonal_2026-10-14.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import intraday_protocol as I
from qts.research.longhistory import protocol as D
from qts.research.longhistory import seasonal_signals as SS
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-SES-2026-10-14"

# Shared with the parent protocols: windows, costs and gates are not part of
# this cycle's changes. Assigned explicitly so the sharing is visible.
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

# M15 calendar (same values as the intraday cycle: 92 bars per complete day).
BARS_PER_DAY = I.BARS_PER_DAY
TRADING_DAYS_PER_YEAR = I.TRADING_DAYS_PER_YEAR
PERIODS_PER_YEAR = I.PERIODS_PER_YEAR
VOL_BARS = I.VOL_BARS
REGIME_TREND_BARS = I.REGIME_TREND_BARS
REGIME_MIN_BARS = I.REGIME_MIN_BARS

# ----------------------------------------------------------------- cycle knobs
T_FLOOR = SS.T_FLOOR
MIN_OCCURRENCES = SS.MIN_OCCURRENCES
MIN_NFP_EVENTS = SS.MIN_NFP_EVENTS
#: G8 (this cycle only, stricter than the parents): the evaluation-window
#: break-even cost multiplier must reach this multiple of the base cost.
GATE_BREAK_EVEN_MIN = 2.0
#: Pre-declared non-gating swap assumption: USD per lot per 22:00 UTC rollover.
SWAP_USD_PER_LOT_ROLLOVER = 3.5

# ----------------------------------------------------------------- candidates
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "sd_all",
        "session_drift",
        "CANDIDATE",
        partial(
            SS.session_drift,
            strongest=False,
            t_floor=T_FLOOR,
            min_occ=MIN_OCCURRENCES,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
        ),
        "All three UTC session windows traded on expanding signed drift (|t|>=2, n>=250)",
    ),
    Candidate(
        "sd_strongest",
        "session_drift",
        "CANDIDATE",
        partial(
            SS.session_drift,
            strongest=True,
            t_floor=T_FLOOR,
            min_occ=MIN_OCCURRENCES,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
        ),
        "Only the single window with the highest |t| each day (|t|>=2, n>=250)",
    ),
    Candidate(
        "wd_all",
        "weekday_drift",
        "CANDIDATE",
        partial(
            SS.weekday_drift,
            permuted=False,
            t_floor=T_FLOOR,
            min_occ=MIN_OCCURRENCES,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
        ),
        "Whole trading days by weekday on expanding signed drift (|t|>=2, n>=250)",
    ),
    Candidate(
        "nfp_h4",
        "nfp_drift",
        "CANDIDATE",
        partial(
            SS.nfp_drift,
            hold_bars=4,
            t_floor=T_FLOOR,
            min_events=MIN_NFP_EVENTS,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
        ),
        "Post-payrolls 1-hour continuation, direction from earlier releases only",
    ),
    Candidate(
        "nfp_h16",
        "nfp_drift",
        "CANDIDATE",
        partial(
            SS.nfp_drift,
            hold_bars=16,
            t_floor=T_FLOOR,
            min_events=MIN_NFP_EVENTS,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
        ),
        "Post-payrolls 4-hour continuation, direction from earlier releases only",
    ),
    Candidate(
        "wd_perm1_control",
        "weekday_drift_control",
        "CONTROL",
        partial(
            SS.weekday_drift,
            permuted=True,
            t_floor=T_FLOOR,
            min_occ=MIN_OCCURRENCES,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
        ),
        "CONTROL: wd_all with weekday statistics rotated by one weekday. Never a candidate.",
    ),
    Candidate(
        "sd_placebo_h3_control",
        "session_drift_control",
        "CONTROL",
        partial(
            SS.session_drift,
            strongest=False,
            t_floor=T_FLOOR,
            min_occ=MIN_OCCURRENCES,
            ann=PERIODS_PER_YEAR,
            vol_n=VOL_BARS,
            windows=SS.PLACEBO_WINDOWS,
        ),
        "CONTROL: sd_all on fixed +3h placebo windows [03,10),[10,16),[16,21) UTC. Never a candidate.",
    ),
)

#: Configurations evaluated in THIS cycle (candidates plus controls).
N_TRIALS_THIS_CYCLE = len(CANDIDATES)
#: Cumulative deflation count: daily 26 + intraday 14 + this cycle 7 = 47.
N_TRIALS = I.N_TRIALS + N_TRIALS_THIS_CYCLE
FAMILY_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE"))
#: Controls are evaluated as diagnostics; they never enter selection or gates.
CONTROL_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(c.group for c in CANDIDATES if c.role == "CONTROL"))


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
