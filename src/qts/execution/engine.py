"""OrderManager + ExecutionEngine with Risk integration and idempotency."""

from __future__ import annotations

from decimal import Decimal

from qts.domain.events import DomainEvent, EventType
from qts.domain.value_objects import (
    Account,
    Bar,
    Fill,
    Order,
    OrderIntent,
    OrderState,
    Position,
    Tick,
    uuid7,
)
from qts.execution.matching import MatchingEngine
from qts.observability.audit import AuditLog
from qts.risk.engine import RiskContext, RiskEngine


class OrderManager:
    def __init__(self, audit: AuditLog | None = None):
        self.orders: dict[str, Order] = {}  # client_order_id -> Order
        self.audit = audit

    def submit(self, intent: OrderIntent) -> Order:
        # idempotency
        if intent.client_order_id in self.orders:
            return self.orders[intent.client_order_id]
        order = Order(
            order_id=uuid7(),
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            state=OrderState.PENDING,
            strategy_id=intent.strategy_id,
        )
        self.orders[intent.client_order_id] = order
        if self.audit:
            self.audit.emit(
                DomainEvent(
                    event_type=EventType.ORDER_EVENT,
                    payload={
                        "client_order_id": order.client_order_id,
                        "state": order.state.value,
                        "strategy_id": order.strategy_id,
                    },
                )
            )
        return order

    def update_state(self, client_order_id: str, state: OrderState, **kwargs) -> Order:
        order = self.orders[client_order_id]
        new = order.with_state(state, **kwargs)
        self.orders[client_order_id] = new
        if self.audit:
            self.audit.emit(
                DomainEvent(
                    event_type=EventType.ORDER_EVENT,
                    payload={
                        "client_order_id": client_order_id,
                        "from": order.state.value,
                        "to": state.value,
                    },
                )
            )
        return new

    def get(self, client_order_id: str) -> Order | None:
        return self.orders.get(client_order_id)

    def open_count(self) -> int:
        return sum(
            1
            for o in self.orders.values()
            if o.state in (OrderState.PENDING, OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED)
        )


class ReconcileReport:
    def __init__(self, drift: str, details: str = ""):
        self.drift = drift
        self.details = details


class BrokerAdapter:
    """Protocol for adapters. Minimal for tests."""

    def submit(self, intent: OrderIntent) -> Order:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def positions(self) -> list[Position]:
        return []

    def account(self) -> Account:
        return Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD")

    def orders(self) -> list[Order]:
        return []


class PaperBrokerAdapter(BrokerAdapter):
    def __init__(self, matching: MatchingEngine | None = None, account: Account | None = None):
        self.matching = matching or MatchingEngine()
        self._account = account or Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD")
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}

    def submit(self, intent: OrderIntent) -> Order:
        # immediate accept
        order = Order(
            order_id=uuid7(),
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            state=OrderState.ACCEPTED,
            strategy_id=intent.strategy_id,
        )
        self._orders[intent.client_order_id] = order
        return order

    def apply_fill(self, fill: Fill) -> None:
        sym = fill.instrument.symbol
        pos = self._positions.get(sym)
        qty_delta = fill.quantity if fill.side.value == "BUY" else -fill.quantity
        if pos is None:
            self._positions[sym] = Position(instrument=fill.instrument, quantity=qty_delta, avg_price=fill.price)
        else:
            # weighted avg
            new_qty = pos.quantity + qty_delta
            if new_qty == 0:
                self._positions[sym] = Position(
                    instrument=fill.instrument, quantity=Decimal("0"), avg_price=Decimal("0")
                )
            elif pos.quantity == 0:
                self._positions[sym] = Position(instrument=fill.instrument, quantity=new_qty, avg_price=fill.price)
            else:
                # if same direction, weighted
                if (pos.quantity > 0 and qty_delta > 0) or (pos.quantity < 0 and qty_delta < 0):
                    total = abs(pos.quantity) + abs(qty_delta)
                    avg = (abs(pos.quantity) * pos.avg_price + abs(qty_delta) * fill.price) / total
                    self._positions[sym] = Position(instrument=fill.instrument, quantity=new_qty, avg_price=avg)
                else:
                    # reducing or flipping — keep avg for remaining
                    self._positions[sym] = Position(
                        instrument=fill.instrument,
                        quantity=new_qty,
                        avg_price=pos.avg_price if new_qty != 0 else Decimal("0"),
                    )
        # mark order filled
        if fill.client_order_id in self._orders:
            o = self._orders[fill.client_order_id]
            self._orders[fill.client_order_id] = o.with_state(
                OrderState.FILLED, filled_quantity=fill.quantity, avg_fill_price=fill.price
            )

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def account(self) -> Account:
        return self._account

    def orders(self) -> list[Order]:
        return list(self._orders.values())


