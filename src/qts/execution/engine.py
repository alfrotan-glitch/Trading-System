"""OrderManager + ExecutionEngine with Risk integration, idempotency, reconciliation."""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from qts.adapters.base import BrokerAdapter, ReconcileReport
from qts.adapters.matching import MatchingEngine
from qts.db import connect as db_connect
from qts.domain.events import DomainEvent, EventType
from qts.domain.value_objects import (
    Account,
    Bar,
    Fill,
    Instrument,
    Order,
    OrderIntent,
    OrderState,
    Side,
    Tick,
    uuid7,
)
from qts.execution.idempotency import IdempotencyStore
from qts.observability.audit import AuditLog
from qts.portfolio.portfolio import Portfolio
from qts.risk.engine import RiskContext, RiskEngine

# For market data safety, import lazily to avoid circular
try:
    from qts.adapters.market_data import MarketDataError, MarketDataProvider
except ImportError:
    MarketDataProvider = None  # type: ignore
    MarketDataError = RuntimeError  # type: ignore


class OrderManager:
    def __init__(self, audit: AuditLog | None = None, idempotency: IdempotencyStore | None = None):
        self.orders: dict[str, Order] = {}  # client_order_id -> Order
        self.audit = audit
        self.idempotency = idempotency

    def submit(self, intent: OrderIntent) -> Order:
        if intent.client_order_id in self.orders:
            return self.orders[intent.client_order_id]
        # Persistent idempotency check. The durable store can know an id this
        # process does not (restart). That case previously fell through an
        # unfinished branch (a bare ``pass`` behind comments saying "do not
        # create new economic order") and created a FRESH PENDING order with a
        # new order_id — a duplicate economic order for an id already recorded
        # as, e.g., FILLED. It is now restored from the persisted status and
        # returned without any new submission path.
        if self.idempotency and self.idempotency.seen(intent.client_order_id):
            return self._restore_persisted_duplicate(intent)
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

    def _restore_persisted_duplicate(self, intent: OrderIntent) -> Order:
        """Rebuild the order for an id the DURABLE store already knows.

        Never creates a new economic order and never returns a fresh PENDING:
        the restored state is the persisted one, so a duplicate submission
        after restart cannot be mistaken for a new order by a caller. An
        unparseable/absent persisted status restores as REJECTED (fail closed);
        AMBIGUOUS is preserved because it must not auto-heal without reconcile.
        """
        persisted_status = self.idempotency.get_status(intent.client_order_id) if self.idempotency else None
        try:
            restored_state = OrderState(persisted_status) if persisted_status else OrderState.REJECTED
        except ValueError:
            restored_state = OrderState.REJECTED
        order = Order(
            order_id=intent.client_order_id,
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            state=restored_state,
            strategy_id=intent.strategy_id,
            reject_reason="duplicate-persistent-ambiguous"
            if restored_state is OrderState.AMBIGUOUS
            else "duplicate-persistent",
        )
        self.orders[intent.client_order_id] = order
        if self.audit:
            self.audit.emit(
                DomainEvent(
                    event_type=EventType.ORDER_EVENT,
                    payload={
                        "client_order_id": intent.client_order_id,
                        "duplicate": True,
                        "restored": True,
                        "persistent": True,
                        "existing_state": restored_state.value,
                        "persisted_status": persisted_status,
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
        db_path: Path | str | None = None,
        market_data: Any | None = None,
        persist_reconcile_state: bool = True,
    ):
        self.om = order_manager
        self.risk = risk_engine
        self.broker = broker
        self.matching = matching
        self.portfolio = portfolio
        self.audit = audit
        self.peak_equity = portfolio.equity()
        self.drawdown = Decimal("0")
        self._day_start_equity = portfolio.equity()
        self._db_path = Path(db_path) if db_path else Path(getattr(risk_engine, "db_path", "data/sqlite/qts.db"))
        self.persist_reconcile_state = persist_reconcile_state
        self.market_data = market_data
        # stable fill ids already applied this process — poll dedupe (never apply the
        # same economic fill twice); portfolio.fills covers cross-restart dedupe
        self._applied_fill_ids: set[str] = set()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.persist_reconcile_state:
            self._init_reconcile_db()
            loaded_suspended, loaded_reason = self._load_reconcile_suspend()
        else:
            loaded_suspended, loaded_reason = False, None
        self._suspended = loaded_suspended
        self._suspend_reason: str | None = loaded_reason
        if self._suspended and self.audit:
            self.audit.emit(
                DomainEvent(
                    event_type=EventType.RECONCILE,
                    payload={
                        "drift": "RESTORED_SUSPEND",
                        "details": self._suspend_reason or "",
                        "requires_suspend": True,
                    },
                )
            )

    def _init_reconcile_db(self) -> None:
        with db_connect(self._db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS reconcile_state (k INTEGER PRIMARY KEY, suspended INTEGER NOT NULL, reason TEXT, updated_at TEXT)"
            )
            con.commit()

    def _load_reconcile_suspend(self) -> tuple[bool, str | None]:
        """Restore the durable suspension flag — FAIL CLOSED on a read error.

        Every exception used to be suppressed and ``(False, None)`` returned, so
        a locked, corrupt or otherwise unreadable suspension store silently
        restarted the engine as HEALTHY and defeated the durable-suspend
        recovery guarantee the live gate claims to check. Now:

        * a recorded row is restored exactly;
        * "no such table" honestly means no suspension was ever persisted;
        * any other read failure is treated as SUSPENDED.
        """
        try:
            with db_connect(self._db_path) as con:
                row = con.execute("SELECT suspended, reason FROM reconcile_state WHERE k=1").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                return False, None
            return True, f"reconcile suspend state unreadable — fail closed ({type(e).__name__}: {e})"
        except Exception as e:
            return True, f"reconcile suspend state unreadable — fail closed ({type(e).__name__}: {e})"
        if row:
            return bool(row[0]), row[1]
        return False, None

    def _persist_reconcile_suspend(self, suspended: bool, reason: str | None) -> None:
        if not self.persist_reconcile_state:
            return
        with db_connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO reconcile_state VALUES (1,?,?,?)",
                (1 if suspended else 0, reason or "", datetime.now(UTC).isoformat()),
            )
            con.commit()

    def _update_drawdown(self) -> None:
        eq = self.portfolio.equity()
        if eq > self.peak_equity:
            self.peak_equity = eq
        # drawdown in USD (peak - current)
        self.drawdown = self.peak_equity - eq if eq < self.peak_equity else Decimal("0")

    def _risk_ctx(self, reference_prices: dict[str, Decimal] | None = None) -> RiskContext:
        self._update_drawdown()
        # Determine broker type: live (MT5), realistic paper, or legacy paper/shadow
        # Use is_live flag if present, else fallback to class name check
        is_live = bool(getattr(self.broker, "is_live", False))
        # Also treat MT5Adapter by name as live (for backward compat without flag)
        if not is_live and self.broker.__class__.__name__ == "MT5Adapter":
            is_live = True
        # Realistic paper also uses broker account for margin realism, but not stale check as strict
        is_realistic_paper = self.broker.__class__.__name__ == "RealisticPaperBroker"
        use_broker_account = is_live or is_realistic_paper
        if use_broker_account:
            try:
                account = self.broker.account()
                from datetime import datetime

                # Validate account fields — fail closed on missing/stale/contradictory/malformed
                if account.balance is None or account.equity is None:
                    raise ValueError("account balance/equity missing")
                if not account.balance.is_finite() or not account.equity.is_finite():
                    raise ValueError("account values not finite")
                # Check staleness
                age = (datetime.now(UTC) - account.updated_at).total_seconds() if account.updated_at else 999999
                if age > 300:
                    raise ValueError(f"stale account {age:.0f}s")
                # Check contradictory: equity cannot be negative large vs balance
                # For live, free_margin should be consistent with margin
                # Basic sanity: margin <= equity*leverage approx
                # margin should not exceed equity * leverage * 1.5
                # (leverage may be UNAVAILABLE (None) — the consistency check
                # is then skipped, never computed against a guessed leverage)
                if (
                    account.margin
                    and account.equity
                    and account.leverage is not None
                    and account.margin > account.equity * account.leverage * Decimal("1.5") + Decimal("1")
                ):
                    raise ValueError(
                        f"account margin {account.margin} inconsistent with equity {account.equity} leverage {account.leverage}"
                    )
                if account.free_margin and account.free_margin < Decimal("-1000"):
                    raise ValueError(f"account free_margin {account.free_margin} too negative")
                equity = account.equity
            except Exception as e:
                raise RuntimeError(f"account unavailable: {e}") from e
        else:
            equity = self.portfolio.equity()
            account = Account(
                balance=self.portfolio.balance,
                equity=equity,
                margin=Decimal("0"),
                free_margin=equity,
                leverage=None,  # UNAVAILABLE in simulation — never guessed
                currency=self.portfolio.currency,
                source="PORTFOLIO_SIMULATION",
            )
        daily_pnl = (
            equity - self._day_start_equity if not use_broker_account else account.equity - self._day_start_equity
        )
        # authoritative market snapshot: portfolio last prices + any override from bar/tick
        # This is the price Risk must use for market-order notional (auditable)
        ref = dict(self.portfolio._last_price)  # copy
        if reference_prices:
            ref.update(reference_prices)
        return RiskContext(
            account=account,
            positions=self.portfolio.positions,
            open_orders_count=self.om.open_count(),
            daily_pnl=daily_pnl,
            drawdown=self.drawdown,
            instrument_suspended=set(),
            realized_vol=None,
            reference_prices=ref if ref else None,
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
                with contextlib.suppress(Exception):
                    self.broker.cancel(order.client_order_id)

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
                # AMBIGUOUS must not auto-heal or auto-retry — fail closed until reconcile
                # PENDING/ACCEPTED/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED all block duplicate economic action
                return existing, []
            if is_duplicate_persistent:
                # persistent seen but in-memory lost (restart): restore persisted state, block without new economic fill
                persisted_status = (
                    self.om.idempotency.get_status(intent.client_order_id) if self.om.idempotency else None
                )
                try:
                    restored_state = OrderState(persisted_status) if persisted_status else OrderState.REJECTED
                except Exception:
                    restored_state = OrderState.REJECTED
                # Do not auto-convert AMBIGUOUS to REJECTED — requires reconcile
                placeholder = Order(
                    order_id=intent.client_order_id,
                    client_order_id=intent.client_order_id,
                    instrument=intent.instrument,
                    side=intent.side,
                    quantity=intent.quantity,
                    order_type=intent.order_type,
                    limit_price=intent.limit_price,
                    stop_price=intent.stop_price,
                    state=restored_state,
                    strategy_id=intent.strategy_id,
                    reject_reason="duplicate-persistent"
                    if restored_state != OrderState.AMBIGUOUS
                    else "duplicate-persistent-ambiguous",
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
        # Shadow mode check — if broker is shadow, record intent but do not submit to venue
        is_shadow = bool(getattr(self.broker, "is_shadow", False))
        if is_shadow:
            # Still do risk and idempotency, but do not call broker.submit
            # Record shadow intent for later comparison
            pass

        # Market data safety: for live, validate via MarketDataProvider if available
        # Define one authoritative live pricing path: MarketDataProvider.get_tick
        # For live market orders, use executable bid/ask, not mid/close
        ref_override: dict[str, Decimal] = {}
        is_live = bool(getattr(self.broker, "is_live", False)) or self.broker.__class__.__name__ == "MT5Adapter"
        if is_live and self.market_data is not None:
            try:
                # Validate tick freshness, spread, symbol, market availability
                md_tick = self.market_data.get_tick(intent.instrument)
                # Use correct side for executable price
                side_price = md_tick.ask if intent.side.value == "BUY" else md_tick.bid
                ref_override[intent.instrument.symbol] = side_price
                # Also validate that tick is for correct symbol
                if md_tick.instrument.symbol != intent.instrument.symbol:
                    raise ValueError(f"tick symbol mismatch {md_tick.instrument.symbol} vs {intent.instrument.symbol}")
            except Exception as e:
                # Market data unsafe — fail closed, suspend, NO_TRADE
                self._suspended = True
                self._suspend_reason = f"market data unsafe: {e}"
                self._persist_reconcile_suspend(True, self._suspend_reason)
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.RECONCILE,
                            payload={"drift": "MARKET_DATA_UNSAFE", "details": str(e), "requires_suspend": True},
                        )
                    )
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.NO_TRADE,
                            payload={
                                "client_order_id": intent.client_order_id,
                                "strategy_id": intent.strategy_id,
                                "reason": "MARKET_DATA_UNSAFE",
                                "detail": str(e),
                            },
                        )
                    )
                return None, []
        elif bar is not None:
            # For next-bar execution, the executable price is bar open (or close for limit)
            # For risk, the reference is the current market price: bar close if available, else open
            # Use bar.close as last known, and bar.open as executable for market
            ref_override[intent.instrument.symbol] = bar.close if bar.close else bar.open
            # Also include portfolio last price fallback
        elif tick is not None:
            # For tick-based, distinguish executable bid/ask vs mid
            # If tick provided, use side-specific price for risk (BUY→ask, SELL→bid) not mid
            if is_live:
                ref_override[intent.instrument.symbol] = tick.ask if intent.side.value == "BUY" else tick.bid
            else:
                ref_override[intent.instrument.symbol] = tick.mid if hasattr(tick, "mid") else tick.bid
        try:
            ctx = self._risk_ctx(reference_prices=ref_override if ref_override else None)
        except Exception as e:
            self._suspended = True
            self._suspend_reason = f"account unavailable: {e}"
            self._persist_reconcile_suspend(True, self._suspend_reason)
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RECONCILE,
                        payload={"drift": "ACCOUNT_UNAVAILABLE", "details": str(e), "requires_suspend": True},
                    )
                )
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "ACCOUNT_UNAVAILABLE",
                            "detail": str(e),
                        },
                    )
                )
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RISK_VETO,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "ACCOUNT_UNAVAILABLE",
                            "detail": str(e),
                        },
                    )
                )
            return None, []
        # reconciliation suspend check — fail closed
        if self._suspended:
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "SUSPENDED",
                            "detail": self._suspend_reason or "reconcile suspend",
                        },
                    )
                )
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RECONCILE,
                        payload={"drift": "SUSPENDED", "details": self._suspend_reason or ""},
                    )
                )
            return None, []
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
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "KILL_SWITCH",
                            "detail": "kill active — NO_TRADE",
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
                            "price": str(decision.price)
                            if getattr(decision, "price", None)
                            else str(intent.limit_price or ctx.reference_price_for(intent.instrument.symbol) or ""),
                            "price_source": getattr(decision, "price_source", None) or "",
                            "notional": str(getattr(decision, "notional", None) or ""),
                            "symbol": intent.instrument.symbol,
                        },
                    )
                )
                # explicit NO_TRADE — auditable capital preservation
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": decision.veto_reason.value if decision.veto_reason else "RISK_VETO",
                            "detail": decision.reason_detail,
                            "price": str(decision.price)
                            if getattr(decision, "price", None)
                            else str(intent.limit_price or ""),
                            "price_source": getattr(decision, "price_source", None) or "",
                            "notional": str(getattr(decision, "notional", None) or ""),
                        },
                    )
                )
            # record veto as terminal? not needed
            return None, []

        if decision.resized_quantity is not None:
            intent = intent.model_copy(update={"quantity": decision.resized_quantity})

        # check again idempotency after resize (quantity change would be new intent, but keep same id)
        self.om.submit(intent)

        # Shadow mode: do not actually submit to broker, just record would-be
        is_shadow = bool(getattr(self.broker, "is_shadow", False))
        if is_shadow:
            # Shadow records intent, marks as ACCEPTED but never fills on venue
            # Still audit the intent, but no broker interaction
            self.om.update_state(
                intent.client_order_id,
                OrderState.ACCEPTED,
                exchange_order_id=f"shadow_{intent.client_order_id}",
            )
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.ORDER_EVENT,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "from": OrderState.PENDING.value,
                            "to": OrderState.ACCEPTED.value,
                            "shadow": True,
                        },
                    )
                )
                # Also emit NO_TRADE for shadow to distinguish
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "SHADOW_NO_SUBMIT",
                            "detail": "shadow mode: intent recorded, no venue order",
                        },
                    )
                )
            # In shadow, also record would-be fill price based on reference (if available)
            # For comparison with paper, we can store would-be executable price
            if hasattr(self.broker, "record_would_be_fill"):
                with contextlib.suppress(Exception):
                    ref_price = ref_override.get(intent.instrument.symbol) if ref_override else None
                    self.broker.record_would_be_fill(
                        {
                            "client_order_id": intent.client_order_id,
                            "price": str(ref_price) if ref_price else "",
                            "quantity": str(intent.quantity),
                        }
                    )
            # Return shadow accepted, no fills
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.ORDER_INTENT,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "quantity": str(intent.quantity),
                            "side": intent.side.value,
                            "shadow": True,
                        },
                    )
                )
            return self.om.get(intent.client_order_id), []

        try:
            broker_order = self.broker.submit(intent)
            self.om.update_state(
                intent.client_order_id,
                OrderState.ACCEPTED,
                exchange_order_id=broker_order.exchange_order_id or broker_order.order_id,
            )
        except Exception as e:
            # Classify: definitive rejection vs ambiguous transport failure
            err_msg = str(e).lower()
            # Heuristic: timeout, connection, network, ambiguous -> AMBIGUOUS
            is_ambiguous = any(
                k in err_msg for k in ["timeout", "connection", "network", "ambiguous", "unknown", "disconnected"]
            )
            # Also check exception type
            if isinstance(e, (TimeoutError, ConnectionError)):
                is_ambiguous = True
            state = OrderState.AMBIGUOUS if is_ambiguous else OrderState.REJECTED
            self.om.update_state(intent.client_order_id, state, reject_reason=str(e))
            if self.audit:
                # Use consistent from/to schema plus error detail (G12)
                # The update_state above already emitted from/to, this is additional error context
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.ORDER_EVENT,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "from": OrderState.PENDING.value,
                            "to": state.value,
                            "error": str(e),
                            "state": state.value,
                        },
                    )
                )
            if state == OrderState.AMBIGUOUS:
                # Fail closed: suspend trading until reconcile
                self._suspended = True
                self._suspend_reason = f"ambiguous broker state {intent.client_order_id}: {e}"
                self._persist_reconcile_suspend(True, self._suspend_reason)
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.RECONCILE,
                            payload={"drift": "AMBIGUOUS", "details": str(e), "requires_suspend": True},
                        )
                    )
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.NO_TRADE,
                            payload={
                                "client_order_id": intent.client_order_id,
                                "strategy_id": intent.strategy_id,
                                "reason": "AMBIGUOUS",
                                "detail": str(e),
                            },
                        )
                    )
            else:
                # For definitive REJECTED, still ensure ORDER_EVENT uses consistent from/to (G12)
                pass
            return None, []

        fills: list[Fill] = []
        # Paper brokers use matching to generate fills synchronously; live fills come via poll
        is_paper = (
            not bool(getattr(self.broker, "is_live", False))
            and not bool(getattr(self.broker, "is_shadow", False))
            and hasattr(self.broker, "apply_fill")
        )
        if is_paper and bar is not None:
            fills = self.matching.match(intent, bar, tick)
            cumulative_qty = Decimal("0")
            for idx, fill in enumerate(fills):
                # portfolio is authoritative
                self.portfolio.apply_fill(fill)
                cumulative_qty += fill.quantity
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
                                "cumulative_quantity": str(cumulative_qty),
                            },
                        )
                    )
                # post-trade risk (check kill) — reference price is fill price
                try:
                    ctx2 = self._risk_ctx(reference_prices={fill.instrument.symbol: fill.price})
                except Exception as e:
                    self._suspended = True
                    self._suspend_reason = f"account unavailable post-trade: {e}"
                    self._persist_reconcile_suspend(True, self._suspend_reason)
                    if self.audit:
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.RECONCILE,
                                payload={
                                    "drift": "ACCOUNT_UNAVAILABLE_POST",
                                    "details": str(e),
                                    "requires_suspend": True,
                                },
                            )
                        )
                    ctx2 = None
                if ctx2 is not None:
                    self.risk.post_trade(fill, ctx2)
                if self.risk.killed:
                    self.handle_kill(f"post-trade kill: {fill.fill_id}")
                # keep broker mirror for reconciliation (is_paper above guarantees
                # the adapter exposes apply_fill; getattr keeps the protocol honest)
                _apply = getattr(self.broker, "apply_fill", None)
                if _apply is not None:
                    _apply(fill)
                # Real partial-fill state (G11): emit PARTIALLY_FILLED until fully filled
                if idx < len(fills) - 1 or cumulative_qty < intent.quantity:
                    # Not yet fully filled
                    self.om.update_state(
                        intent.client_order_id,
                        OrderState.PARTIALLY_FILLED,
                        filled_quantity=cumulative_qty,
                        avg_fill_price=fill.price,
                    )
                else:
                    self.om.update_state(
                        intent.client_order_id,
                        OrderState.FILLED,
                        filled_quantity=cumulative_qty,
                        avg_fill_price=fills[0].price if fills else None,
                    )
            # If fills empty, keep as ACCEPTED? But matching always returns at least one if called
            if not fills:
                self.om.update_state(
                    intent.client_order_id,
                    OrderState.ACCEPTED,
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

    def poll_live_fills(self) -> list[Fill]:
        """Poll live broker for new fills (deals) and apply to portfolio.

        For MT5, fills are deals; for paper, this is no-op (fills already applied synchronously).
        Must be called periodically in live mode. Each fill is applied to portfolio
        and audited. Returns list of new fills.
        """
        if not bool(getattr(self.broker, "is_live", False)) and self.broker.__class__.__name__ != "MT5Adapter":
            return []
        new_fills: list[Fill] = []
        # For MT5, use history_deals or positions diff
        # We need to track which deals have been applied — for now, poll all and deduplicate via fill_id?
        # Simplify: if broker has poll_fills or history_deals, use it
        try:
            if hasattr(self.broker, "poll_fills"):
                # poll_fills may return dicts or fills
                raw = self.broker.poll_fills("")  # empty means all
                for item in raw or []:
                    # If item is already Fill, use it
                    if isinstance(item, Fill):
                        fill = item
                    elif isinstance(item, dict):
                        # dict from MT5Adapter.poll_fills — attribution is mandatory:
                        # a fill we cannot tie to a known order is NEVER applied to the
                        # portfolio (fail closed); it is audited for reconciliation.
                        cid = item.get("client_order_id")
                        if not cid:
                            if self.audit:
                                self.audit.emit(
                                    DomainEvent(
                                        event_type=EventType.RECONCILE,
                                        payload={
                                            "drift": "UNATTRIBUTED_FILL",
                                            "details": f"deal {item.get('fill_id')} could not be mapped to a client_order_id — not applied",
                                            "requires_suspend": False,
                                        },
                                    )
                                )
                            continue
                        from qts.domain.value_objects import uuid7 as _uuid7

                        fill_id = item.get("fill_id") or _uuid7()
                        known = self.om.get(cid)
                        fill = Fill(
                            fill_id=fill_id,
                            order_id=known.order_id if known is not None else cid,
                            client_order_id=cid,
                            instrument=Instrument(symbol=item.get("symbol", "XAUUSD")),
                            side=item.get("side", Side.BUY),
                            quantity=item.get("volume", Decimal("0")),
                            price=item.get("price", Decimal("0")),
                            event_time=item.get("time", datetime.now(UTC)),
                        )
                    else:
                        continue
                    # Deduplicate by STABLE fill_id (deal ticket) across polls
                    if fill.fill_id in self._applied_fill_ids or any(
                        f.fill_id == fill.fill_id for f in self.portfolio.fills
                    ):
                        continue
                    self._applied_fill_ids.add(fill.fill_id)
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
                                },
                            )
                        )
                    # Update order state to FILLED or PARTIALLY_FILLED — a submitted
                    # order is never assumed filled; state follows observed fill quantity.
                    existing = self.om.get(fill.client_order_id)
                    if existing is not None:
                        new_filled = existing.filled_quantity + fill.quantity
                        new_state = (
                            OrderState.FILLED if new_filled >= existing.quantity else OrderState.PARTIALLY_FILLED
                        )
                        self.om.update_state(
                            fill.client_order_id, new_state, filled_quantity=new_filled, avg_fill_price=fill.price
                        )
                    elif self.audit:
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.RECONCILE,
                                payload={
                                    "drift": "UNATTRIBUTED_FILL",
                                    "details": f"fill {fill.fill_id} references unknown order {fill.client_order_id} — not applied to order state",
                                    "requires_suspend": False,
                                },
                            )
                        )
                    # Also update broker mirror if needed
                    if hasattr(self.broker, "apply_fill"):
                        with contextlib.suppress(Exception):
                            self.broker.apply_fill(fill)
                    new_fills.append(fill)
                    # post-trade risk
                    try:
                        ctx2 = self._risk_ctx(reference_prices={fill.instrument.symbol: fill.price})
                    except Exception as e:
                        self._suspended = True
                        self._suspend_reason = f"account unavailable post-trade poll: {e}"
                        self._persist_reconcile_suspend(True, self._suspend_reason)
                        ctx2 = None
                    if ctx2 is not None:
                        self.risk.post_trade(fill, ctx2)
                        if self.risk.killed:
                            self.handle_kill(f"poll post-trade kill: {fill.fill_id}")
        except Exception as e:
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RECONCILE,
                        payload={"drift": "POLL_ERROR", "details": str(e), "requires_suspend": False},
                    )
                )
        return new_fills

    def reconcile(self) -> ReconcileReport:
        """Compare local Portfolio vs venue truth.

        For PaperBroker, venue is mirror; for live, venue is source of truth.
        Critical divergence → requires_suspend = True.
        When requires_suspend is True, caller must enforce NO_TRADE until healed.
        """
        # Check broker connectivity first — fail closed on disconnect
        try:
            venue_positions = {p.instrument.symbol: p for p in self.broker.positions()}
            venue_orders = {o.client_order_id: o for o in self.broker.orders()}
        except Exception as e:
            report = ReconcileReport("BROKER_DISCONNECT", f"broker positions/orders failed: {e}", requires_suspend=True)
            self._suspended = True
            self._suspend_reason = f"broker disconnect: {e}"
            self._persist_reconcile_suspend(True, self._suspend_reason)
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.RECONCILE,
                        payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                    )
                )
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE, payload={"reason": "BROKER_DISCONNECT", "detail": report.details}
                    )
                )
            return report
        # check local vs venue quantity
        for sym, local in self.portfolio.positions.items():
            if local.quantity == Decimal("0"):
                continue
            venue = venue_positions.get(sym)
            if venue is None:
                report = ReconcileReport(
                    "MISSING_POSITION", f"local {sym} {local.quantity} not on venue", requires_suspend=True
                )
                self._suspended = True
                self._suspend_reason = report.details
                self._persist_reconcile_suspend(True, self._suspend_reason)
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.RECONCILE,
                            payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                        )
                    )
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.NO_TRADE, payload={"reason": report.drift, "detail": report.details}
                        )
                    )
                return report
            if venue.quantity != local.quantity:
                report = ReconcileReport(
                    "QUANTITY_MISMATCH",
                    f"{sym} local {local.quantity} vs venue {venue.quantity}",
                    requires_suspend=True,
                )
                self._suspended = True
                self._suspend_reason = report.details
                self._persist_reconcile_suspend(True, self._suspend_reason)
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.RECONCILE,
                            payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                        )
                    )
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.NO_TRADE, payload={"reason": report.drift, "detail": report.details}
                        )
                    )
                return report
            # avg price mismatch — if significant (>0.5% or > 10 points), suspend (G5)
            if venue.avg_price != local.avg_price:
                # Use relative diff: abs(diff)/price > 0.005 (0.5%) or absolute > 10*point
                try:
                    diff = abs(venue.avg_price - local.avg_price)
                    # Get point from broker spec if available
                    point = Decimal("0.01")
                    with contextlib.suppress(Exception):
                        if hasattr(self.broker, "get_symbol_spec"):
                            spec = self.broker.get_symbol_spec(sym)
                            point = spec.point
                    # Threshold: max(10*point, 0.5% of price)
                    thresh = max(
                        point * Decimal("10"), local.avg_price * Decimal("0.005") if local.avg_price else point
                    )
                    if diff > thresh:
                        report = ReconcileReport(
                            "PRICE_MISMATCH",
                            f"{sym} local avg {local.avg_price} vs venue {venue.avg_price} diff {diff} > thresh {thresh}",
                            requires_suspend=True,
                        )
                        self._suspended = True
                        self._suspend_reason = report.details
                        self._persist_reconcile_suspend(True, self._suspend_reason)
                        if self.audit:
                            self.audit.emit(
                                DomainEvent(
                                    event_type=EventType.RECONCILE,
                                    payload={
                                        "drift": report.drift,
                                        "details": report.details,
                                        "requires_suspend": True,
                                    },
                                )
                            )
                            self.audit.emit(
                                DomainEvent(
                                    event_type=EventType.NO_TRADE,
                                    payload={"reason": report.drift, "detail": report.details},
                                )
                            )
                        return report
                except Exception as e:
                    # If price check itself fails, log but don't block unless it's suspend case above
                    if "PRICE_MISMATCH" in str(e):
                        raise
                    pass

        for sym, venue in venue_positions.items():
            if venue.quantity != Decimal("0") and sym not in self.portfolio.positions:
                report = ReconcileReport(
                    "UNKNOWN_POSITION", f"venue {sym} {venue.quantity} not local", requires_suspend=True
                )
                self._suspended = True
                self._suspend_reason = report.details
                self._persist_reconcile_suspend(True, self._suspend_reason)
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.RECONCILE,
                            payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                        )
                    )
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.NO_TRADE, payload={"reason": report.drift, "detail": report.details}
                        )
                    )
                return report
            if venue.quantity != Decimal("0"):
                local_pos = self.portfolio.positions.get(sym)
                if local_pos is None or local_pos.quantity == Decimal("0"):
                    report = ReconcileReport(
                        "UNKNOWN_POSITION", f"venue {sym} {venue.quantity} not local", requires_suspend=True
                    )
                    self._suspended = True
                    self._suspend_reason = report.details
                    self._persist_reconcile_suspend(True, self._suspend_reason)
                    if self.audit:
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.RECONCILE,
                                payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                            )
                        )
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.NO_TRADE,
                                payload={"reason": report.drift, "detail": report.details},
                            )
                        )
                    return report

        # also check venue orders vs local orders (unknown/missing/status-mismatch) — must suspend
        # unknown order: venue has order not in local -> drift
        for cid, venue_order in venue_orders.items():
            local_order = self.om.orders.get(cid)
            if local_order is None:
                # venue has order we don't track -> unknown
                report = ReconcileReport("UNKNOWN_ORDER", f"venue order {cid} not local", requires_suspend=True)
                self._suspended = True
                self._suspend_reason = report.details
                self._persist_reconcile_suspend(True, self._suspend_reason)
                if self.audit:
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.RECONCILE,
                            payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                        )
                    )
                    self.audit.emit(
                        DomainEvent(
                            event_type=EventType.NO_TRADE, payload={"reason": report.drift, "detail": report.details}
                        )
                    )
                return report
            # status mismatch: local vs venue state differs
            # For live, venue is truth — if local is FILLED but venue is still ACCEPTED, or vice versa, suspend
            if local_order.state != venue_order.state:
                # Allow PENDING→ACCEPTED as normal transition, but not FILLED vs ACCEPTED long-term
                # If local is ACCEPTED and venue is FILLED, we need to apply fill; but if mismatch persists, suspend
                # Check if venue is more advanced (FILLED) but local is still ACCEPTED/PENDING — then we have missed fill
                # Or local is FILLED but venue is CANCELLED/REJECTED — then we have phantom fill
                # Any state mismatch where one is terminal and other is not → suspend
                terminal = {OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELLED, OrderState.AMBIGUOUS}
                if (
                    (local_order.state in terminal) != (venue_order.state in terminal)
                    or (local_order.state == OrderState.FILLED and venue_order.state != OrderState.FILLED)
                    or (venue_order.state == OrderState.FILLED and local_order.state != OrderState.FILLED)
                ):
                    report = ReconcileReport(
                        "STATUS_MISMATCH",
                        f"order {cid} local {local_order.state} vs venue {venue_order.state}",
                        requires_suspend=True,
                    )
                    self._suspended = True
                    self._suspend_reason = report.details
                    self._persist_reconcile_suspend(True, self._suspend_reason)
                    if self.audit:
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.RECONCILE,
                                payload={"drift": report.drift, "details": report.details, "requires_suspend": True},
                            )
                        )
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.NO_TRADE,
                                payload={"reason": report.drift, "detail": report.details},
                            )
                        )
                    return report
        for cid, local_order in self.om.orders.items():
            if (
                local_order.state in (OrderState.PENDING, OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED)
                and cid not in venue_orders
            ):
                from datetime import datetime

                age = (datetime.now(UTC) - local_order.created_at).total_seconds()
                if age > 10:
                    report = ReconcileReport(
                        "MISSING_ORDER", f"local order {cid} not on venue age {age:.1f}s", requires_suspend=True
                    )
                    self._suspended = True
                    self._suspend_reason = report.details
                    self._persist_reconcile_suspend(True, self._suspend_reason)
                    if self.audit:
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.RECONCILE,
                                payload={
                                    "drift": report.drift,
                                    "details": report.details,
                                    "requires_suspend": True,
                                },
                            )
                        )
                        self.audit.emit(
                            DomainEvent(
                                event_type=EventType.NO_TRADE,
                                payload={"reason": report.drift, "detail": report.details},
                            )
                        )
                    return report

        report = ReconcileReport("NONE", "ok", requires_suspend=False)
        # On healthy reconcile, do NOT auto-heal suspend; require explicit heal()
        if self.audit:
            pass
        return report

    def heal_reconcile(self, reason: str = "manual") -> None:
        """Explicit reactivation after drift healed — required (no auto-heal)."""
        self._suspended = False
        self._suspend_reason = None
        self._persist_reconcile_suspend(False, None)
        if self.audit:
            self.audit.emit(DomainEvent(event_type=EventType.RECONCILE, payload={"drift": "HEALED", "details": reason}))

    @property
    def is_suspended(self) -> bool:
        return self._suspended or self.risk.killed

    def close(self) -> None:
        with contextlib.suppress(Exception):
            from pathlib import Path

            db = getattr(self, "_db_path", getattr(self, "db_path", None))
            if db is not None and self.persist_reconcile_state:
                db = Path(db)
                if db.exists() and str(db) != ":memory:":
                    with db_connect(db) as con, contextlib.suppress(Exception):
                        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        con.commit()
            # close subcomponents if they have close
            for attr in ("risk", "om", "_risk", "_om"):
                obj = getattr(self, attr, None)
                if obj is not None and hasattr(obj, "close"):
                    with contextlib.suppress(Exception):
                        obj.close()
                # also close order manager's idempotency
                om = getattr(self, "om", None)
                if om is not None:
                    idem = getattr(om, "idempotency", None)
                    if idem is not None and hasattr(idem, "close"):
                        with contextlib.suppress(Exception):
                            idem.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
