"""NO_TRADE explicit sentinel — capital preservation default.

Principle: When uncertain, do nothing. Empty signals, risk vetoes, data gaps,
reconciliation drift, or kill-switch all collapse to NO_TRADE with a reason.
This makes the default auditable instead of an absent trade.

Usage:
    - Strategy.on_bar returns []  -> NO_TRADE/EMPTY_SIGNAL
    - RiskEngine.pre_trade veto   -> NO_TRADE/RISK_VETO
    - Backtest/Execution records NoTradeEvent to audit log
    - Lifecycle remains in current state; PROMOTE blocked

This module centralizes the reasons so dashboards and validation can aggregate
why the system stayed flat, rather than inferring from missing fills.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class NoTradeReason(StrEnum):
    EMPTY_SIGNAL = "EMPTY_SIGNAL"  # strategy returned []
    RISK_VETO = "RISK_VETO"  # RiskEngine blocked
    KILL_SWITCH = "KILL_SWITCH"  # kill active
    RECONCILE_SUSPEND = "RECONCILE_SUSPEND"  # reconcile requires_suspend
    DATA_GAP = "DATA_GAP"  # missing bar / stale feed
    DATA_QUALITY_FAIL = "DATA_QUALITY_FAIL"  # quality gate failed
    INVALID_QUANTITY = "INVALID_QUANTITY"  # lot step/min violation
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"  # warmup not satisfied
    REGIME_FILTER = "REGIME_FILTER"  # regime says no trade
    VALIDATION_FAIL = "VALIDATION_FAIL"  # edge not validated
    UNKNOWN = "UNKNOWN"


class NoTradeEvent(BaseModel):
    """Structured record of a NO_TRADE decision — always audited."""

    model_config = {"frozen": True}

    reason: NoTradeReason
    strategy_id: str
    detail: str = ""
    bar_time: str | None = None  # iso timestamp of bar that triggered it
