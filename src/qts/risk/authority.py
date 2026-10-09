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
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

from qts.domain.modes import ExecutionMode

if TYPE_CHECKING:
    from qts.risk.engine import RiskLimits


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
    max_open_orders: int = 5

    # Loss control
    daily_loss_limit: Decimal = Decimal("200")
    #: Absolute peak-to-current drawdown, USD.
    max_drawdown: Decimal = Decimal("500")
    #: Peak-to-current drawdown as a PERCENT of the peak equity (0 < pct <= 100).
    #:
    #: The absolute USD cap alone is not scale-invariant: the same percentage
    #: loss is survivable on a large account and fatal on a small one, and a
    #: DEMO account whose balance changes would silently move the meaning of a
    #: fixed dollar number. Both caps are enforced and BOTH must hold.
    max_drawdown_pct: Decimal = Decimal("10")

    # Market-condition limits
    max_spread_bps: Decimal = Decimal("100")
    max_slippage_bps: Decimal = Decimal("50")
    volatility_target: Decimal | None = None
    stale_data_limit_s: Decimal = Decimal("60")

    # Order rate (research modes may simulate faster; DEMO_EXECUTION tightens to 4)
    max_orders_per_minute: int = 60

    # Controls
    kill_switch_enabled: bool = True
    flatten_on_kill: bool = False
    approved: bool = False  # operator acknowledgement — required for LIVE family
    version: int = 3

    @model_validator(mode="after")
    def _validate_percentage_caps(self) -> CanonicalRiskLimits:
        """A percentage cap must be a percentage — never a silent no-op.

        ``0`` would mean "any drawdown breaches" and is almost certainly a unit
        mistake (0.05 written where 5 was meant); a value above 100 cannot be
        breached by a long-only equity curve. Both fail closed at construction.
        """
        pct = self.max_drawdown_pct
        if not pct.is_finite() or pct <= 0 or pct > 100:
            raise ValueError(f"max_drawdown_pct must be a finite percentage in (0, 100] — got {pct}")
        return self


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
        "max_spread_bps": Decimal("30"),
        "max_slippage_bps": Decimal("20"),
        "kill_switch_enabled": True,
    },
    # LIVE resolves to base + mandatory operator approval; the live gate
    # separately demands far more than a risk snapshot (see lifecycle.live_gate).
    ExecutionMode.LIVE: {},
}


#: Cap fields (lower is safer) that mode restrictions may only tighten.
_CAP_FIELDS = frozenset(
    {
        "max_quantity",
        "max_exposure_lots",
        "max_open_orders",
        "max_orders_per_minute",
        "daily_loss_limit",
        "max_drawdown",
        "max_drawdown_pct",
        "max_spread_bps",
        "max_slippage_bps",
    }
)

#: Percentage-valued cap fields. Only these may be tightened from a
#: percentage-valued source (an authorization ceiling) — see
#: :func:`apply_risk_ceiling`.
_PCT_CAP_FIELDS = frozenset({"max_drawdown_pct"})


def _assert_restriction_tightens(mode: ExecutionMode, overrides: dict[str, Any]) -> None:
    for key in _CAP_FIELDS:
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
        approved_ack = bool(config_overrides.get("approved", False)) or (os.getenv("QTS_RISK_LOOSEN_ACK") == "accepted")
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
                warnings.append(f"override {k}={v} loosens {base_v} and was REJECTED (requires risk.approved)")
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


def resolve_risk_limits_from_settings(mode: ExecutionMode | str | None = None) -> ResolvedRiskSnapshot:
    """Resolve effective risk with YAML/settings risk config as the override
    layer — so configuration flows through the ONE authority instead of a
    parallel consumer path.

    Only values that actually DIFFER from the canonical base are passed as
    overrides: pydantic model defaults would otherwise be mislabeled as
    "config_override" in the snapshot's per-field provenance.
    """
    from qts.config.settings import load_settings

    settings = load_settings()
    overrides = {
        k: v
        for k, v in settings.risk.model_dump().items()
        if k != "version" and v is not None and getattr(BASE_LIMITS, k, None) != v
    }
    return resolve_risk_limits(mode, config_overrides=overrides)


