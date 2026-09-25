"""API routes — DEMO execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from qts.api.deps import (
    _demo_policy,
    _wizard_setup_kwargs,
)
from qts.config.settings import load_settings

router = APIRouter()


def _bind():
    """Late lookup so tests can patch seams on ``qts.api.server``."""
    import qts.api.server as server

    return server


@router.get("/api/demo/readiness")
def demo_readiness(terminal_path: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    # Wizard inputs (query params) override the saved setup; env fallbacks
    # live inside the gate. Fail-closed: the gate itself initializes MT5 and
    # surfaces last_error — never mocked, never skipped.
    try:
        return demo_forward_readiness_report(**_wizard_setup_kwargs(terminal_path, symbol))
    except Exception as e:
        return {"passed": False, "demo_enabled": False, "blocked_reasons": [str(e)], "checks": {}}




@router.get("/api/demo/safety")
def demo_safety() -> dict[str, Any]:
    from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS, SAFETY_BOUNDARY

    return {
        "boundary": SAFETY_BOUNDARY,
        "demo_limits": DEMO_FORWARD_DEFAULTS.model_dump(),
        "live_locked": True,
        "note": "No env can silently become another. LIVE remains LOCKED unless all scientific+safety gates pass.",
    }




@router.get("/api/demo/comparison")
def demo_comparison() -> dict[str, Any]:
    """Fresh comparison — computed from current inputs, never a stale file.

    The JSON file is a derived export refreshed by /api/demo/comparison/refresh;
    serving it as live truth could present outdated metrics as current.
    """
    from qts.execution.demo_comparison import compare_paper_shadow_demo

    try:
        return compare_paper_shadow_demo()
    except Exception as e:
        return {"status": "UNAVAILABLE", "reason": f"comparison computation failed: {e}"}




@router.post("/api/demo/comparison/refresh")
def demo_comparison_refresh() -> dict[str, Any]:
    from qts.execution.demo_comparison import write_comparison

    return write_comparison()




@router.get("/api/demo/observations")
def demo_observations(limit: int = 20) -> list[dict[str, Any]]:
    """Recent observations from the ONE canonical store (SQLite).

    The previous implementation read ``demo_forward_observations.json`` — a
    fabricated, quarantined artifact. Records carry their provenance class;
    only DEMO/REAL-class observations are returned as market evidence.
    """
    from qts.observability.forward_observatory import ForwardObservatory

    try:
        obs = ForwardObservatory()
        return obs.list_ticks(limit=max(1, min(int(limit), 500)))
    except Exception as e:
        return [{"error": f"canonical observation store unavailable: {e}", "provenance": "UNVERIFIED"}]


# --- OBSERVE-ONLY live collection (REAL market data, ZERO orders) ---


@router.get("/api/demo/config")
def demo_config() -> dict[str, Any]:
    """Demo configuration — observation facts plus the disabled execution policy.

    Risk limits remain visible as declared DEMO boundary metadata; they are not
    evidence of an enabled order path or broker account state.
    """
    from qts.domain.modes import resolve_mode
    from qts.risk.authority import demo_forward_limits_from, resolve_risk_limits_from_settings

    mode = resolve_mode()
    snapshot = resolve_risk_limits_from_settings(mode)
    limits = demo_forward_limits_from(snapshot)
    decision = _bind()._demo_authority().current()
    from qts.config.paths import paths_report
    from qts.domain.modes import mode_source, persisted_mode_declaration, refused_mode_declarations

    return {
        "env": load_settings().env,
        "mode": mode.value,
        # Provenance, so the UI can show WHY it reports this mode instead of
        # silently disagreeing with a CLI that resolved a different one.
        "mode_source": mode_source(),
        "mode_declaration": persisted_mode_declaration()[0],
        "mode_refused_declarations": refused_mode_declarations(),
        "state": paths_report(),
        "mode_can_submit_orders": (mode.can_submit_broker_orders and _demo_policy().enabled),
        "demo_execution_disabled": not _demo_policy().enabled,
        "demo_execution": decision.as_dict(),
        "risk": limits,
        "observation_mode": "OBSERVE_ONLY",  # observe endpoint is physically order-free
        "lifecycle": [
            "RESEARCH",
            "VALIDATING",
            "FORWARD_OBSERVATION",
            "PAPER_VERIFIED",
            "SHADOW_VERIFIED",
            "DEMO_OBSERVATION",
        ],
        "demo_execution_policy": (
            f"DEMO_EXECUTION = {_demo_policy().state} — resolved from the recorded owner authorization "
            "(DEMO only, LIVE locked); per-order permission additionally requires the staged progression "
            "and the full pre-trade gate (every required safeguard, contract check and registered-policy limit)"
        ),
    }




@router.post("/api/demo/enable")
def demo_enable(payload: dict[str, Any]) -> Any:
    """Enable DEMO execution — authority-gated, never a policy bypass.

    With no valid owner authorization artifact this is the durable 409 refusal
    the product shipped with (``DEMO_EXECUTION = DISABLED BY POLICY``). With
    one, every retained gate still applies: explicit confirmation, risk
    acknowledgement, a FRESH passing readiness report, the required checks and
    a broker-capable mode. A refused attempt is recorded in the durable
    authority table and the audit log.
    """
    confirmed = bool(payload.get("confirmed"))
    risk_ack = bool(payload.get("risk_ack"))
    if not confirmed or not risk_ack:
        raise HTTPException(400, "DEMO execution requires explicit confirmed=true and risk_ack=true")

    from qts.lifecycle.demo_authority import readiness_age_seconds
    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    policy = _demo_policy()
    setup = _wizard_setup_kwargs(None, None)
    try:
        rpt = demo_forward_readiness_report(**setup)
    except Exception as exc:
        rpt = {"passed": False, "checks": {}, "blocked_reasons": [f"readiness probe failed: {exc}"]}

    if not policy.enabled:
        return JSONResponse(
            status_code=409,
            content={
                "authority": "demo_execution_state",
                "enabled": False,
                "execution_permitted": False,
                "state": "DISABLED",
                "policy": policy.state,
                "reasons": list(policy.reasons)
                or ["no valid owner authorization artifact — DEMO_EXECUTION = DISABLED BY POLICY"],
                "mode": "DEMO_FORWARD",
                "demo_execution_disabled": True,
                "readiness": rpt,
            },
        )

    decision = _bind()._demo_authority().enable(
        readiness=rpt,
        confirmed=True,
        risk_ack=True,
        readiness_age_s=readiness_age_seconds(rpt),
        actor="api",
    )
    body = decision.as_dict()
    body["policy"] = policy.state
    body["authorization_id"] = policy.authorization_id
    if not decision.execution_permitted:
        return JSONResponse(status_code=409, content=body)
    return body




@router.get("/api/demo/state")
def demo_state() -> dict[str, Any]:
    """The authoritative DEMO execution permission state (single source).

    Two readiness facts are reported and may LEGITIMATELY disagree:

    * ``readiness_passed`` / ``readiness_evidence`` — the PERSISTED decision
      record: the readiness report bound to the latest authority transition
      (enable/refusal/disable). ``readiness_passed=false`` with
      ``readiness_evidence="none"`` simply means no passing readiness was ever
      durably recorded (e.g. never enabled) — not that the terminal now fails.
    * ``current_readiness.passed`` — a FRESH 14-check probe of the terminal
      computed in THIS request.

    So ``readiness_passed=false`` + ``current_readiness.passed=true`` is a
    coherent state: the environment is ready now, but no enablement decision
    carries passing readiness evidence. Execution stays forbidden because
    DEMO_EXECUTION is disabled by product policy; the fresh result can only
    authorize DEMO_FORWARD observation.
    """
    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    setup = _wizard_setup_kwargs(None, None)
    try:
        rpt = demo_forward_readiness_report(**setup)
    except Exception as e:
        rpt = {"passed": False, "blocked_reasons": [f"readiness probe failed: {e}"], "checks": {}}
    decision = _bind()._demo_authority().current(fresh_readiness=rpt)
    out = decision.as_dict()
    out["current_readiness"] = {
        "passed": bool(rpt.get("passed")),
        "blocked_reasons": rpt.get("blocked_reasons", []),
    }
    out["demo_execution_disabled"] = not _demo_policy().enabled
    out["demo_execution_policy"] = _demo_policy().state
    out["policy_reasons"] = list(_demo_policy().reasons)
    return out




@router.post("/api/demo/disable")
def demo_disable() -> dict[str, Any]:
    decision = _bind()._demo_authority().disable(reason="operator requested via API")
    return decision.as_dict()




@router.get("/api/demo/authorization")
def demo_authorization() -> dict[str, Any]:
    """The owner authorization artifact: what it grants, and its validation."""
    from qts.lifecycle.demo_authorization import authorization_status

    status = authorization_status()
    policy = _demo_policy()
    return {
        "authorization": status.as_dict(),
        "resolved_policy": policy.as_dict(),
        "live_locked": True,
        "real_capital_exposure_usd": 0,
    }




@router.get("/api/demo/stage")
def demo_stage() -> dict[str, Any]:
    """DEMO execution stage machine (staged progression, never a jump)."""
    return _bind()._demo_session().stage.as_dict()




@router.get("/api/demo/preflight")
@router.post("/api/demo/preflight")
def demo_preflight(side: str = "BUY", lots: str | None = None, stop_loss: str | None = None) -> Any:
    """Run the DEMO pre-trade gate for a would-be order — submits nothing."""
    from decimal import Decimal

    session = _bind()._demo_session()
    out = session.preflight(
        side=side,
        lots=Decimal(lots) if lots else None,
        stop_loss=Decimal(stop_loss) if stop_loss else None,
        entry=getattr(session, "_entry", None),
    )
    return JSONResponse(
        status_code=200 if out["verdict"]["passed"] else 409,
        content=out,
    )




@router.post("/api/demo/order")
def demo_order(payload: dict[str, Any]) -> Any:
    """Submit ONE DEMO order through the gate (409 on any failed safeguard)."""
    from decimal import Decimal

    side = str(payload.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(400, "side must be BUY or SELL")
    if not payload.get("confirmed") or not payload.get("risk_ack"):
        raise HTTPException(400, "DEMO order requires explicit confirmed=true and risk_ack=true")

    session = _bind()._demo_session(payload.get("symbol"))
    # Resolve the registered experiment HERE, per request: the registry is
    # re-checked on every order so a policy that was revoked, drifted or
    # de-registered since the last call cannot still authorise one.
    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    entry, entry_reasons = resolve_entry(load_registry(), payload.get("strategy"))
    if entry is None:
        return JSONResponse(
            status_code=409,
            content={
                "allowed": False,
                "state": "NO_TRADE",
                "reasons": list(entry_reasons)
                + [
                    "no eligible strategy in the forward-validation registry — DEMO_EXECUTION may be "
                    "ENABLED while no strategy has passed the research gates"
                ],
            },
        )
    if payload.get("dry_run"):
        return session.preflight(
            side=side,
            lots=Decimal(str(payload["lots"])) if payload.get("lots") else None,
            stop_loss=Decimal(str(payload["stop_loss"])) if payload.get("stop_loss") else None,
            entry=entry,
        )
    result = session.submit(
        side=side,
        lots=Decimal(str(payload["lots"])) if payload.get("lots") else None,
        stop_loss=Decimal(str(payload["stop_loss"])) if payload.get("stop_loss") else None,
        take_profit=Decimal(str(payload["take_profit"])) if payload.get("take_profit") else None,
        rationale=str(payload.get("rationale") or "RESEARCH_DEMO_ORDER via API"),
        entry=entry,
    )
    return JSONResponse(status_code=200 if result.allowed else 409, content=result.as_dict())




@router.get("/api/demo/positions")
def demo_positions() -> dict[str, Any]:
    """List open DEMO positions on the connected MT5 venue."""
    session = _bind()._demo_session()
    positions = session.positions()
    return {
        "positions": positions,
        "count": len(positions),
        "symbol": session.canonical_symbol,
        "broker_symbol": session.broker_symbol,
        "checked_at": datetime.now(UTC).isoformat(),
    }




@router.post("/api/demo/close")
def demo_close(payload: dict[str, Any]) -> dict[str, Any]:
    """Close an open DEMO position by ticket (requires confirmed=true and risk_ack=true)."""
    from decimal import Decimal

    ticket = payload.get("ticket")
    if ticket is None:
        raise HTTPException(400, "ticket is required to close a position")
    try:
        ticket_int = int(ticket)
    except (TypeError, ValueError) as err:
        raise HTTPException(400, f"invalid ticket id: {ticket}") from err

    if not payload.get("confirmed") or not payload.get("risk_ack"):
        raise HTTPException(400, "closing a DEMO position requires explicit confirmed=true and risk_ack=true")

    volume_str = payload.get("volume")
    volume = Decimal(str(volume_str)) if volume_str is not None else None
    reason = str(payload.get("reason") or "operator-close via API")

    session = _bind()._demo_session(payload.get("symbol"))
    try:
        return session.close_position(ticket_int, volume=volume, reason=reason, actor="api:demo-close")
    except Exception as exc:
        raise HTTPException(500, f"failed to close position {ticket_int}: {exc}") from exc




@router.post("/api/demo/kill")
def demo_kill(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Raise the durable kill switch and halt the DEMO stage machine."""
    reason = str((payload or {}).get("reason") or "operator kill via API")
    return _bind()._demo_session().raise_kill_switch(reason)




@router.get("/api/demo/journal")
def demo_journal(limit: int = 50) -> dict[str, Any]:
    """Forward-observation audit trail for DEMO orders."""
    from qts.execution.demo_journal import summarize

    session = _bind()._demo_session()
    return {
        "summary": summarize(session.journal).as_dict(),
        "orders": session.journal.list_orders(limit=limit),
        "label": "RESEARCH_DEMO_ORDER",
        "capital_class": "DEMO",
    }


# Mount static UI if exists

