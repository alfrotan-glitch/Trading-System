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
3. Persisted machine-local declaration
4. ``QTS_ENV`` environment variable (mapped; unknown values fail closed)
5. Configuration file env selection (``configs/<env>.yaml``)
6. Default: ``DEVELOPMENT`` (fail-safe)

The operator may persist a machine-local non-LIVE declaration. A restart
re-resolves the mode from the ordered sources above; there is no silent
mid-session mode change. LIVE cannot be selected by a persisted declaration.
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
    DEMO_EXECUTION = "DEMO_EXECUTION"  # capability label; product policy disables it
    LIVE = "LIVE"  # real money — structurally locked behind the live gate

    @property
    def can_submit_broker_orders(self) -> bool:
        """Whether the mode has a broker-capable boundary in the capability model.

        Capability is not permission. DEMO_EXECUTION is the only broker-capable
        mode permitted by the shipped demo authority; LIVE remains separately
        and structurally locked behind the live gate.
        """
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


def persisted_mode_declaration() -> tuple[str | None, str | None]:
    """The operator's persisted mode declaration, and where it came from.

    ``QTS_MODE`` is a *per-process* environment variable: the desktop backend
    (launched by double-click, in a thread of the launcher process) does not
    inherit whatever an operator exported in one shell. That is exactly how the
    UI came to report ``DEVELOPMENT / DEMO DISABLED BY POLICY`` while the CLI in
    the operator's shell reported ``DEMO_EXECUTION / AUTHORIZED`` — two honest
    answers about two different processes, and no way for the operator to see
    the difference.

    The machine-local setup file therefore carries an optional ``mode``
    declaration that BOTH surfaces read, below the environment in precedence.
    Two hard limits keep this from becoming a permission grant:

    * it can never select a real-capital mode — ``LIVE`` (or any alias of it)
      in the file is refused and falls through to lower-priority declarations
      or ``DEVELOPMENT``;
    * only the allowlisted non-LIVE modes can be written through the setup
      API/UI or ``qts mode declare``; selecting a mode is not an execution
      permission grant, and every resolution reports its provenance.
    """
    try:
        from qts.config.wizard import load_setup, setup_file

        declared = load_setup().get("mode")
    except Exception:  # noqa: BLE001 - an unreadable declaration is no declaration
        return None, None
    if isinstance(declared, str) and declared.strip():
        return declared.strip(), f"mode declaration in {setup_file()}"
    return None, None


def _coerce_mode(raw: str) -> ExecutionMode | None:
    value = str(raw).strip().lower()
    if value in _ENV_ALIASES:
        return ExecutionMode(_ENV_ALIASES[value])
    try:
        return ExecutionMode(value.upper())
    except ValueError:
        return None


def _mode_candidates(explicit: str | None = None, config_env: str | None = None) -> list[tuple[str, str]]:
    """Return mode declarations in the one canonical resolution order."""
    candidates: list[tuple[str, str]] = []
    if explicit is not None:
        candidates.append((f"explicit:{explicit}", explicit))
    raw_mode = os.getenv(MODE_ENV_VAR)
    if raw_mode:
        candidates.append((f"{MODE_ENV_VAR}={raw_mode}", raw_mode))
    declared, declared_source = persisted_mode_declaration()
    if declared:
        candidates.append((declared_source or "persisted declaration", declared))
    raw_env = os.getenv(ENV_ENV_VAR)
    if raw_env:
        candidates.append((f"{ENV_ENV_VAR}={raw_env}", raw_env))
    if config_env:
        candidates.append((f"config:{config_env}", config_env))
    return candidates


def _is_allowed_live_source(source: str) -> bool:
    """Whether a LIVE declaration came from an explicitly authorized source."""
    return source.startswith(("explicit:", MODE_ENV_VAR, ENV_ENV_VAR))


def _unknown_mode_error(source: str, raw: str) -> ModeResolutionError:
    return ModeResolutionError(
        f"unknown mode selection {source}={raw!r}; valid values: "
        f"{sorted(set(_ENV_ALIASES))} or canonical {sorted(m.value for m in ExecutionMode)}"
    )


def resolve_mode(explicit: str | None = None, config_env: str | None = None) -> ExecutionMode:
    """Resolve the canonical effective mode from the documented precedence.

    explicit > ``QTS_MODE`` > persisted declaration > ``QTS_ENV`` >
    ``config_env`` > ``DEVELOPMENT``.

    Raises :class:`ModeResolutionError` (fail closed) on unknown values —
    an unrecognised mode must never silently become DEVELOPMENT.
    """
    refused: list[str] = []
    for source, raw in _mode_candidates(explicit=explicit, config_env=config_env):
        mode = _coerce_mode(raw)
        if mode is None:
            # Never let a lower-priority valid declaration mask a typo in a
            # higher-priority selection (especially an explicit API/CLI mode).
            if refused:
                _record_refused_declarations(refused)
            raise _unknown_mode_error(source, raw)
        if mode.is_money_at_risk and not _is_allowed_live_source(source):
            # A real-capital mode may never be selected from a persisted file or
            # a config default: LIVE stays locked behind its own gate.
            refused.append(f"{source}={raw} (real-capital modes cannot be declared there)")
            continue
        if refused:
            _record_refused_declarations(refused)
        return mode
    if refused:
        _record_refused_declarations(refused)
    return ExecutionMode.DEVELOPMENT


_REFUSED_DECLARATIONS: list[str] = []


def _record_refused_declarations(refused: list[str]) -> None:
    """Keep refused real-capital declarations visible in diagnostics."""
    for item in refused:
        if item not in _REFUSED_DECLARATIONS:
            _REFUSED_DECLARATIONS.append(item)


def refused_mode_declarations() -> list[str]:
    """Real-capital mode declarations that were refused (audit/diagnostics)."""
    return list(_REFUSED_DECLARATIONS)


def mode_source(explicit: str | None = None, config_env: str | None = None) -> str:
    """Which source decided the effective mode — provenance for both surfaces.

    The UI and the CLI must be able to show *why* they report the mode they do,
    otherwise "DEVELOPMENT here, DEMO_EXECUTION there" is indistinguishable from
    a backend that has quietly diverged.
    """
    for source, raw in _mode_candidates(explicit=explicit, config_env=config_env):
        mode = _coerce_mode(raw)
        if mode is None:
            # Keep diagnostics aligned with resolve_mode(): an invalid higher
            # priority declaration must not be hidden by a lower one.
            return f"{source} (invalid selection)"
        if mode.is_money_at_risk and not _is_allowed_live_source(source):
            continue
        if source.startswith("mode declaration in "):
            return f"{source}: mode={raw}"
        return source
    return "no mode declared — DEVELOPMENT (least capable, fail closed)"


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
        "mode_source": mode_source(explicit=explicit, config_env=config_env),
        "persisted_mode_declaration": (persisted_mode_declaration()[0]),
        "refused_real_capital_declarations": refused_mode_declarations(),
        "resolution_error": error,
        "restart_semantics": (
            "mode is re-resolved on every process start from explicit args, "
            "QTS_MODE, the persisted machine-local declaration, then QTS_ENV; "
            "a real-capital mode can never come from the persisted declaration"
        ),
        "resolved_at": datetime.now(UTC).isoformat(),
    }
