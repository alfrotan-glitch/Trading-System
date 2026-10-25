"""Bid/ask tick replay for pending LIMIT research; NOT a broker-fill simulator.

Touch fills assume available liquidity at the limit and are optimistic about
queue priority; live fill-rate, fees and latency must be measured separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class Tick:
    time_ms: int
    bid: float
    ask: float


@dataclass(frozen=True)
class LimitPlan:
    side: int  # 1 buy limit, -1 sell limit
    entry: float
    stop: float
    target: float
    placed_ms: int
    expires_ms: int
    volume_lots: float = 0.01
    contract_size: float = 100.0
    round_turn_fee_per_lot: float = 10.0
    adverse_slip_price: float = 0.10
    max_hold_ms: int = 15 * 60 * 1000


@dataclass(frozen=True)
class Result:
    outcome: str  # pending_unfilled, pending_at_end, stop, target, timeout, open_at_end
    filled_ms: int | None
    closed_ms: int | None
    gross_usd: float
    net_usd: float


def replay(plan: LimitPlan, ticks: Iterable[Tick]) -> Result:
    """Apply the quote on the correct side; stop is checked before TP.

    Fill price remains the pending limit on a touch (no fictitious favorable
    gap improvement). A gap through the stop uses the adverse market quote.
    Missing quotes cannot be invented; open_at_end is NOT a closed trade.
    """
    vals = (plan.entry, plan.stop, plan.target, plan.volume_lots,
            plan.contract_size, plan.round_turn_fee_per_lot,
            plan.adverse_slip_price)
    if (plan.side not in (-1, 1) or not all(isfinite(v) for v in vals)
            or min(plan.entry, plan.stop, plan.target, plan.volume_lots,
                   plan.contract_size) <= 0
            or plan.round_turn_fee_per_lot < 0 or plan.adverse_slip_price < 0
            or plan.placed_ms >= plan.expires_ms or plan.max_hold_ms <= 0
            or plan.side * (plan.entry - plan.stop) <= 0
            or plan.side * (plan.target - plan.entry) <= 0):
        raise ValueError("invalid limit plan")
    filled_at: int | None = None
    last_ms: int | None = None
    fees = plan.round_turn_fee_per_lot * plan.volume_lots

    def closed(why: str, t: int, price: float) -> Result:
        gross = plan.side * (price - plan.entry) * plan.contract_size * plan.volume_lots
        return Result(why, filled_at, t, gross, gross - fees)

    for tick in ticks:
        if (tick.time_ms < 0 or not all(isfinite(x) for x in (tick.bid, tick.ask))
                or tick.bid <= 0 or tick.ask <= tick.bid):
            raise ValueError("invalid bid/ask tick")
        if last_ms is not None and tick.time_ms <= last_ms:
            raise ValueError("ticks must be strictly chronological")
        last_ms = tick.time_ms
        if tick.time_ms <= plan.placed_ms:  # never execute using decision tick
            continue
        if filled_at is None:
            if tick.time_ms >= plan.expires_ms:  # expiration wins exact timestamp
                return Result("pending_unfilled", None, None, 0.0, 0.0)
            hit = tick.ask <= plan.entry if plan.side == 1 else tick.bid >= plan.entry
            if not hit:
                continue
            filled_at = tick.time_ms
        # Quotes are executable: liquidate BUY at bid / SELL at ask.
        exit_quote = tick.bid if plan.side == 1 else tick.ask
        stop_hit = exit_quote <= plan.stop if plan.side == 1 else exit_quote >= plan.stop
        if stop_hit:
            price = (min(exit_quote, plan.stop) - plan.adverse_slip_price
                     if plan.side == 1 else
                     max(exit_quote, plan.stop) + plan.adverse_slip_price)
            return closed("stop", tick.time_ms, price)
        target_hit = exit_quote >= plan.target if plan.side == 1 else exit_quote <= plan.target
        if target_hit:
            return closed("target", tick.time_ms, plan.target)
        if tick.time_ms - filled_at >= plan.max_hold_ms:
            return closed("timeout", tick.time_ms, exit_quote)
    if filled_at is None:
        # Quote coverage ended before broker-side expiry. This is not
        # evidence that the order would never have filled.
        return Result("pending_at_end", None, None, 0.0, 0.0)
    return Result("open_at_end", filled_at, None, 0.0, 0.0)
