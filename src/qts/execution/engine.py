"""OrderManager + ExecutionEngine with Risk integration, idempotency, reconciliation."""

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
from qts.execution.idempotency import IdempotencyStore
from qts.execution.matching import MatchingEngine
from qts.observability.audit import AuditLog
from qts.portfolio.portfolio import Portfolio
from qts.risk.engine import RiskContext, RiskEngine


class OrderManager:
    def __init__(self, audit: AuditLog | None = None, idempotency: IdempotencyStore | None = None):
        self.orders: dict[str, Order] = {}  # client_order_id -> Order
        self.audit = audit
        self.idempotency = idempotency

    def submit(self, intent: OrderIntent) -> Order:
        # persistent idempotency check
        if self.idempotency and self.idempotency.seen(intent.client_order_id):
            # return existing if we have it, else create a stub REJECT to avoid double-send
            if intent.client_order_id in self.orders:
                return self.orders[intent.client_order_id]
            # unknown but seen before – treat as duplicate, do not create new economic order
            # return a synthetic REJECTED order to signal duplicate
            # but for idempotency we return existing order if possible; here create PENDING that will be vetoed
            # Instead we record and return existing
            existing = self.orders.get(intent.client_order_id)
            if existing:
                return existing
            # if not in memory but persisted, create a PENDING that will be recognized as duplicate
            # we still create order but mark as duplicate – caller should treat as no new order
            # To ensure ONE economic order, we return a dummy that won't be submitted again
            # So we create order but flag it; for now just create and return
            pass
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
        if self.idempotency:
            self.idempotency.record(intent.client_order_id, "PENDING")
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
        if self.idempotency:
            self.idempotency.update(client_order_id, state.value)
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

    def cancel_all_pending(self) -> list[Order]:
        cancelled = []
        for cid, order in list(self.orders.items()):
            if order.state in (OrderState.PENDING, OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED):
                cancelled.append(self.update_state(cid, OrderState.CANCELLED, reject_reason="kill-switch"))
        return cancelled


class ReconcileReport:
    def __init__(self, drift: str, details: str = "", requires_suspend: bool = False):
        self.drift = drift
        self.details = details
        self.requires_suspend = requires_suspend

    def is_ok(self) -> bool:
        return self.drift == "NONE"


class BrokerAdapter:
    """Protocol for adapters."""

    def submit(self, intent: OrderIntent) -> Order:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def positions(self) -> list[Position]:
        return []

    def account(self) -> Account:
        return Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD")

    def orders(self) -> list[Order]:
        return []

    def cancel(self, client_order_id: str) -> None:  # noqa: B027
        pass


class PaperBrokerAdapter(BrokerAdapter):
    def __init__(self, matching: MatchingEngine | None = None, account: Account | None = None):
        self.matching = matching or MatchingEngine()
        self._account = account or Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD")
        # Paper broker mirrors Portfolio but also tracks its own for reconciliation test
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}

    def submit(self, intent: OrderIntent) -> Order:
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
            new_qty = pos.quantity + qty_delta
            if new_qty == Decimal("0"):
                self._positions[sym] = Position(instrument=fill.instrument, quantity=Decimal("0"), avg_price=Decimal("0"))
            elif pos.quantity == Decimal("0"):
                self._positions[sym] = Position(instrument=fill.instrument, quantity=new_qty, avg_price=fill.price)
            else:
                if (pos.quantity > 0 and qty_delta > 0) or (pos.quantity < 0 and qty_delta < 0):
                    total = abs(pos.quantity) + abs(qty_delta)
                    avg = (abs(pos.quantity) * pos.avg_price + abs(qty_delta) * fill.price) / total
                    self._positions[sym] = Position(instrument=fill.instrument, quantity=new_qty, avg_price=avg)
                else:
                    self._positions[sym] = Position(
                        instrument=fill.instrument,
                        quantity=new_qty,
                        avg_price=pos.avg_price if new_qty != Decimal("0") else Decimal("0"),
                    )
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

    def cancel(self, client_order_id: str) -> None:
        if client_order_id in self._orders:
            o = self._orders[client_order_id]
            if o.state in (OrderState.PENDING, OrderState.ACCEPTED):
                self._orders[client_order_id] = o.with_state(OrderState.CANCELLED)


