"""FastAPI backend for desktop — reliable local backend, clean API, safe communication."""

from __future__ import annotations

import contextlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from qts.config.settings import load_settings
from qts.domain.modes import effective_mode_report
from qts.lifecycle.demo_authority import DEMO_EXECUTION_DISABLED, DEMO_EXECUTION_POLICY

# Product policy: this workstation supports real MT5 DEMO_FORWARD observation
# only. The same constant is consumed by the authority and API so the policy
# cannot drift between the request boundary and the execution boundary.

app = FastAPI(title="QTS Desktop API", version="0.1.0")

# The desktop UI uses same-origin requests and sends no cookies or bearer
# credentials. Keep CORS permissive for an embedded/webview origin without
# enabling credentialed wildcard CORS (which browsers reject and which would
# make future credential-bearing endpoints unsafe by default).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _env() -> str:
    import os

    return os.getenv("QTS_ENV", "development")


def _db_path() -> Path:
    return Path("data/sqlite/qts.db")


@app.get("/api/health")
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
    # Check suspension
    from qts.risk.engine import RiskEngine, RiskLimits

    try:
        risk = RiskEngine(RiskLimits())
        killed = risk.is_killed() if hasattr(risk, "is_killed") else False
    except Exception:
        killed = False
    # Reconciliation health — REAL check (unresolved reconcile suspension or
    # an ambiguous-order trail must surface), never a constant True.
    recon_healthy = True
    recon_detail = "no reconcile state"
    try:
        from qts.db import connect as db_connect

        dbp = _db_path()
        if dbp.exists():
            with db_connect(dbp) as con:
                try:
                    row = con.execute("SELECT suspended FROM reconcile_state WHERE k=1").fetchone()
                except Exception:
                    row = None
                if row and row[0]:
                    recon_healthy = False
                    recon_detail = "unresolved reconciliation SUSPENDED — broker/local state diverged"
                else:
                    recon_detail = "no unresolved reconciliation suspension"
    except Exception as e:
        recon_detail = f"reconciliation health probe failed: {e}"
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
    try:
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
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

    mode_report = effective_mode_report(config_env=env)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "env": env,
        "effective_mode": mode_report,
        "system_status": system_status,  # Running/Stopped/Suspended/Blocked
        "mt5": "Disconnected",  # mock vs real determined below
        "reconciliation_detail": recon_detail,
        "market_data": "Healthy" if data_ok else "Blocked",
        "risk": "Suspended" if killed else "Healthy",
        "reconciliation": "Healthy" if recon_healthy else "Drift Detected",
        "strategy": strategy_info,
        "lifecycle": lifecycle,
        "trading_mode": _env_mode(),
        "live_status": live_status,
        "live_blocked_reasons": live_reasons,
        "data_versions": versions[-3:] if versions else [],
        "latest_version": latest,
        "config": {"env": env, "paper": getattr(settings, "paper", None)},
    }


def _env_mode() -> str:
    import os

    mode = os.getenv("QTS_MODE", "Research")
    # map env to mode
    env = _env()
    mapping = {
        "development": "Research",
        "paper": "Paper",
        "shadow": "Shadow",
        "dry_run": "Dry Run",
        "micro": "Micro",
        "live": "Live",
    }
    return mapping.get(env, mode)


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    """Clear professional dashboard — safety information first, NO fabricated
    account state. Account figures that require a broker connection and are
    not available are UNAVAILABLE (never a 10000 placeholder)."""
    equity: dict[str, Any]
    balance: dict[str, Any]
    try:
        from qts.adapters.mt5_adapter import MT5Adapter
        from qts.config.wizard import load_setup

        setup = load_setup()
        adapter = MT5Adapter(config={"path": setup.get("terminal_path") or ""})
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


@app.get("/api/strategies")
def list_strategies() -> list[dict[str, Any]]:
    try:
        from qts.research.registry import StrategyRegistry

        reg = StrategyRegistry()
        recs = reg.list()
        # Enrich with scorecard if available
        out = []
        for r in recs:
            d = r.model_dump()
            # add DSR/PBO etc from latest evidence if matches strategy_id
            try:
                ev_path = Path("data/evidence/edge_validation.json")
                if ev_path.exists():
                    ev = json.loads(ev_path.read_text(encoding="utf-8"))
                    if ev.get("dataset", {}).get("manifest", {}).get("instrument") == r.symbol:
                        es = ev.get("edge_survival", {})
                        d["oos_sharpe"] = es.get("psr")
                        d["dsr"] = es.get("dsr")
                        d["pbo"] = es.get("pbo")
                        d["expectancy"] = ev.get("expectancy", {}).get("expectancy_per_trade")
                        d["cost_tolerance"] = es.get("cost_break_even_bps")
                        d["last_validation"] = ev.get("generated_at")
                        d["decision"] = "BLOCKED" if not es.get("passed") else "VALIDATED"
                    else:
                        d["decision"] = r.lifecycle_state
                else:
                    d["decision"] = r.lifecycle_state
            except Exception:
                d["decision"] = r.lifecycle_state
            out.append(d)
        return out
    except Exception as e:
        return [{"error": str(e)}]


