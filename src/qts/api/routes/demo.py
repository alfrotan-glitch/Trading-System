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
    try:
        positions = session.positions()
    except Exception as exc:
        raise HTTPException(503, f"positions unavailable: {exc}") from exc
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
        result = session.close_position(ticket_int, volume=volume, reason=reason, actor="api:demo-close")
        state = str(result.get("state") or "")
        if state == "AMBIGUOUS":
            raise HTTPException(409, result.get("error") or "close outcome is ambiguous; reconciliation required")
        return result
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, f"close unavailable: {exc}") from exc




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


# ------------------------------------------------------------- guided product
# The guided workflow is the PRODUCT surface for DEMO trading: one aggregated
# plain-language state ("connect / review identity / prepare / refresh /
# trade") plus the actions that move it. Every endpoint here drives the SAME
# lifecycle machinery the CLI uses (stage machine, identity pin, authority,
# readiness gate) — nothing is bypassed, relaxed or re-implemented. The
# engineering internals (stage names, pin files, readiness check ids, audit
# ids) travel under the ``technical`` key for Advanced views only.


def _plain_blocker(reason: str) -> str:
    """Translate the first technical blocker into one product sentence."""
    r = str(reason or "")
    low = r.lower()
    if "not installed" in low:
        return "MetaTrader 5 is not installed on this computer."
    if "terminal not running" in low or "terminal" in low and "not running" in low:
        return "MetaTrader 5 is not running. Open it and sign in to your demo account."
    if "account not connected" in low:
        return "No account is signed in. Open MetaTrader 5 and sign in to your demo account."
    if "not demo" in low:
        return "The connected account is not a demo account."
    if "market data not fresh" in low or "bid/ask" in low:
        return "No fresh gold price is available right now. Check that the terminal is connected."
    if "spread" in low:
        return "The current gold spread is too wide for the demo limits."
    return r


def _guide_connection(report: dict[str, Any]) -> dict[str, Any]:
    identity = report.get("identity") or {}
    connected = bool(identity.get("ok"))
    is_demo = identity.get("is_demo")
    if connected:
        detail = "MetaTrader 5 is connected." if is_demo else "MetaTrader 5 is connected, but the account is not a demo account."
    else:
        detail = "MetaTrader 5 is not connected."
    return {
        "connected": connected,
        "detail": detail,
        "account_type": "Demo" if is_demo is True else ("Not demo" if is_demo is False else None),
        "broker": identity.get("company") or identity.get("server"),
        "server": identity.get("server"),
        "login": identity.get("login"),
        "error": None if connected else str(identity.get("error") or "terminal unreachable"),
    }


def _guide_pin_state(report: dict[str, Any]) -> dict[str, Any]:
    pin = report.get("identity_pin") or {}
    pinned = bool(pin.get("pinned"))
    status = str(pin.get("status") or "")
    confirmed = status == "CONFIRMED"
    verified = pin.get("verified") is True
    if not pinned:
        detail = "The account identity has not been recorded yet."
    elif not confirmed:
        detail = "The account identity was recorded and waits for your review."
    elif not verified:
        detail = "The connected account no longer matches the recorded identity."
    else:
        detail = "The account identity is recorded and confirmed."
    return {"recorded": pinned, "confirmed": confirmed, "verified": verified, "status": status or None, "detail": detail}


