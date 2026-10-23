"""Cost-reserved, executable-quote scalping exits for registered DEMO policies.

No signal generation or profitability claim. A profit exit is only an
estimate: true P&L is determined by matched broker execution/deal records.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


def _positive(raw: Any, name: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError(f"scalp exit {name} must be a finite positive number") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError(f"scalp exit {name} must be a finite positive number")
    return value


@dataclass(frozen=True)
class ScalpExitPlan:
    """Frozen quote-based exit thresholds, in basis points unless specified."""

    take_profit_net_bps: Decimal
    extra_cost_reserve_bps: Decimal
    max_loss_net_bps: Decimal
    max_spread_bps: Decimal
    max_tick_age_s: Decimal

    @classmethod
    def from_mapping(cls, values: Any) -> ScalpExitPlan:
        if not isinstance(values, dict):
            raise ValueError("scalp exit must be an object")
        return cls(
            take_profit_net_bps=_positive(values.get("take_profit_net_bps"), "take_profit_net_bps"),
            extra_cost_reserve_bps=_positive(values.get("extra_cost_reserve_bps"), "extra_cost_reserve_bps"),
            max_loss_net_bps=_positive(values.get("max_loss_net_bps"), "max_loss_net_bps"),
            max_spread_bps=_positive(values.get("max_spread_bps"), "max_spread_bps"),
            max_tick_age_s=_positive(values.get("max_tick_age_s"), "max_tick_age_s"),
        )


@dataclass(frozen=True)
class ScalpExitDecision:
    close: bool
    reason: str
    estimated_net_bps: Decimal
    executable_quote_bps: Decimal
    spread_bps: Decimal


def decide_scalp_exit(
    plan: ScalpExitPlan,
    *,
    side: str,
    entry_price: Any,
    bid: Any,
    ask: Any,
    tick_age_s: Any,
) -> ScalpExitDecision:
    """Decide using bid to liquidate BUY and ask to liquidate SELL.

    The net result subtracts a strictly positive, preregistered reserve for
    commission/slippage/unknown costs. It is never a guaranteed realized profit.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError("scalp exit requires BUY or SELL broker direction")
    try:
        entry = Decimal(str(entry_price))
        bid_price = Decimal(str(bid))
        ask_price = Decimal(str(ask))
        age = Decimal(str(tick_age_s))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("scalp exit requires valid broker prices and tick age") from exc
    if (
        not all(x.is_finite() for x in (entry, bid_price, ask_price, age))
        or min(entry, bid_price, ask_price) <= 0
        or bid_price >= ask_price
        or age < 0
    ):
        raise ValueError("scalp exit requires positive, noncrossed broker quotes and finite age")
    if age > plan.max_tick_age_s:
        raise ValueError("scalp exit quote is stale; cannot authorize an estimated profit exit")

    executable_move = bid_price - entry if side == "BUY" else entry - ask_price
    executable_bps = executable_move / entry * Decimal("10000")
    estimated_net = executable_bps - plan.extra_cost_reserve_bps
    spread = (ask_price - bid_price) / ((bid_price + ask_price) / 2) * Decimal("10000")
    if estimated_net <= -plan.max_loss_net_bps:
        return ScalpExitDecision(True, "scalp_max_loss", estimated_net, executable_bps, spread)
    if spread > plan.max_spread_bps:
        return ScalpExitDecision(False, "scalp_spread_too_wide", estimated_net, executable_bps, spread)
    if estimated_net >= plan.take_profit_net_bps:
        return ScalpExitDecision(True, "scalp_take_profit", estimated_net, executable_bps, spread)
    return ScalpExitDecision(False, "scalp_hold", estimated_net, executable_bps, spread)
