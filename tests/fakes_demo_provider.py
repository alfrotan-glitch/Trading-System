"""Deterministic, frozen signal providers for the DEMO forward-validation tests.

These exist so the autonomous DEMO loop can be exercised end-to-end without a
terminal and without inventing a strategy: the provider below is deliberately
**not** a trading idea. It emits a fixed number of minimum-size BUY signals with
a mechanical stop and target purely so the plumbing (signal → gate → order →
fill → manage → close → journal) can be observed and asserted.

Registry rules the fakes obey (see ``qts.lifecycle.demo_registry``):

* parameters are frozen — ``config_hash()`` is the sha256 of ``PARAMS``, the
  same fingerprint the registry stores, so any edit is ``PARAMETER_DRIFT``;
* no optimization hook — ``SelfOptimizingProvider`` exposes one on purpose and
  must therefore be *refused* by the autopilot.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from qts.execution.demo_autopilot import Signal
from qts.lifecycle.demo_registry import params_fingerprint

STRATEGY_ID = "TEST-PREREG-01"

#: The registered (frozen) parameter set. Editing this breaks the registry hash.
PARAMS: dict[str, Any] = {
    "description": "test fixture — mechanical signal, not a trading hypothesis",
    "lots": 0.01,
    "stop_points": 5.0,
    "target_points": 10.0,
    "max_signals": 1,
}


def _signal(side: str, lots: Decimal, stop_loss: Decimal, take_profit: Decimal, rationale: str, n: int) -> Signal:
    return Signal(
        side=side,
        lots=lots,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rationale=rationale,
        signal_id=f"fake-signal-{n}",
    )


class FakeSignalProvider:
    """Emits ``max_signals`` BUYs with a fixed stop/target, then stays flat."""

    strategy_id = STRATEGY_ID

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = dict(params or PARAMS)
        self.emitted = 0

    def config_hash(self) -> str:
        return params_fingerprint(self.params)

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        max_signals = int(self.params.get("max_signals", 1))
        if self.emitted >= max_signals:
            return None
        self.emitted += 1
        bid = Decimal(str(market_state.get("bid") or "0"))
        ask = Decimal(str(market_state.get("ask") or "0"))
        stop_points = Decimal(str(self.params.get("stop_points", 5.0)))
        target_points = Decimal(str(self.params.get("target_points", 10.0)))
        lots = Decimal(str(self.params.get("lots", 0.01)))
        return _signal(
            side="BUY",
            lots=lots,
            stop_loss=(bid - stop_points).quantize(Decimal("0.01")),
            take_profit=(ask + target_points).quantize(Decimal("0.01")),
            rationale="test fixture: fixed mechanical entry with protective stop",
            n=self.emitted,
        )


class NoSignalProvider(FakeSignalProvider):
    """Registered and eligible, but declines to trade — the system stays flat."""

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        return None


class DriftingSignalProvider(FakeSignalProvider):
    """Provider whose runtime parameters no longer match the registration."""

    def config_hash(self) -> str:
        return hashlib.sha256(b"someone-edited-the-parameters-after-registration").hexdigest()


class SelfOptimizingProvider(FakeSignalProvider):
    """Provider exposing a re-fit hook — must be refused (research integrity)."""

    def optimize(self, observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:  # pragma: no cover - refused
        return {"status": "would-re-fit-on-forward-demo-results"}


def registry_entry(
    *,
    provider: str = "fakes_demo_provider:FakeSignalProvider",
    params: dict[str, Any] | None = None,
    strategy_id: str = STRATEGY_ID,
    status: str = "ELIGIBLE",
    max_orders_per_day: int = 3,
    max_hold_seconds: float | None = None,
    allowed_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Build a registry entry dict whose ``params_hash`` matches ``params``."""
    body = dict(params or PARAMS)
    entry: dict[str, Any] = {
        "strategy_id": strategy_id,
        "status": status,
        "hypothesis_id": "H-TEST-001",
        "preregistration_artifact": "docs/demo_execution_authorization_and_safety_2026-09-23.md#test-fixture",
        "signal_provider": provider,
        "params": body,
        "params_hash": params_fingerprint(body),
        "size_policy": {"mode": "fixed_lots", "lots": body.get("lots", 0.01)},
        "stop_policy": {"required": True, "type": "fixed_points", "points": body.get("stop_points", 5.0)},
        "exit_policy": {"max_hold_seconds": 3600.0 if max_hold_seconds is None else max_hold_seconds},
        "allowed_symbols": allowed_symbols if allowed_symbols is not None else ["XAUUSD"],
        "max_orders_per_day": max_orders_per_day,
        "notes": "TEST FIXTURE — mechanical provider used to exercise the DEMO loop, not a hypothesis",
    }
    return entry


__all__ = [
    "PARAMS",
    "STRATEGY_ID",
    "DriftingSignalProvider",
    "FakeSignalProvider",
    "NoSignalProvider",
    "SelfOptimizingProvider",
    "registry_entry",
]