def _build_guide(session: Any | None = None) -> dict[str, Any]:
    """One aggregated, plain-language DEMO workflow state (read-only).

    Fails closed and honest: any probe that cannot run is reported as a
    blocker with a human sentence, never guessed away. This function never
    changes state — it probes, reads and translates.
    """
    from qts.lifecycle.demo_registry import load_registry, resolve_entry
    from qts.lifecycle.demo_stage import ORDER_STAGES

    server = _bind()
    session = session or server._demo_session()
    now = datetime.now(UTC).isoformat()
    guide: dict[str, Any] = {
        "checked_at": now,
        "instrument": f"Gold ({session.canonical_symbol})",
        "live_locked": True,
        "real_capital_exposure_usd": 0,
    }

    mode = str(getattr(session, "mode", "") or "")
    guide["mode_ok"] = mode == "DEMO_EXECUTION"
    guide["mode"] = mode

    policy = session.policy
    guide["authorization_ok"] = bool(policy.enabled)
    guide["authorization_detail"] = str(policy.state)

    try:
        report = session.connectivity_report()
    except Exception as exc:
        report = {
            "readiness": {"passed": False, "blocked_reasons": [f"connectivity probe failed: {exc}"], "checks": {}},
            "identity": {"ok": False, "is_demo": None, "error": f"{type(exc).__name__}: {exc}"},
            "identity_pin": {},
            "symbol_mapping": {},
            "quote": {},
            "order_check": None,
        }
    conn = _guide_connection(report)
    pin = _guide_pin_state(report)
    readiness = report.get("readiness") or {}
    readiness_passed = bool(readiness.get("passed"))
    # ONE plain reason for the product surface (the first blocker is the one
    # the next action addresses); the full list stays under ``technical``.
    blockers = list(readiness.get("blocked_reasons") or [])
    readiness_reason = _plain_blocker(blockers[0]) if blockers else None
    quote = report.get("quote") or {}

    guide["connection"] = conn
    guide["identity"] = pin
    guide["readiness"] = {"ready": readiness_passed, "reason": readiness_reason}
    guide["quote"] = {
        "fresh": bool(quote.get("fresh")),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "spread_bps": quote.get("spread_bps"),
    }

    kill = session.kill_switch_state()
    guide["kill_switch"] = {
        "active": bool(kill.get("killed")),
        "readable": bool(kill.get("readable")),
        "reason": kill.get("reason"),
    }
    try:
        reconciliation = session.reconcile()
    except Exception as exc:
        reconciliation = {"requires_suspend": True, "drift": "UNAVAILABLE", "details": f"reconciliation failed: {exc}"}
    guide["reconciliation"] = {
        "clean": not reconciliation.get("requires_suspend"),
        "drift": reconciliation.get("drift"),
        "details": reconciliation.get("details"),
    }
    ambiguous_orders = [
        row for row in session.journal.list_orders(limit=500)
        if row.get("state") == "AMBIGUOUS"
    ]
    guide["execution_barrier"] = {
        "active": bool(ambiguous_orders) or bool(reconciliation.get("requires_suspend")),
        "reason": (
            f"Broker outcome for {ambiguous_orders[0].get('client_order_id')} is unresolved."
            if ambiguous_orders
            else reconciliation.get("details") if reconciliation.get("requires_suspend")
            else None
        ),
        "action": (
            "Reconcile the broker state before sending any new order."
            if ambiguous_orders or reconciliation.get("requires_suspend")
            else None
        ),
    }

    stage_record = session.stage.current()
    stage = stage_record.stage
    guide["stage_allows_orders"] = stage in ORDER_STAGES

    authority = session.authority.current()
    guide["permission"] = {
        "permitted": bool(authority.execution_permitted),
        "refresh_needed": bool(getattr(authority, "readiness_expired", False)) and stage in ORDER_STAGES,
        "reasons": list(authority.reasons),
    }

    entry, entry_reasons = resolve_entry(load_registry())
    guide["plan_registered"] = entry is not None
    guide["plan_reasons"] = list(entry_reasons or [])
    guide["plan_id"] = entry.strategy_id if entry else None

    # Order defaults for the ticket — measured from the broker spec, never
    # invented. UNAVAILABLE keeps the ticket honest when the terminal is gone.
    size_default = None
    try:
        spec = session.adapter.get_symbol_spec(session.canonical_symbol)
        size_default = str(spec.volume_min)
    except Exception:
        size_default = None
    guide["order_defaults"] = {"size": size_default, "stop_required": True}

    # ------------------------------------------------- steps + the ONE next
    steps: list[dict[str, Any]] = []

    def step(id_: str, title: str, done: bool, detail: str) -> None:
        steps.append({"id": id_, "title": title, "state": "done" if done else "todo", "detail": detail})

    step("connect", "Connect the demo account", conn["connected"] and conn["account_type"] == "Demo", conn["detail"])
    step(
        "identity",
        "Confirm the account identity",
        pin["verified"],
        pin["detail"],
    )
    step(
        "prepare",
        "Prepare demo trading",
        stage in ORDER_STAGES,
        "Demo trading is prepared." if stage in ORDER_STAGES else "Runs the safety checks and prepares the demo account.",
    )
    step(
        "plan",
        "Approved trading plan",
        entry is not None,
        f"Plan {entry.strategy_id} is registered." if entry else "No approved trading plan is registered yet. QTS will not trade without one.",
    )
    guide["steps"] = steps

    can_trade = (
        guide["mode_ok"]
        and guide["authorization_ok"]
        and conn["connected"]
        and conn["account_type"] == "Demo"
        and pin["verified"]
        and readiness_passed
        and not guide["kill_switch"]["active"]
        and guide["reconciliation"]["clean"]
        and stage in ORDER_STAGES
        and guide["permission"]["permitted"]
        and entry is not None
    )
    guide["can_trade"] = can_trade

    next_action: dict[str, Any] | None = None
    if not guide["mode_ok"]:
        headline, reason = "Not ready", "QTS is not running in demo-trading mode."
        next_action = {
            "action": "open_setup",
            "label": "Open setup",
            "description": "Choose “Demo trading” in System → Setup, then come back. QTS never switches itself into a trading mode.",
        }
    elif not guide["authorization_ok"]:
        headline, reason = "Not ready", "Demo trading has no recorded owner approval on this machine."
        next_action = {
            "action": "review_authorization",
            "label": "See what is missing",
            "description": "An owner approval file for demo trading must be recorded first. It is a governance record — see Advanced → Governance. Live trading stays locked either way.",
        }
    elif guide["kill_switch"]["active"]:
        # The operator stop is reviewable regardless of connection state: the
        # UI promises "review and resume from Trading", and clearing the stop
        # never grants order permission (the stage must be prepared again and
        # every gate still applies). It must not be hidden behind the
        # connection/identity/readiness steps, which need a running terminal.
        headline, reason = "Stopped", "Trading is stopped by the kill switch."
        next_action = {
            "action": "resume",
            "label": "Review and resume",
            "description": "Clearing the stop is recorded with your reason. After that the demo account is prepared again from the start.",
            "requires_reason": True,
        }
    elif not conn["connected"]:
        headline, reason = "Not connected", "MetaTrader 5 is not connected."
        next_action = {
            "action": "check_connection",
            "label": "Check connection",
            "description": "Open MetaTrader 5 on this computer and sign in to your demo account, then press Check connection.",
        }
    elif conn["account_type"] != "Demo":
        headline, reason = "Not ready", "The connected account is not a demo account. QTS only trades demo accounts."
        next_action = {
            "action": "check_connection",
            "label": "Check connection",
            "description": "Sign in to your demo account in MetaTrader 5, then press Check connection.",
        }
    elif not pin["recorded"]:
        headline, reason = "Not ready", "The account identity has not been recorded yet."
        next_action = {
            "action": "record_identity",
            "label": "Record account identity",
            "description": "QTS records which demo account is connected, so a different account can never be traded by mistake.",
        }
    elif not pin["confirmed"]:
        headline, reason = "Not ready", "Please review the recorded account identity."
        next_action = {
            "action": "confirm_identity",
            "label": "Confirm this is my demo account",
            "description": "Check the account number, broker and server shown below. Confirming is your review that this is the right demo account.",
        }
    elif not pin["verified"]:
        headline, reason = "Not ready", "The connected account no longer matches the confirmed identity."
        next_action = {
            "action": "record_identity",
            "label": "Review the new account",
            "description": "The terminal now shows a different account than the one you confirmed. Review and record it again before any order.",
        }
    elif not readiness_passed:
        headline, reason = "Not ready", readiness_reason or "The safety checks did not pass."
        next_action = {
            "action": "check_connection",
            "label": "Check connection",
            "description": "QTS re-runs its safety checks: terminal, demo account, gold symbol and fresh prices.",
        }
    elif not guide["reconciliation"]["clean"]:
        headline, reason = "Not ready", "QTS and the broker disagree about open positions."
        next_action = {
            "action": "check_connection",
            "label": "Check connection",
            "description": "QTS compares its own records with the broker again. Trading stays off until they agree.",
        }
    elif stage not in ORDER_STAGES:
        headline, reason = "Almost ready", "The demo account still needs to be prepared."
        next_action = {
            "action": "prepare",
            "label": "Prepare demo trading",
            "description": "QTS runs the full safety checks, confirms your risk acknowledgement and prepares the demo account. No real money is involved.",
            "requires_confirmation": True,
        }
    elif not guide["permission"]["permitted"]:
        headline, reason = "Connection needs to be refreshed", "The proof that the terminal is healthy has expired."
        next_action = {
            "action": "refresh",
            "label": "Refresh connection",
            "description": "QTS re-proves the connection against the terminal. This is routine and takes a moment.",
            "requires_confirmation": True,
        }
    elif entry is None:
        headline, reason = "Not ready", "There is no approved trading plan yet."
        next_action = {
            "action": "none",
            "label": "Waiting for research",
            "description": "QTS only trades a plan that passed the research gates. Until one is registered, no order is possible — this is safety, not an error.",
        }
    else:
        headline, reason = "Ready for demo trading", None
        next_action = None

    guide["status"] = "ready" if can_trade else ("stopped" if guide["kill_switch"]["active"] else "blocked")
    guide["headline"] = headline
    guide["reason"] = reason
    guide["next"] = next_action

    guide["technical"] = {
        "stage": stage_record.as_dict(),
        "mode": mode,
        "authorization": policy.as_dict(),
        "authority": authority.as_dict(),
        "readiness": readiness,
        "identity_pin": report.get("identity_pin"),
        "symbol_mapping": report.get("symbol_mapping"),
        "order_check": report.get("order_check"),
        "kill_switch": kill,
        "reconciliation": reconciliation,
        "registry_reasons": list(entry_reasons or []),
        "note": "Engineering detail for Advanced views. None of it changes what the product workflow enforces.",
    }
    return guide


