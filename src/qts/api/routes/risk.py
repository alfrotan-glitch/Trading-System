"""API routes — risk and live lock."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from qts.api.deps import (
    _evidence_strategy_id,
    _reconciliation_status,
)
from qts.config.paths import artifact_path

router = APIRouter()


def _bind():
    """Late lookup so tests can patch seams on ``qts.api.server``."""
    import qts.api.server as server

    return server


@router.get("/api/risk")
def risk_center() -> dict[str, Any]:
    """Effective risk — THE resolved snapshot from the unified Risk Authority.

    The previous response invented display values ("1%", "2 lots", "$500",
    "2/sec", "5 losses → suspend") that existed nowhere in the risk engine.
    Every value now comes from resolve_risk_limits() with its source and a
    config hash; the reconciliation state is the REAL health probe.
    """
    from qts.domain.modes import resolve_mode
    from qts.risk.authority import resolve_risk_limits_from_settings
    from qts.risk.engine import RiskEngine, RiskLimits

    mode = resolve_mode()
    snap = resolve_risk_limits_from_settings(mode)
    lim = snap.limits
    # The kill switch is DURABLE state owned by RiskEngine (the same flag
    # pre_trade() enforces). EmergencyControls holds only a per-instance
    # in-memory flag, so a freshly constructed one always reports "not killed"
    # and silently hid an operator kill switch from this endpoint and the UI.
    try:
        kill_state = RiskEngine(RiskLimits()).kill_state()
    except Exception as e:  # fail closed: unreadable kill state is ACTIVE
        kill_state = {
            "killed": True,
            "reason": f"kill-switch state unreadable: {type(e).__name__}: {e}",
            "source": "unreadable",
        }
    killed = bool(kill_state.get("killed"))
    blocked_reasons: list[str] = []
    if killed:
        blocked_reasons.append("KILL_SWITCH_ACTIVE")
    try:
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
        if not rpt.get("ready", False):
            blocked_reasons.extend(rpt.get("blocked_reasons", []))
    except Exception as e:
        # Fail closed: a live-gate that could not be evaluated is a blocker, not
        # a silent pass. Suppressing this made /api/risk able to report
        # "TRADING ALLOWED" while the gate was unevaluable.
        blocked_reasons.append(f"LIVE_GATE_UNEVALUABLE:{type(e).__name__}")
    if not blocked_reasons:
        try:
            ev = json.loads(artifact_path("edge_validation").read_text(encoding="utf-8"))
            # A passing file that does not name a strategy is not a validated edge.
            if not (_evidence_strategy_id(ev) and ev.get("edge_survival", {}).get("passed")):
                blocked_reasons.append("NO_VALIDATED_EDGE")
        except Exception:
            blocked_reasons.append("NO_VALIDATED_EDGE")

    _recon_ok, recon_state, _recon_detail = _reconciliation_status()
    return {
        "mode": mode.value,
        "config_hash": snap.config_hash,
        "limits": {
            "max_quantity_lots": str(lim.max_quantity),
            "min_quantity_lots": str(lim.min_quantity),
            "quantity_step_lots": str(lim.quantity_step),
            "max_notional_usd": str(lim.max_notional),
            "risk_per_trade_bps": str(lim.max_risk_per_trade_bps),
            "max_exposure_lots": str(lim.max_exposure_lots),
            "max_leverage": str(lim.max_leverage),
            "max_open_orders": lim.max_open_orders,
            "max_orders_per_minute": lim.max_orders_per_minute,
            "daily_loss_limit_usd": str(lim.daily_loss_limit),
            "max_drawdown_usd": str(lim.max_drawdown),
            "max_drawdown_pct": str(lim.max_drawdown_pct),
            "spread_limit_bps": str(lim.max_spread_bps),
            "slippage_limit_bps": str(lim.max_slippage_bps),
            "stale_data_limit_s": str(lim.stale_data_limit_s),
            "stop_loss_required": lim.stop_loss_required,
            "kill_switch": "ACTIVE" if killed else "ARMED",
            "risk_approved": lim.approved,
            "reconciliation_state": recon_state,
            "sources": snap.sources,
        },
        "kill_switch_detail": kill_state,
        "overrides_applied": {k: str(v) for k, v in snap.overrides_applied.items()},
        "warnings": snap.warnings,
        "blocked": len(blocked_reasons) > 0,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "status_text": "TRADING BLOCKED" if blocked_reasons else "RISK CLEAR — NOT AN ORDER",
        "explanations": {
            "MISSING_MARKET_PRICE": "Market data stale or unavailable — no authoritative price for risk check",
            "ACCOUNT_STATE_UNAVAILABLE": "Authoritative account equity unavailable — order vetoed, never computed against guessed capital",
            "RECONCILIATION_DRIFT": "Broker positions vs local state diverge — suspend to prevent overexposure",
            "NO_VALIDATED_EDGE": "No strategy has passed scientific+economic gates — capital preservation blocks trading",
        },
    }




@router.get("/api/live/status")
def live_status() -> dict[str, Any]:
    try:
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
        eligible = rpt.get("ready", False)
        reasons = rpt.get("blocked_reasons", [])

        # Every checklist item is derived from a real authority. Two of them
        # were previously hardcoded ``True`` and rendered by the Governance
        # view as "satisfied — independently evidenced" without any evidence
        # being consulted at all; ``mt5_connectivity`` was derived from a
        # hardcoded health field and could therefore never be satisfied. An
        # item that cannot be evaluated is reported as NOT satisfied.
        checklist = {
            "validated_edge": False,
            "forward_observation": False,
            "risk_configuration": False,
            "mt5_connectivity": False,
            "reconciliation": False,
            "human_approval": False,
        }
        checklist_detail: dict[str, str] = {
            "validated_edge": "no edge_validation evidence read",
            "forward_observation": "no forward-observation evidence read",
            "risk_configuration": "risk authority not evaluated",
            "mt5_connectivity": "live gate did not report a connectivity check",
            "reconciliation": "live gate did not report a reconciliation check",
            # There is no recorded human-approval authority in this system, so
            # this item is never satisfied by inference — fail closed.
            "human_approval": "no explicit, recorded human approval exists",
        }

        def _gate_passed(*names: str) -> tuple[bool, str]:
            """All named live-gate checks passed; otherwise the first failure."""
            missing = [n for n in names if not isinstance(rpt.get(n), dict)]
            if missing:
                return False, f"live gate reported no result for {missing}"
            failed = [n for n in names if not rpt[n].get("passed")]
            if failed:
                return False, "; ".join(f"{n}: {rpt[n].get('detail')}" for n in failed)
            return True, "; ".join(f"{n}: {rpt[n].get('detail')}" for n in names)

        try:
            ev = json.loads(artifact_path("edge_validation").read_text(encoding="utf-8"))
            sid = _evidence_strategy_id(ev)
            if sid and ev.get("edge_survival", {}).get("passed"):
                checklist["validated_edge"] = True
                checklist_detail["validated_edge"] = (
                    f"edge_survival.passed=true for strategy_id={sid!r} in data/evidence/edge_validation.json"
                )
            elif ev.get("edge_survival", {}).get("passed"):
                checklist_detail["validated_edge"] = (
                    "edge_survival.passed=true but the file records no strategy_id — "
                    "unattributed evidence is not a validated edge"
                )
            else:
                checklist_detail["validated_edge"] = "edge_survival.passed is not true"
            # forward.signals on this validation file is not a forward-observation
            # record. The producer writes observation counts under a different
            # shape, and an unattributed file must not satisfy the item by a
            # caller-placed integer.
            forward = ev.get("forward") if isinstance(ev.get("forward"), dict) else {}
            forward_sid = _evidence_strategy_id(forward) or sid
            signals = forward.get("signals")
            if forward_sid and isinstance(signals, int) and signals >= 10 and forward.get("status") != "UNAVAILABLE":
                checklist["forward_observation"] = True
                checklist_detail["forward_observation"] = (
                    f"forward.signals={signals} (>=10) for strategy_id={forward_sid!r}"
                )
            else:
                checklist_detail["forward_observation"] = (
                    f"no attributed forward-observation record (strategy_id={forward_sid!r}, signals={signals!r})"
                )
        except Exception as e:
            checklist_detail["validated_edge"] = f"edge_validation evidence unreadable: {type(e).__name__}: {e}"
            checklist_detail["forward_observation"] = checklist_detail["validated_edge"]

        # REAL-terminal connectivity: the live gate's own real_environment-tier
        # probe, already computed above — no second probe, no recursion into
        # /api/health.
        ok, detail = _gate_passed("mt5_connectivity")
        checklist["mt5_connectivity"] = ok
        checklist_detail["mt5_connectivity"] = detail

        # Reconciliation: structural capability AND the durable "no unresolved
        # suspension" probe must both hold.
        ok, detail = _gate_passed("reconciliation", "reconciliation_health")
        checklist["reconciliation"] = ok
        checklist_detail["reconciliation"] = detail

        # Risk configuration: the ONE risk authority must resolve, carry an
        # explicit operator approval, produce no warnings, and the DURABLE kill
        # switch must not be active.
        try:
            from qts.domain.modes import resolve_mode
            from qts.risk.authority import resolve_risk_limits_from_settings
            from qts.risk.engine import RiskEngine, RiskLimits

            snap = resolve_risk_limits_from_settings(resolve_mode())
            kill_state = RiskEngine(RiskLimits()).kill_state()
            killed = bool(kill_state.get("killed"))
            approved = bool(snap.limits.approved)
            checklist["risk_configuration"] = approved and not killed and not snap.warnings
            checklist_detail["risk_configuration"] = (
                f"risk.approved={approved} (config_hash={snap.config_hash}); "
                f"kill_switch={'ACTIVE' if killed else 'ARMED'}; "
                f"authority_warnings={snap.warnings or 'none'}"
            )
        except Exception as e:
            checklist["risk_configuration"] = False
            checklist_detail["risk_configuration"] = f"risk authority unresolved: {type(e).__name__}: {e}"

        return {
            "live_trading": "LOCKED" if not eligible else "ELIGIBLE (GATED)",
            "eligible": eligible,
            "blocked_reasons": reasons,
            "checklist": checklist,
            "checklist_detail": checklist_detail,
            "message": "LIVE NOT AVAILABLE"
            if not eligible
            else "All prerequisites met — explicit confirmation required",
            "explicit_confirmation_required": True,
        }
    except Exception as e:
        # Same shape as the success path: a gate that could not be evaluated
        # satisfies nothing, and the UI must be able to say why per item rather
        # than render an empty grid. LOCKED either way.
        reason = f"live readiness gate could not be evaluated: {type(e).__name__}: {e}"
        keys = (
            "validated_edge",
            "forward_observation",
            "risk_configuration",
            "mt5_connectivity",
            "reconciliation",
            "human_approval",
        )
        return {
            "live_trading": "LOCKED",
            "eligible": False,
            "blocked_reasons": [reason],
            "checklist": dict.fromkeys(keys, False),
            "checklist_detail": dict.fromkeys(keys, reason),
            "message": "LIVE NOT AVAILABLE",
            "explicit_confirmation_required": True,
        }



