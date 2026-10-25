"""Offline risk-budget parity model for small XAUUSD accounts.

RESEARCH ONLY: execution EA must use real-time OrderCalcProfit/OrderCalcMargin.
No model guarantees stop fills or profitable trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from math import isfinite


@dataclass(frozen=True)
class Contract:
    contract_size: float = 100.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 100.0
    margin_per_lot_usd: float = 0.0


@dataclass(frozen=True)
class QuoteRisk:
    equity_usd: float
    free_margin_usd: float
    side: int
    entry: float
    stop: float
    requested_risk_pct: float = 1.0
    max_risk_pct: float = 2.0
    max_margin_fraction: float = 0.20
    round_turn_commission_per_lot_usd: float = 10.0
    stop_slippage_price: float = 0.10


@dataclass(frozen=True)
class SizeDecision:
    lots: float
    budget_usd: float
    estimated_loss_usd: float
    reason: str


def _positive_finite(*values: float) -> bool:
    return all(isfinite(v) and v > 0 for v in values)


def size_trade(contract: Contract, risk: QuoteRisk) -> SizeDecision:
    """Floor to legal volume steps; never buy an unaffordable minimum lot."""
    if not _positive_finite(
        risk.equity_usd, risk.free_margin_usd, risk.entry, risk.stop,
        contract.contract_size, contract.min_lot, contract.lot_step,
        contract.max_lot, contract.margin_per_lot_usd,
        risk.requested_risk_pct, risk.max_risk_pct,
        risk.max_margin_fraction,
    ):
        return SizeDecision(0.0, 0.0, 0.0, "invalid_or_unverified_input")
    if risk.side not in (-1, 1):
        return SizeDecision(0.0, 0.0, 0.0, "invalid_direction")
    if risk.side * (risk.entry - risk.stop) <= 0:
        return SizeDecision(0.0, 0.0, 0.0, "stop_wrong_side")
    if not 0 < risk.requested_risk_pct <= risk.max_risk_pct <= 2.0:
        return SizeDecision(0.0, 0.0, 0.0, "risk_cap_exceeded")
    if not 0 < risk.max_margin_fraction <= 1.0:
        return SizeDecision(0.0, 0.0, 0.0, "invalid_margin_limit")
    if not all(isfinite(v) and v >= 0 for v in (
        risk.round_turn_commission_per_lot_usd, risk.stop_slippage_price
    )):
        return SizeDecision(0.0, 0.0, 0.0, "invalid_cost_assumption")

    budget = risk.equity_usd * risk.requested_risk_pct / 100
    loss_per_lot = (
        (abs(risk.entry - risk.stop) + risk.stop_slippage_price)
        * contract.contract_size + risk.round_turn_commission_per_lot_usd
    )
    step = Decimal(str(contract.lot_step))
    units = (Decimal(str(budget / loss_per_lot)) / step).to_integral_value(
        rounding=ROUND_FLOOR
    )
    lots = min(float(units * step), contract.max_lot)
    if lots + 1e-10 < contract.min_lot:
        return SizeDecision(0.0, budget, 0.0, "min_lot_exceeds_risk")
    estimated = lots * loss_per_lot
    if estimated > budget + 1e-8:
        return SizeDecision(0.0, budget, 0.0, "rounded_size_exceeds_risk")
    if lots * contract.margin_per_lot_usd > (
        risk.free_margin_usd * risk.max_margin_fraction
    ):
        return SizeDecision(0.0, budget, 0.0, "insufficient_margin")
    return SizeDecision(lots, budget, estimated, "allowed")
