"""Frozen monthly experiment: candidates, windows, gates, multiple-testing count.

Mirrors :mod:`qts.research.longhistory.seasonal_protocol` (which mirrors the
intraday and daily protocols) so the same runner executes this cycle. Windows,
costs, gates and the selection rule are re-exported by explicit assignment from
the daily protocol, so they cannot drift. Only the calendar (monthly bars), the
USD-index data column, the candidate set and the trial count differ. Mirrored
in ``docs/research/preregistration_longhistory_monthly_2026-10-15.md``.
"""

from __future__ import annotations

from functools import partial

from qts.research.longhistory import monthly_signals as MS
from qts.research.longhistory import protocol as D
from qts.research.longhistory import reversal_protocol as RV
from qts.research.longhistory import signals as G
from qts.research.longhistory.protocol import Candidate

PREREG_ID = "LH-XAUUSD-MON-2026-10-15"

# Shared with the parent protocols: costs, gates and the selection rule are
# not part of this cycle's changes. Assigned explicitly so the sharing is
# visible to readers and to linters. HOLDOUT_START / RESEARCH_END /
# REPLICATE_* are re-declared below because this cycle defines its own
# windows on its own monthly series (see the preregistration).
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
PERIODS_PER_YEAR = MS.MONTHS_PER_YEAR
VOL_BARS = MS.VOL_MONTHS
#: Regime labels: 24-month trend and the expanding volatility median.
REGIME_TREND_BARS = 24
REGIME_MIN_BARS = 24

# ----------------------------------------------------------------- windows
#: Research series (World Bank monthly gold average + Federal Reserve daily
#: FX, aggregated to months). Starts after the Smithsonian float of 1973.
RESEARCH_START = "1973-01-01"
RESEARCH_END = "2026-09-30"
#: Last month visible to parameter selection for the evaluation window.
DEV_END = "1999-12-31"
HOLDOUT_START = "2000-01-01"
#: Walk-forward: one test year per fold, selection on all earlier months.
WF_TEST_YEARS = tuple(range(1990, 2000))
#: Source replication on BaseMax monthly bars (independent quote stream and an
#: independent next-open execution convention), informational, final stage only.
#: BaseMax coverage begins 2004-06-11; the window opens one month earlier and
#: the run starts at the first available bar.
REPLICATE_START = "2004-06-01"
REPLICATE_END = "2025-02-28"

# ----------------------------------------------------------------- trials
#: Configurations carried through discovery on this monthly series (every
#: family/parameter variant evaluated in ``scratch/explore_monthly*.py`` on
#: the 1973-1989 discovery partition, including the discarded control and the
#: discarded variants, enumerated in the preregistration §Discovery ledger).
DISCOVERY_TRIALS = 22
#: Inherited cumulative count of the parent long-history series: 26 daily +
#: 14 M15 + 7 seasonal + 3 reversal = 50 through
#: LH-XAUUSD-M15-REV-2026-10-14 (``RV.N_TRIALS``), because this cycle's
#: evaluation window overlaps the parent holdout calendar.
N_TRIALS_INHERITED = RV.N_TRIALS
N_TRIALS_THIS_CYCLE = DISCOVERY_TRIALS
N_TRIALS = N_TRIALS_INHERITED + N_TRIALS_THIS_CYCLE

# ----------------------------------------------------------------- candidates
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "m_tsmom_6",
        "gold_trend",
        "CANDIDATE",
        partial(MS.gold_tsmom, lookback=6, vol_n=VOL_BARS, ann=PERIODS_PER_YEAR),
        "Sign of the trailing 6-month gold return, 10% vol target, monthly rebalance",
    ),
    Candidate(
        "m_tsmom_12",
        "gold_trend",
        "CANDIDATE",
        partial(MS.gold_tsmom, lookback=12, vol_n=VOL_BARS, ann=PERIODS_PER_YEAR),
        "Sign of the trailing 12-month gold return, 10% vol target, monthly rebalance",
    ),
    Candidate(
        "m_usdveto_6_12",
        "usd_veto",
        "CANDIDATE",
        partial(MS.usd_veto_tsmom, gold_lb=6, usd_lb=12, vol_n=VOL_BARS, ann=PERIODS_PER_YEAR),
        "Gold 6-month trend; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "m_usdveto_12_12",
        "usd_veto",
        "CANDIDATE",
        partial(MS.usd_veto_tsmom, gold_lb=12, usd_lb=12, vol_n=VOL_BARS, ann=PERIODS_PER_YEAR),
        "Gold 12-month trend; shorts only while the USD index rose over 12 months",
    ),
    Candidate(
        "m_agree_6_12",
        "usd_agreement",
        "CANDIDATE",
        partial(MS.usd_agreement, gold_lb=6, usd_lb=12, vol_n=VOL_BARS, ann=PERIODS_PER_YEAR),
        "6-month gold trend sign with 12-month dollar-weakening sign; flat when they disagree",
    ),
    Candidate(
        "m_agree_12_12",
        "usd_agreement",
        "CANDIDATE",
        partial(MS.usd_agreement, gold_lb=12, usd_lb=12, vol_n=VOL_BARS, ann=PERIODS_PER_YEAR),
        "12-month gold trend sign with 12-month dollar-weakening sign; flat when they disagree",
    ),
    Candidate(
        "m_boll20_2",
        "monthly_reversion",
        "CONTROL",
        partial(G.bollinger, n=20, k=2.0, ann=PERIODS_PER_YEAR, vol_n=VOL_BARS),
        "CONTROL: 20-month two-sigma mean-reversion state; exists to be falsified",
    ),
)

FAMILY_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE")
)
CONTROL_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(c.group for c in CANDIDATES if c.role == "CONTROL")
)

#: G8 (stricter than the parents, as in the seasonal cycle): the evaluation
#: window break-even cost multiplier must reach this multiple of the base cost.
GATE_BREAK_EVEN_MIN = 2.0
#: G9 (this cycle only): net evaluation-window P&L must stay positive under
#: ``COST_FINANCING`` — the inherited base costs plus a symmetric financing
#: charge of ``FINANCING_BPS_PER_DAY`` on the marked notional for every
#: calendar day a position is held.
GATE_FINANCING_CHARGED_POSITIVE = True
#: 0.25 bps/day is the disclosed ASSUMED swap figure of 3.5 USD per lot per
#: 22:00 UTC rollover quoted at 1,400 USD/oz (3.5/100/1400 = 0.25 bps), held
#: fixed across the whole sample so modern, higher prices charge *less* than
#: this regime — i.e. the regime is conservative, ASSUMED, never MEASURED.
FINANCING_BPS_PER_DAY = 0.25
COST_FINANCING = D.COST_BASE.__class__(
    spread_bps=D.COST_BASE.spread_bps,
    slippage_bps=D.COST_BASE.slippage_bps,
    commission_usd_per_lot_side=D.COST_BASE.commission_usd_per_lot_side,
    financing_bps_per_day=FINANCING_BPS_PER_DAY,
    basis=D.COST_BASE.basis,
)
#: Pre-declared non-gating swap assumption: USD per lot per 22:00 UTC rollover.
SWAP_USD_PER_LOT_ROLLOVER = 3.5


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
