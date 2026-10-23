"""Causal one-minute regime-based scalp entry proposals (research-only).

The movement proxy describes *past observed price variation*, not a prediction
of future profit. This module cannot place an order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal


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
    if regime == "UP" and (
        past[-1] < past[-2]
        and current > past[-1]
        and max(recent) - past[-1] >= volatility
        and current < max(recent)
    ):
        return ScalpIdea("BUY", "trend_pullback", regime, volatility * 2)
    if regime == "DOWN" and (
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


def propose_anticipatory_entry(closes: Sequence[Decimal]) -> ScalpIdea | None:
    """Detect a *potential* breakout setup BEFORE a confirmed range break.

    A causal price-compression and directional-pressure heuristic, not a
    calibrated probability, guarantee of a reversal, or future-price oracle.
    All 34 observations must be completed bars available at decision time.
    """
    if len(closes) < 34:
        return None
    values = [Decimal(str(v)) for v in closes[-34:]]
    if any(not v.is_finite() or v <= 0 for v in values):
        return None
    past, current = values[:-1], values[-1]
    channel = past[-20:]
    low, high = min(channel), max(channel)
    width = high - low
    if width <= 0 or not low < current < high:
        # Never chase a breakout that has already crossed its old boundary.
        return None

    changes = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    older = sum(changes[-24:-6], Decimal(0)) / Decimal(18)
    recent = sum(changes[-6:], Decimal(0)) / Decimal(6)
    if older <= 0 or width < older or recent <= 0 or recent > older * Decimal("0.65"):
        return None

    # A reproducible fixed setup window, NOT a probability estimate.
    # Require visible room before the old boundary, avoiding an entry that
    # already spent the whole available move.
    near_min = width * Decimal("0.12")
    near_max = width * Decimal("0.35")
    room_above = high - current
    if (
        near_min <= room_above <= near_max
        and current > past[-1] >= past[-2]
        and current > (high + low) / 2
    ):
        return ScalpIdea("BUY", "pre_breakout", "COMPRESSION", width / 2)
    room_below = current - low
    if (
        near_min <= room_below <= near_max
        and current < past[-1] <= past[-2]
        and current < (high + low) / 2
    ):
        return ScalpIdea("SELL", "pre_breakout", "COMPRESSION", width / 2)
    return None