def apply_risk_ceiling(
    snapshot: ResolvedRiskSnapshot,
    ceiling: dict[str, Any] | None,
    *,
    origin: str = "authorization",
) -> ResolvedRiskSnapshot:
    """Return a snapshot tightened by an explicit, already-validated ceiling.

    A ``risk_ceiling`` (owner authorization artifact, policy, operator
    directive) may only ever TIGHTEN a resolved limit — never widen it. This
    function is the enforcement half of that rule: the caller validates the
    ceiling, this applies it, and the returned snapshot carries per-field
    provenance so the UI/API can state exactly where each number came from.

    Unknown keys are ignored (validation owns that decision — an unknown key
    must already have failed the artifact). Values that do not tighten are
    recorded as ``ignored`` and never applied.
    """
    if not ceiling:
        return snapshot

    values = snapshot.limits.model_dump()
    sources = dict(snapshot.sources)
    applied = dict(snapshot.overrides_applied)
    warnings = list(snapshot.warnings)

    for key, raw in ceiling.items():
        if key not in _CAP_FIELDS:
            continue
        current = values.get(key)
        if current is None:
            continue
        try:
            current_dec = Decimal(str(current))
            ceiling_dec = Decimal(str(raw))
        except Exception:
            warnings.append(f"ceiling {key}={raw!r} is not numeric — ignored (canonical value retained)")
            continue
        if not ceiling_dec.is_finite():
            warnings.append(f"ceiling {key}={raw!r} is not finite — ignored (canonical value retained)")
            continue
        if key in _PCT_CAP_FIELDS and (ceiling_dec <= 0 or ceiling_dec > 100):
            warnings.append(f"ceiling {key}={raw!r} is not a valid percentage — ignored (canonical value retained)")
            continue
        if ceiling_dec > current_dec:
            # Widening: never applied, always visible. An artifact that asks for
            # more than the canonical limit is a fact the operator must see.
            warnings.append(
                f"ceiling {key}={ceiling_dec} exceeds resolved {current_dec} and was NOT applied "
                "(a ceiling may only tighten)"
            )
            continue
        if ceiling_dec == current_dec:
            # Agreement with the resolved limit — nothing to apply, nothing to report.
            continue
        values[key] = ceiling_dec
        sources[key] = origin
        applied[key] = ceiling_dec

    tightened = ResolvedRiskSnapshot(
        limits=CanonicalRiskLimits(**values),
        mode=snapshot.mode,
        overrides_applied=applied,
        sources=sources,
        warnings=warnings,
        resolved_at=snapshot.resolved_at,
    )
    return tightened


def engine_limits_from(snapshot: ResolvedRiskSnapshot) -> RiskLimits:
    """Translate one resolved authority snapshot into the engine limits.

    This is the only snapshot-to-engine mapping used by broker-capable
    execution paths. The engine kill switch is always durable and enabled.
    """
    from qts.risk.engine import RiskLimits

    lim = snapshot.limits
    return RiskLimits(
        max_quantity=lim.max_quantity,
        min_quantity=lim.min_quantity,
        quantity_step=lim.quantity_step,
        max_notional=lim.max_notional,
        max_risk_per_trade_bps=lim.max_risk_per_trade_bps,
        stop_loss_required=bool(lim.stop_loss_required),
        max_exposure_lots=lim.max_exposure_lots,
        max_exposure_notional=lim.max_exposure_notional,
        max_leverage=lim.max_leverage,
        max_open_orders=lim.max_open_orders,
        daily_loss_limit=lim.daily_loss_limit,
        max_drawdown=lim.max_drawdown,
        max_drawdown_pct=lim.max_drawdown_pct,
        volatility_target=lim.volatility_target,
        kill_switch_enabled=True,
        approved=bool(lim.approved),
    )


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
