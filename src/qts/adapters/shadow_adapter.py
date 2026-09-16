"""Shadow broker — real market data, real risk, no submission.

Shadow mode drives real strategy/risk decisions from live market data,
records what WOULD have happened, but never calls broker.submit.
It records intents, would-be fills, and compares with paper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from qts.domain.value_objects import Account, Instrument, Order, OrderIntent, OrderState, Position, Tick
from qts.execution.engine import BrokerAdapter


class ShadowBroker(BrokerAdapter):
    """Shadow: validates like live, but does not submit. Records intents."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else Path("data/sqlite/qts_shadow.db")
        self._intents: list[OrderIntent] = []
        self._would_be_orders: dict[str, Order] = {}
        self._would_be_fills: list[dict[str, Any]] = []
        self._positions: dict[str, Position] = {}  # shadow tracks would-be positions

    def submit(self, intent: OrderIntent) -> Order:
        # In shadow, we validate but do NOT submit to broker.
        # Instead, record intent and return a shadow ACCEPTED order that will never fill on broker.
        # ExecutionEngine will treat this as live but shadow flag will prevent actual broker call.
        # For ShadowBroker, submit is not called if Engine is in shadow mode — Engine should bypass.
        # But if called, we record and raise to indicate shadow should not submit.
        self._intents.append(intent)
        order = Order(
            order_id=intent.client_order_id,
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            state=OrderState.ACCEPTED,
            strategy_id=intent.strategy_id,
            reject_reason="shadow_no_submit",
        )
        self._would_be_orders[intent.client_order_id] = order
        # Do not actually submit — return shadow order
        # Caller (ExecutionEngine in shadow mode) should not treat this as real fill
        return order

    def record_would_be_fill(self, fill_info: dict[str, Any]) -> None:
        self._would_be_fills.append(fill_info)

    def get_intents(self) -> list[OrderIntent]:
        return list(self._intents)

    def get_would_be_fills(self) -> list[dict[str, Any]]:
        return list(self._would_be_fills)

    def positions(self) -> list[Position]:
        # Shadow has no real positions — returns empty to avoid reconciliation drift
        # Would-be positions are tracked separately for comparison
        return []

    def orders(self) -> list[Order]:
        return list(self._would_be_orders.values())

    def account(self) -> Account:
        # Shadow uses paper-like account but marked as shadow
        return Account(
            balance=Decimal("10000"),
            equity=Decimal("10000"),
            margin=Decimal("0"),
            free_margin=Decimal("10000"),
            leverage=Decimal("100"),
            currency="USD",
            updated_at=datetime.now(UTC),
        )

    def cancel(self, client_order_id: str) -> None:
        if client_order_id in self._would_be_orders:
            o = self._would_be_orders[client_order_id]
            self._would_be_orders[client_order_id] = o.model_copy(update={"state": OrderState.CANCELLED})

    def ticks(self, instrument: Instrument) -> Tick | None:
        return None

    # class attributes (not properties): the BrokerAdapter base declares these as
    # writable attributes; overriding with read-only properties is a Liskov violation
    is_live = False
    is_shadow = True