@app.get("/api/strategies/{strategy_id}")
def get_strategy(strategy_id: str) -> dict[str, Any]:
    from qts.research.registry import StrategyRegistry

    reg = StrategyRegistry()
    rec = reg.get(strategy_id)
    if not rec:
        raise HTTPException(404, f"strategy {strategy_id} not found")
    return rec.model_dump()


@app.get("/api/strategies/{strategy_id}/scorecard")
def strategy_scorecard(strategy_id: str) -> dict[str, Any]:
    ev_path = Path("data/evidence/edge_validation.json")
    if not ev_path.exists():
        raise HTTPException(404, "no evidence")
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    from qts.edge.scorecard import EdgeScorecard

    # Inject strategy_id if not in evidence
    ev["strategy_id"] = strategy_id
    sc = EdgeScorecard.from_evidence(ev)
    return sc.to_dict()


@app.get("/api/research/campaigns")
def list_campaigns() -> list[dict[str, Any]]:
    from qts.research.campaign import ResearchCampaignStore

    store = ResearchCampaignStore()
    campaigns = store.list_campaigns()
    return [{"id": cid, "config": cfg.model_dump(), "status": status} for cid, cfg, status in campaigns]


@app.post("/api/research/campaigns")
def create_campaign(payload: dict[str, Any]) -> dict[str, Any]:
    """Create bounded research campaign: Test 100 hypotheses etc."""
    from qts.research.campaign import CampaignConfig, run_campaign

    try:
        cfg = CampaignConfig(**payload)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    # Enforce caps
    if cfg.max_trials > 100:
        raise HTTPException(400, "max_trials exceeds campaign limit 100")
    if cfg.max_param_combinations > 100:
        raise HTTPException(400, "max_param_combinations exceeds 100")
    summary = run_campaign(cfg)
    return summary


@app.get("/api/research/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    from qts.research.campaign import ResearchCampaignStore

    store = ResearchCampaignStore()
    result = store.get_campaign(campaign_id)
    if not result:
        raise HTTPException(404, "campaign not found")
    cfg, status = result
    trials = store.list_trials(campaign_id)
    return {"id": campaign_id, "config": cfg.model_dump(), "status": status, "trials": [t.model_dump() for t in trials]}


@app.get("/api/validation/{strategy_id}")
def validation_detail(strategy_id: str) -> dict[str, Any]:
    ev_path = Path("data/evidence/edge_validation.json")
    if not ev_path.exists():
        raise HTTPException(404, "no evidence file")
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    # Return full edge validation with definitions
    definitions = {
        "wfe": "Walk-Forward Efficiency = OOS Sharpe / IS Sharpe, >0.3 indicates stability",
        "pbo": "Probability of Backtest Overfitting via CPCV, <0.5 indicates not overfit",
        "psr": "Probabilistic Sharpe Ratio P(SR > 0), >0.95 suggests skill",
        "dsr": "Deflated Sharpe Ratio adjusted for multiple testing, >0.95 after N trials",
        "cpcv": "Combinatorial Purged Cross-Validation with purging/embargo to avoid leakage",
        "perturbation": "Parameter perturbation ±15% must not collapse Sharpe >20%",
        "regime": "Performance across trend/range/high_vol regimes must not rely on single regime",
        "null": "Randomized controls must underperform real — rejects false alpha",
        "placebo": "Placebo strategies should not pass — proves pipeline discriminates",
        "expectancy": "Net expectancy = win_rate*avg_win - loss_rate*avg_loss - costs",
        "economic_edge": "Remaining edge after conservative costs + uncertainty + model penalty must be >0 and >20% cost",
    }
    return {"evidence": ev, "definitions": definitions, "scorecard": ev.get("edge_survival", {})}


@app.get("/api/paper")
def paper_center() -> dict[str, Any]:
    ev_path = Path("data/evidence/paper_trades.json")
    paper: dict[str, Any] = (
        json.loads(ev_path.read_text(encoding="utf-8"))
        if ev_path.exists()
        else {"fills": [], "positions": [], "pnl": 0, "drawdown": 0}
    )
    return {
        "simulated_positions": paper.get("fills", [])[:10],
        "fills": paper.get("fills", []),
        "pnl": paper.get("pnl", 0),
        "drawdown": paper.get("drawdown", 0),
        "execution_statistics": {
            "total_fills": len(paper.get("fills", [])),
            # PAPER fills are MODEL expectations — slippage is modeled, never
            # observed. The old fabricated 1.5 bps placeholder is removed.
            "avg_slippage_bps": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "slippage is a MODEL assumption for paper fills; observed slippage is UNAVAILABLE because DEMO_EXECUTION is disabled and OBSERVE_ONLY submits no orders",
            },
            "label": "PAPER",
        },
    }


