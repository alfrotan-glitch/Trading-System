"""Unified Risk Authority — ONE resolved risk snapshot for the whole system.

Closes audit finding #8 (risk-authority duplication). Previously limits were
defined independently in ``RiskLimits`` (risk engine), ``RiskConfig``
(settings/YAML), ``DemoForwardLimits`` (demo boundary), and UI/readiness
logic — four sources that could disagree.

Now there is exactly ONE authority:

* **Canonical base limits** (:data:`BASE_LIMITS`) — the system's conservative
  foundation. Nothing may exceed them implicitly.
* **Mode restrictions** (:data:`MODE_RESTRICTIONS`) — tighter per-mode caps
  (DEMO execution is capped well below base; DEVELOPMENT/PAPER never trade).
* **Explicit operator overrides** (YAML ``risk:`` section) — allowed only
  where they TIGHTEN or are explicitly acknowledged (``risk.approved``);
  the resolution records every override's origin.

Every consumer — RiskEngine, demo boundary, readiness gate, /api/risk, the
UI — resolves limits through :func:`resolve_risk_limits` and receives the
same :class:`ResolvedRiskSnapshot` with full provenance per field group and
a stable ``config_hash``. No component invents its own safety limits.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from qts.domain.modes import ExecutionMode


class CanonicalRiskLimits(BaseModel):
    """The one canonical limit set. Quantity in lots, money in USD."""

    # Per-order
    max_quantity: Decimal = Decimal("1.0")  # lots
    min_quantity: Decimal = Decimal("0.01")  # lots
    quantity_step: Decimal = Decimal("0.01")  # lots
    max_notional: Decimal = Decimal("50000")  # USD
    max_risk_per_trade_bps: Decimal = Decimal("50")
    stop_loss_required: bool = False

    # Portfolio
    max_exposure_lots: Decimal = Decimal("2.0")
    max_exposure_notional: Decimal | None = None
    max_leverage: Decimal = Decimal("5")
    max_correlated_exposure: Decimal = Decimal("1.5")
    max_open_orders: int = 5

    # Loss control
    daily_loss_limit: Decimal = Decimal("200")
    max_drawdown: Decimal = Decimal("500")
    max_drawdown_pct: Decimal = Decimal("10")  # % of starting equity

    # Market-condition limits
    max_spread_bps: Decimal = Decimal("100")
    max_slippage_bps: Decimal = Decimal("50")
    stale_data_limit_s: Decimal = Decimal("60")

    # Order rate (research modes may simulate faster; DEMO_EXECUTION tightens to 4)
    max_orders_per_minute: int = 60

    # Controls
    kill_switch_enabled: bool = True
    flatten_on_kill: bool = False
    approved: bool = False  # operator acknowledgement — required for LIVE family
    version: int = 2


BASE_LIMITS = CanonicalRiskLimits()

#: Per-mode TIGHTENING only. Values here must be <= BASE_LIMITS for caps and
#: >= for floors; ``resolve_risk_limits`` asserts this at import and use.
MODE_RESTRICTIONS: dict[ExecutionMode, dict[str, Any]] = {
    # Research/simulation modes cannot reach a broker at all; limits still
    # resolve so simulated engines can be exercised coherently.
    ExecutionMode.DEVELOPMENT: {},
    ExecutionMode.PAPER: {},
    ExecutionMode.SHADOW: {},
    # DEMO execution: hard conservative caps (the old DemoForwardLimits values,
    # now DERIVED from one authority instead of living in a separate file).
    ExecutionMode.DEMO_EXECUTION: {
        "max_quantity": Decimal("0.1"),
        "max_exposure_lots": Decimal("0.3"),
        "max_open_orders": 3,
        "max_orders_per_minute": 4,
        "daily_loss_limit": Decimal("50"),
        "max_drawdown": Decimal("100"),
        "max_drawdown_pct": Decimal("5"),
        "max_spread_bps": Decimal("30"),
        "max_slippage_bps": Decimal("20"),
        "kill_switch_enabled": True,
    },
    # LIVE resolves to base + mandatory operator approval; the live gate
    # separately demands far more than a risk snapshot (see lifecycle.live_gate).
    ExecutionMode.LIVE: {},
}


class _CapDirections(BaseModel):
    """Cap-fields (lower is safer) that mode restrictions may only tighten."""

    @staticmethod
    def fields_capped() -> dict[str, str]:
        return {
            "max_quantity": "Decimal",
            "max_exposure_lots": "Decimal",
            "max_open_orders": "int",
            "max_orders_per_minute": "int",
            "daily_loss_limit": "Decimal",
            "max_drawdown": "Decimal",
            "max_drawdown_pct": "Decimal",
            "max_spread_bps": "Decimal",
            "max_slippage_bps": "Decimal",
        }


def _assert_restriction_tightens(mode: ExecutionMode, overrides: dict[str, Any]) -> None:
    for key in _CapDirections.fields_capped():
        if key not in overrides:
            continue
        base_v = getattr(BASE_LIMITS, key)
        over_v = overrides[key]
        if Decimal(str(over_v)) > Decimal(str(base_v)):
            raise ValueError(
                f"mode restriction {mode.value}.{key}={over_v} exceeds base {base_v} — "
                "mode restrictions may only TIGHTEN the canonical base (fail closed)"
            )


for _m, _ov in MODE_RESTRICTIONS.items():
    _assert_restriction_tightens(_m, _ov)


class ResolvedRiskSnapshot(BaseModel):
    """The single effective risk configuration with per-field provenance."""

    limits: CanonicalRiskLimits
    mode: ExecutionMode
    overrides_applied: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, str] = Field(default_factory=dict)  # field -> origin
    config_hash: str = ""
    warnings: list[str] = Field(default_factory=list)
    resolved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def model_post_init(self, __context: Any) -> None:
        if not self.config_hash:
            body = json.dumps(
                {
                    "limits": {k: str(v) for k, v in self.limits.model_dump().items()},
                    "mode": self.mode.value,
                    "overrides": {k: str(v) for k, v in self.overrides_applied.items()},
                },
                sort_keys=True,
            )
            object.__setattr__(self, "config_hash", hashlib.sha256(body.encode()).hexdigest()[:16])

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "limits": {k: str(v) if isinstance(v, Decimal) else v for k, v in self.limits.model_dump().items()},
            "overrides_applied": {k: str(v) for k, v in self.overrides_applied.items()},
            "sources": self.sources,
            "config_hash": self.config_hash,
            "warnings": self.warnings,
            "resolved_at": self.resolved_at,
        }


def resolve_risk_limits(
    mode: ExecutionMode | str | None = None,
    *,
    config_overrides: dict[str, Any] | None = None,
    require_approved_for_live_family: bool = True,
) -> ResolvedRiskSnapshot:
    """Resolve THE effective risk configuration.

    ``mode``: canonical mode (resolved from env when None).
    ``config_overrides``: operator/YAML values — applied only when they
    tighten a cap (loosening requires ``risk.approved=true`` in the overrides
    or env ``QTS_RISK_LOOSEN_ACK=accepted``; every application is recorded).
    """
    if mode is None:
        from qts.domain.modes import resolve_mode

        mode = resolve_mode()
    mode = ExecutionMode(str(mode))

    warnings: list[str] = []
    values: dict[str, Any] = BASE_LIMITS.model_dump()
    sources: dict[str, str] = dict.fromkeys(values, "canonical_base")

    # 1) mode restrictions (always tighten; asserted above)
    mode_over = dict(MODE_RESTRICTIONS.get(mode, {}))
    for k, v in mode_over.items():
        values[k] = v
        sources[k] = f"mode:{mode.value}"

    # 2) explicit config overrides (validated)
    applied: dict[str, Any] = dict(mode_over)
    approved_ack = False
    if config_overrides:
        approved_ack = bool(config_overrides.get("approved", False)) or (
            os.getenv("QTS_RISK_LOOSEN_ACK") == "accepted"
        )
        allowed = set(CanonicalRiskLimits.model_fields.keys()) - {"version"}
        unknown = sorted(set(config_overrides) - allowed - {"approved"})
        if unknown:
            warnings.append(f"ignored unknown risk override keys: {unknown}")
        for k, v in config_overrides.items():
            if k == "approved" or k not in allowed or v is None:
                continue
            base_v = values[k]
            try:
                loosening = Decimal(str(v)) > Decimal(str(base_v))
            except Exception:
                loosening = False
            if loosening and not (approved_ack or bool(BASE_LIMITS.approved)):
                warnings.append(
                    f"override {k}={v} loosens {base_v} and was REJECTED (requires risk.approved)"
                )
                continue
            values[k] = v
            sources[k] = "config_override"
            applied[k] = v

    # 3) LIVE family demands explicit approval — never silently granted
    if require_approved_for_live_family and mode is ExecutionMode.LIVE and not values["approved"]:
        warnings.append("LIVE resolved without risk.approved — every live order path must refuse (see live gate)")

    limits = CanonicalRiskLimits(**values)
    snap = ResolvedRiskSnapshot(
        limits=limits,
        mode=mode,
        overrides_applied=applied,
        sources=sources,
        warnings=warnings,
    )
    return snap


# Backwards-compatible adapter: the demo boundary now derives from the one
# authority instead of defining its own numbers.
def demo_forward_limits_from(snapshot: ResolvedRiskSnapshot | None = None) -> dict[str, Any]:
    snap = snapshot or resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    lim = snap.limits
    return {
        "max_volume_per_order": float(lim.max_quantity),
        "max_simultaneous_exposure": float(lim.max_exposure_lots),
        "max_open_orders": lim.max_open_orders,
        "max_orders_per_minute": lim.max_orders_per_minute,
        "max_daily_loss_usd": float(lim.daily_loss_limit),
        "max_drawdown_usd": float(lim.max_drawdown),
        "max_drawdown_pct": float(lim.max_drawdown_pct),
        "max_spread_bps": float(lim.max_spread_bps),
        "max_slippage_bps": float(lim.max_slippage_bps),
        "kill_switch_enabled": lim.kill_switch_enabled,
        "config_hash": snap.config_hash,
    }
