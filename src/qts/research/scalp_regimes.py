"""Causal one-minute regime-based scalp entry proposals (research-only).

The movement proxy describes *past observed price variation*, not a prediction
of future profit. This module cannot place an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence


@dataclass(frozen=True)
class ScalpIdea:
    side: str
    family: str
    regime: str
    movement_proxy_price: Decimal


def propose_scalp_entry(closes: Sequence[Decimal]) -> ScalpIdea | None:
    """Propose trend-pullback, breakout, or range-fade on 34 closed bars."""
    if len(closes) < 34:
        return None
    values = [Decimal(str(c)) for c in closes[-34:]]
    if any(not p.is_finite() or p <= 0 for p in values):
        return None
    past = values[-33:-1]
    current = values[-1]
    steps = [past[i] - past[i - 1] for i in range(1, len(past))]
    absolute_steps = sum((abs(v) for v in steps), Decimal("0"))
    if absolute_steps <= 0:
        return None
    efficiency = abs(past[-1] - past[0]) / absolute_steps
    volatility = absolute_steps / Decimal(len(steps))
    low, high = min(past), max(past)
    width = high - low
    if width <= volatility:
        return None
    drift = past[-1] - past[0]
    if efficiency >= Decimal("0.43") and drift > 0:
        regime = "UP"
    elif efficiency >= Decimal("0.43") and drift < 0:
        regime = "DOWN"
    elif efficiency <= Decimal("0.28"):
        regime = "RANGE"
    else:
        regime = "TRANSITION"

    recent = past[-9:]
    if regime == "UP":
        if (
            past[-1] < past[-2]
            and current > past[-1]
            and max(recent) - past[-1] >= volatility
            and current < max(recent)
        ):
            return ScalpIdea("BUY", "trend_pullback", regime, volatility * 2)
    if regime == "DOWN":
        if (
            past[-1] > past[-2]
            and current < past[-1]
            and past[-1] - min(recent) >= volatility
            and current > min(recent)
        ):
            return ScalpIdea("SELL", "trend_pullback", regime, volatility * 2)
    if regime == "RANGE":
        if low <= current <= low + width * Decimal("0.25") and current > past[-1]:
            return ScalpIdea("BUY", "range_fade", regime, volatility * 2)
        if high - width * Decimal("0.25") <= current <= high and current < past[-1]:
            return ScalpIdea("SELL", "range_fade", regime, volatility * 2)
    if regime in ("UP", "TRANSITION") and current > max(past[-20:]) + volatility * Decimal("0.2"):
        return ScalpIdea("BUY", "breakout", regime, volatility * 2)
    if regime in ("DOWN", "TRANSITION") and current < min(past[-20:]) - volatility * Decimal("0.2"):
        return ScalpIdea("SELL", "breakout", regime, volatility * 2)
    return None