def _guide_response(result: dict[str, Any], ok: bool, headline: str, detail: str | None = None) -> Any:
    body = {"result": {"ok": ok, "headline": headline, "detail": detail}, "guide": result}
    return JSONResponse(status_code=200 if ok else 409, content=body)


@router.get("/api/demo/guide")
def demo_guide() -> dict[str, Any]:
    """The plain-language DEMO workflow state — one honest product picture.

    Read-only: probes the terminal, reads the durable state and translates it
    into the guided steps. Every gate still decides; this endpoint only
    reports. ``technical`` carries the engineering internals for Advanced.
    """
    return _build_guide()


@router.post("/api/demo/guide/record-identity")
def demo_guide_record_identity(payload: dict[str, Any] | None = None) -> Any:
    """Record the connected demo account as the identity pin (PENDING_REVIEW).

    Same semantics as ``qts demo connectivity --pin``: recording is evidence,
    not permission — the owner must confirm the pin before any order path can
    arm. Refuses when no terminal identity can be observed (fail closed).
    """
    from qts.execution.demo_identity import write_pin

    server = _bind()
    session = server._demo_session()
    try:
        report = session.connectivity_report()
    except Exception as exc:
        return _guide_response(_build_guide(session), False, "The account could not be recorded.", f"MetaTrader 5 did not answer: {exc}")
    identity = report.get("identity") or {}
    if not identity.get("ok"):
        return _guide_response(
            _build_guide(session),
            False,
            "The account could not be recorded.",
            "MetaTrader 5 is not connected. Open it, sign in to your demo account, then try again.",
        )
    try:
        adapter_identity = session.adapter.broker_identity()
        path = write_pin(adapter_identity, actor="api:guide", symbol=report.get("symbol_mapping"))
    except Exception as exc:
        return _guide_response(_build_guide(session), False, "The account could not be recorded.", f"{type(exc).__name__}: {exc}")
    guide = _build_guide(session)
    login = identity.get("login")
    server_name = identity.get("server")
    return _guide_response(
        guide,
        True,
        "Account identity recorded.",
        f"Recorded demo account {login} at {server_name}. Please review it and confirm. (pin: {path})",
    )


