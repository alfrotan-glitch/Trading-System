"""Portfolio — positions + account, updated only via fills."""

from __future__ import annotations

from decimal import Decimal

from qts.domain.value_objects import Account, Fill, Position


class Portfolio:
    def __init__(self, account: Account):
        self.account = account
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []

    def apply_fill(self, fill: Fill) -> None:
        self.fills.append(fill)
        sym = fill.instrument.symbol
        pos = self.positions.get(sym)
        delta = fill.quantity if fill.side.value == "BUY" else -fill.quantity
        if pos is None:
            self.positions[sym] = Position(instrument=fill.instrument, quantity=delta, avg_price=fill.price)
        else:
            new_qty = pos.quantity + delta
            # simplified avg
            self.positions[sym] = Position(
                instrument=fill.instrument,
                quantity=new_qty,
                avg_price=fill.price if new_qty != 0 else Decimal("0"),
            )

    def exposure(self) -> Decimal:
        return sum((abs(p.quantity) for p in self.positions.values()), Decimal("0"))

    def net_quantity(self, symbol: str) -> Decimal:
        p = self.positions.get(symbol)
        return p.quantity if p else Decimal("0")
