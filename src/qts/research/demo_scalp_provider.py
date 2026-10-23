"""One-minute, regime-aware DEMO scalp signal provider (unregistered by default).

Reuses the existing completed-bar clock, warmup, frozen parameter hash and
protected broker entry path. It is NOT a validated profitable strategy.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from qts.adapters.base import MEASURED_SERVER_OFFSET_BASES
from qts.execution.demo_autopilot import Signal
from qts.research.demo_trend_tsmom import TrendTimeSeriesMomentum
from qts.research.scalp_regimes import (
    ScalpIdea,
    early_entry_still_has_room,
    propose_anticipatory_entry,
    propose_scalp_entry,
)

STRATEGY_ID = "DEMO-XAUUSD-REGIME-SCALP-V1"

DEFAULT_PARAMS: dict[str, Any] = {
    "fast_ema": 4,
    "slow_ema": 48,
    "bar_timeframe_minutes": 1,
    "stop_distance_price": 3.0,
    "max_hold_seconds": 900,
    "max_tick_age_s": 2.0,
    "lots": 0.01,
    "require_spread_within_policy": True,
    "max_spread_bps": 3.0,
    "extra_cost_reserve_bps": 2.0,
    "min_price_movement_after_cost_bps": 1.0,
    "comment": "RESEARCH_DEMO_ORDER regime scalper",
}


class RegimeScalpProvider(TrendTimeSeriesMomentum):
    """Produces executable-side demo *candidates* after completed minute bars."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(DEFAULT_PARAMS if params is None else params)
        self._pending: ScalpIdea | None = None
        for key in ("max_spread_bps", "extra_cost_reserve_bps", "min_price_movement_after_cost_bps"):
            value = Decimal(str(self.params[key]))
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{key} must be finite and positive")
        if self._timeframe_minutes != 1 or self._slow_n < 34:
            raise ValueError("regime scalper needs 1-minute bars and >=34-bar causal history")

    @property
    def strategy_id(self) -> str:
        return STRATEGY_ID

    @property
    def requires_registered_scalp_exit(self) -> bool:
        return True

    def seed_completed_bars(
        self,
        bars: Iterable[tuple[datetime, Decimal | str]],
        *,
        source: str = "unstated",
    ) -> dict[str, Any]:
        supplied = list(bars)
        try:
            times = [self._coerce_boundary(item[0]) for item in supplied]
        except (TypeError, IndexError, KeyError):
            return {"accepted": False, "bars": 0, "reason": "malformed completed-minute history"}
        for left, right in zip(times, times[1:], strict=False):
            if left is not None and right is not None and right - left != timedelta(minutes=1):
                return {"accepted": False, "bars": 0, "reason": "noncontiguous completed-minute history"}
        return super().seed_completed_bars(supplied, source=source)

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        """Refuse unmeasured broker clocks before the minute-bar engine runs."""
        if market_state.get("timestamp_basis") not in MEASURED_SERVER_OFFSET_BASES:
            self._last_rationale = "unmeasured broker clock basis — no scalp signal"
            return None
        return super().generate(market_state)

    def _propose_candidate(self, closes: list[Decimal]) -> ScalpIdea | None:
        """Virtual signal selector; baseline provider remains unchanged."""
        return propose_scalp_entry(closes)

    def _complete_previous_bar(self, boundary: datetime, close: Decimal) -> str | None:
        """Never bridge a missing minute or an old seeded window."""
        expected_gap = timedelta(minutes=1)
        previous = self._last_completed_bar
        if self._bar_start is None or (
            previous is not None and self._bar_start - previous != expected_gap
        ) or boundary - self._bar_start != expected_gap:
            self._closes.clear()
            self._pending = None
            self._last_rationale = "minute gap: history reset without fabrication"
        self._closes.append(close)
        self._last_completed_bar = self._bar_start
        self._pending = self._propose_candidate(list(self._closes))
        if self._pending is None:
            self._last_rationale = "no causal trend-pullback, range-fade, or breakout opportunity"
            return None
        return self._pending.side

    def _signal(
        self,
        *,
        side: str,
        boundary: datetime,
        bid: Decimal,
        ask: Decimal,
        basis: str | None,
    ) -> Signal | None:
        idea = self._pending
        if idea is None or idea.side != side or self._last_signal_bar == boundary:
            return None
        mid = (bid + ask) / 2
        if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask <= bid:
            self._last_rationale = "invalid executable quote"
            return None
        if not early_entry_still_has_room(
            idea,
            bid=bid, ask=ask,
            reserve_bps=Decimal(str(self.params["extra_cost_reserve_bps"])),
            margin_bps=Decimal(str(self.params["min_price_movement_after_cost_bps"])),
        ):
            self._last_rationale = "early setup is no longer executable before the causal range boundary"
            return None
        spread_bps = (ask - bid) / mid * Decimal("10000")
        proxy_bps = idea.movement_proxy_price / mid * Decimal("10000")
        max_spread = Decimal(str(self.params["max_spread_bps"]))
        required = (
            spread_bps
            + Decimal(str(self.params["extra_cost_reserve_bps"]))
            + Decimal(str(self.params["min_price_movement_after_cost_bps"]))
        )
        if spread_bps > max_spread or proxy_bps <= required:
            self._last_rationale = (
                f"cost/volatility gate: spread={spread_bps:.3f} bps, "
                f"historical movement proxy={proxy_bps:.3f} bps, minimum={required:.3f} bps"
            )
            return None
        self._last_signal_bar = boundary
        reference = ask if side == "BUY" else bid
        stop_distance = Decimal(str(self.params["stop_distance_price"]))
        stop = reference - stop_distance if side == "BUY" else reference + stop_distance
        if stop <= 0:
            raise ValueError("registered protective stop crosses zero")
        self._signals += 1
        self._last_rationale = (
            f"Unvalidated DEMO scalp candidate: {idea.family}/{idea.regime}; "
            f"completed 1m boundary {boundary.isoformat()}; spread {spread_bps:.3f} bps; "
            f"past movement proxy {proxy_bps:.3f} bps is NOT expected profit; "
            "protective stop and registered close policy mandatory"
        )
        stamp = boundary.strftime("%Y%m%dT%H%M%SZ")
        return Signal(
            side=side,
            lots=Decimal(str(self.params["lots"])),
            stop_loss=stop,
            take_profit=None,
            rationale=self._last_rationale,
            signal_id=f"regime-scalp-{idea.family}-{side.lower()}-{stamp}",
        )


class AnticipatoryScalpProvider(RegimeScalpProvider):
    """Separate *unregistered* pre-confirmation DEMO research candidate.

    Distinct strategy identity prevents silently changing the previously
    frozen confirmation-only strategy's semantics.
    """

    @property
    def strategy_id(self) -> str:
        return "DEMO-XAUUSD-PREBREAKOUT-SCALP-V1"

    def _propose_candidate(self, closes: list[Decimal]) -> ScalpIdea | None:
        return propose_anticipatory_entry(closes)