@router.post("/api/demo/guide/confirm-identity")
def demo_guide_confirm_identity(payload: dict[str, Any] | None = None) -> Any:
    """Owner confirmation of the recorded pin — requires explicit confirmation.

    Same semantics as ``qts demo connectivity --confirm-pin``. Without
    ``confirmed=true`` this is a 400: a review step must be an explicit act.
    """
    from qts.execution.demo_identity import confirm_pin

    body = payload or {}
    if not bool(body.get("confirmed")):
        raise HTTPException(400, "confirming the account identity requires explicit confirmed=true")
    server = _bind()
    session = server._demo_session()
    ok, detail = confirm_pin(actor="owner:desktop-ui")
    guide = _build_guide(session)
    if not ok:
        return _guide_response(guide, False, "The identity could not be confirmed.", detail)
    return _guide_response(guide, True, "Account identity confirmed.", detail)


@router.post("/api/demo/guide/prepare")
def demo_guide_prepare(payload: dict[str, Any] | None = None) -> Any:
    """Guided arming: advance the stage machine the way the CLI arm does.

    Requires explicit ``confirmed=true`` and ``risk_ack=true``. Every
    prerequisite the CLI demands is re-proven here against the live terminal:
    fresh readiness, demo account, symbol mapping, fresh quote, a confirmed
    identity pin, a valid owner authorization and durable authority
    enablement. Each stage transition is recorded by the SAME state machine —
    refusals are durable evidence. Already-prepared sessions re-verify
    instead of re-arming (no self-transition exists, by design).
    """
    from qts.lifecycle.demo_stage import DemoStage, StageTransitionError

    body = payload or {}
    confirmed = bool(body.get("confirmed"))
    risk_ack = bool(body.get("risk_ack"))
    if not confirmed or not risk_ack:
        raise HTTPException(400, "preparing demo trading requires explicit confirmed=true and risk_ack=true")

    server = _bind()
    session = server._demo_session()
    try:
        report = session.connectivity_report()
    except Exception as exc:
        return _guide_response(_build_guide(session), False, "Demo trading could not be prepared.", f"MetaTrader 5 did not answer: {exc}")

    prereq: dict[str, bool] = {
        "readiness_passed": bool((report.get("readiness") or {}).get("passed")),
        "account_is_demo": (report.get("identity") or {}).get("is_demo") is True,
        "symbol_ok": bool((report.get("symbol_mapping") or {}).get("ok")),
        "quote_fresh": bool((report.get("quote") or {}).get("fresh")),
    }
    done: list[str] = []
    try:
        current = session.stage.current().stage
        if current == DemoStage.HALTED.value:
            session.stage.reset_to_disabled(reason="guided preparation acknowledged the halt", actor="api:guide")
            done.append("halt acknowledged")
            current = DemoStage.DISABLED.value
        if current == DemoStage.DISABLED.value:
            session.stage.advance(
                DemoStage.STAGE_1_CONNECTIVITY,
                actor="api:guide",
                reason="guided preparation (desktop UI)",
                prerequisites=prereq,
            )
            done.append("connection verified")
            current = DemoStage.STAGE_1_CONNECTIVITY.value
        if current == DemoStage.STAGE_1_CONNECTIVITY.value:
            prereq2 = dict(prereq)
            prereq2["policy_authorized"] = bool(session.policy.enabled)
            prereq2["identity_pinned_confirmed"] = (report.get("identity_pin") or {}).get("verified") is True
            prereq2["operator_confirmation"] = True
            if prereq2["operator_confirmation"]:
                from qts.lifecycle.demo_authority import readiness_age_seconds
                from qts.lifecycle.demo_gate import demo_forward_readiness_report

                rpt = demo_forward_readiness_report(
                    mt5_module=None,
                    terminal_path=session.config.terminal_path,
                    symbol=session.canonical_symbol,
                    symbol_map=session.config.symbol_map or None,
                )
                decision = session.authority.enable(
                    readiness=rpt,
                    confirmed=True,
                    risk_ack=True,
                    readiness_age_s=readiness_age_seconds(rpt),
                    actor="api:guide",
                )
                prereq2["authority_enabled"] = bool(decision.execution_permitted)
            else:
                prereq2["authority_enabled"] = False
            session.stage.advance(
                DemoStage.STAGE_2_MIN_SIZE_ORDER,
                actor="api:guide",
                reason="guided preparation (desktop UI)",
                prerequisites=prereq2,
            )
            done.append("demo trading prepared")
        elif current in (DemoStage.STAGE_2_MIN_SIZE_ORDER.value, DemoStage.STAGE_3_FORWARD_OBSERVATION.value):
            outcome = session.reverify_authority(confirmed=True, risk_ack=True, actor="api:guide")
            if not outcome.get("reverified"):
                return _guide_response(
                    _build_guide(session),
                    False,
                    "Demo trading could not be refreshed.",
                    "; ".join(outcome.get("authority", {}).get("reasons") or ["the safety checks did not pass"]),
                )
            done.append("permission refreshed")
    except StageTransitionError as exc:
        return _guide_response(
            _build_guide(session),
            False,
            "Demo trading could not be prepared.",
            f"The safety checks refused: {exc}",
        )
    guide = _build_guide(session)
    return _guide_response(guide, True, "Demo trading is prepared.", " · ".join(done) if done else None)