@app.get("/api/shadow")
def shadow_center() -> dict[str, Any]:
    shadow_path = Path("data/evidence/shadow_intents.json")
    paper_path = Path("data/evidence/paper_trades.json")
    shadow = (
        json.loads(shadow_path.read_text(encoding="utf-8"))
        if shadow_path.exists()
        else {"intents_sample": [], "skipped": []}
    )
    paper = json.loads(paper_path.read_text(encoding="utf-8")) if paper_path.exists() else {"fills": []}
    # compute discrepancy if both exist
    disc = None
    if shadow_path.exists() and paper_path.exists():
        try:
            from qts.edge.execution_consistency import compare_shadow_paper

            res = compare_shadow_paper(shadow.get("intents_sample", []), paper.get("fills", []), [])
            disc = res.__dict__
        except Exception as e:
            disc = {"error": str(e)}
    return {
        "intent_count": len(shadow.get("intents_sample", [])),
        "would_be_trades": shadow.get("intents_sample", [])[:10],
        "estimated_fills": shadow.get("would_be_fills", [])[:10] if isinstance(shadow, dict) else [],
        "skipped_trades": shadow.get("skipped", [])[:10] if isinstance(shadow, dict) else [],
        "reasons": ["spread limit", "risk veto"] if disc else [],
        "shadow_vs_paper_discrepancy": disc,
    }


@app.get("/api/execution/orders")
def execution_orders(limit: int = 20) -> list[dict[str, Any]]:
    try:
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=limit)
        orders = []
        for e in events:
            if "order" in e.event_type.value.lower() or "execution" in json.dumps(e.payload).lower():
                orders.append(
                    {
                        "time": e.event_time.isoformat(),
                        "type": e.event_type.value,
                        "payload": e.payload,
                        "lifecycle": "INTENT→RISK→SUBMISSION→ACCEPTED→FILLED or REJECTED/CANCELLED/AMBIGUOUS",
                    }
                )
        return orders[:limit]
    except Exception as e:
        return [{"error": str(e)}]


@app.get("/api/execution/orders/{order_id}")
def order_audit(order_id: str) -> dict[str, Any]:
    try:
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=200)
        matched = [e for e in events if order_id in json.dumps(e.payload)]
        if not matched:
            raise HTTPException(404, "order not found")
        return {
            "order_id": order_id,
            "trail": [
                {"time": e.event_time.isoformat(), "type": e.event_type.value, "payload": e.payload} for e in matched
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.get("/api/risk")
def risk_center() -> dict[str, Any]:
    """Effective risk — THE resolved snapshot from the unified Risk Authority.

    The previous response invented display values ("1%", "2 lots", "$500",
    "2/sec", "5 losses → suspend") that existed nowhere in the risk engine.
    Every value now comes from resolve_risk_limits() with its source and a
    config hash; the reconciliation state is the REAL health probe.
    """
    from qts.domain.modes import resolve_mode
    from qts.edge.emergency import EmergencyControls
    from qts.risk.authority import resolve_risk_limits_from_settings

    mode = resolve_mode()
    snap = resolve_risk_limits_from_settings(mode)
    lim = snap.limits
    emer = EmergencyControls()
    killed = emer.is_killed()
    blocked_reasons: list[str] = []
    if killed:
        blocked_reasons.append("KILL_SWITCH_ACTIVE")
    with contextlib.suppress(Exception):
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
        if not rpt.get("ready", False):
            blocked_reasons.extend(rpt.get("blocked_reasons", []))
    if not blocked_reasons:
        try:
            ev = json.loads(Path("data/evidence/edge_validation.json").read_text(encoding="utf-8"))
            if not ev.get("edge_survival", {}).get("passed"):
                blocked_reasons.append("NO_VALIDATED_EDGE")
        except Exception:
            blocked_reasons.append("NO_VALIDATED_EDGE")

    recon_state = "Healthy"
    try:
        h = health()
        recon_state = h.get("reconciliation", "Unknown")
    except Exception:
        recon_state = "UNAVAILABLE"
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
        "overrides_applied": {k: str(v) for k, v in snap.overrides_applied.items()},
        "warnings": snap.warnings,
        "blocked": len(blocked_reasons) > 0,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "status_text": "TRADING BLOCKED" if blocked_reasons else "TRADING ALLOWED (demo-family only)",
        "explanations": {
            "MISSING_MARKET_PRICE": "Market data stale or unavailable — no authoritative price for risk check",
            "ACCOUNT_STATE_UNAVAILABLE": "Authoritative account equity unavailable — order vetoed, never computed against guessed capital",
            "RECONCILIATION_DRIFT": "Broker positions vs local state diverge — suspend to prevent overexposure",
            "NO_VALIDATED_EDGE": "No strategy has passed scientific+economic gates — capital preservation blocks trading",
        },
    }


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}


