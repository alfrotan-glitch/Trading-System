"""Publicly documented trend-following benchmark for DEMO forward observation.

This is deliberately a simple, frozen implementation inspired by publicly
documented managed-futures/time-series-momentum practice (fast/slow trend
response, small fixed risk, protective stop). It is NOT represented as a
validated edge and must remain a DEMO research policy until independent
validation passes.

No proprietary code or private fund parameters are copied.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from qts.execution.demo_autopilot import Signal

STRATEGY_ID = "DEMO-XAUUSD-TREND-TSMOM-V1"

DEFAULT_PARAMS: dict[str, Any] = {
    "fast_ema": 12,
    "slow_ema": 48,
    "min_cross_gap_bps": 0.0,
    "stop_distance_price": 3.0,
    "max_hold_seconds": 14400,
    "max_tick_age_s": 5.0,
    "lots": 0.01,
    "require_spread_within_policy": True,
    "comment": "RESEARCH_DEMO_ORDER trend benchmark",
}


def _hash(params: dict[str, Any]) -> str:
    from qts.lifecycle.demo_registry import params_fingerprint
    return params_fingerprint(params)


class TrendTimeSeriesMomentum:
    """Frozen EMA crossover benchmark with deterministic DEMO risk controls."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = dict(DEFAULT_PARAMS if params is None else params)
        self._prices: deque[Decimal] = deque(maxlen=int(self.params["slow_ema"]) + 2)
        self._last_fast: Decimal | None = None
        self._last_slow: Decimal | None = None
        self._last_signal_bucket: str | None = None
        self._last_rationale = "waiting for enough price history"

    @property
    def strategy_id(self) -> str:
        return STRATEGY_ID

    def config_hash(self) -> str:
        return _hash(self.params)

    def last_rationale(self) -> str:
        return self._last_rationale

    @staticmethod
    def _ema(values: list[Decimal], period: int) -> Decimal:
        alpha = Decimal("2") / Decimal(period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = alpha * value + (Decimal("1") - alpha) * ema
        return ema

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        bid = market_state.get("bid")
        ask = market_state.get("ask")
        if bid is None or ask is None:
            self._last_rationale = "no two-sided quote"
            return None
        age = market_state.get("age_s")
        if age is None or float(age) > float(self.params["max_tick_age_s"]):
            self._last_rationale = f"quote is stale: age={age}s"
            return None

        spread = market_state.get("spread_bps")
        if self.params["require_spread_within_policy"] and spread is None:
            self._last_rationale = "spread unavailable"
            return None

        mid = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")
        self._prices.append(mid)
        slow_n = int(self.params["slow_ema"])
        fast_n = int(self.params["fast_ema"])
        if len(self._prices) < slow_n + 1:
            self._last_rationale = f"warming up: {len(self._prices)}/{slow_n + 1} quotes"
            return None

        values = list(self._prices)
        fast = self._ema(values[-fast_n:], fast_n)
        slow = self._ema(values[-slow_n:], slow_n)
        prev_values = values[:-1]
        prev_fast = self._ema(prev_values[-fast_n:], fast_n)
        prev_slow = self._ema(prev_values[-slow_n:], slow_n)

        side: str | None = None
        if prev_fast <= prev_slow and fast > slow:
            side = "BUY"
        elif prev_fast >= prev_slow and fast < slow:
            side = "SELL"

        self._last_fast, self._last_slow = fast, slow
        if side is None:
            self._last_rationale = f"no crossover: fast={fast:.5f}, slow={slow:.5f}"
            return None

        bucket = f"{market_state.get('event_time') or market_state.get('at')}:{side}"
        if bucket == self._last_signal_bucket:
            return None
        self._last_signal_bucket = bucket

        reference = Decimal(str(ask if side == "BUY" else bid))
        distance = Decimal(str(self.params["stop_distance_price"]))
        stop = reference - distance if side == "BUY" else reference + distance
        lots = Decimal(str(self.params["lots"]))
        self._last_rationale = (
            f"public trend-following benchmark crossover: {side}; "
            f"EMA{fast_n} crossed EMA{slow_n}; fixed DEMO size={lots}; "
            f"protective stop distance={distance}; no validated-edge claim"
        )
        return Signal(
            side=side,
            lots=lots,
            stop_loss=stop,
            take_profit=None,
            rationale=self._last_rationale,
            signal_id=f"tsmom-{side.lower()}-{market_state.get('event_time') or market_state.get('at')}",
        )