@router.post("/api/demo/guide/refresh")
def demo_guide_refresh(payload: dict[str, Any] | None = None) -> Any:
    """Guided re-verification at the current order stage.

    Same gates as ``qts demo reverify``: fresh readiness against the terminal,
    explicit confirmation and risk acknowledgement. The stage is unchanged —
    this is a permission refresh, never a transition.
    """
    from qts.lifecycle.demo_stage import ORDER_STAGES

    body = payload or {}
    confirmed = bool(body.get("confirmed"))
    risk_ack = bool(body.get("risk_ack"))
    if not confirmed or not risk_ack:
        raise HTTPException(400, "refreshing the connection requires explicit confirmed=true and risk_ack=true")

    server = _bind()
    session = server._demo_session()
    if session.stage.current().stage not in ORDER_STAGES:
        return _guide_response(
            _build_guide(session),
            False,
            "Nothing to refresh yet.",
            "The demo account is not prepared. Prepare it first — QTS will tell you when.",
        )
    outcome = session.reverify_authority(confirmed=True, risk_ack=True, actor="api:guide")
    guide = _build_guide(session)
    if not outcome.get("reverified"):
        reasons = outcome.get("authority", {}).get("reasons") or ["the safety checks did not pass"]
        return _guide_response(guide, False, "The connection could not be refreshed.", "; ".join(reasons))
    return _guide_response(guide, True, "Connection refreshed.", "The terminal was re-checked and demo trading stays prepared.")