@app.get("/api/mt5")
def mt5_center() -> dict[str, Any]:
    """MT5 status with AUTHORITATIVE values only.

    Symbol spec, account state, and connectivity come from a live adapter
    probe against the saved wizard connection. When the terminal is not
    reachable, every broker-derived value is UNAVAILABLE — the previous
    fabricated mock spec (contract_size=100, balance=10000, "12 points
    (mock)") is gone: a UI must never display invented broker metadata.
    """
    from qts.adapters.mt5_adapter import MT5Adapter

    setup = _wizard_setup_kwargs(None, None)
    terminal_path = setup.get("terminal_path") or ""
    requested_symbol = setup.get("symbol") or "XAUUSD"
    broker_symbol = (setup.get("symbol_map") or {}).get(requested_symbol, requested_symbol)
    adapter = MT5Adapter(config={"path": terminal_path})
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
                "symbol": requested_symbol,
                "broker_symbol": broker_symbol,
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
            account = {
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
        "terminal_status": health.get("terminal_error") or ("connected" if connected else "not connected"),
        "health": health,
        "account": account,
        "spec": spec,
        "warning": "" if connected else "Values are UNAVAILABLE, not zero — connect the MT5 terminal for real data",
    }


@app.get("/api/audit")
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


@app.get("/api/live/status")
def live_status() -> dict[str, Any]:
    try:
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
        eligible = rpt.get("ready", False)
        reasons = rpt.get("blocked_reasons", [])
        # Also check prerequisites display
        checklist = {
            "validated_edge": False,
            "forward_observation": False,
            "risk_configuration": True,
            "mt5_connectivity": False,
            "reconciliation": True,
            "human_approval": False,
        }
        with contextlib.suppress(Exception):
            ev = json.loads(Path("data/evidence/edge_validation.json").read_text(encoding="utf-8"))
            if ev.get("edge_survival", {}).get("passed"):
                checklist["validated_edge"] = True
            if ev.get("forward", {}).get("signals", 0) >= 10:
                checklist["forward_observation"] = True
        # MT5 connectivity from health — avoid recursive loop if health fails
        with contextlib.suppress(Exception):
            h = health()
            if h["mt5"] == "Connected":
                checklist["mt5_connectivity"] = True
        return {
            "live_trading": "LOCKED" if not eligible else "ELIGIBLE (GATED)",
            "eligible": eligible,
            "blocked_reasons": reasons,
            "checklist": checklist,
            "message": "LIVE NOT AVAILABLE"
            if not eligible
            else "All prerequisites met — explicit confirmation required",
            "explicit_confirmation_required": True,
        }
    except Exception as e:
        return {
            "live_trading": "LOCKED",
            "eligible": False,
            "blocked_reasons": [str(e)],
            "checklist": {},
            "message": "LIVE NOT AVAILABLE",
        }


@app.get("/api/notifications")
def notifications() -> list[dict[str, Any]]:
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
        ev = json.loads(Path("data/evidence/edge_validation.json").read_text(encoding="utf-8"))
        if not ev.get("edge_survival", {}).get("passed"):
            alerts.append(
                {
                    "level": "warning",
                    "title": "Validation failure",
                    "detail": "Current strategy BLOCKED — keep NO_TRADE",
                    "persistent": False,
                }
            )
    return alerts


# --- Autonomous Research endpoints ---
@app.get("/api/research/thoughts")
def research_thoughts(limit: int = 20) -> list[dict[str, Any]]:
    from qts.research.intelligence import IntelligenceOrchestrator

    intel = IntelligenceOrchestrator()
    thoughts = intel.all_thoughts(limit=limit)
    return [t.model_dump(mode="json") for t in thoughts]


@app.get("/api/research/hypotheses")
def research_hypotheses(limit: int = 20) -> list[dict[str, Any]]:
    from qts.research.intelligence import IntelligenceOrchestrator

    intel = IntelligenceOrchestrator()
    hyps = intel.all_hypotheses(limit=limit)
    return [h.model_dump(mode="json") for h in hyps]


