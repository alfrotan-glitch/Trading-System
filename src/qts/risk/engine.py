"""Independent Risk Engine — fail closed, quantity in lots, notional in USD."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from qts.db import connect as db_connect
from qts.domain.value_objects import Account, Fill, OrderIntent, Position


class RiskVetoReason(StrEnum):
    EXCEEDS_MAX_QUANTITY = "EXCEEDS_MAX_QUANTITY"
    EXCEEDS_NOTIONAL = "EXCEEDS_NOTIONAL"
    EXCEEDS_RISK_PER_TRADE = "EXCEEDS_RISK_PER_TRADE"
    MISSING_STOP = "MISSING_STOP"
    EXCEEDS_LEVERAGE = "EXCEEDS_LEVERAGE"
    EXCEEDS_EXPOSURE = "EXCEEDS_EXPOSURE"
    EXCEEDS_CORRELATED = "EXCEEDS_CORRELATED"
    TOO_MANY_ORDERS = "TOO_MANY_ORDERS"
    DAILY_LOSS_BREACH = "DAILY_LOSS_BREACH"
    DRAWDOWN_BREACH = "DRAWDOWN_BREACH"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    INSTRUMENT_SUSPENDED = "INSTRUMENT_SUSPENDED"
    VOL_RESIZE = "VOL_RESIZE"
    QUANTITY_STEP_VIOLATION = "QUANTITY_STEP_VIOLATION"
    MIN_QUANTITY_VIOLATION = "MIN_QUANTITY_VIOLATION"
    MISSING_MARKET_PRICE = "MISSING_MARKET_PRICE"
    #: Authoritative account equity unavailable — leverage/loss checks cannot
    #: be computed honestly. UNKNOWN -> BLOCK, never UNKNOWN -> GUESS.
    ACCOUNT_STATE_UNAVAILABLE = "ACCOUNT_STATE_UNAVAILABLE"


class RiskLimits(BaseModel):
    max_quantity: Decimal = Decimal("1.0")  # lots
    min_quantity: Decimal = Decimal("0.01")  # lots
    quantity_step: Decimal = Decimal("0.01")  # lots
    max_notional: Decimal = Decimal("50000")  # USD
    max_risk_per_trade_bps: Decimal = Decimal("50")
    stop_loss_required: bool = False
    max_exposure_lots: Decimal = Decimal("2.0")  # lots net abs
    max_exposure_notional: Decimal | None = None  # optional USD
    max_leverage: Decimal = Decimal("5")  # notional/equity
    max_correlated_exposure: Decimal = Decimal("1.5")
    max_open_orders: int = 5
    daily_loss_limit: Decimal = Decimal("200")  # USD loss (positive = max loss allowed)
    max_drawdown: Decimal = Decimal("500")  # USD drawdown
    volatility_target: Decimal | None = None
    kill_switch_enabled: bool = True
    approved: bool = False
    version: int = 1

    # legacy alias
    @property
    def max_exposure(self) -> Decimal:
        return self.max_exposure_lots

    @property
    def max_notional_alias(self) -> Decimal:
        return self.max_notional


@dataclass
class RiskContext:
    account: Account
    positions: dict[str, Position]  # symbol -> Position (qty lots)
    open_orders_count: int
    daily_pnl: Decimal  # can be negative
    drawdown: Decimal  # USD peak - current
    instrument_suspended: set[str]
    realized_vol: Decimal | None = None
    # Authoritative market snapshot — must be provided for market orders (Blocker 5)
    reference_prices: dict[str, Decimal] | None = None

    def reference_price_for(self, symbol: str) -> Decimal | None:
        if self.reference_prices is None:
            return None
        return self.reference_prices.get(symbol)


class RiskDecision(BaseModel):
    allowed: bool
    veto_reason: RiskVetoReason | None = None
    resized_quantity: Decimal | None = None
    reason_detail: str = ""
    # Audit fields for G10: durable price source traceability
    price: Decimal | None = None
    price_source: str | None = None
    notional: Decimal | None = None
    symbol: str | None = None


class RiskEngine:
    """Independent authority. Persists kill flag. Quantity canonical: lots.

    ``persist_kill`` is disabled for isolated research/simulation runs.  A
    backtest must not clear or overwrite a durable production kill switch just
    because it shares the repository's SQLite data store.  Live, paper, and
    shadow callers retain the durable default.
    """

    def __init__(
        self,
        limits: RiskLimits,
        db_path: Path | str | None = None,
        persist_kill: bool = True,
    ):
        from qts.config.paths import artifact_path, resolve_state_path

        self.limits = limits
        if db_path is None or str(db_path) == "data/sqlite/qts.db":
            self.db_path = artifact_path("db")
        else:
            self.db_path = resolve_state_path(db_path)
        self.persist_kill = persist_kill
        #: Set when the durable kill flag could not be read (fail closed to True).
        self._kill_read_error: str | None = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.persist_kill:
            self._init_db()
            self._killed = self._load_killed()
        else:
            self._killed = False

    def _init_db(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS risk_state (k INTEGER PRIMARY KEY, killed INTEGER, reason TEXT, updated_at TEXT)"
            )
            con.commit()

    def _load_killed(self) -> bool:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT killed FROM risk_state WHERE k=1").fetchone()
            return bool(row[0]) if row else False

    @property
    def killed(self) -> bool:
        """The DURABLE kill-switch flag — the one ``pre_trade`` enforces.

        When ``persist_kill`` is active the persisted row is authoritative and
        is re-read on access. The kill switch can be raised by ANOTHER process
        (``qts risk kill``, ``ExecutionEngine.handle_kill``) after this engine
        was constructed; a long-lived engine must never keep trading against a
        stale in-memory ``False``. A read failure is treated as KILLED (fail
        closed) and surfaced through :meth:`kill_state`.

        When ``persist_kill`` is disabled (isolated research/backtest runs) the
        flag stays purely local by design — those runs must neither read nor
        disturb the durable production kill switch.
        """
        if not self.persist_kill:
            return self._killed
        try:
            self._killed = self._load_killed()
            self._kill_read_error = None
        except Exception as exc:  # fail closed: unknown kill state == killed
            self._killed = True
            self._kill_read_error = f"{type(exc).__name__}: {exc}"
        return self._killed

    def is_killed(self) -> bool:
        """Explicit durable kill-switch query for reporting surfaces and gates.

        Status code previously probed ``hasattr(engine, "is_killed")`` and
        silently fell back to ``False`` because the method did not exist, so an
        ACTIVE kill switch was reported as healthy/armed by ``/api/health``,
        ``/api/risk`` and the startup health check. Enforcement and reporting
        now share one answer.
        """
        return self.killed

    def kill_state(self) -> dict[str, Any]:
        """Durable kill-switch record for honest status reporting."""
        killed = self.killed
        reason: str | None = None
        updated_at: str | None = None
        if killed and self.persist_kill and self._kill_read_error is None:
            with contextlib.suppress(Exception):
                with db_connect(self.db_path) as con:
                    row = con.execute("SELECT reason, updated_at FROM risk_state WHERE k=1").fetchone()
                if row:
                    reason, updated_at = row[0], row[1]
        return {
            "killed": killed,
            "reason": reason or (self._kill_read_error if killed else None),
            "updated_at": updated_at,
            "source": "durable:risk_state" if self.persist_kill else "process-local",
            "read_error": self._kill_read_error,
        }

    def kill_switch(self, reason: str) -> None:
        self._killed = True
        if not self.persist_kill:
            return
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO risk_state VALUES (1,1,?,?)",
                (reason, datetime.now(UTC).isoformat()),
            )
            con.commit()

    def reset_kill(self) -> None:
        self._killed = False
        if not self.persist_kill:
            return
        with db_connect(self.db_path) as con:
            con.execute("DELETE FROM risk_state WHERE k=1")
            con.commit()

    def _notional_for(self, intent: OrderIntent, est_price: Decimal) -> Decimal:
        """Notional USD = lots * contract_size(oz/lot) * price(USD/oz)."""
        return intent.quantity * intent.instrument.contract_size * est_price

    def pre_trade(self, intent: OrderIntent, ctx: RiskContext) -> RiskDecision:
        sym = intent.instrument.symbol
        if self.killed:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.KILL_SWITCH_ACTIVE,
                reason_detail="kill active",
                symbol=sym,
            )
        if sym in ctx.instrument_suspended:
            return RiskDecision(allowed=False, veto_reason=RiskVetoReason.INSTRUMENT_SUSPENDED, symbol=sym)

        # quantity step / min
        if intent.quantity < self.limits.min_quantity:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.MIN_QUANTITY_VIOLATION,
                reason_detail=f"{intent.quantity} < min {self.limits.min_quantity}",
                symbol=sym,
            )
        # Broker symbol geometry is authoritative. The configured risk step
        # may be stricter, but it must never permit a quantity the broker cannot
        # represent.
        configured_step = self.limits.quantity_step
        broker_step = intent.instrument.lot_size
        if configured_step <= 0 or broker_step <= 0:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.QUANTITY_STEP_VIOLATION,
                reason_detail="invalid quantity step",
                symbol=sym,
            )
        for step_name, step_value in (("risk", configured_step), ("broker", broker_step)):
            remainder = intent.quantity % step_value
            if remainder != 0 and abs(remainder) > Decimal("0.0000001") and abs(step_value - remainder) > Decimal("0.0000001"):
                return RiskDecision(
                    allowed=False,
                    veto_reason=RiskVetoReason.QUANTITY_STEP_VIOLATION,
                    reason_detail=f"{intent.quantity} is not a multiple of {step_name} step {step_value}",
                    symbol=sym,
                )

        if intent.quantity > self.limits.max_quantity:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_MAX_QUANTITY,
                reason_detail=f"{intent.quantity} > {self.limits.max_quantity}",
                symbol=sym,
            )

        # Notional price must match the order's execution semantics:
        # LIMIT/STOP orders use their explicit trigger/limit price; MARKET
        # orders use the current authoritative reference price. Never let an
        # unrelated stop/trigger field become a fake market price.
        est_price: Decimal | None = None
        price_source = "missing"
        if intent.order_type.value == "LIMIT":
            est_price = intent.limit_price
            price_source = "limit_price"
        elif intent.order_type.value in ("STOP", "STOP_LIMIT"):
            est_price = intent.stop_price or intent.limit_price
            price_source = "stop/limit_price"
        if est_price is None:
            est_price = ctx.reference_price_for(sym) if ctx.reference_prices else None
            price_source = "reference_prices"
        if est_price is None:
            # No market price available — fail closed, do not trade, auditable
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.MISSING_MARKET_PRICE,
                reason_detail=f"no market price for {sym}: need limit_price or reference_prices[{sym}]",
                price=None,
                price_source="missing",
                notional=None,
                symbol=sym,
            )
        notional = self._notional_for(intent, est_price)
        # audit detail includes price_source for traceability
        if notional > self.limits.max_notional:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_NOTIONAL,
                reason_detail=f"notional {notional} > {self.limits.max_notional} price {est_price} source {price_source}",
                price=est_price,
                price_source=price_source,
                notional=notional,
                symbol=sym,
            )

        if (
            self.limits.stop_loss_required
            and intent.stop_loss is None
            and intent.order_type.value not in ("STOP", "STOP_LIMIT")
        ):
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.MISSING_STOP,
                reason_detail="protective stop_loss is required",
                symbol=sym,
                price=est_price,
                price_source=price_source,
                notional=notional,
            )

        if ctx.open_orders_count >= self.limits.max_open_orders:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.TOO_MANY_ORDERS,
                symbol=sym,
                price=est_price if "est_price" in locals() else None,
                price_source=price_source if "price_source" in locals() else None,
            )

        # daily loss: ctx.daily_pnl is negative if losing
        if ctx.daily_pnl <= -self.limits.daily_loss_limit:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.DAILY_LOSS_BREACH,
                reason_detail=f"daily_pnl {ctx.daily_pnl} price {est_price} source {price_source}",
                price=est_price,
                price_source=price_source,
                symbol=sym,
            )
        if ctx.drawdown >= self.limits.max_drawdown:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.DRAWDOWN_BREACH,
                symbol=sym,
                price=est_price if "est_price" in locals() else None,
                price_source=price_source if "price_source" in locals() else None,
            )

        # Exposure is the sum of absolute signed positions. Netting across
        # unrelated symbols can hide real capital exposure (e.g. +1 XAUUSD
        # and -1 EURUSD incorrectly becoming zero).
        current_exposure_lots = sum((abs(p.quantity) for p in ctx.positions.values()), Decimal("0"))
        delta = intent.quantity if intent.side.value == "BUY" else -intent.quantity
        current_position = ctx.positions.get(sym)
        if current_position is not None:
            new_qty = current_position.quantity + delta
            current_exposure_lots -= abs(current_position.quantity)
        else:
            new_qty = delta
        new_exposure_lots = current_exposure_lots + abs(new_qty)
        if new_exposure_lots > self.limits.max_exposure_lots:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_EXPOSURE,
                reason_detail=f"exposure lots {new_exposure_lots} > {self.limits.max_exposure_lots} price {est_price} source {price_source}",
                price=est_price,
                price_source=price_source,
                notional=notional,
                symbol=sym,
            )
        # exposure notional (optional)
        if self.limits.max_exposure_notional is not None:
            # estimate total notional after trade: sum of abs(qty)*contract*price
            # approximate using est_price for new position
            current_notional = Decimal("0")
            for p in ctx.positions.values():
                p_price = est_price if p.instrument.symbol == sym else ctx.reference_price_for(p.instrument.symbol)
                if p_price is None or not p_price.is_finite() or p_price <= 0:
                    return RiskDecision(
                        allowed=False,
                        veto_reason=RiskVetoReason.MISSING_MARKET_PRICE,
                        reason_detail=f"no valid reference price for existing position {p.instrument.symbol}",
                        price=est_price,
                        price_source=price_source,
                        notional=notional,
                        symbol=sym,
                    )
                current_notional += abs(p.quantity) * p.instrument.contract_size * p_price
            # The new position notional replaces the current symbol's notional
            # rather than blindly adding it, so reducing/reversing a position
            # is not charged twice.
            old_symbol_notional = (
                abs(current_position.quantity) * current_position.instrument.contract_size * est_price
                if current_position is not None
                else Decimal("0")
            )
            new_symbol_notional = abs(new_qty) * intent.instrument.contract_size * est_price
            new_notional = current_notional - old_symbol_notional + new_symbol_notional
            if new_notional > self.limits.max_exposure_notional:
                return RiskDecision(
                    allowed=False,
                    veto_reason=RiskVetoReason.EXCEEDS_EXPOSURE,
                    reason_detail=f"exposure notional {new_notional} > {self.limits.max_exposure_notional} price {est_price} source {price_source}",
                    price=est_price,
                    price_source=price_source,
                    notional=new_notional,
                    symbol=sym,
                )

        # leverage: total notional / equity — FAIL CLOSED on unknown equity.
        # The previous fallback `equity = 10000` when account equity was 0
        # fabricated the denominator of the leverage check (finding #9):
        # unknown equity now vetoes the order instead of guessing capital.
        equity = ctx.account.equity
        if equity is None or equity <= Decimal("0"):
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.ACCOUNT_STATE_UNAVAILABLE,
                reason_detail=f"authoritative account equity unavailable ({equity}) — leverage check cannot run, fail-closed",
                price=est_price,
                price_source=price_source,
                notional=notional,
                symbol=sym,
            )
        # Leverage must use the same post-trade gross exposure model as
        # max_exposure_notional: replace the target symbol's old notional with
        # its post-trade notional; never blindly add a reduction/reversal.
        if self.limits.max_exposure_notional is not None:
            total_notional_for_lev = new_notional
        else:
            total_notional_for_lev = Decimal("0")
            for p in ctx.positions.values():
                p_price = est_price if p.instrument.symbol == sym else ctx.reference_price_for(p.instrument.symbol)
                if p_price is None or not p_price.is_finite() or p_price <= 0:
                    return RiskDecision(
                        allowed=False,
                        veto_reason=RiskVetoReason.MISSING_MARKET_PRICE,
                        reason_detail=f"no valid reference price for existing position {p.instrument.symbol}",
                        price=est_price,
                        price_source=price_source,
                        notional=notional,
                        symbol=sym,
                    )
                total_notional_for_lev += abs(p.quantity) * p.instrument.contract_size * p_price
            new_symbol_notional_for_lev = (
                abs(new_qty) * intent.instrument.contract_size * est_price
            )
            total_notional_for_lev = total_notional_for_lev - (
                abs(current_position.quantity) * current_position.instrument.contract_size * est_price
                if current_position is not None
                else Decimal("0")
            ) + new_symbol_notional_for_lev
        lev = total_notional_for_lev / equity
        if lev > self.limits.max_leverage:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_LEVERAGE,
                reason_detail=f"leverage {lev:.2f} > {self.limits.max_leverage} price {est_price} source {price_source}",
                price=est_price,
                price_source=price_source,
                notional=notional,
                symbol=sym,
            )

        # vol-aware resize (not veto)
        if self.limits.volatility_target is not None and ctx.realized_vol is not None and ctx.realized_vol > 0:
            target = self.limits.volatility_target
            factor = target / ctx.realized_vol
            factor = max(Decimal("0.25"), min(Decimal("1.0"), factor))
            if factor < Decimal("0.99"):
                step = intent.instrument.lot_size
                resized_steps = (intent.quantity * factor / step).to_integral_value(rounding=ROUND_FLOOR)
                resized = resized_steps * step
                if resized < self.limits.min_quantity:
                    resized = self.limits.min_quantity
                return RiskDecision(
                    allowed=True,
                    resized_quantity=resized,
                    veto_reason=RiskVetoReason.VOL_RESIZE,
                    reason_detail=f"vol resize {factor:.2f}",
                    price=est_price,
                    price_source=price_source,
                    notional=notional,
                    symbol=sym,
                )
        return RiskDecision(allowed=True, price=est_price, price_source=price_source, notional=notional, symbol=sym)

    def post_trade(self, fill: Fill, ctx: RiskContext) -> None:
        if not self.limits.kill_switch_enabled:
            return
        if ctx.daily_pnl <= -self.limits.daily_loss_limit:
            self.kill_switch(f"daily loss {ctx.daily_pnl}")
        if ctx.drawdown >= self.limits.max_drawdown:
            self.kill_switch(f"drawdown {ctx.drawdown}")

    def check_portfolio(self, ctx: RiskContext) -> list[RiskDecision]:
        out: list[RiskDecision] = []
        total = sum((abs(p.quantity) for p in ctx.positions.values()), Decimal("0"))
        if total > self.limits.max_exposure_lots:
            out.append(RiskDecision(allowed=False, veto_reason=RiskVetoReason.EXCEEDS_EXPOSURE))
        if ctx.daily_pnl <= -self.limits.daily_loss_limit:
            out.append(RiskDecision(allowed=False, veto_reason=RiskVetoReason.DAILY_LOSS_BREACH))
        if ctx.drawdown >= self.limits.max_drawdown:
            out.append(RiskDecision(allowed=False, veto_reason=RiskVetoReason.DRAWDOWN_BREACH))
        if self.killed:
            out.append(RiskDecision(allowed=False, veto_reason=RiskVetoReason.KILL_SWITCH_ACTIVE))
        return out

    def close(self) -> None:
        with contextlib.suppress(Exception):
            # File-backed connections are opened/closed per operation via qts.db.connect,
            # so no persistent handle exists here. We must NOT re-open the database file
            # in close()/__del__: that recreates deleted files and re-acquires Windows
            # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                with contextlib.suppress(Exception):
                    mem.commit()
                    mem.close()
                self._memory_con = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
