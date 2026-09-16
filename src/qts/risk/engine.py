"""Independent Risk Engine — fail closed."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

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


class RiskLimits(BaseModel):
    max_quantity: Decimal = Decimal("1.0")
    max_notional: Decimal = Decimal("10000")
    max_risk_per_trade_bps: Decimal = Decimal("50")
    stop_loss_required: bool = False
    max_exposure: Decimal = Decimal("2.0")
    max_leverage: Decimal = Decimal("5")
    max_correlated_exposure: Decimal = Decimal("1.5")
    max_open_orders: int = 5
    daily_loss_limit: Decimal = Decimal("200")
    max_drawdown: Decimal = Decimal("500")
    volatility_target: Decimal | None = None
    kill_switch_enabled: bool = True
    approved: bool = False
    version: int = 1


@dataclass
class RiskContext:
    account: Account
    positions: dict[str, Position]  # symbol -> Position
    open_orders_count: int
    daily_pnl: Decimal
    drawdown: Decimal
    instrument_suspended: set[str]
    realized_vol: Decimal | None = None


class RiskDecision(BaseModel):
    allowed: bool
    veto_reason: RiskVetoReason | None = None
    resized_quantity: Decimal | None = None
    reason_detail: str = ""


class RiskEngine:
    """Independent authority. Persists kill flag."""

    def __init__(self, limits: RiskLimits, db_path: Path | str = "data/sqlite/qts.db"):
        self.limits = limits
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._killed = self._load_killed()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS risk_state (k INTEGER PRIMARY KEY, killed INTEGER, reason TEXT, updated_at TEXT)"
            )
            con.commit()

    def _load_killed(self) -> bool:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT killed FROM risk_state WHERE k=1").fetchone()
            return bool(row[0]) if row else False

    @property
    def killed(self) -> bool:
        return self._killed

    def kill_switch(self, reason: str) -> None:
        self._killed = True
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO risk_state VALUES (1,1,?,?)",
                (reason, datetime.now(UTC).isoformat()),
            )
            con.commit()

    def reset_kill(self) -> None:
        self._killed = False
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM risk_state WHERE k=1")
            con.commit()

    def pre_trade(self, intent: OrderIntent, ctx: RiskContext) -> RiskDecision:
        if self._killed:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.KILL_SWITCH_ACTIVE,
                reason_detail="kill active",
            )
        sym = intent.instrument.symbol
        if sym in ctx.instrument_suspended:
            return RiskDecision(allowed=False, veto_reason=RiskVetoReason.INSTRUMENT_SUSPENDED)
        # quantity
        if intent.quantity > self.limits.max_quantity:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_MAX_QUANTITY,
                reason_detail=f"{intent.quantity} > {self.limits.max_quantity}",
            )
        # notional: quantity * price (use limit or estimate) — approximate with 2000 for XAUUSD if no price
        est_price = intent.limit_price or intent.stop_price or Decimal("2000")
        notional = (
            intent.quantity * est_price * intent.instrument.contract_size / Decimal("100")
        )  # lot semantics approx
        # simpler: for XAUUSD quantity in lots already vs oz confusion -> just quantity*price
        # For domain quantity = lots, notional = qty * 100 * price
        # We'll compute both interpretations and take larger
        notional2 = intent.quantity * est_price
        notional = max(notional, notional2)
        if notional > self.limits.max_notional:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_NOTIONAL,
                reason_detail=f"{notional} > {self.limits.max_notional}",
            )
        if (
            self.limits.stop_loss_required
            and intent.stop_price is None
            and intent.order_type.value not in ("STOP", "STOP_LIMIT")
        ):
            # missing stop — if required
            return RiskDecision(allowed=False, veto_reason=RiskVetoReason.MISSING_STOP)
        # open orders
        if ctx.open_orders_count >= self.limits.max_open_orders:
            return RiskDecision(allowed=False, veto_reason=RiskVetoReason.TOO_MANY_ORDERS)
        # daily loss
        if ctx.daily_pnl <= -self.limits.daily_loss_limit:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.DAILY_LOSS_BREACH,
                reason_detail=f"daily_pnl {ctx.daily_pnl}",
            )
        if ctx.drawdown >= self.limits.max_drawdown:
            return RiskDecision(allowed=False, veto_reason=RiskVetoReason.DRAWDOWN_BREACH)
        # exposure (net quantity)
        current_qty = sum((p.quantity for p in ctx.positions.values()), Decimal("0"))
        # signed by side
        delta = intent.quantity if intent.side.value == "BUY" else -intent.quantity
        new_exposure = abs(current_qty + delta)
        if new_exposure > self.limits.max_exposure:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_EXPOSURE,
                reason_detail=f"{new_exposure} > {self.limits.max_exposure}",
            )
        # leverage: notional / equity
        equity = ctx.account.equity if ctx.account.equity != 0 else Decimal("10000")
        lev = notional / equity
        if lev > self.limits.max_leverage:
            return RiskDecision(
                allowed=False,
                veto_reason=RiskVetoReason.EXCEEDS_LEVERAGE,
                reason_detail=f"{lev:.2f} > {self.limits.max_leverage}",
            )
        # vol-aware resize (not veto)
        if self.limits.volatility_target is not None and ctx.realized_vol is not None and ctx.realized_vol > 0:
            target = self.limits.volatility_target
            # reduce size if vol high
            factor = target / ctx.realized_vol
            factor = max(Decimal("0.25"), min(Decimal("1.0"), factor))
            if factor < Decimal("0.99"):
                resized = (intent.quantity * factor).quantize(Decimal("0.01"))
                if resized < Decimal("0.01"):
                    resized = Decimal("0.01")
                return RiskDecision(
                    allowed=True,
                    resized_quantity=resized,
                    veto_reason=RiskVetoReason.VOL_RESIZE,
                    reason_detail=f"vol resize {factor:.2f}",
                )
        return RiskDecision(allowed=True)

    def post_trade(self, fill: Fill, ctx: RiskContext) -> None:
        # update daily PnL/drawdown handled by caller; here check kill triggers
        if not self.limits.kill_switch_enabled:
            return
        if ctx.daily_pnl <= -self.limits.daily_loss_limit:
            self.kill_switch(f"daily loss {ctx.daily_pnl}")
        if ctx.drawdown >= self.limits.max_drawdown:
            self.kill_switch(f"drawdown {ctx.drawdown}")

    def check_portfolio(self, ctx: RiskContext) -> list[RiskDecision]:
        out: list[RiskDecision] = []
        # exposure check
        total = sum((abs(p.quantity) for p in ctx.positions.values()), Decimal("0"))
        if total > self.limits.max_exposure:
            out.append(RiskDecision(allowed=False, veto_reason=RiskVetoReason.EXCEEDS_EXPOSURE))
        if ctx.daily_pnl <= -self.limits.daily_loss_limit:
            out.append(RiskDecision(allowed=False, veto_reason=RiskVetoReason.DAILY_LOSS_BREACH))
        return out
