"""DEMO_FORWARD safety boundary — independent conservative hard limits, never live capital assumptions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DemoForwardLimits(BaseModel):
    """Explicit safety boundary for DEMO_FORWARD. No env can silently become another."""

    # Order / position
    max_volume_per_order: float = 0.1  # lots, conservative (vs live 0.2)
    max_simultaneous_exposure: float = 0.3  # lots total
    max_open_orders: int = 3
    max_orders_per_minute: int = 4  # frequency
    # Risk
    max_daily_loss_usd: float = 50.0
    max_drawdown_usd: float = 100.0
    max_drawdown_pct: float = 5.0
    # Market
    max_spread_bps: float = 30.0  # 3.0 pips for XAUUSD
    max_slippage_bps: float = 20.0
    # Kill switch always armed
    kill_switch_enabled: bool = True

    # Env boundary
    allowed_envs: list[str] = Field(default_factory=lambda: ["demo_forward", "demo", "paper"])
    label: str = "DEMO"  # every result labeled DEMO, never LIVE
    # LIVE remains separately gated — this file never grants LIVE
    live_requires: list[str] = Field(
        default_factory=lambda: [
            "env=live",
            "--confirm live",
            "risk.approved",
            "validation.passed",
            "reconciliation.healthy",
            "human_approval",
        ]
    )


DEMO_FORWARD_DEFAULTS = DemoForwardLimits()

# Explicit boundary table for docs/UI
SAFETY_BOUNDARY = {
    "DEVELOPMENT": "backtest only, no broker, mock data",
    "PAPER": "simulated fills, no broker orders, next-bar-open",
    "SHADOW": "would-be intents, no submission",
    "DEMO_FORWARD": "REAL MT5 terminal + REAL market data + REAL DEMO account + REAL demo order lifecycle — labeled DEMO, independent conservative limits, kill switch, never LIVE",
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
    if requested_mode == "live" and current_env != "live":
        return False, f"live mode requires env=live, got env={current_env}"
    if requested_mode == "demo_forward" and current_env not in ("demo_forward", "demo", "paper"):
        return False, f"demo_forward requires env=demo_forward, got {current_env}"
    return True, "env boundary ok"
