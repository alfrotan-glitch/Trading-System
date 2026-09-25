"""Realistic paper broker — same validation/lifecycle as MT5, but paper.

Uses same SymbolSpec, quantity/price validation as MT5Adapter, so paper
trading is broker-realistic and shares the production execution path.

No second simplified architecture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from qts.adapters.base import BrokerAdapter
from qts.adapters.matching import MatchingConfig, MatchingEngine
from qts.adapters.mt5_adapter import SymbolSpec
from qts.db import connect as db_connect
from qts.domain.value_objects import (
    Account,
    Instrument,
    Order,
    OrderIntent,
    OrderState,
    Position,
    Side,
    Tick,
)

# Realistic XAUUSD spec — matches typical MT5 broker (e.g., ICMarkets, Pepperstone)
DEFAULT_XAUUSD_SPEC = SymbolSpec(
    symbol="XAUUSD",
    contract_size=Decimal("100"),
    volume_min=Decimal("0.01"),
    volume_max=Decimal("100"),
    volume_step=Decimal("0.01"),
    digits=2,
    point=Decimal("0.01"),
    tick_size=Decimal("0.01"),
    trade_mode=4,
    trade_allowed=True,
    filling_mode=1,
    raw={"source": "paper_default"},
)


class RealisticPaperBroker(BrokerAdapter):
    """Paper broker that enforces MT5-like constraints and realistic lifecycle.

    - Validates quantity/price against SymbolSpec (same as MT5)
    - Persists comment map for restart
    - Provides realistic account with margin (not mocked equity=balance)
    - Provides ticks derived from last bar or simulated
    - Fills via MatchingEngine but with same validation as live
    """

    def __init__(
        self,
        matching: MatchingEngine | None = None,
        initial_balance: Decimal = Decimal("10000"),
        leverage: Decimal = Decimal("100"),
        db_path: Path | str | None = None,
        symbol_specs: dict[str, SymbolSpec] | None = None,
        config: dict[str, Any] | None = None,
        simulated_reference_price: Decimal = Decimal("2000"),
    ):
        self.matching = matching or MatchingEngine(MatchingConfig())
        self._balance = initial_balance
        self._leverage = leverage
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._ticks: dict[str, Tick] = {}
        from qts.config.paths import artifact_path, resolve_state_path

        self._db_path = resolve_state_path(db_path) if db_path else artifact_path("db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_comment_db()
        self.symbol_specs: dict[str, SymbolSpec] = symbol_specs or {"XAUUSD": DEFAULT_XAUUSD_SPEC}
        self.config = config or {}
        # Explicitly SIMULATED price used ONLY for paper margin estimation when no
        # tick/limit/stop/position mark exists. This is a declared simulation
        # parameter of the paper broker — never a claim about the real market, and
        # never used on live/demo paths (those fail closed on missing market price).
        self.simulated_reference_price = simulated_reference_price
        # For paper, we track margin realistically
        self._account_updated_at = datetime.now(UTC)

    def _init_comment_db(self) -> None:
        with db_connect(self._db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS paper_comment_map (
                    client_order_id TEXT PRIMARY KEY,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            con.commit()

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        if symbol in self.symbol_specs:
            return self.symbol_specs[symbol]
        # Fallback: create generic spec from instrument defaults
        # Try to infer from Instrument?
        return SymbolSpec(
            symbol=symbol,
            contract_size=Decimal("100"),
            volume_min=Decimal("0.01"),
            volume_max=Decimal("100"),
            volume_step=Decimal("0.01"),
            digits=2,
            point=Decimal("0.01"),
            tick_size=Decimal("0.01"),
            trade_mode=4,
            trade_allowed=True,
            filling_mode=1,
        )

    def validate_and_normalize_quantity(self, quantity: Decimal, spec: SymbolSpec) -> Decimal:
        if quantity <= 0:
            raise ValueError(f"quantity must be >0, got {quantity}")
        if quantity < spec.volume_min - Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} < broker min {spec.volume_min} for {spec.symbol}")
        if quantity > spec.volume_max + Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} > broker max {spec.volume_max} for {spec.symbol}")
        # Quantize to step
        steps = (quantity / spec.volume_step).to_integral_value(rounding=ROUND_HALF_UP)
        normalized = steps * spec.volume_step
        # Check remainder
        remainder = (quantity / spec.volume_step) % 1
        if remainder != 0 and abs(remainder) > Decimal("0.0000001") and abs(1 - remainder) > Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} not multiple of step {spec.volume_step} for {spec.symbol}")
        return normalized

    def validate_price_precision(self, price: Decimal | None, spec: SymbolSpec) -> Decimal | None:
        if price is None:
            return None
        quantum = Decimal("1").scaleb(-spec.digits)
        if spec.tick_size < quantum:
            quantum = spec.tick_size
        quantized = (price / quantum).to_integral_value(rounding=ROUND_HALF_UP) * quantum
        if price != quantized and abs(price - quantized) > Decimal("0.0000001"):
            raise ValueError(
                f"price {price} not at broker precision {quantum} (digits {spec.digits}) for {spec.symbol} quantized {quantized}"
            )
        if quantized <= 0:
            raise ValueError(f"price must be >0, got {quantized}")
        return quantized

    def submit(self, intent: OrderIntent) -> Order:
        spec = self.get_symbol_spec(intent.instrument.symbol)
        normalized_qty = self.validate_and_normalize_quantity(intent.quantity, spec)
        # Validate prices
        limit_price = self.validate_price_precision(intent.limit_price, spec) if intent.limit_price else None
        stop_price = self.validate_price_precision(intent.stop_price, spec) if intent.stop_price else None

        # Check free margin for paper — realistic
        # For paper, compute notional and check leverage
        # Use last tick or limit price
        est_price = limit_price or stop_price
        if est_price is None:
            # Try to get tick for market
            tick = self._ticks.get(intent.instrument.symbol)
            pos = self._positions.get(intent.instrument.symbol)
            if tick:
                est_price = tick.ask if intent.side == Side.BUY else tick.bid
            elif pos is not None and pos.avg_price > 0:
                est_price = pos.avg_price  # last known mark from the simulation itself
            else:
                est_price = self.simulated_reference_price  # declared SIMULATED fallback
        notional = normalized_qty * spec.contract_size * est_price
        account = self.account()
        # Check free margin
        # For paper, free_margin = equity - margin
        # If notional / leverage > free_margin, reject
        required_margin = notional / self._leverage
        if required_margin > account.free_margin + Decimal("0.01"):
            raise ValueError(
                f"insufficient free margin: need {required_margin:.2f} have {account.free_margin:.2f} for {intent.instrument.symbol} qty {normalized_qty} price {est_price}"
            )

        # Check trade allowed
        if not spec.trade_allowed or spec.trade_mode == 0:
            raise ValueError(f"symbol {intent.instrument.symbol} trade disabled")

        order = Order(
            order_id=intent.client_order_id,
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=normalized_qty,
            order_type=intent.order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            state=OrderState.ACCEPTED,
            strategy_id=intent.strategy_id,
        )
        self._orders[intent.client_order_id] = order
        # Store comment map
        with db_connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO paper_comment_map VALUES (?,?,?)",
                (intent.client_order_id, intent.client_order_id[:31], datetime.now(UTC).isoformat()),
            )
            con.commit()
        return order

    def apply_fill(self, fill) -> None:
        sym = fill.instrument.symbol
        pos = self._positions.get(sym)
        qty_delta = fill.quantity if fill.side.value == "BUY" else -fill.quantity
        if pos is None:
            self._positions[sym] = Position(instrument=fill.instrument, quantity=qty_delta, avg_price=fill.price)
        else:
            new_qty = pos.quantity + qty_delta
            if new_qty == Decimal("0"):
                self._positions[sym] = Position(
                    instrument=fill.instrument, quantity=Decimal("0"), avg_price=Decimal("0")
                )
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
            self._orders[fill.client_order_id] = o.model_copy(
                update={"state": OrderState.FILLED, "filled_quantity": fill.quantity, "avg_fill_price": fill.price}
            )

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def orders(self) -> list[Order]:
        return list(self._orders.values())

    def cancel(self, client_order_id: str) -> None:
        if client_order_id in self._orders:
            o = self._orders[client_order_id]
            if o.state in (OrderState.PENDING, OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED):
                self._orders[client_order_id] = o.model_copy(update={"state": OrderState.CANCELLED})
            else:
                raise RuntimeError(f"cannot cancel order {client_order_id} in state {o.state}")
        else:
            raise RuntimeError(f"order {client_order_id} not found")

    def account(self) -> Account:
        # Realistic account: compute margin from positions
        # For each position, margin = notional / leverage
        total_margin = Decimal("0")
        for pos in self._positions.values():
            if pos.quantity == 0:
                continue
            # Use last tick or avg_price
            price = self._ticks.get(pos.instrument.symbol)
            mid = price.mid if price else pos.avg_price if pos.avg_price != 0 else Decimal("2000")
            notional = abs(pos.quantity) * pos.instrument.contract_size * mid
            total_margin += notional / self._leverage
        # Equity = balance + unrealized
        unrealized = Decimal("0")
        for pos in self._positions.values():
            if pos.quantity == 0:
                continue
            tick = self._ticks.get(pos.instrument.symbol)
            cur = tick.mid if tick else pos.avg_price
            if pos.quantity > 0:
                unrealized += pos.quantity * pos.instrument.contract_size * (cur - pos.avg_price)
            else:
                unrealized += abs(pos.quantity) * pos.instrument.contract_size * (pos.avg_price - cur)
        equity = self._balance + unrealized
        free_margin = equity - total_margin
        # Ensure free_margin not negative beyond tolerance
        return Account(
            balance=self._balance,
            equity=equity,
            margin=total_margin,
            free_margin=free_margin,
            leverage=self._leverage,
            currency="PAPER_SIM",  # labeled simulation — never broker truth
            source="PAPER_SIMULATION",
            updated_at=datetime.now(UTC),
        )

    def update_balance(self, new_balance: Decimal) -> None:
        self._balance = new_balance
        self._account_updated_at = datetime.now(UTC)

    def set_tick(self, tick: Tick) -> None:
        self._ticks[tick.instrument.symbol] = tick

    def ticks(self, instrument: Instrument) -> Tick | None:
        """For paper, return last set tick or synthesize from positions."""
        if instrument.symbol in self._ticks:
            return self._ticks[instrument.symbol]
        # Synthesize a tick from avg_price or default
        # For backtest, we don't have ticks, so return None to indicate no live market data
        return None

    # class attribute (not property) — matches writable BrokerAdapter.is_live base
    is_live = False