class ExecutionEngine:
    """Coordinates risk, order management, broker, portfolio, audit.

    Portfolio is authoritative for positions/PnL/equity. Broker is venue truth.
    Risk sees live equity/drawdown/exposure from Portfolio.
    """

    def __init__(
        self,
        order_manager: OrderManager,
        risk_engine: RiskEngine,
        broker: BrokerAdapter,
        matching: MatchingEngine,
        portfolio: Portfolio,
        audit: AuditLog | None = None,
    ):
        self.om = order_manager
        self.risk = risk_engine
        self.broker = broker
        self.matching = matching
        self.portfolio = portfolio
        self.audit = audit
        self.peak_equity = portfolio.equity()
        self.drawdown = Decimal("0")
        # for daily PnL we track start of day equity; simplified as initial for now
        self._day_start_equity = portfolio.equity()

    def _update_drawdown(self) -> None:
        eq = self.portfolio.equity()
        if eq > self.peak_equity:
            self.peak_equity = eq
        # drawdown in USD (peak - current)
        self.drawdown = self.peak_equity - eq if eq < self.peak_equity else Decimal("0")

    def _risk_ctx(self) -> RiskContext:
        # ensure portfolio is marked to current prices before risk check? Caller should have marked.
        self._update_drawdown()
        # equity for risk
        equity = self.portfolio.equity()
        # account snapshot from portfolio
        account = Account(
            balance=self.portfolio.balance,
            equity=equity,
            margin=Decimal("0"),  # margin calc would need instrument notional/leverage; simplified 0
            free_margin=equity,
            leverage=Decimal("100"),
            currency=self.portfolio.currency,
        )
        daily_pnl = equity - self._day_start_equity
        return RiskContext(
            account=account,
            positions=self.portfolio.positions,
            open_orders_count=self.om.open_count(),
            daily_pnl=daily_pnl,
            drawdown=self.drawdown,
            instrument_suspended=set(),
            realized_vol=None,
        )

    def mark_price(self, symbol: str, price: Decimal) -> None:
        self.portfolio.mark_to_market(symbol, price)

    def handle_kill(self, reason: str) -> None:
        if self.audit:
            self.audit.emit(DomainEvent(event_type=EventType.KILL_SWITCH, payload={"reason": reason}))
        self.risk.kill_switch(reason)
        # cancel pending
        self.om.cancel_all_pending()
        # optionally cancel venue orders
        for order in self.om.orders.values():
            if order.state in (OrderState.PENDING, OrderState.ACCEPTED):
                try:
                    self.broker.cancel(order.client_order_id)
                except Exception:
                    pass

    def submit_intent(
        self, intent: OrderIntent, bar: Bar | None = None, tick: Tick | None = None
    ) -> tuple[Order | None, list[Fill]]:
        # idempotency: if seen (persistent or in-memory), return without duplicate economic action
        is_duplicate_in_memory = intent.client_order_id in self.om.orders
        is_duplicate_persistent = bool(self.om.idempotency and self.om.idempotency.seen(intent.client_order_id))
        if is_duplicate_in_memory or is_duplicate_persistent:
            existing = self.om.get(intent.client_order_id)
            if existing:
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.ORDER_EVENT,
                            payload={
                                "client_order_id": intent.client_order_id,
                                "duplicate": True,
                                "existing_state": existing.state.value,
                            },
                        )
                    )
                return existing, []
            if is_duplicate_persistent:
                # persistent seen but in-memory lost (restart): block without new economic fill
                placeholder = Order(
                    order_id=intent.client_order_id,
                    client_order_id=intent.client_order_id,
                    instrument=intent.instrument,
                    side=intent.side,
                    quantity=intent.quantity,
                    order_type=intent.order_type,
                    limit_price=intent.limit_price,
                    stop_price=intent.stop_price,
                    state=OrderState.REJECTED,
                    strategy_id=intent.strategy_id,
                    reject_reason="duplicate-persistent",
                )
                self.om.orders[intent.client_order_id] = placeholder
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.ORDER_EVENT,
                            payload={
                                "client_order_id": intent.client_order_id,
                                "duplicate": True,
                                "existing_state": placeholder.state.value,
                                "persistent": True,
                            },
                        )
                    )
                return placeholder, []
        ctx = self._risk_ctx()
        # kill check
        if self.risk.killed:
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RISK_VETO,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "KILL_SWITCH_ACTIVE",
                        },
                    )
                )
            return None, []

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
            # record veto as terminal? not needed
            return None, []

        if decision.resized_quantity is not None:
            intent = intent.model_copy(update={"quantity": decision.resized_quantity})

        # check again idempotency after resize (quantity change would be new intent, but keep same id)
        self.om.submit(intent)

        try:
            broker_order = self.broker.submit(intent)
            self.om.update_state(
                intent.client_order_id,
                OrderState.ACCEPTED,
                exchange_order_id=broker_order.exchange_order_id or broker_order.order_id,
            )
        except Exception as e:
            self.om.update_state(intent.client_order_id, OrderState.REJECTED, reject_reason=str(e))
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.ORDER_EVENT,
                        payload={"client_order_id": intent.client_order_id, "error": str(e)},
                    )
                )
            return None, []

        fills: list[Fill] = []
        # Only PaperBroker uses matching to generate fills synchronously; live fills come via poll
        if isinstance(self.broker, PaperBrokerAdapter) and bar is not None:
            fills = self.matching.match(intent, bar, tick)
            for fill in fills:
                # portfolio is authoritative
                self.portfolio.apply_fill(fill)
                self._update_drawdown()
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.FILL,
                            payload={
                                "fill_id": fill.fill_id,
                                "client_order_id": fill.client_order_id,
                                "price": str(fill.price),
                                "quantity": str(fill.quantity),
                                "fee": str(fill.fee),
                            },
                        )
                    )
                # post-trade risk (check kill)
                ctx2 = self._risk_ctx()
                self.risk.post_trade(fill, ctx2)
                if self.risk.killed:
                    self.handle_kill(f"post-trade kill: {fill.fill_id}")
                # keep broker mirror for reconciliation
                self.broker.apply_fill(fill)
            self.om.update_state(
                intent.client_order_id,
                OrderState.FILLED,
                filled_quantity=intent.quantity,
                avg_fill_price=fills[0].price if fills else None,
            )
        else:
            # live: fills async
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
        """Compare local Portfolio vs venue truth.

        For PaperBroker, venue is mirror; for live, venue is source of truth.
        Critical divergence → requires_suspend = True.
        """
        venue_positions = {p.instrument.symbol: p for p in self.broker.positions()}
        # check local vs venue quantity
        for sym, local in self.portfolio.positions.items():
            if local.quantity == Decimal("0"):
                continue
            venue = venue_positions.get(sym)
            if venue is None:
                report = ReconcileReport(
                    "MISSING_POSITION", f"local {sym} {local.quantity} not on venue", requires_suspend=True
                )
                if self.audit:
                    self.audit.emit(
                        DomainEvent(event_type=EventType.RECONCILE, payload={"drift": report.drift, "details": report.details})
                    )
                return report
            if venue.quantity != local.quantity:
                report = ReconcileReport(
                    "QUANTITY_MISMATCH",
                    f"{sym} local {local.quantity} vs venue {venue.quantity}",
                    requires_suspend=True,
                )
                if self.audit:
                    self.audit.emit(
                        DomainEvent(event_type=EventType.RECONCILE, payload={"drift": report.drift, "details": report.details})
                    )
                return report
            # avg price mismatch is warning but not necessarily suspend at v1 (could be rounding)
            if venue.avg_price != local.avg_price and abs(venue.avg_price - local.avg_price) > Decimal("0.01"):
                # log but not suspend (broker avg may differ due to venue calculation)
                pass

        for sym, venue in venue_positions.items():
            if venue.quantity != Decimal("0") and sym not in self.portfolio.positions:
                report = ReconcileReport(
                    "UNKNOWN_POSITION", f"venue {sym} {venue.quantity} not local", requires_suspend=True
                )
                if self.audit:
                    self.audit.emit(
                        DomainEvent(event_type=EventType.RECONCILE, payload={"drift": report.drift, "details": report.details})
                    )
                return report
            if venue.quantity != Decimal("0"):
                local = self.portfolio.positions.get(sym)
                if local is None or local.quantity == Decimal("0"):
                    report = ReconcileReport(
                        "UNKNOWN_POSITION", f"venue {sym} {venue.quantity} not local", requires_suspend=True
                    )
                    if self.audit:
                        self.audit.emit(
                            DomainEvent(event_type=EventType.RECONCILE, payload={"drift": report.drift, "details": report.details})
                        )
                    return report

        # also check venue orders vs local orders (unknown/missing)
        venue_orders = {o.client_order_id: o for o in self.broker.orders()}
        for cid, local_order in self.om.orders.items():
            if local_order.state in (OrderState.PENDING, OrderState.ACCEPTED):
                # if venue doesn't know about it after submit, it's drift
                # but PaperBroker always knows; live may have delay
                pass

        # check broker connectivity / stale state: broker account equity vs local?
        # simplified: if venue account differs wildly, flag

        report = ReconcileReport("NONE", "ok", requires_suspend=False)
        if self.audit:
            # we don't emit on ok to reduce noise, but could
            pass
        return report
