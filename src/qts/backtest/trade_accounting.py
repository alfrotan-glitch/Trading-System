"""Read-only completed-position accounting for PAPER backtest fills.

Do not confuse fills with completed round trips. Aggregate consecutive same-side
adds using the weighted-average cost convention in qts.portfolio.portfolio.
Partial closes contribute to an eventual completed round trip; an unfinished
position is NOT counted as a win or loss. Execution fills already incorporate
spread/slippage in executed prices, and broker fees are deducted only once.

This module only summarizes the existing fill ledger. It makes no orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class TradeAccounting:
    completed_net_usd: tuple[Decimal, ...]
    fill_count: int
    incomplete_position_count: int
    realized_partial_close_pnl_usd: Decimal
    open_entry_fees_usd: Decimal

    @property
    def profit_factor(self) -> float:
        gains = sum((x for x in self.completed_net_usd if x > 0), Decimal("0"))
        losses = -sum((x for x in self.completed_net_usd if x < 0), Decimal("0"))
        # With no losing round trip, PF is mathematically undefined.
        # The research gate must never interpret +inf as validated alpha.
        if losses == 0:
            return 0.0
        return float(gains / losses)


@dataclass
class _OpenRoundTrip:
    signed_lots: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    entry_fee_remaining: Decimal = Decimal("0")
    accrued_net_partial_exits: Decimal = Decimal("0")
    contract_size: Decimal = Decimal("0")


def _positive_decimal(raw: Any, name: str) -> Decimal:
    try:
        x = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid fill {name}") from exc
    if not x.is_finite() or x <= 0:
        raise ValueError(f"invalid fill {name}")
    return x


def _fee(raw: Any) -> Decimal:
    try:
        x = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid fill fee") from exc
    if not x.is_finite() or x < 0:
        raise ValueError("invalid fill fee")
    return x


def summarize_completed_trades(fills: list[dict[str, Any]]) -> TradeAccounting:
    """Pure ledger fold; never infers profit from marks or unclosed positions."""
    states: dict[str, _OpenRoundTrip] = {}
    completed: list[Decimal] = []
    for item in fills:
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("missing fill symbol")
        side = item.get("side")
        if side not in ("BUY", "SELL"):
            raise ValueError("invalid fill side")
        volume = _positive_decimal(item.get("qty"), "quantity")
        price = _positive_decimal(item.get("price"), "price")
        contract = _positive_decimal(item.get("contract_size"), "contract size")
        fee = _fee(item.get("fee"))
        signed = volume if side == "BUY" else -volume
        state = states.setdefault(symbol, _OpenRoundTrip(contract_size=contract))
        if state.contract_size != contract:
            raise ValueError("contract size changed mid-position")

        if state.signed_lots == 0:
            state.signed_lots = signed
            state.avg_price = price
            state.entry_fee_remaining = fee
            state.accrued_net_partial_exits = Decimal("0")
            continue

        old = state.signed_lots
        if (old > 0 and signed > 0) or (old < 0 and signed < 0):
            state.avg_price = (
                abs(old) * state.avg_price + volume * price
            ) / (abs(old) + volume)
            state.signed_lots += signed
            state.entry_fee_remaining += fee
            continue

        close_lots = min(abs(old), volume)
        closed_fee = fee * close_lots / volume
        entry_fee_closed = state.entry_fee_remaining * close_lots / abs(old)
        direction = Decimal("1") if old > 0 else Decimal("-1")
        price_pnl = direction * close_lots * contract * (price - state.avg_price)
        state.accrued_net_partial_exits += price_pnl - closed_fee - entry_fee_closed
        state.entry_fee_remaining -= entry_fee_closed

        remaining = old + signed
        if remaining == 0 or (remaining > 0) != (old > 0):
            completed.append(state.accrued_net_partial_exits)
            # A single reversal fill closes the former position AND opens
            # a new one. Split its fees according to the actual fill volume.
            new_fee = fee - closed_fee
            state.signed_lots = remaining
            if remaining:
                state.avg_price = price
                state.entry_fee_remaining = new_fee
            else:
                state.avg_price = Decimal("0")
                state.entry_fee_remaining = Decimal("0")
            state.accrued_net_partial_exits = Decimal("0")
        else:
            # Partial close: same entry basis, remaining opening costs
            # are still attached to the unfinished position.
            state.signed_lots = remaining

    unfinished = [state for state in states.values() if state.signed_lots]
    return TradeAccounting(
        completed_net_usd=tuple(completed),
        fill_count=len(fills),
        incomplete_position_count=len(unfinished),
        realized_partial_close_pnl_usd=sum(
            (x.accrued_net_partial_exits for x in unfinished), Decimal("0")
        ),
        open_entry_fees_usd=sum(
            (x.entry_fee_remaining for x in unfinished), Decimal("0")
        ),
    )
