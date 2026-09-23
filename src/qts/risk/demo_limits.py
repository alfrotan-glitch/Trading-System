"""DEMO_FORWARD safety metadata — derived from the unified Risk Authority.

DEMO_EXECUTION remains a historical compatibility label but is disabled by
product policy. Every displayed limit is resolved by
:data:`qts.risk.authority.resolve_risk_limits`; these values describe a safety
boundary and never represent broker account state or authorize orders.
"""

from __future__ import annotations

from qts.domain.modes import ExecutionMode
from qts.risk.authority import demo_forward_limits_from, resolve_risk_limits

_DEMO_SNAPSHOT = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
_L = _DEMO_SNAPSHOT.limits


class DemoForwardLimits:
    """View over the authoritative DEMO risk resolution (read-only).

    Attribute names preserved for existing consumers (readiness gate, docs,
    UI). Values come from the ONE canonical risk authority — never edited
    locally.
    """

    mode: str = ExecutionMode.DEMO_EXECUTION.value

    def __init__(self) -> None:
        d = demo_forward_limits_from(_DEMO_SNAPSHOT)
        # Order / position
        self.max_volume_per_order: float = d["max_volume_per_order"]
        self.max_simultaneous_exposure: float = d["max_simultaneous_exposure"]
        self.max_open_orders: int = d["max_open_orders"]
        self.max_orders_per_minute: int = d["max_orders_per_minute"]
        # Risk
        self.max_daily_loss_usd: float = d["max_daily_loss_usd"]
        self.max_drawdown_usd: float = d["max_drawdown_usd"]
        self.max_drawdown_pct: float = d["max_drawdown_pct"]
        # Market
        self.max_spread_bps: float = d["max_spread_bps"]
        self.max_slippage_bps: float = d["max_slippage_bps"]
        # Kill switch always armed for demo execution
        self.kill_switch_enabled: bool = d["kill_switch_enabled"]
        # Provenance
        self.config_hash: str = d["config_hash"]
        # Env boundary
        self.allowed_envs: list[str] = ["demo_forward", "demo", "paper"]
        self.label: str = "DEMO"  # every result labeled DEMO, never LIVE

    def model_dump(self) -> dict:  # duck-typed for the old pydantic usage
        return {
            "max_volume_per_order": self.max_volume_per_order,
            "max_simultaneous_exposure": self.max_simultaneous_exposure,
            "max_open_orders": self.max_open_orders,
            "max_orders_per_minute": self.max_orders_per_minute,
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "max_drawdown_usd": self.max_drawdown_usd,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_spread_bps": self.max_spread_bps,
            "max_slippage_bps": self.max_slippage_bps,
            "kill_switch_enabled": self.kill_switch_enabled,
            "label": self.label,
            "config_hash": self.config_hash,
            "authority": "qts.risk.authority.resolve_risk_limits(DEMO_EXECUTION)",
        }


DEMO_FORWARD_DEFAULTS = DemoForwardLimits()

# Explicit boundary table for docs/UI
SAFETY_BOUNDARY = {
    "DEVELOPMENT": "backtest only, no broker, mock data",
    "PAPER": "simulated fills, no broker orders, next-bar-open",
    "SHADOW": "would-be intents, no submission",
    "DEMO_FORWARD": "REAL MT5 terminal + REAL market data + REAL DEMO account + observation ONLY — no order path exists in this mode",
    "DEMO_EXECUTION": "AUTHORIZED for DEMO only (owner authorization artifact, hashed and revocable) — staged arming + pinned broker identity + registered strategy + 22 pre-trade checks per order; never LIVE, never real capital",
    "LIVE": "REAL money, separately gated, requires env=live + --confirm live + risk.approved + validation.passed + reconciliation + human approval — LOCKED unless all pass",
}


def assert_demo_limits(volume: float, exposure: float, spread_bps: float, slippage_bps: float) -> tuple[bool, str]:
    lim = DEMO_FORWARD_DEFAULTS
    if volume > lim.max_volume_per_order:
        return False, f"volume {volume} > demo limit {lim.max_volume_per_order}"
    if exposure > lim.max_simultaneous_exposure:
        return False, f"exposure {exposure} > demo limit {lim.max_simultaneous_exposure}"
    if spread_bps > lim.max_spread_bps:
        return False, f"spread {spread_bps}bps > demo limit {lim.max_spread_bps}bps"
    if slippage_bps > lim.max_slippage_bps:
        return False, f"slippage {slippage_bps}bps > demo limit {lim.max_slippage_bps}bps"
    return True, "within demo limits"


def env_boundary_check(current_env: str, requested_mode: str) -> tuple[bool, str]:
    """No environment can silently become another."""
    from qts.domain.modes import resolve_mode

    try:
        current = resolve_mode(current_env)
    except Exception:
        return False, f"unknown current env {current_env!r} — fail closed"
    try:
        requested = resolve_mode(requested_mode)
    except Exception:
        return False, f"unknown requested mode {requested_mode!r} — fail closed"
    if requested is ExecutionMode.LIVE and current is not ExecutionMode.LIVE:
        return False, f"live mode requires env=live, got env={current_env}"
    if requested is ExecutionMode.DEMO_EXECUTION and current not in (
        ExecutionMode.DEMO_EXECUTION,
        ExecutionMode.DEMO_FORWARD,
        ExecutionMode.PAPER,
    ):
        return False, f"demo_execution requires a demo-family env, got {current_env}"
    if requested is ExecutionMode.DEMO_FORWARD and current not in (
        ExecutionMode.DEMO_FORWARD,
        ExecutionMode.DEMO_EXECUTION,
        ExecutionMode.PAPER,
    ):
        return False, f"demo_forward requires a demo-family env, got {current_env}"
    return True, "env boundary ok"