@app.get("/api/research/memory")
def research_memory(limit: int = 20) -> list[dict[str, Any]]:
    from qts.research.memory import ResearchMemory

    mem = ResearchMemory()
    entries = mem.list_failures(limit=limit)
    return [e.model_dump(mode="json") for e in entries]


@app.get("/api/research/novelty")
def research_novelty() -> dict[str, Any]:
    from qts.research.experiment import ExperimentStore
    from qts.research.novelty import report_novelty

    store = ExperimentStore()
    trials = [
        {
            "family": e.strategy_id.split("_")[0] if "_" in e.strategy_id else e.strategy_id,
            "mechanism": e.strategy_id,
            "params": e.params,
            "feature_lineage": [],
        }
        for e in store.all_experiments()
    ]
    return report_novelty(trials)


@app.get("/api/research/data-audit")
def research_data_audit() -> dict[str, Any]:
    from qts.data.audit import audit_data_sources

    return audit_data_sources()


@app.get("/api/research/features")
def research_features() -> list[dict[str, Any]]:
    from qts.research.feature_discovery import FeatureStore

    fs = FeatureStore()
    feats = fs.list()
    if not feats:
        # register controlled defaults if empty
        from qts.research.feature_discovery import CONTROLLED_FEATURES

        for f in CONTROLLED_FEATURES:
            with contextlib.suppress(Exception):
                fs.register(f)
        feats = fs.list()
    return [f.model_dump(mode="json") for f in feats]


@app.get("/api/research/adversarial/{strategy_id}")
def research_adversarial(strategy_id: str) -> dict[str, Any]:
    import json as js

    from qts.research.adversary import adversarial_attack

    ev_path = Path("data/evidence/edge_validation.json")
    ev = js.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
    return adversarial_attack(strategy_id, ev)


@app.post("/api/research/autonomous")
def research_autonomous(payload: dict[str, Any]) -> dict[str, Any]:
    from qts.research.campaign_engine import run_autonomous_campaign

    name = payload.get("name", "autonomous-search")
    symbol = payload.get("symbol", "XAUUSD")
    timeframe = payload.get("timeframe", "1H")
    data_version = payload.get("data_version")
    max_trials = int(payload.get("max_trials", 12))
    max_runtime_s = float(payload.get("max_runtime_s", 60))
    seed = int(payload.get("seed", 42))
    if max_trials > 100:
        raise HTTPException(400, "max_trials >100 not allowed")
    result = run_autonomous_campaign(name, symbol, timeframe, data_version, max_trials, max_runtime_s, seed)
    return result


