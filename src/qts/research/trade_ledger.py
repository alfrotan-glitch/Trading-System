"""Turn a stream of fills into round-turn trades with a measured cost.

Why this module exists
----------------------
A backtest produces *fills*. Everything an edge claim needs — expectancy,
profit factor, cost sensitivity, break-even — is defined on *round turns*.
The gap between those two is why the canonical edge evidence recorded
``net_exp 0.0000 pf 0.00``: there was no code that paired an entry with its
exit and attributed the P&L between them.

Pairing rules
-------------
* **FIFO.** The oldest open lot is the first one closed. Not LIFO, not
  average-cost, not "whatever makes it look best" — FIFO is the convention a
  broker statement uses, so it is the convention the numbers must use.
* **Direction flips close.** A fill against the current inventory closes lots;
  a fill in the same direction (or from flat) opens them.
* **Unpaired remainder stays open.** An unfinished position is reported as an
  open lot, never as a completed trade, and never as a zero-P&L round turn.

Two P&L figures, deliberately
-----------------------------
``gross_pnl_usd`` is the frictionless mid-to-mid P&L, using the reference price
the matching engine priced the fill against. ``realized_pnl_usd`` is the P&L at
the prices actually filled, net of fees. The difference is
``measured_cost_usd`` — the cost the simulation really charged, as opposed to
the cost a :class:`~qts.research.costs.CostModel` predicts.

A backtest can therefore say "your model assumed 5 USD per round turn; the
simulation charged 7.20 USD" instead of reporting one conflated number.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RoundTurn:
    """One completed entry/exit pair."""

    side: str  # direction of the OPENING fill
    lots: float
    entry_price: float  # filled price
    exit_price: float  # filled price
    entry_mid: float  # reference price the fill was priced against
    exit_mid: float  # reference price the fill was priced against
    opened_at: str | None
    closed_at: str | None
    nights_held: float
    #: Frictionless mid-to-mid P&L, in USD.
    gross_pnl_usd: float
    #: P&L at the filled prices, net of fees, in USD.
    realized_pnl_usd: float
    #: Fees charged on both fills, in USD (positive).
    fees_usd: float

    @property
    def measured_cost_usd(self) -> float:
        """What the simulation actually took: spread, slippage and fees."""
        return self.gross_pnl_usd - self.realized_pnl_usd

    def as_dict(self) -> dict[str, object]:
        return {
            "side": self.side,
            "lots": self.lots,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_mid": self.entry_mid,
            "exit_mid": self.exit_mid,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "nights_held": self.nights_held,
            "gross_pnl_usd": self.gross_pnl_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "fees_usd": self.fees_usd,
            "measured_cost_usd": self.measured_cost_usd,
        }


@dataclass(frozen=True)
class OpenLot:
    """Inventory left open at the end of the fill stream."""

    side: str
    lots: float
    price: float
    mid: float
    opened_at: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "side": self.side,
            "lots": self.lots,
            "price": self.price,
            "mid": self.mid,
            "opened_at": self.opened_at,
        }


@dataclass
class TradeLedger:
    """The result of pairing a fill stream."""

    round_turns: list[RoundTurn] = field(default_factory=list)
    open_lots: list[OpenLot] = field(default_factory=list)
    fills_consumed: int = 0
    unparseable_fills: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def trades(self) -> int:
        return len(self.round_turns)

    @property
    def gross_pnl_usd(self) -> float:
        return float(sum(t.gross_pnl_usd for t in self.round_turns))

    @property
    def realized_pnl_usd(self) -> float:
        return float(sum(t.realized_pnl_usd for t in self.round_turns))

    @property
    def measured_cost_usd(self) -> float:
        return float(sum(t.measured_cost_usd for t in self.round_turns))

    def as_dict(self) -> dict[str, object]:
        return {
            "trades": self.trades,
            "open_lots": [lot.as_dict() for lot in self.open_lots],
            "fills_consumed": self.fills_consumed,
            "unparseable_fills": self.unparseable_fills,
            "gross_pnl_usd": self.gross_pnl_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "measured_cost_usd": self.measured_cost_usd,
            "round_turns": [t.as_dict() for t in self.round_turns],
            "reasons": list(self.reasons),
        }


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #


def _to_float(value: object) -> float | None:
    try:
        out = float(str(value))
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _nights_between(start: datetime | None, end: datetime | None) -> float:
    """Calendar nights a position was held across.

    Intraday is 0. Held across one midnight is 1. This is the unit a swap
    schedule charges in, so it is the unit reported here — not hours, not bars.
    """
    if start is None or end is None:
        return 0.0
    days = (end.date() - start.date()).days
    return float(max(0, days))


# --------------------------------------------------------------------------- #
# the pairing
# --------------------------------------------------------------------------- #


def round_turns_from_fills(
    fills: list[dict],
    contract_size: float = 100.0,
) -> TradeLedger:
    """Pair a chronological fill stream into round turns (FIFO).

    ``fills`` items are the dictionaries a :class:`BacktestResult` records:
    ``price``, ``qty``, ``side``, ``time``, ``bar_open`` (the reference price)
    and optionally ``fee``. Quantities are in lots; P&L is converted to USD
    with ``contract_size``.

    Fills that cannot be parsed are counted, not skipped silently: a ledger
    that quietly dropped a fill would understate cost and overstate edge.
    """
    if contract_size <= 0:
        raise ValueError("contract_size must be > 0")

    ledger = TradeLedger()
    # Inventory of open lots in one direction, oldest first. Only one direction
    # can be open at a time (netting), which is what a single-instrument
    # long/short strategy actually does.
    inventory: deque[OpenLot] = deque()

    for raw in fills:
        if not isinstance(raw, dict):
            ledger.unparseable_fills += 1
            continue
        side = str(raw.get("side") or "").upper()
        qty = _to_float(raw.get("qty"))
        price = _to_float(raw.get("price"))
        mid = _to_float(raw.get("bar_open"))
        if side not in ("BUY", "SELL") or qty is None or price is None or qty <= 0:
            ledger.unparseable_fills += 1
            continue
        if mid is None:
            # No reference price: fall back to the fill price. The measured cost
            # is then structurally 0, which must be visible, not hidden.
            mid = price
            ledger.reasons.append(
                f"fill at {raw.get('time')} has no reference price (bar_open) — measured cost understated"
            )
        at = raw.get("time")
        at_text = str(at) if at is not None else None
        moment = _parse_time(at)
        ledger.fills_consumed += 1

        remaining = qty
        # 1) close against the opposite side of the book, oldest first
        while remaining > 0 and inventory and inventory[0].side != side:
            lot = inventory[0]
            closed = min(lot.lots, remaining)
            direction = 1.0 if lot.side == "BUY" else -1.0
            notional_lots = closed * contract_size

            gross = (mid - lot.mid) * direction * notional_lots
            realized = (price - lot.price) * direction * notional_lots
            fee_share = (float(raw.get("fee") or 0.0) / qty) * closed if qty else 0.0

            ledger.round_turns.append(
                RoundTurn(
                    side=lot.side,
                    lots=closed,
                    entry_price=lot.price,
                    exit_price=price,
                    entry_mid=lot.mid,
                    exit_mid=mid,
                    opened_at=lot.opened_at,
                    closed_at=at_text,
                    nights_held=_nights_between(_parse_time(lot.opened_at), moment),
                    gross_pnl_usd=gross,
                    realized_pnl_usd=realized - fee_share,
                    fees_usd=fee_share,
                )
            )
            remaining -= closed
            if closed >= lot.lots:
                inventory.popleft()
            else:
                inventory[0] = OpenLot(
                    side=lot.side,
                    lots=lot.lots - closed,
                    price=lot.price,
                    mid=lot.mid,
                    opened_at=lot.opened_at,
                )

        # 2) whatever is left opens (or extends) a position.
        #
        # Lots are APPENDED, never merged. Averaging two entry prices into one
        # lot would be average-cost accounting, and it would make the P&L of a
        # partial close depend on lots that are still open — which is not what
        # a broker statement does and not what FIFO means.
        if remaining > 0:
            fee_share_open = (float(raw.get("fee") or 0.0) / qty) * remaining if qty else 0.0
            inventory.append(OpenLot(side=side, lots=remaining, price=price, mid=mid, opened_at=at_text))
            # Record the opening fee immediately so it is never lost: it is
            # attributed to the next round turn this lot participates in.
            if fee_share_open:
                ledger.reasons.append(
                    f"opening fee {fee_share_open:.4f} USD carried on an open {side} lot "
                    "(charged when the lot is closed; not yet in realized P&L)"
                )

    ledger.open_lots = list(inventory)
    if ledger.unparseable_fills:
        ledger.reasons.append(
            f"{ledger.unparseable_fills} fill(s) could not be parsed — the ledger is incomplete, not favourable"
        )
    return ledger


def to_trade_records(ledger: TradeLedger) -> list:
    """Convert a ledger into the :class:`TradeRecord` list a ``CostModel`` costs.

    The record carries the FRICTIONLESS gross P&L: a cost model is then applied
    on top of it. Feeding it the realized (already-costed) P&L would charge the
    same cost twice.
    """
    from qts.research.costs import TradeRecord

    return [
        TradeRecord(
            lots=t.lots,
            gross_pnl_usd=t.gross_pnl_usd,
            nights_held=t.nights_held,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            side=t.side,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
        )
        for t in ledger.round_turns
    ]