@router.post("/api/demo/guide/resume")
def demo_guide_resume(payload: dict[str, Any] | None = None) -> Any:
    """Clear the durable kill switch with a recorded reason (guided).

    Same semantics as ``qts demo clear-kill``: the flag is cleared and
    audited, the stage machine stays HALTED until the operator prepares the
    demo account again — clearing never resumes trading by itself.
    """
    body = payload or {}
    confirmed = bool(body.get("confirmed"))
    reason = str(body.get("reason") or "").strip()
    if not confirmed or not reason:
        raise HTTPException(400, "resuming requires explicit confirmed=true and a non-empty reason")

    from qts.risk.engine import RiskEngine, RiskLimits

    server = _bind()
    session = server._demo_session()
    engine = RiskEngine(RiskLimits(), db_path=session.db_path, persist_kill=True)
    was_killed = bool(engine.is_killed())
    engine.reset_kill()
    try:
        from qts.domain.events import DomainEvent, EventType
        from qts.observability.audit import SqliteAuditLog

        audit = SqliteAuditLog()
        audit.emit(
            DomainEvent(
                event_type=EventType.KILL_SWITCH,
                payload={
                    "action": "cleared",
                    "was_killed": was_killed,
                    "reason": reason,
                    "stage": session.stage.current().stage,
                    "actor": "api:guide",
                },
            )
        )
    except Exception as audit_error:  # nosec B110 — audit emission is intentionally best-effort; kill state is authoritative
        _ = audit_error
    guide = _build_guide(session)
    return _guide_response(
        guide,
        True,
        "The stop was cleared.",
        "The demo account still needs to be prepared again before an order. Trading did not resume by itself.",
    )


# Mount static UI if exists

