"""Independent Risk Engine — fail closed, quantity in lots, notional in USD."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

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
        db_path: Path | str = "data/sqlite/qts.db",
        persist_kill: bool = True,
    ):
        self.limits = limits
        self.db_path = Path(db_path)
        self.persist_kill = persist_kill
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
        return self._killed

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
        if self._killed:
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
        # step: quantity must be multiple of step (within tolerance)
        # check (quantity / step) is integer
        step = self.limits.quantity_step
        # use quantize check
        remainder = (intent.quantity / step) % 1
        # tolerate 1e-9
        if remainder != 0 and abs(remainder) > Decimal("0.0000001") and abs(1 - remainder) > Decimal("0.0000001"):
            # also allow instrument's lot_size as step? Use instrument.lot_size as ground truth if stricter
            instr_step = intent.instrument.lot_size
            rem2 = (intent.quantity / instr_step) % 1
            if rem2 != 0 and abs(rem2) > Decimal("0.0000001") and abs(1 - rem2) > Decimal("0.0000001"):
                return RiskDecision(
                    allowed=False,
                    veto_reason=RiskVetoReason.QUANTITY_STEP_VIOLATION,
                    reason_detail=f"{intent.quantity} not multiple of {instr_step}",
                    symbol=sym,
                )

        if intent.quantity > self.limits.max_quantity:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_MAX_QUANTITY,
                reason_detail=f"{intent.quantity} > {self.limits.max_quantity}",
                symbol=sym,
            )

        # notional — must use authoritative market price, not hard-coded fallback (Blocker 5)
        # Priority: limit/stop price if set (explicit), else reference_prices[symbol] from market snapshot
        est_price = intent.limit_price or intent.stop_price
        price_source = "limit/stop"
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
            and intent.stop_price is None
            and intent.order_type.value not in ("STOP", "STOP_LIMIT")
        ):
            return RiskDecision(allowed=False, veto_reason=RiskVetoReason.MISSING_STOP)

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

        # exposure lots: net quantity + new delta
        current_qty = sum((p.quantity for p in ctx.positions.values()), Decimal("0"))
        delta = intent.quantity if intent.side.value == "BUY" else -intent.quantity
        new_exposure_lots = abs(current_qty + delta)
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
            current_notional = sum(
                (abs(p.quantity) * p.instrument.contract_size * est_price for p in ctx.positions.values()),
                Decimal("0"),
            )
            # new notional approx
            new_notional = current_notional + notional  # overestimates but safe
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
        # total notional for leverage: exposure notional
        total_notional_for_lev = (
            sum(
                (abs(p.quantity) * p.instrument.contract_size * est_price for p in ctx.positions.values()),
                Decimal("0"),
            )
            + notional
        )
        # if flat, leverage is just new notional/equity
        if total_notional_for_lev == notional and not ctx.positions:
            lev = notional / equity
        else:
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
                resized = (intent.quantity * factor).quantize(Decimal("0.01"))
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
        if self._killed:
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
