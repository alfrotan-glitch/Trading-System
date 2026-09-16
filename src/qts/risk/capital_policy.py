"""Phase 12: Capital survival policy — hard limits, NO_TRADE/SUSPENDED."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CapitalLimit(StrEnum):
    RISK_PER_TRADE = "risk_per_trade"
    TOTAL_EXPOSURE = "total_exposure"
    DAILY_LOSS = "daily_loss"
    ROLLING_LOSS = "rolling_loss"
    MAX_DRAWDOWN = "max_drawdown"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    NUM_TRADES = "num_trades"
    ORDER_FREQUENCY = "order_frequency"
    SPREAD = "spread"
    SLIPPAGE = "slippage"
    LATENCY = "latency"
    DATA_STALENESS = "data_staleness"
    RECONCILIATION_DRIFT = "reconciliation_drift"


@dataclass
class CapitalPolicy:
    risk_per_trade_bps: float = 50
    max_exposure_lots: float = 2.0
    daily_loss_limit: float = 200
    rolling_loss_limit: float = 500
    max_drawdown: float = 500
    max_consecutive_losses: int = 5
    max_trades_per_day: int = 20
    max_order_frequency_per_min: int = 10
    max_spread_bps: float = 100
    max_slippage_bps: float = 20
    max_latency_ms: float = 2000
    max_data_staleness_s: float = 5.0
    # reconciliation drift handled via ExecutionEngine suspend

    def check(self, ctx: dict[str, Any]) -> tuple[bool, str | None]:
        """Return (ok, violating_limit). If not ok, must force NO_TRADE/SUSPENDED."""
        if ctx.get("risk_per_trade_bps", 0) > self.risk_per_trade_bps:
            return False, CapitalLimit.RISK_PER_TRADE
        if ctx.get("exposure_lots", 0) > self.max_exposure_lots:
            return False, CapitalLimit.TOTAL_EXPOSURE
        if ctx.get("daily_loss", 0) <= -self.daily_loss_limit:
            return False, CapitalLimit.DAILY_LOSS
        if ctx.get("rolling_loss", 0) <= -self.rolling_loss_limit:
            return False, CapitalLimit.ROLLING_LOSS
        if ctx.get("drawdown", 0) >= self.max_drawdown:
            return False, CapitalLimit.MAX_DRAWDOWN
        if ctx.get("consecutive_losses", 0) >= self.max_consecutive_losses:
            return False, CapitalLimit.CONSECUTIVE_LOSSES
        if ctx.get("num_trades", 0) >= self.max_trades_per_day:
            return False, CapitalLimit.NUM_TRADES
        if ctx.get("order_freq", 0) > self.max_order_frequency_per_min:
            return False, CapitalLimit.ORDER_FREQUENCY
        if ctx.get("spread_bps", 0) > self.max_spread_bps:
            return False, CapitalLimit.SPREAD
        if ctx.get("slippage_bps", 0) > self.max_slippage_bps:
            return False, CapitalLimit.SLIPPAGE
        if ctx.get("latency_ms", 0) > self.max_latency_ms:
            return False, CapitalLimit.LATENCY
        if ctx.get("data_staleness_s", 0) > self.max_data_staleness_s:
            return False, CapitalLimit.DATA_STALENESS
        if ctx.get("reconciliation_drift"):
            return False, CapitalLimit.RECONCILIATION_DRIFT
        return True, None

    def is_no_trade(self, ctx: dict) -> bool:
        ok, _ = self.check(ctx)
        return not ok
