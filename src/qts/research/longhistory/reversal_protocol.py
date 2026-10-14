"""Frozen M15 impulse-fade (reversal) experiment: candidates, calendar, trial count.

Preregistration: ``LH-XAUUSD-M15-REV-2026-10-14``
(``docs/research/preregistration_longhistory_m15_reversal_2026-10-14.md``).

Mirrors :mod:`intraday_protocol` attribute names so the shared runner can execute
it. Windows, costs, gates and selection are re-exported from the daily/intraday
protocols so they cannot drift. Only the candidate set and the trial count differ.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import intraday_protocol as I
from qts.research.longhistory import seasonal_protocol as SP
from qts.research.longhistory import signals as G
from qts.research.longhistory.protocol import Candidate

COST_BASE = I.COST_BASE
COST_STRESS_MULTIPLIERS = I.COST_STRESS_MULTIPLIERS
DEV_END = I.DEV_END
GATE_DSR_MIN = I.GATE_DSR_MIN
GATE_HOLM_ALPHA = I.GATE_HOLM_ALPHA
GATE_REGIMES_MIN_POSITIVE = I.GATE_REGIMES_MIN_POSITIVE
GATE_WF_MIN_POSITIVE_YEARS = I.GATE_WF_MIN_POSITIVE_YEARS
HOLDOUT_START = I.HOLDOUT_START
INITIAL_EQUITY = I.INITIAL_EQUITY
MIN_TRADES_OOS_GATE = I.MIN_TRADES_OOS_GATE
MIN_TRAIN_ROUND_TURNS = I.MIN_TRAIN_ROUND_TURNS
REPLICATE_END = I.REPLICATE_END
REPLICATE_START = I.REPLICATE_START
RESEARCH_END = I.RESEARCH_END
RESEARCH_START = I.RESEARCH_START
WF_TEST_YEARS = I.WF_TEST_YEARS

PREREG_ID = "LH-XAUUSD-M15-REV-2026-10-14"

BARS_PER_DAY = I.BARS_PER_DAY
TRADING_DAYS_PER_YEAR = I.TRADING_DAYS_PER_YEAR
PERIODS_PER_YEAR = I.PERIODS_PER_YEAR
VOL_BARS = I.VOL_BARS
REGIME_TREND_BARS = I.REGIME_TREND_BARS
REGIME_MIN_BARS = I.REGIME_MIN_BARS

CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "fade_k20_h4",
        "impulse_fade",
        "CANDIDATE",
        partial(G.impulse_fade, k=2.0, hold=4),
        "bar body > 2.0 ATR20 opens a 4-bar (1 h) trade AGAINST the impulse; 2 ATR stop",
    ),
    Candidate(
        "fade_k20_h16",
        "impulse_fade",
        "CANDIDATE",
        partial(G.impulse_fade, k=2.0, hold=16),
        "bar body > 2.0 ATR20 opens a 16-bar (4 h) trade AGAINST the impulse; 2 ATR stop",
    ),
    Candidate(
        "fade_k10_h4",
        "impulse_fade",
        "CANDIDATE",
        partial(G.impulse_fade, k=1.0, hold=4),
        "bar body > 1.0 ATR20 opens a 4-bar (1 h) trade AGAINST the impulse; 2 ATR stop (sign mirror of rexp_k10_h4)",
    ),
)

#: Configurations evaluated in THIS cycle.
N_TRIALS_THIS_CYCLE = len(CANDIDATES)
#: Cumulative trial count: all configurations on the research series, including
#: the seasonal cycle (47). Conservative for the deflated Sharpe.
N_TRIALS = SP.N_TRIALS + N_TRIALS_THIS_CYCLE
FAMILY_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE"))


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)

#: G8 inherited from the seasonal cycle (stricter than the parents): evaluation-window
#: break-even cost multiplier must reach 2.0x.
GATE_BREAK_EVEN_MIN = SP.GATE_BREAK_EVEN_MIN
