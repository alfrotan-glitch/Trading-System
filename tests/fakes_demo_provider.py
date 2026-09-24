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
from pathlib import Path
from typing import Any

from qts.execution.demo_autopilot import Signal
from qts.lifecycle.demo_policy import POLICY_CLASS, POLICY_SCHEMA
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


def policy_block(
    *,
    strategy_id: str = STRATEGY_ID,
    params: dict[str, Any] | None = None,
    max_orders_per_day: int = 3,
    allowed_symbols: list[str] | None = None,
    max_hold_seconds: float = 3600.0,
    **overrides: Any,
) -> dict[str, Any]:
    """A complete, valid research/execution policy for the fixture entries.

    Tests must register fully specified experiments too — the registry refuses
    an entry whose policy is missing or partial, so "registered" always means
    "specified before the first order".
    """
    body = dict(params or PARAMS)
    block: dict[str, Any] = {
        "schema": POLICY_SCHEMA,
        "policy_id": f"{strategy_id}-POLICY",
        "strategy_id": strategy_id,
        "policy_class": POLICY_CLASS,
        "version": "1.0.0",
        "created_at": "2026-09-24T00:00:00+00:00",
        "purpose": "TEST FIXTURE — exercises the DEMO order path end to end; not a hypothesis",
        "hypothesis_id": "H-TEST-001",
        # Honesty field: a fixture must not pretend to be a validated edge.
        "validated_edge": False,
        "edge_statement": (
            "TEST FIXTURE. Performance observed under this policy does not establish a validated edge: "
            "it measures the execution path, not a hypothesis."
        ),
        "signal_logic": {
            "type": "test_fixture_mechanical",
            "description": "emit max_signals identical BUY probes with a fixed stop and target",
            "indicators": [],
        },
        "entry_conditions": {
            "max_signals_per_run": body.get("max_signals", 1),
            "require_two_sided_quote": True,
        },
        "exit_conditions": {
            "max_hold_seconds": max_hold_seconds,
            "take_profit_points": body.get("target_points", 10.0),
        },
        "stop_loss_logic": {
            "required": True,
            "type": "fixed_points",
            "distance_price": float(body.get("stop_points", 5.0)),
        },
        "position_sizing": {"mode": "fixed", "lots": float(body.get("lots", 0.01))},
        "max_simultaneous_exposure_lots": 0.05,
        "max_daily_loss": 25.0,
        "max_drawdown": 50.0,
        "max_orders_per_day": max_orders_per_day,
        "min_order_interval_s": 0,
        "allowed_symbols": allowed_symbols if allowed_symbols is not None else ["XAUUSD"],
        "allowed_trading_hours": {
            "timezone": "UTC",
            "sessions": [
                {
                    "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                    "start": "00:00",
                    "end": "23:59",
                }
            ],
            "note": "fixture: all hours, so tests are not time-of-day dependent",
        },
        "max_spread_bps": 30.0,
        "max_slippage_bps": 20.0,
        "execution_delay_assumption_ms": 1500.0,
        "min_data_requirements": {
            "requires_historical_dataset": False,
            "required_checks": [
                "market_data_fresh",
                "spread_available",
                "broker_order_check",
                "symbol_mapping_canonical",
            ],
        },
        "stale_data_protection": {"max_tick_age_s": 60.0, "on_stale": "NO_TRADE"},
        "duplicate_order_protection": {"idempotency_required": True, "min_order_interval_s": 0},
        "kill_conditions": [
            "daily_loss_limit",
            "max_drawdown",
            "reconciliation_suspension",
            "parameter_drift",
            "code_drift",
            "identity_mismatch",
        ],
        "reconciliation_requirements": {
            "after_every_order": True,
            "max_age_s": 300.0,
            "on_drift": "HALT",
        },
        # The sha256 of THIS file: the policy pins the code it registered.
        "code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "config_hash": params_fingerprint(body),
        "data_hash": None,
        "data_hash_note": "fixture uses live venue quotes only; no historical dataset to pin",
    }
    block.update(overrides)
    return block


def registry_entry(
    *,
    provider: str = "fakes_demo_provider:FakeSignalProvider",
    params: dict[str, Any] | None = None,
    strategy_id: str = STRATEGY_ID,
    status: str = "ELIGIBLE",
    max_orders_per_day: int = 3,
    max_hold_seconds: float | None = None,
    allowed_symbols: list[str] | None = None,
    policy: dict[str, Any] | None = None,
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
        "policy": policy
        if policy is not None
        else policy_block(
            strategy_id=strategy_id,
            params=body,
            max_orders_per_day=max_orders_per_day,
            allowed_symbols=allowed_symbols,
            max_hold_seconds=3600.0 if max_hold_seconds is None else max_hold_seconds,
        ),
    }
    return entry


__all__ = [
    "PARAMS",
    "STRATEGY_ID",
    "policy_block",
    "DriftingSignalProvider",
    "FakeSignalProvider",
    "NoSignalProvider",
    "SelfOptimizingProvider",
    "registry_entry",
]
