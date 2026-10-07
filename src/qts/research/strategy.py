"""Canonical strategy contract and compatibility helpers.

Production strategy implementations live in :mod:`qts.research.strategies`.
This module intentionally contains no second implementation of a strategy.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from qts.domain.value_objects import Bar, Instrument, OrderIntent, OrderType, Signal, uuid7
from qts.research.strategies import TrendFollowingStrategy


class Strategy(Protocol):
    """Minimal contract consumed by backtest/research orchestration."""

    strategy_id: str

    def on_bar(self, bar: Bar) -> list[Signal]: ...


class SmaBreakoutStrategy(TrendFollowingStrategy):
    """Backward-compatible name for the canonical trend implementation.

    The old module contained a second copy of an SMA crossover algorithm.
    Keeping the name avoids breaking existing experiment references while
    ensuring there is only one implementation to maintain.
    """

    def __init__(
        self,
        instrument: Instrument,
        fast: int = 10,
        slow: int = 20,
        strategy_id: str = "sma_breakout",
    ):
        super().__init__(
            instrument=instrument,
            fast=fast,
            slow=slow,
            ma_type="sma",
            strategy_id=strategy_id,
        )


def signal_to_intent(signal: Signal, quantity: Decimal = Decimal("0.1")) -> OrderIntent:
    """Translate a validated research signal into an execution-neutral intent."""
    return OrderIntent(
        instrument=signal.instrument,
        side=signal.side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        client_order_id=f"{signal.strategy_id}:{uuid7()}",
        strategy_id=signal.strategy_id,
        signal_id=signal.hypothesis_id,
    )
