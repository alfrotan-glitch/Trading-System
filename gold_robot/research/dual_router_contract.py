"""Deterministic contract for TESTER-ONLY Retest/Sweep research.

Modes 1/2 preserve historical routing. Mode 3 is a predeclared, direction-
neutral execution-quality tie-break; it has NO validated profitable edge.
This Python model is used for contract tests, never for sending MT5 orders.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

RETEST = 1
SWEEP = 3
QUALITY_MARGIN_R = 0.15


@dataclass(frozen=True)
class Candidate:
    style: int
    side: int
    executable: bool = True
    quality_score: float | None = None


def candidate_quality_score(
    *, atr: float, price: float, stop: float, target: float,
    bid: float, ask: float, adverse_slip: float,
) -> float | None:
    """Price-unit stress score, NOT a fill probability or net profitability."""
    values=(atr,price,stop,target,bid,ask,adverse_slip)
    if not all(math.isfinite(v) for v in values):
        return None
    risk=abs(price-stop)
    reward=abs(target-price)
    spread=ask-bid
    if atr<=0 or risk<=0 or reward<=0 or spread<0 or adverse_slip<0:
        return None
    mid=(ask+bid)*0.5
    return ((reward-spread-adverse_slip)/(risk+spread+adverse_slip)
            -0.05*abs(price-mid)/atr)


def choose(mode: int, candidates: list[Candidate]) -> tuple[int, int] | None:
    """One candidate or abstain; never combine two exposures.

    Mode 1: original both-direction selection, abstain on collisions.
    Mode 2: hindsight-derived directional challenger, abstain on collisions.
    Mode 3: direction-neutral mode, scores ONLY same-side collisions. Score
    does not override the real MT5 cost/margin/SL/TP eligibility checks.
    """
    if mode not in (1,2,3):
        raise ValueError("Dual router unavailable outside isolated research modes 1/2/3")
    styles=[c.style for c in candidates]
    if len(styles)!=len(set(styles)) or any(style not in (RETEST,SWEEP) for style in styles):
        raise ValueError("Ambiguous or unsupported strategy identity")
    if any(c.side not in (-1,0,1) for c in candidates):
        raise ValueError("Invalid BUY/SELL side")
    valid=[c for c in candidates
           if c.executable and c.side and
           (mode!=2 or (c.style==RETEST and c.side==1) or
            (c.style==SWEEP and c.side==-1))]
    if len(valid)==1:
        return (valid[0].style,valid[0].side)
    if len(valid)!=2 or mode!=3 or valid[0].side!=valid[1].side:
        return None
    x,y=valid
    if (x.quality_score is None or y.quality_score is None or
        not math.isfinite(x.quality_score) or
        not math.isfinite(y.quality_score) or
        x.quality_score<0 or y.quality_score<0 or
        abs(x.quality_score-y.quality_score)<QUALITY_MARGIN_R):
        return None
    winner=x if x.quality_score>y.quality_score else y
    return (winner.style,winner.side)
