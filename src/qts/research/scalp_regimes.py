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
    # Only early candidates record the causal boundary known at signal time.
    # This is a price reference, NOT a promised take-profit fill.
    boundary_price: Decimal | None = None


def propose_scalp_entry(closes: Sequence[Decimal]) -> ScalpIdea | None:
    """Propose trend-pullback, breakout, or range-fade on 34 closed bars."""
    if len(closes) < 34:
        return None
    # Replay stores completed closes in a deque, which does not support
    # slice indexing. Convert only the bounded 34-bar window.
    values = [Decimal(str(c)) for c in list(closes)[-34:]]
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
    values = [Decimal(str(v)) for v in list(closes)[-34:]]
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
        return ScalpIdea("BUY", "pre_breakout", "COMPRESSION", width / 2, high)
    room_below = current - low
    if (
        near_min <= room_below <= near_max
        and current < past[-1] <= past[-2]
        and current < (high + low) / 2
    ):
        return ScalpIdea("SELL", "pre_breakout", "COMPRESSION", width / 2, low)
    return None


def propose_counter_pressure_entry(closes: Sequence[Decimal]) -> ScalpIdea | None:
    """Research challenger: fade the same causal compression pressure setup.

    No new optimized thresholds. The competing hypothesis is a short-lived
    reversal toward the previously observed channel midpoint instead of a
    breakout. Same signals, reverse direction, same fixed risk/exit model.
    """
    original = propose_anticipatory_entry(closes)
    if original is None:
        return None
    values = [Decimal(str(v)) for v in list(closes)[-34:]]
    channel = values[-21:-1]  # Previous 20 completed prices, excluding signal bar.
    midpoint = (min(channel) + max(channel)) / 2
    return ScalpIdea(
        "SELL" if original.side == "BUY" else "BUY",
        "pre_breakout_fade",
        "COMPRESSION_FADE",
        original.movement_proxy_price,
        midpoint,
    )


def early_entry_still_has_room(
    idea: ScalpIdea,
    *,
    bid: Decimal,
    ask: Decimal,
    reserve_bps: Decimal,
    margin_bps: Decimal,
) -> bool:
    """Refuse an early order if its old range boundary is already consumed.

    Use the executable ask for BUY and bid for SELL at *actual entry time*,
    not the earlier signal's mid close. This protects against overnight/gap
    jumps and last-millisecond chasing; it does not assert that the boundary
    will be reached or that its mid price can be filled.
    """
    if idea.family not in ("pre_breakout", "pre_breakout_fade"):
        return True
    boundary = idea.boundary_price
    numbers = (bid, ask, reserve_bps, margin_bps)
    if (
        boundary is None or not boundary.is_finite() or boundary <= 0
        or any(not x.is_finite() for x in numbers)
        or bid <= 0 or ask <= bid or reserve_bps < 0 or margin_bps <= 0
    ):
        return False
    if idea.side == "BUY":
        remaining = (boundary - ask) * Decimal("10000") / ask
    elif idea.side == "SELL":
        remaining = (bid - boundary) * Decimal("10000") / bid
    else:
        return False
    return remaining > reserve_bps + margin_bps
