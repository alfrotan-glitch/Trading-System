"""Portfolio — single source of truth for positions, PnL, equity.

Canonical quantity: **lots** (broker lots). For XAUUSD, contract_size=100 oz/lot.
Notional USD = quantity(lots) * contract_size(oz/lot) * price(USD/oz)
PnL USD     = quantity_closed(lots) * contract_size * price_diff

Positions are netting (single net position per symbol). Avg price is weighted
for same-direction adds, unchanged for partial closes, reset on flip.
"""

from __future__ import annotations

from decimal import Decimal

from qts.domain.value_objects import Fill, Instrument, Position


class Portfolio:
    def __init__(self, initial_balance: Decimal, currency: str = "USD"):
        self.initial_balance: Decimal = Decimal(str(initial_balance))
        self.currency = currency
        self.balance: Decimal = self.initial_balance  # cash balance (realized PnL added)
        self.positions: dict[str, Position] = {}  # symbol -> Position (qty in lots, avg_price per oz)
        self.realized_pnl: Decimal = Decimal("0")  # cumulative realized incl. fees
        self.fills: list[Fill] = []
        # last mark price per symbol for unrealized calc
        self._last_price: dict[str, Decimal] = {}

    def _instrument_for_fill(self, fill: Fill) -> Instrument:
        return fill.instrument

    def apply_fill(self, fill: Fill) -> None:
        """Apply fill to portfolio, updating realized/unrealized and balance.

        Correctly handles:
        - adding to position (same direction) → weighted avg
        - partial close → realized, avg unchanged, qty reduced
        - full close → realized, qty 0, avg 0
        - flip → realized for closed portion, new position qty/direction at fill price
        Fees are deducted from realized immediately.
        """
        self.fills.append(fill)
        sym = fill.instrument.symbol
        contract = fill.instrument.contract_size  # oz per lot, Decimal
        qty_delta_lots = fill.quantity if fill.side.value == "BUY" else -fill.quantity  # signed lots
        fee = fill.fee  # already in account currency
        pos = self.positions.get(sym)

        if pos is None or pos.quantity == Decimal("0"):
            # opening new position (or flat)
            if qty_delta_lots == Decimal("0"):
                return
            self.positions[sym] = Position(
                instrument=fill.instrument,
                quantity=qty_delta_lots,
                avg_price=fill.price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
            self.realized_pnl -= fee
            self.balance -= fee
            self._last_price[sym] = fill.price
            return

        old_qty = pos.quantity
        old_avg = pos.avg_price

        # same direction: add
        if (old_qty > 0 and qty_delta_lots > 0) or (old_qty < 0 and qty_delta_lots < 0):
            total_abs = abs(old_qty) + abs(qty_delta_lots)
            # weighted avg price per oz
            new_avg = (abs(old_qty) * old_avg + abs(qty_delta_lots) * fill.price) / total_abs
            new_qty = old_qty + qty_delta_lots
            self.positions[sym] = Position(
                instrument=fill.instrument,
                quantity=new_qty,
                avg_price=new_avg,
                unrealized_pnl=Decimal("0"),
                realized_pnl=pos.realized_pnl,
            )
            self.realized_pnl -= fee
            self.balance -= fee
            self._last_price[sym] = fill.price
            return

        # opposite direction: closing (partial/full) or flipping
        close_lots = min(abs(old_qty), abs(qty_delta_lots))
        # realized for closed portion: lots * contract_size * price_diff
        # long closed by sell vs short closed by buy
        price_diff = fill.price - old_avg if old_qty > 0 else old_avg - fill.price  # USD/oz

        realized_for_close = close_lots * contract * price_diff
        self.realized_pnl += realized_for_close - fee
        self.balance += realized_for_close - fee

        remaining_old = old_qty + qty_delta_lots  # could be +/ -/0
        # if old and delta have opposite signs and magnitudes
        if remaining_old == Decimal("0"):
            # flat
            self.positions[sym] = Position(
                instrument=fill.instrument,
                quantity=Decimal("0"),
                avg_price=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
        elif (remaining_old > 0) == (old_qty > 0):
            # partial close, same direction remains, avg unchanged
            self.positions[sym] = Position(
                instrument=fill.instrument,
                quantity=remaining_old,
                avg_price=old_avg,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
        else:
            # flip: remaining is opposite direction, opened at fill price
            # e.g. long 0.5, sell 1.0 → close 0.5, new short 0.5 at  fill price
            self.positions[sym] = Position(
                instrument=fill.instrument,
                quantity=remaining_old,
                avg_price=fill.price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
        self._last_price[sym] = fill.price

    def mark_to_market(self, symbol: str, price: Decimal) -> None:
        """Update unrealized PnL for symbol at given price (mid/close)."""
        self._last_price[symbol] = price
        pos = self.positions.get(symbol)
        if pos is None or pos.quantity == Decimal("0"):
            return
        contract = pos.instrument.contract_size
        if pos.quantity > 0:
            unrealized = pos.quantity * contract * (price - pos.avg_price)
        else:
            unrealized = abs(pos.quantity) * contract * (pos.avg_price - price)
        # update position with unrealized
        self.positions[symbol] = pos.model_copy(update={"unrealized_pnl": unrealized})

    def mark_all(self, prices: dict[str, Decimal]) -> None:
        for sym, price in prices.items():
            self.mark_to_market(sym, price)

    def unrealized_total(self) -> Decimal:
        return sum((p.unrealized_pnl for p in self.positions.values()), Decimal("0"))

    def equity(self) -> Decimal:
        """Equity = balance + unrealized (balance already includes realized)."""
        # balance = initial + realized (fees already deducted)
        # equity = balance + unrealized
        return self.balance + self.unrealized_total()

    def exposure_lots(self) -> Decimal:
        return sum((abs(p.quantity) for p in self.positions.values()), Decimal("0"))

    def exposure_notional(self) -> Decimal:
        """Sum of notional per position: |qty| * contract_size * price."""
        total = Decimal("0")
        for sym, pos in self.positions.items():
            price = self._last_price.get(sym, pos.avg_price)
            if price == Decimal("0"):
                continue
            total += abs(pos.quantity) * pos.instrument.contract_size * price
        return total

    def net_quantity(self, symbol: str) -> Decimal:
        p = self.positions.get(symbol)
        return p.quantity if p else Decimal("0")

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def daily_pnl(self) -> Decimal:
        """Simplified: realized + unrealized relative to initial_balance."""
        return self.equity() - self.initial_balance
