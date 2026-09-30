"""Strategy interface and examples."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from qts.domain.value_objects import Bar, Instrument, OrderIntent, OrderType, Side, Signal, uuid7


class Strategy(Protocol):
    strategy_id: str

    def on_bar(self, bar: Bar) -> list[Signal]: ...


class SmaBreakoutStrategy:
    """Simple SMA breakout — for testing, not claimed edge.

    Long if close > SMA(n), short if close < SMA(n). Used to exercise pipeline.
    """

    def __init__(
        self,
        instrument: Instrument,
        fast: int = 10,
        slow: int = 20,
        strategy_id: str = "sma_breakout",
    ):
        self.instrument = instrument
        self.fast = fast
        self.slow = slow
        self.strategy_id = strategy_id
        self._closes: list[Decimal] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._closes.append(bar.close)
        if len(self._closes) < self.slow + 1:
            return []
        # simple SMA
        fast_sma = sum(self._closes[-self.fast :]) / Decimal(self.fast)
        slow_sma = sum(self._closes[-self.slow :]) / Decimal(self.slow)
        prev_fast = sum(self._closes[-self.fast - 1 : -1]) / Decimal(self.fast)
        prev_slow = sum(self._closes[-self.slow - 1 : -1]) / Decimal(self.slow)
        # crossover
        if prev_fast <= prev_slow and fast_sma > slow_sma:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=0.7,
                    event_time=bar.close_time,
                    hypothesis_id="H-SMA",
                    strategy_id=self.strategy_id,
                    features={"fast": float(fast_sma), "slow": float(slow_sma)},
                )
            ]
        if prev_fast >= prev_slow and fast_sma < slow_sma:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=0.7,
                    event_time=bar.close_time,
                    hypothesis_id="H-SMA",
                    strategy_id=self.strategy_id,
                    features={"fast": float(fast_sma), "slow": float(slow_sma)},
                )
            ]
        return []


def signal_to_intent(signal: Signal, quantity: Decimal = Decimal("0.1")) -> OrderIntent:
    return OrderIntent(
        instrument=signal.instrument,
        side=signal.side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        client_order_id=f"{signal.strategy_id}:{uuid7()}",
        strategy_id=signal.strategy_id,
        signal_id=signal.hypothesis_id,
    )
