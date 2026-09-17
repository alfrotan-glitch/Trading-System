"""Canonical environment / execution-mode authority — ONE resolution model.

Before this module the effective mode was derived independently in several
places (``QTS_ENV`` in the API, ``QTS_MODE``, batch defaults, YAML config,
UI state, wizard), which allowed silent disagreement between what the UI
displayed and what the execution layer enforced.

The single rule now is:

    **The effective mode is computed once, from explicit precedence, and
    every component consumes the same result.**

Resolution precedence (highest wins):

1. Explicit argument (API call / CLI flag — audited at the call site)
2. ``QTS_MODE`` environment variable (exact :class:`ExecutionMode` value)
3. ``QTS_ENV`` environment variable (mapped; unknown values fail closed)
4. Configuration file env selection (``configs/<env>.yaml``)
5. Default: ``DEVELOPMENT`` (fail-safe)

Restart semantics are explicit: the mode is NOT persisted by the app. A
restart re-resolves from the environment — there is no hidden sticky mode.
Transitions between modes require a process restart with a different
explicit selection (no silent mid-session mode change).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

#: Env vars consulted, in precedence order (documented, deterministic).
MODE_ENV_VAR = "QTS_MODE"
ENV_ENV_VAR = "QTS_ENV"
CONFIG_ENV_DEFAULT = "dev"

# QTS_ENV values that predate the canonical modes. Each maps to exactly ONE
# canonical mode. "dev"/"development" deliberately maps to DEVELOPMENT —
# it can never execute anything against a broker.
_ENV_ALIASES: dict[str, str] = {
    "dev": "DEVELOPMENT",
    "development": "DEVELOPMENT",
    "paper": "PAPER",
    "shadow": "SHADOW",
    "demo_forward": "DEMO_FORWARD",
    "demo": "DEMO_FORWARD",
    "demo_execution": "DEMO_EXECUTION",
    "live": "LIVE",
    # Compatibility: "dry_run"/"micro" were historical YAML modes. dry_run is
    # development-grade (no orders can be sent); micro is LIVE-family and is
    # additionally gated elsewhere (QTS_MICRO_ENABLED + risk.approved).
    "dry_run": "DEVELOPMENT",
    "micro": "LIVE",
}


class ExecutionMode(StrEnum):
    """Canonical modes. Each mode carries its execution capability."""

    DEVELOPMENT = "DEVELOPMENT"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    DEMO_FORWARD = "DEMO_FORWARD"  # observation only — physically no orders
    DEMO_EXECUTION = "DEMO_EXECUTION"  # real demo-account orders, gated
    LIVE = "LIVE"  # real money — structurally locked behind the live gate

    @property
    def can_submit_broker_orders(self) -> bool:
        """Whether this mode may reach a real broker order-submission path at all."""
        return self in (ExecutionMode.DEMO_EXECUTION, ExecutionMode.LIVE)

    @property
    def uses_real_broker_data(self) -> bool:
        return self in (
            ExecutionMode.DEMO_FORWARD,
            ExecutionMode.DEMO_EXECUTION,
            ExecutionMode.LIVE,
        )

    @property
    def is_money_at_risk(self) -> bool:
        return self is ExecutionMode.LIVE


class ModeResolutionError(ValueError):
    """An unknown/ambiguous mode selection was supplied — fail closed."""


def resolve_mode(explicit: str | None = None, config_env: str | None = None) -> ExecutionMode:
    """Resolve the canonical effective mode from the documented precedence.

    Raises :class:`ModeResolutionError` (fail closed) on unknown values —
    an unrecognised mode must never silently become DEVELOPMENT.
    """
    candidates: list[tuple[str, str]] = []
    if explicit is not None:
        candidates.append((f"explicit:{explicit}", explicit))
    raw_mode = os.getenv(MODE_ENV_VAR)
    if raw_mode:
        candidates.append((f"{MODE_ENV_VAR}={raw_mode}", raw_mode))
    raw_env = os.getenv(ENV_ENV_VAR)
    if raw_env:
        candidates.append((f"{ENV_ENV_VAR}={raw_env}", raw_env))
    if config_env:
        candidates.append((f"config:{config_env}", config_env))

    for _source, raw in candidates:
        value = str(raw).strip().lower()
        if value in _ENV_ALIASES:
            return ExecutionMode(_ENV_ALIASES[value])
        try:
            return ExecutionMode(value.upper())
        except ValueError:
            continue
    if candidates:
        # An explicit selection existed but matched nothing — never guess.
        raise ModeResolutionError(
            f"unknown mode selection {candidates!r}; valid values: "
            f"{sorted(set(_ENV_ALIASES))} or canonical {sorted(m.value for m in ExecutionMode)}"
        )
    return ExecutionMode.DEVELOPMENT


def effective_mode_report(explicit: str | None = None, config_env: str | None = None) -> dict[str, Any]:
    """Runtime diagnostics: what mode is effective, how it was resolved."""
    try:
        mode = resolve_mode(explicit=explicit, config_env=config_env)
        error: str | None = None
    except ModeResolutionError as e:
        # Fail closed: an unresolvable mode is DEVELOPMENT-grade capability
        # with a loud error surfaced in diagnostics.
        mode = ExecutionMode.DEVELOPMENT
        error = str(e)
    return {
        "effective_mode": mode.value,
        "can_submit_broker_orders": mode.can_submit_broker_orders,
        "uses_real_broker_data": mode.uses_real_broker_data,
        "money_at_risk": mode.is_money_at_risk,
        "mode_source_env": {MODE_ENV_VAR: os.getenv(MODE_ENV_VAR), ENV_ENV_VAR: os.getenv(ENV_ENV_VAR)},
        "resolution_error": error,
        "restart_semantics": "mode is re-resolved from env/args on every process start; never persisted",
        "resolved_at": datetime.now(UTC).isoformat(),
    }
