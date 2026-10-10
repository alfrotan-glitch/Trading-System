"""Frozen experiment definition: candidates, windows, selection rule and gates.

Everything a result depends on is declared here and mirrored in
``docs/research/preregistration_longhistory_2026-10-10.md``. Changing a value
here is a new experiment. Results must not be used to adjust these values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import pandas as pd

from qts.research.longhistory import signals as G
from qts.research.longhistory.engine import CostModel

PREREG_ID = "LH-XAUUSD-D1-2026-10-10"

# ----------------------------------------------------------------- windows
#: Research series (UTC trading days). BaseMax coverage is complete only to here;
#: 2025-03 onward is partial in the source (see the data-quality evidence).
RESEARCH_START = "2004-06-11"
RESEARCH_END = "2025-02-28"
#: Last day visible to parameter selection for the untouched holdout.
DEV_END = "2019-12-31"
HOLDOUT_START = "2020-01-01"
#: Walk-forward: one test year per fold, selection on all earlier data.
WF_TEST_YEARS = tuple(range(2010, 2020))
#: Independent replicate on the Dukascopy mirror (already seen by earlier work).
REPLICATE_START = "2025-08-06"
REPLICATE_END = "2026-09-16"

# ----------------------------------------------------------------- selection
MIN_TRAIN_ROUND_TURNS = 20
MIN_TRADES_OOS_GATE = 100

# ----------------------------------------------------------------- costs
#: ASSUMED retail XAUUSD costs. No broker cost in this repository is measured.
COST_BASE = CostModel(
    spread_bps=3.0,
    slippage_bps=1.0,
    commission_usd_per_lot_side=7.0,
    financing_bps_per_day=0.0,
    basis="ASSUMED",
)
COST_STRESS_MULTIPLIERS = (2.0, 3.0)

INITIAL_EQUITY = 10_000.0

# ----------------------------------------------------------------- gates
GATE_DSR_MIN = 0.95
GATE_HOLM_ALPHA = 0.05
GATE_WF_MIN_POSITIVE_YEARS = 6
GATE_REGIMES_MIN_POSITIVE = 3


@dataclass(frozen=True)
class Candidate:
    cid: str
    group: str
    role: str  # CANDIDATE or CONTROL
    builder: Callable[[pd.DataFrame], G.Plan]
    description: str


def _gated_donchian(df: pd.DataFrame, threshold: float) -> G.Plan:
    gate = G.efficiency_gate(df, 60, threshold)
    return G.donchian(df, 55, 20, 3.0, gate=gate)


CANDIDATES: tuple[Candidate, ...] = (
    Candidate("tsmom_L63", "tsmom", "CANDIDATE", partial(G.tsmom, lookback=63), "3-month TSMOM, monthly rebalance"),
    Candidate("tsmom_L126", "tsmom", "CANDIDATE", partial(G.tsmom, lookback=126), "6-month TSMOM"),
    Candidate("tsmom_L252", "tsmom", "CANDIDATE", partial(G.tsmom, lookback=252), "12-month TSMOM"),
    Candidate(
        "ma_20_100_nostop",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=20, slow=100, stop_mult=None),
        "SMA 20/100 stop-and-reverse, no stop",
    ),
    Candidate(
        "ma_20_100_atr3",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=20, slow=100, stop_mult=3.0),
        "SMA 20/100 stop-and-reverse, 3 ATR stop",
    ),
    Candidate(
        "ma_20_200_nostop",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=20, slow=200, stop_mult=None),
        "SMA 20/200 stop-and-reverse, no stop",
    ),
    Candidate(
        "ma_20_200_atr3",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=20, slow=200, stop_mult=3.0),
        "SMA 20/200 stop-and-reverse, 3 ATR stop",
    ),
    Candidate(
        "ma_50_200_nostop",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=50, slow=200, stop_mult=None),
        "SMA 50/200 stop-and-reverse, no stop",
    ),
    Candidate(
        "ma_50_200_atr3",
        "ma_cross",
        "CANDIDATE",
        partial(G.ma_cross, fast=50, slow=200, stop_mult=3.0),
        "SMA 50/200 stop-and-reverse, 3 ATR stop",
    ),
    Candidate(
        "donchian_20_10_atr2",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=20, exit_n=10, stop_mult=2.0),
        "20-bar breakout, 10-bar exit, 2 ATR stop",
    ),
    Candidate(
        "donchian_20_10_atr3",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=20, exit_n=10, stop_mult=3.0),
        "20-bar breakout, 10-bar exit, 3 ATR stop",
    ),
    Candidate(
        "donchian_55_20_atr2",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=55, exit_n=20, stop_mult=2.0),
        "55-bar breakout, 20-bar exit, 2 ATR stop",
    ),
    Candidate(
        "donchian_55_20_atr3",
        "donchian",
        "CANDIDATE",
        partial(G.donchian, entry=55, exit_n=20, stop_mult=3.0),
        "55-bar breakout, 20-bar exit, 3 ATR stop",
    ),
    Candidate(
        "rexp_k05_h1",
        "volatility_expansion",
        "CANDIDATE",
        partial(G.range_expansion, k=0.5, hold=1),
        "body > 0.5 ATR20 expansion, hold 1 bar",
    ),
    Candidate(
        "rexp_k05_h3",
        "volatility_expansion",
        "CANDIDATE",
        partial(G.range_expansion, k=0.5, hold=3),
        "body > 0.5 ATR20 expansion, hold 3 bars",
    ),
    Candidate(
        "rexp_k10_h1",
        "volatility_expansion",
        "CANDIDATE",
        partial(G.range_expansion, k=1.0, hold=1),
        "body > 1.0 ATR20 expansion, hold 1 bar",
    ),
    Candidate(
        "rexp_k10_h3",
        "volatility_expansion",
        "CANDIDATE",
        partial(G.range_expansion, k=1.0, hold=3),
        "body > 1.0 ATR20 expansion, hold 3 bars",
    ),
    Candidate("nr7_h3", "volatility_expansion", "CANDIDATE", partial(G.nr7, hold=3), "NR7 breakout, hold 3 bars"),
    Candidate("nr7_h5", "volatility_expansion", "CANDIDATE", partial(G.nr7, hold=5), "NR7 breakout, hold 5 bars"),
    Candidate(
        "gated_er60_025",
        "trend_gated",
        "CANDIDATE",
        partial(_gated_donchian, threshold=0.25),
        "55/20 breakout with efficiency-ratio(60) >= 0.25 entry gate",
    ),
    Candidate(
        "gated_er60_035",
        "trend_gated",
        "CANDIDATE",
        partial(_gated_donchian, threshold=0.35),
        "55/20 breakout with efficiency-ratio(60) >= 0.35 entry gate",
    ),
    Candidate(
        "rsi2_t5_nofilter",
        "mean_reversion",
        "CANDIDATE",
        partial(G.rsi2, threshold=5.0, trend_filter=False),
        "RSI(2) < 5 buy / > 95 sell, no trend filter",
    ),
    Candidate(
        "rsi2_t5_sma200",
        "mean_reversion",
        "CANDIDATE",
        partial(G.rsi2, threshold=5.0, trend_filter=True),
        "RSI(2) < 5 buy above SMA200 / > 95 sell below SMA200",
    ),
    Candidate(
        "rsi2_t10_nofilter",
        "mean_reversion",
        "CANDIDATE",
        partial(G.rsi2, threshold=10.0, trend_filter=False),
        "RSI(2) < 10 buy / > 90 sell, no trend filter",
    ),
    Candidate(
        "rsi2_t10_sma200",
        "mean_reversion",
        "CANDIDATE",
        partial(G.rsi2, threshold=10.0, trend_filter=True),
        "RSI(2) < 10 buy above SMA200 / > 90 sell below SMA200",
    ),
    Candidate(
        "bollinger_20_2_control",
        "bollinger_control",
        "CONTROL",
        partial(G.bollinger, n=20, k=2.0),
        "Bollinger(20,2) fade to mean. Falsification control, never a candidate",
    ),
)

#: Every evaluated configuration counts toward the multiple-testing deflation.
N_TRIALS = len(CANDIDATES)
FAMILY_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(c.group for c in CANDIDATES if c.role == "CANDIDATE"))


def candidates_in(group: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CANDIDATES if c.group == group and c.role == "CANDIDATE")


def candidate_by_id(cid: str) -> Candidate:
    for c in CANDIDATES:
        if c.cid == cid:
            return c
    raise KeyError(cid)