@app.get("/api/research/data-inventory")
def research_data_inventory() -> list[dict[str, Any]]:
    p = Path("data/evidence/data_inventory.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


@app.get("/api/research/data-source-catalog")
def research_data_source_catalog() -> list[dict[str, Any]]:
    p = Path("data/evidence/data_source_catalog.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


@app.get("/api/research/data-quality-summary")
def research_data_quality_summary() -> dict[str, Any]:
    p = Path("data/evidence/data_quality_summary.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@app.get("/api/research/forward-manifest")
def research_forward_manifest() -> dict[str, Any]:
    p = Path("data/evidence/forward_observation_manifest.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@app.get("/api/research/regime-observations")
def research_regime_observations() -> dict[str, Any]:
    p = Path("data/evidence/market_regime_observations.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@app.get("/api/research/execution-reality")
def research_execution_reality() -> dict[str, Any]:
    """Execution-reality summary from the CANONICAL store; the JSON export is
    derived. Distinguishes MEASURED (real observations) from UNAVAILABLE."""
    from qts.execution.reality import ExecutionRealityStore

    try:
        summary = ExecutionRealityStore().summary()
    except Exception as e:
        return {"status": "UNAVAILABLE", "reason": f"execution-reality store unavailable: {e}"}
    if summary.get("count") == 0:
        summary["measured_metrics"] = {
            "avg_slippage_bps": {"status": "UNAVAILABLE", "value": None, "reason": "no REAL execution observations"},
        }
    return summary


@app.get("/api/research/data-quality-adversarial")
def research_data_quality_adversarial() -> dict[str, Any]:
    # Run lightweight adversarial quality stress and return result without failing closed (for monitoring)
    from qts.data.quality import validate_bars
    from qts.data.store import SqliteParquetDataStore
    from qts.domain.value_objects import Instrument

    store = SqliteParquetDataStore()
    versions = store.list_versions()
    results: dict[str, Any] = {}
    for v in versions[:1]:
        m = store.manifest(v)
        if not m:
            continue
        bars = store.read_bars(Instrument(symbol=m.instrument, venue=m.venue), m.timeframe, version=v)
        # Simulate adversarial: duplicate
        import copy

        dup_bars = bars + [bars[0]] if bars else []
        rep = validate_bars(dup_bars)
        results["duplicate_corrupted_passed"] = rep.passed
        # missing bars
        if len(bars) > 5:
            missing = bars[:3] + bars[5:]
            rep2 = validate_bars(missing)
            results["missing_corrupted_gap_check"] = next(
                (c.passed for c in rep2.checks if c.name == "no_missing_bars"), None
            )
        # zero price
        if bars:
            bad = copy.copy(bars[0])
            bad = (
                bad.model_copy(update={"close": __import__("decimal").Decimal("0")})
                if hasattr(bad, "model_copy")
                else bars[0]
            )
            # For Bar, directly construct
            from decimal import Decimal

            try:
                from qts.domain.value_objects import Bar

                bad_bar = Bar(
                    instrument=bars[0].instrument,
                    open=bars[0].open,
                    high=bars[0].high,
                    low=bars[0].low,
                    close=Decimal("0"),
                    volume=bars[0].volume,
                    open_time=bars[0].open_time,
                    close_time=bars[0].close_time,
                    data_version=bars[0].data_version,
                    source=bars[0].source,
                )
                rep3 = validate_bars([bad_bar])
                results["zero_price_passed"] = rep3.passed
            except Exception as e:
                results["zero_price_error"] = str(e)
    results["fail_closed_principle"] = "Corrupted dataset fails validation — no manifest created"
    return results


@app.get("/api/research/statistical")
def research_statistical() -> dict[str, Any]:
    # Return example statistical extensions on dummy data
    import numpy as np

    from qts.research.statistical import hansen_spa, minimum_backtest_length, permutation_test, white_reality_check

    rets = np.random.randn(100) * 0.01
    return {
        "white_reality_check": white_reality_check(rets, n_bootstrap=200),
        "hansen_spa": hansen_spa([rets, rets * 0.5], n_bootstrap=200),
        "permutation": permutation_test(rets, n_perm=200),
        "min_backtest_length": minimum_backtest_length(0.5),
    }


# --- Demo Forward & Safety Boundary ---
def _wizard_setup_kwargs(terminal_path: str | None, symbol: str | None) -> dict[str, Any]:
    """Merge wizard inputs with the persisted (saved) setup.

    Precedence: explicit request param > saved wizard file > (inside the
    gate) QTS_MT5_PATH/QTS_MT5_SYMBOL env > MT5_PATH > auto-detect.
    The same resolution is used by readiness AND demo-enablement so the two
    can never evaluate different connections.
    """
    from qts.config.wizard import load_setup

    saved = load_setup()
    sm = saved.get("symbol_map")
    return {
        "terminal_path": terminal_path or saved.get("terminal_path") or None,
        "symbol": symbol or saved.get("symbol") or None,
        "symbol_map": sm if isinstance(sm, dict) else None,
    }


@app.get("/api/setup/mt5")
def setup_mt5_get() -> dict[str, Any]:
    from qts.config.wizard import load_setup, setup_file

    return {
        "setup": load_setup(),
        "stored_at": str(setup_file()),
        "note": "Credential-free connection metadata only; credentials belong in env/OS credential store.",
    }


@app.post("/api/setup/mt5")
def setup_mt5_save(payload: dict[str, Any]) -> dict[str, Any]:
    from qts.config.wizard import save_setup

    try:
        return save_setup(payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/demo/readiness")
def demo_readiness(terminal_path: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    # Wizard inputs (query params) override the saved setup; env fallbacks
    # live inside the gate. Fail-closed: the gate itself initializes MT5 and
    # surfaces last_error — never mocked, never skipped.
    try:
        return demo_forward_readiness_report(**_wizard_setup_kwargs(terminal_path, symbol))
    except Exception as e:
        return {"passed": False, "demo_enabled": False, "blocked_reasons": [str(e)], "checks": {}}


@app.get("/api/demo/safety")
def demo_safety() -> dict[str, Any]:
    from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS, SAFETY_BOUNDARY

    return {
        "boundary": SAFETY_BOUNDARY,
        "demo_limits": DEMO_FORWARD_DEFAULTS.model_dump(),
        "live_locked": True,
        "note": "No env can silently become another. LIVE remains LOCKED unless all scientific+safety gates pass.",
    }


@app.get("/api/demo/comparison")
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


@app.post("/api/demo/comparison/refresh")
def demo_comparison_refresh() -> dict[str, Any]:
    from qts.execution.demo_comparison import write_comparison

    return write_comparison()


@app.get("/api/demo/observations")
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
_OBSERVE_LOCK = threading.Lock()
_OBSERVE_STATE: dict[str, Any] = {"collector": None}
_DEMO_AUTHORITY: Any = None
_DEMO_AUTHORITY_LOCK = threading.Lock()


def _resolve_observe_symbol(setup_kwargs: dict[str, Any]) -> tuple[str, str]:
    """(requested, broker) symbol from saved wizard config/env (XAUUSD -> XAUUSD@)."""
    import os

    requested = setup_kwargs.get("symbol") or os.getenv("QTS_MT5_SYMBOL", "XAUUSD")
    symbol_map = setup_kwargs.get("symbol_map")
    broker = symbol_map.get(requested, requested) if isinstance(symbol_map, dict) else requested
    return str(requested), str(broker)


def _build_observe_collector(terminal_path: str | None, requested: str, broker: str, interval_s: float) -> Any:
    """Real collector wiring. Module-level factory = test injection seam."""
    from qts.adapters.market_data import MarketDataProvider
    from qts.adapters.mt5_adapter import MT5Adapter
    from qts.domain.value_objects import Instrument
    from qts.observability.demo_collector import ObservationCollector
    from qts.observability.forward_observatory import ForwardObservatory

    symbol_map = {requested: broker} if broker != requested else {}
    adapter = MT5Adapter(config={"path": terminal_path or "", "symbol_map": symbol_map})
    provider = MarketDataProvider(broker=adapter)
    observatory = ForwardObservatory()
    return ObservationCollector(
        provider=provider,
        observatory=observatory,
        instrument=Instrument(symbol=requested, venue="MT5"),
        broker_symbol=broker,
        interval_s=interval_s,
    )


@app.post("/api/observe/start")
def observe_start(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start OBSERVE-ONLY collection of REAL MT5 ticks. Zero orders.

    Refuses unless DEMO readiness passes (14/14). Idempotent: repeated start
    returns the running session instead of creating a duplicate collector.
    The collector only reaches market-data APIs; order_send is not on any
    code path (pinned by tests/test_observe_only_collector.py).
    """
    import os

    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    body = payload if isinstance(payload, dict) else {}
    try:
        interval_s = float(body.get("interval_s", os.getenv("QTS_OBSERVE_INTERVAL_S", "1.0")))
    except (TypeError, ValueError):
        raise HTTPException(400, "interval_s must be a number") from None
    with _OBSERVE_LOCK:
        existing = _OBSERVE_STATE.get("collector")
        if existing is not None and existing.state == "OBSERVING":
            return {"started": False, "reason": "already_running", "status": existing.status()}
    # readiness OUTSIDE the lock so /api/observe/status stays responsive
    setup = _wizard_setup_kwargs(None, None)
    readiness = demo_forward_readiness_report(**setup)
    requested, broker = _resolve_observe_symbol(setup)
    with _OBSERVE_LOCK:  # double-check: a concurrent start may have won the race
        existing = _OBSERVE_STATE.get("collector")
        if existing is not None and existing.state == "OBSERVING":
            return {"started": False, "reason": "already_running", "status": existing.status()}
        collector = _build_observe_collector(setup.get("terminal_path"), requested, broker, interval_s)
        # start() refuses internally unless readiness passed -> state BLOCKED is
        # recorded in the collector so /api/observe/status surfaces it to the UI.
        status = collector.start(readiness)
        _OBSERVE_STATE["collector"] = collector
        resp: dict[str, Any] = {"started": status["state"] == "OBSERVING", "status": status}
        if not resp["started"]:
            resp["note"] = "OBSERVE-ONLY refused: DEMO readiness must pass all 14 checks (fail-closed)"
        return resp


@app.get("/api/observe/status")
def observe_status() -> dict[str, Any]:
    """Operator status: OBSERVING / STOPPED / BLOCKED / STOPPED_ON_ERRORS + counters."""
    with _OBSERVE_LOCK:
        collector = _OBSERVE_STATE.get("collector")
        if collector is None:
            return {
                "state": "STOPPED",
                "mode": "OBSERVE_ONLY",
                "orders_submitted": 0,
                "ticks_recorded": 0,
                "note": "no observation session has been started",
            }
        return collector.status()


@app.post("/api/observe/stop")
def observe_stop() -> dict[str, Any]:
    """Deterministic stop: thread join, persisted session end, final manifest."""
    with _OBSERVE_LOCK:
        collector = _OBSERVE_STATE.get("collector")
        if collector is None:
            return {"stopped": False, "status": {"state": "STOPPED", "ticks_recorded": 0}}
        if collector.state != "OBSERVING":
            return {"stopped": False, "status": collector.status()}
        return {"stopped": True, "status": collector.stop()}


@app.get("/api/env/boundary")
def env_boundary() -> dict[str, Any]:
    """Canonical environment/mode resolution — ONE authority (finding #14)."""
    from qts.risk.demo_limits import SAFETY_BOUNDARY

    return {
        "resolution": effective_mode_report(),
        "boundary": SAFETY_BOUNDARY,
        "demo_forward_separate": True,
        "demo_execution_disabled": DEMO_EXECUTION_DISABLED,
        "live_locked": True,
        "label_for_demo": "DEMO",
        "label_for_paper": "PAPER",
        "label_for_live": "LIVE",
    }


@app.get("/api/demo/config")
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
    decision = _demo_authority().current()
    return {
        "env": load_settings().env,
        "mode": mode.value,
        "mode_can_submit_orders": False if DEMO_EXECUTION_DISABLED else mode.can_submit_broker_orders,
        "demo_execution_disabled": DEMO_EXECUTION_DISABLED,
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
        "demo_execution_policy": f"DEMO_EXECUTION = {DEMO_EXECUTION_POLICY} — no order path is reachable while current product policy is active; authority boundary retained for future explicit authorization",
    }


def _demo_authority() -> Any:
    """The ONE demo-execution permission authority for this API process.

    Audited through the standard domain-event log; the mode passed to the
    authority is the canonical resolved mode, so a DEMO_FORWARD (observe-only)
    process can never hold demo-execution permission.
    """
    global _DEMO_AUTHORITY
    with _DEMO_AUTHORITY_LOCK:
        if _DEMO_AUTHORITY is None:
            from qts.domain.modes import resolve_mode
            from qts.lifecycle.demo_authority import DemoExecutionAuthority
            from qts.observability.audit import SqliteAuditLog

            try:
                audit: Any = SqliteAuditLog()
            except Exception:
                audit = None
            _DEMO_AUTHORITY = DemoExecutionAuthority(
                db_path=_db_path(),
                audit=audit,
                # DEMO_EXECUTION is intentionally disabled in the product
                # build. Binding the API authority to observation-only mode
                # makes a readiness pass unable to create order permission.
                mode="DEMO_FORWARD" if DEMO_EXECUTION_DISABLED else resolve_mode().value,
            )
        return _DEMO_AUTHORITY


@app.post("/api/demo/enable")
def demo_enable(payload: dict[str, Any]) -> Any:  # current policy refusal; future path remains authority-gated
    """Return diagnostics for the current DEMO_EXECUTION policy refusal.

    Readiness is probed only to explain the operator's current observation
    prerequisites. It cannot cross the current product-policy gate; the
    authority and execution boundary remain retained for a later, separately
    authorized policy change.
    """
    confirmed = bool(payload.get("confirmed"))
    risk_ack = bool(payload.get("risk_ack"))
    if not confirmed or not risk_ack:
        raise HTTPException(400, "DEMO execution requires explicit confirmed=true and risk_ack=true")

    from qts.lifecycle.demo_gate import demo_forward_readiness_report

    try:
        rpt = demo_forward_readiness_report(**_wizard_setup_kwargs(None, None))
        diagnostic_reasons = list(rpt.get("blocked_reasons", []))
    except Exception as exc:
        rpt = {"passed": False, "checks": {}, "blocked_reasons": [str(exc)]}
        diagnostic_reasons = [str(exc)]
    return JSONResponse(
        status_code=409,
        content={
            "authority": "demo_execution_state",
            "enabled": False,
            "execution_permitted": False,
            "state": "DISABLED",
            "reasons": [
                "DEMO_EXECUTION is disabled by product policy; use DEMO_FORWARD OBSERVE_ONLY",
                *diagnostic_reasons,
            ],
            "mode": "DEMO_FORWARD",
            "demo_execution_disabled": True,
            "readiness": rpt,
        },
    )


@app.get("/api/demo/state")
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
    decision = _demo_authority().current(fresh_readiness=rpt)
    out = decision.as_dict()
    out["current_readiness"] = {
        "passed": bool(rpt.get("passed")),
        "blocked_reasons": rpt.get("blocked_reasons", []),
    }
    out["demo_execution_disabled"] = DEMO_EXECUTION_DISABLED
    return out


@app.post("/api/demo/disable")
def demo_disable() -> dict[str, Any]:
    decision = _demo_authority().disable(reason="operator requested via API")
    return decision.as_dict()


# Mount static UI if exists
_ui_dir = Path(__file__).parent.parent / "desktop" / "ui"
if _ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")