class ExecutionEngine:
    def __init__(
        self,
        order_manager: OrderManager,
        risk_engine: RiskEngine,
        broker: BrokerAdapter,
        matching: MatchingEngine,
        audit: AuditLog | None = None,
        account: Account | None = None,
    ):
        self.om = order_manager
        self.risk = risk_engine
        self.broker = broker
        self.matching = matching
        self.audit = audit
        self.account = account or Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD")
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.daily_pnl = Decimal("0")
        self.drawdown = Decimal("0")
        self.peak_equity = self.account.equity

    def _risk_ctx(self) -> RiskContext:
        return RiskContext(
            account=self.account,
            positions=self.positions,
            open_orders_count=self.om.open_count(),
            daily_pnl=self.daily_pnl,
            drawdown=self.drawdown,
            instrument_suspended=set(),
        )

    def submit_intent(
        self, intent: OrderIntent, bar: Bar | None = None, tick: Tick | None = None
    ) -> tuple[Order | None, list[Fill]]:
        # risk gate
        ctx = self._risk_ctx()
        decision = self.risk.pre_trade(intent, ctx)
        if not decision.allowed:
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RISK_VETO,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": decision.veto_reason.value if decision.veto_reason else "UNKNOWN",
                            "detail": decision.reason_detail,
                        },
                    )
                )
            return None, []
        # resize if needed
        if decision.resized_quantity is not None:
            intent = intent.model_copy(update={"quantity": decision.resized_quantity})
        self.om.submit(intent)
        # broker submit
        try:
            broker_order = self.broker.submit(intent)
            # update to accepted
            self.om.update_state(
                intent.client_order_id,
                OrderState.ACCEPTED,
                exchange_order_id=broker_order.exchange_order_id or broker_order.order_id,
            )
        except Exception as e:
            self.om.update_state(intent.client_order_id, OrderState.REJECTED, reject_reason=str(e))
            return None, []
        # matching to produce fills (for backtest/paper, broker is paper and matching drives fills)
        fills: list[Fill] = []
        if isinstance(self.broker, PaperBrokerAdapter) and bar is not None:
            fills = self.matching.match(intent, bar, tick)
            for fill in fills:
                self.fills.append(fill)
                # update positions
                sym = fill.instrument.symbol
                qty_delta = fill.quantity if fill.side.value == "BUY" else -fill.quantity
                pos = self.positions.get(sym)
                if pos is None:
                    self.positions[sym] = Position(instrument=fill.instrument, quantity=qty_delta, avg_price=fill.price)
                else:
                    new_qty = pos.quantity + qty_delta
                    self.positions[sym] = Position(
                        instrument=fill.instrument,
                        quantity=new_qty,
                        avg_price=fill.price if new_qty != 0 else Decimal("0"),
                    )
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.FILL,
                            payload={
                                "fill_id": fill.fill_id,
                                "client_order_id": fill.client_order_id,
                                "price": str(fill.price),
                                "quantity": str(fill.quantity),
                            },
                        )
                    )
                # post-trade risk
                self.risk.post_trade(fill, self._risk_ctx())
                # apply to paper broker
                self.broker.apply_fill(fill)
            # mark order filled
            self.om.update_state(
                intent.client_order_id,
                OrderState.FILLED,
                filled_quantity=intent.quantity,
                avg_fill_price=fills[0].price if fills else None,
            )
        else:
            # live: fills come via reconciler/poll, not here
            pass
        if self.audit:
            self.audit.emit(
                DomainEvent(
                    event_type=EventType.ORDER_INTENT,
                    payload={
                        "client_order_id": intent.client_order_id,
                        "quantity": str(intent.quantity),
                        "side": intent.side.value,
                    },
                )
            )
        return self.om.get(intent.client_order_id), fills

    def reconcile(self) -> ReconcileReport:
        venue_positions = {p.instrument.symbol: p for p in self.broker.positions()}
        for sym, local in self.positions.items():
            venue = venue_positions.get(sym)
            if venue is None and local.quantity != 0:
                return ReconcileReport("MISSING_POSITION", f"local {sym} {local.quantity} not on venue")
            if venue and venue.quantity != local.quantity:
                return ReconcileReport("QUANTITY_MISMATCH", f"{sym} local {local.quantity} vs venue {venue.quantity}")
        for sym, venue in venue_positions.items():
            if sym not in self.positions and venue.quantity != 0:
                return ReconcileReport("UNKNOWN_POSITION", f"venue {sym} {venue.quantity} not local")
        return ReconcileReport("NONE", "ok")
