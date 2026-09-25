"""API routes — system, setup, and health."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from qts.api.deps import (
    _demo_policy,
    _env,
    _env_mode,
    _evidence_strategy_id,
    _reconciliation_status,
    _unavailable,
)
from qts.config.paths import artifact_path
from qts.config.settings import load_settings
from qts.domain.modes import effective_mode_report

router = APIRouter()


def _bind():
    """Late lookup so tests can patch seams on ``qts.api.server``."""
    import qts.api.server as server

    return server


@router.get("/api/health")
def health() -> dict[str, Any]:
    """Startup health check: loads durable state, verifies suspension, pending orders, data, config, account, reconciliation."""
    settings = load_settings()
    env = _env()
    # Check data versions
    from qts.data.store import SqliteParquetDataStore

    try:
        store = SqliteParquetDataStore()
        versions = store.list_versions()
        data_ok = len(versions) > 0
        latest = versions[-1] if versions else None
    except Exception:
        data_ok = False
        latest = None
        versions = []
    # Check suspension — the DURABLE kill-switch authority (RiskEngine), which
    # is the same flag pre_trade() enforces. EmergencyControls() holds only a
    # per-instance in-memory flag, so a freshly constructed one always reports
    # "not killed" and can never surface an operator kill switch.
    from qts.risk.engine import RiskEngine, RiskLimits

    kill_state: dict[str, Any] = {"killed": False, "source": "unavailable"}
    try:
        risk = RiskEngine(RiskLimits())
        kill_state = risk.kill_state()
    except Exception as e:
        # Fail closed: an unreadable kill-switch state is treated as ACTIVE.
        kill_state = {
            "killed": True,
            "reason": f"kill-switch state unreadable: {type(e).__name__}: {e}",
            "source": "unreadable",
        }
    killed = bool(kill_state.get("killed"))
    recon_healthy, recon_status, recon_detail = _reconciliation_status()
    # Strategy lifecycle
    try:
        from qts.edge.promotion import PromotionLedger

        _ledger = PromotionLedger()
        # pick latest strategy
        strategies = []
        with contextlib.suppress(Exception):
            from qts.research.registry import StrategyRegistry

            reg = StrategyRegistry()
            strategies = reg.list()
        strategy_info = strategies[0].model_dump() if strategies else None
        lifecycle = strategy_info.get("lifecycle_state") if strategy_info else "RESEARCH"
    except Exception:
        lifecycle = "RESEARCH"
        strategy_info = None

    # Determine system status
    if killed:
        system_status = "Suspended"
    elif not data_ok:
        system_status = "Blocked"
    else:
        system_status = "Running"

    # Live gate — use live_readiness_report
    live_report: dict[str, Any] | None = None
    try:
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
        live_report = rpt
        ready = rpt.get("ready", False)
        blocked = rpt.get("blocked_reasons", [])
        if ready:
            live_status = "ELIGIBLE"
        elif blocked:
            live_status = "BLOCKED"
        else:
            live_status = "LOCKED"
        live_reasons = blocked
    except Exception as e:
        live_status = "LOCKED"
        live_reasons = [str(e)]

    # MT5 connectivity — MEASURED, never a constant. The report above already
    # performs the ONE real-terminal probe (``check_mt5_connectivity``, proof
    # tier ``real_environment``), so this reuses it instead of hardcoding a
    # value or paying for a second probe. When the gate itself could not be
    # evaluated the state is UNAVAILABLE, not "Disconnected": an unmeasured
    # connection must not be reported as a measured absent one.
    mt5_connectivity = live_report.get("mt5_connectivity") if isinstance(live_report, dict) else None
    if isinstance(mt5_connectivity, dict):
        mt5_status = "Connected" if mt5_connectivity.get("passed") else "Disconnected"
        mt5_detail = str(mt5_connectivity.get("detail") or "")
    else:
        mt5_status = "UNAVAILABLE"
        mt5_detail = "live readiness gate could not be evaluated — MT5 connectivity not probed"

    mode_report = effective_mode_report(config_env=env)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "env": env,
        "effective_mode": mode_report,
        "system_status": system_status,  # Running/Stopped/Suspended/Blocked
        "mt5": mt5_status,
        "mt5_detail": mt5_detail,
        "reconciliation_detail": recon_detail,
        "market_data": "Healthy" if data_ok else "Blocked",
        "risk": "Suspended" if killed else "Healthy",
        "kill_switch": {
            "state": "ACTIVE" if killed else "ARMED",
            "reason": kill_state.get("reason"),
            "updated_at": kill_state.get("updated_at"),
            "source": kill_state.get("source"),
        },
        "reconciliation": recon_status,
        "strategy": strategy_info,
        "lifecycle": lifecycle,
        "trading_mode": _env_mode(),
        "live_status": live_status,
        "live_blocked_reasons": live_reasons,
        "data_versions": versions[-3:] if versions else [],
        "latest_version": latest,
        "config": {"env": env, "paper": getattr(settings, "paper", None)},
    }




@router.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    """Clear professional dashboard — safety information first, NO fabricated
    account state. Account figures that require a broker connection and are
    not available are UNAVAILABLE (never a 10000 placeholder)."""
    equity: dict[str, Any]
    balance: dict[str, Any]
    try:
        # Through the one connection factory: an adapter built here without the
        # alias table asks the broker for a symbol that does not exist on this
        # venue (XAUUSD instead of XAUUSD@) and reports UNAVAILABLE.
        adapter, _connection = _bind()._connection_adapter()
        acct = adapter.account()
        equity = {"status": "MEASURED", "value": float(acct.equity), "source": acct.source}
        balance = {"status": "MEASURED", "value": float(acct.balance), "source": acct.source}
    except Exception as e:
        equity = {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": f"no authoritative broker account: {type(e).__name__}",
        }
        balance = {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": f"no authoritative broker account: {type(e).__name__}",
        }
    unrealized = {"status": "UNAVAILABLE", "value": None, "reason": "requires broker positions + authoritative marks"}
    realized = {"status": "UNAVAILABLE", "value": None, "reason": "requires broker deal history"}
    drawdown = {"status": "UNAVAILABLE", "value": None, "reason": "requires authoritative equity series"}
    # Positions
    try:
        # check latest execution via audit
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=5)
        latest_decision = events[0].payload if events else None
        latest_order = next((e.payload for e in events if "order" in json.dumps(e.payload).lower()), None)
    except Exception:
        latest_decision = None
        latest_order = None

    # Health
    h = health()

    return {
        "equity": equity,
        "balance": balance,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "drawdown": drawdown,
        "exposure": {"status": "UNAVAILABLE", "value": None, "reason": "requires broker positions"},
        "open_positions": [],
        "market_status": h["market_data"],
        "spread": {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": "live spread requires an active broker tick session",
        },
        "account_state": "Active" if h["system_status"] == "Running" else h["system_status"],
        "current_strategy": h["strategy"],
        "current_regime": {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": "regime requires observed market data; it is never inferred from system status",
        },
        "latest_decision": latest_decision,
        "latest_order": latest_order,
        "latest_fill": None,
        "latest_risk_veto": None,
        "reconciliation_status": h["reconciliation"],
        "health": h,
    }




@router.get("/api/mt5")
def mt5_center() -> dict[str, Any]:
    """MT5 status with AUTHORITATIVE values only.

    Symbol spec, account state, and connectivity come from a live adapter
    probe against the saved wizard connection. When the terminal is not
    reachable, every broker-derived value is UNAVAILABLE — the previous
    fabricated mock spec (contract_size=100, balance=10000, "12 points
    (mock)") is gone: a UI must never display invented broker metadata.
    """
    adapter, connection = _bind()._connection_adapter()
    terminal_path = connection["terminal_path"] or ""
    requested_symbol = connection["canonical_symbol"]
    broker_symbol = connection["broker_symbol"]
    connected = False
    health: dict[str, Any] = {}
    spec: dict[str, Any] = {}
    account: dict[str, Any] = {}
    try:
        health = adapter.health_check()
        connected = bool(health.get("connected"))
    except Exception as e:
        health = {"error": str(e)}
    if connected:
        try:
            s = adapter.get_symbol_spec(requested_symbol)
            spec = {
                "status": "MEASURED",
                "value": f"{broker_symbol} (contract={s.contract_size}, min={s.volume_min})",
                "symbol": requested_symbol,
                "broker_symbol": broker_symbol,
                "probed_symbol": broker_symbol,
                "alias_declared": connection["alias_declared"],
                "symbol_map": connection["symbol_map"],
                "contract_size": str(s.contract_size),
                "min_volume": str(s.volume_min),
                "max_volume": str(s.volume_max),
                "volume_step": str(s.volume_step),
                "digits": s.digits,
                "tick_size": str(s.tick_size),
                "trade_mode": s.trade_mode,
                "filling_mode": s.filling_mode,
                "stops_level": s.stops_level,
                "freeze_level": s.freeze_level,
                "source": "MT5 SymbolInfo (authoritative)",
            }
        except Exception as e:
            spec = {"status": "UNAVAILABLE", "value": None, "reason": f"symbol spec unavailable: {e}"}
        try:
            a = adapter.account()
            bal_str = f"{a.balance} {a.currency}" if a.currency else str(a.balance)
            account = {
                "status": "MEASURED",
                "value": bal_str,
                "login": health.get("account", {}).get("login"),
                "balance": str(a.balance),
                "currency": a.currency,  # may be None = UNAVAILABLE
                "leverage": str(a.leverage) if a.leverage is not None else None,
                "source": a.source,
            }
        except Exception as e:
            account = _unavailable(f"account unavailable: {e}")
    else:
        reason = "MT5 terminal not connected — no broker metadata is invented"
        spec = _unavailable(reason)
        account = _unavailable(reason)
    return {
        "mode": "REAL_TERMINAL" if connected else "DISCONNECTED",
        "connected": connected,
        "terminal_status": (
            health.get("session_error")
            or health.get("terminal_error")
            or ("connected" if connected else "not connected")
        ),
        "health": health,
        "account": account,
        "spec": spec,
        # Which connection was actually probed, and whether this process holds
        # the IPC link. Without this the panel could say "terminal connected"
        # while asking the broker for a symbol this venue does not have.
        "connection": {
            "terminal_path": terminal_path or None,
            "canonical_symbol": requested_symbol,
            "broker_symbol": broker_symbol,
            "symbol_map": connection["symbol_map"],
            "alias_declared": connection["alias_declared"],
            "setup_file": connection["setup_file"],
            "setup_exists": connection["setup_exists"],
            "session": adapter.session_state(),
        },
        "warning": "" if connected else "Values are UNAVAILABLE, not zero — connect the MT5 terminal for real data",
    }




@router.get("/api/audit")
def audit_center(limit: int = 50, q: str | None = None) -> list[dict[str, Any]]:
    try:
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=limit)
        out = []
        for e in events:
            payload_str = json.dumps(e.payload, default=str)
            if q and q.lower() not in payload_str.lower() and q.lower() not in e.event_type.value.lower():
                continue
            out.append({"time": e.event_time.isoformat(), "type": e.event_type.value, "payload": e.payload})
        return out
    except Exception as e:
        return [{"error": str(e)}]




@router.get("/api/notifications")
def notifications() -> list[dict[str, Any]]:
    from qts.api.routes.risk import live_status
    alerts = []
    h = health()
    if h["system_status"] == "Suspended":
        alerts.append(
            {
                "level": "critical",
                "title": "Trading suspended",
                "detail": "Kill switch or reconciliation drift",
                "persistent": True,
            }
        )
    if h["market_data"] == "Stale":
        alerts.append(
            {"level": "warning", "title": "Stale data", "detail": "Market data not fresh", "persistent": True}
        )
    if h["reconciliation"] == "Drift Detected":
        alerts.append(
            {
                "level": "critical",
                "title": "Reconciliation drift",
                "detail": "Broker vs local state mismatch",
                "persistent": True,
            }
        )
    # Live gate blocked
    live = live_status()
    if not live.get("eligible"):
        alerts.append(
            {
                "level": "info",
                "title": "Live gate blocked",
                "detail": "; ".join(live.get("blocked_reasons", [])[:2]),
                "persistent": False,
            }
        )
    # Validation failure
    with contextlib.suppress(Exception):
        ev = json.loads(artifact_path("edge_validation").read_text(encoding="utf-8"))
        if not ev.get("edge_survival", {}).get("passed"):
            sid = _evidence_strategy_id(ev)
            alerts.append(
                {
                    "level": "warning",
                    "title": "Validation failure",
                    "detail": (
                        f"strategy {sid} validation did not pass — keep NO_TRADE"
                        if sid
                        else "validation file on disk did not pass and does not name a strategy — not a current-strategy verdict"
                    ),
                    "persistent": False,
                }
            )
    return alerts




@router.get("/api/setup/mt5")
def setup_mt5_get() -> dict[str, Any]:
    from qts.config.wizard import load_setup, setup_file

    return {
        "setup": load_setup(),
        "stored_at": str(setup_file()),
        "note": "Credential-free connection metadata only; credentials belong in env/OS credential store.",
    }




@router.post("/api/setup/mt5")
def setup_mt5_save(payload: dict[str, Any]) -> dict[str, Any]:
    from qts.config.wizard import save_setup

    try:
        return save_setup(payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e




@router.get("/api/runtime/state")
def runtime_state() -> dict[str, Any]:
    """The authoritative runtime facts both surfaces must agree on.

    Mode (with provenance), the machine-local state root and every resolved
    artefact path, and the DEMO policy/stage. The UI shows this verbatim: if the
    backend and a CLI on the same machine disagree, this response names the file
    each one read, so the disagreement is diagnosable instead of mysterious.
    """
    from qts.config.paths import paths_report
    from qts.domain.modes import effective_mode_report
    from qts.lifecycle.demo_authorization import authorization_status

    mode_report = effective_mode_report()
    return {
        "mode": mode_report,
        "state": paths_report(),
        "demo_execution_policy": _demo_policy().as_dict() if hasattr(_demo_policy(), "as_dict") else str(_demo_policy().state),
        "authorization": {
            "valid": authorization_status().valid,
            "reasons": authorization_status().reasons,
        },
        "note": (
            "QTS_MODE/QTS_ENV override the persisted declaration; a real-capital mode can never be "
            "declared in the setup file, and no API/UI call can write it. LIVE stays locked."
        ),
    }




@router.get("/api/env/boundary")
def env_boundary() -> dict[str, Any]:
    """Canonical environment/mode resolution — ONE authority (finding #14)."""
    from qts.risk.demo_limits import SAFETY_BOUNDARY

    return {
        "resolution": effective_mode_report(),
        "boundary": SAFETY_BOUNDARY,
        "demo_forward_separate": True,
        "demo_execution_disabled": not _demo_policy().enabled,
        "demo_execution_policy": _demo_policy().state,
        "live_locked": True,
        "label_for_demo": "DEMO",
        "label_for_paper": "PAPER",
        "label_for_live": "LIVE",
    }



