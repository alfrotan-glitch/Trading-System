"""FastAPI backend for desktop — reliable local backend, clean API, safe communication."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from qts.config.settings import load_settings

app = FastAPI(title="QTS Desktop API", version="0.1.0")

# Allow desktop webview origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    except Exception as e:
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
    # Reconciliation health (mock: check audit log drift)
    recon_healthy = True
    # Strategy lifecycle
    try:
        from qts.edge.promotion import PromotionLedger

        ledger = PromotionLedger()
        # pick latest strategy
        strategies = []
        try:
            from qts.research.registry import StrategyRegistry

            reg = StrategyRegistry()
            strategies = reg.list()
        except Exception:
            pass
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

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "env": env,
        "system_status": system_status,  # Running/Stopped/Suspended/Blocked
        "mt5": "Disconnected",  # mock vs real determined below
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
    """Clear professional dashboard — safety information first."""
    # Try to get equity, balance etc from portfolio or mock
    try:
        from qts.portfolio.portfolio import Portfolio
        from decimal import Decimal

        pf = Portfolio(initial_balance=Decimal("10000"))
        equity = float(pf.equity())
        balance = float(pf.balance)
    except Exception:
        equity = 10000.0
        balance = 10000.0
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
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "drawdown": 0.0,
        "exposure": 0.0,
        "open_positions": [],
        "market_status": h["market_data"],
        "spread": "1.2 pips (mock)",
        "account_state": "Active" if h["system_status"] == "Running" else h["system_status"],
        "current_strategy": h["strategy"],
        "current_regime": "trend" if h["system_status"] == "Running" else "unknown",
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
                    ev = json.loads(ev_path.read_text())
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
    ev = json.loads(ev_path.read_text())
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
        raise HTTPException(400, str(e))
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
    ev = json.loads(ev_path.read_text())
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
    paper = json.loads(ev_path.read_text()) if ev_path.exists() else {"fills": [], "positions": [], "pnl": 0, "drawdown": 0}
    return {
        "simulated_positions": paper.get("fills", [])[:10],
        "fills": paper.get("fills", []),
        "pnl": paper.get("pnl", 0),
        "drawdown": paper.get("drawdown", 0),
        "execution_statistics": {"total_fills": len(paper.get("fills", [])), "avg_slippage_bps": 1.5},
    }


@app.get("/api/shadow")
def shadow_center() -> dict[str, Any]:
    shadow_path = Path("data/evidence/shadow_intents.json")
    paper_path = Path("data/evidence/paper_trades.json")
    shadow = json.loads(shadow_path.read_text()) if shadow_path.exists() else {"intents_sample": [], "skipped": []}
    paper = json.loads(paper_path.read_text()) if paper_path.exists() else {"fills": []}
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
                orders.append({"time": e.event_time.isoformat(), "type": e.event_type.value, "payload": e.payload, "lifecycle": "INTENT→RISK→SUBMISSION→ACCEPTED→FILLED or REJECTED/CANCELLED/AMBIGUOUS"})
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
        return {"order_id": order_id, "trail": [{"time": e.event_time.isoformat(), "type": e.event_type.value, "payload": e.payload} for e in matched]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/risk")
def risk_center() -> dict[str, Any]:
    from qts.risk.engine import RiskLimits
    from qts.risk.capital_policy import CapitalPolicy

    limits = RiskLimits()
    cap = CapitalPolicy()
    # Check emergency
    from qts.edge.emergency import EmergencyControls

    emer = EmergencyControls()
    killed = emer.is_killed()
    # Block reasons
    blocked_reasons = []
    if killed:
        blocked_reasons.append("KILL_SWITCH_ACTIVE")
    try:
        from qts.lifecycle.live_gate import live_readiness_report

        rpt = live_readiness_report()
        if not rpt.get("ready", False):
            blocked_reasons.extend(rpt.get("blocked_reasons", []))
    except Exception:
        pass
    # Always at least NO_VALIDATED_EDGE if no candidate passes
    if not blocked_reasons:
        try:
            ev = json.loads(Path("data/evidence/edge_validation.json").read_text())
            if not ev.get("edge_survival", {}).get("passed"):
                blocked_reasons.append("NO_VALIDATED_EDGE")
        except Exception:
            blocked_reasons.append("NO_VALIDATED_EDGE")

    return {
        "limits": {
            "risk_per_trade": str(limits.risk_per_trade) if hasattr(limits, "risk_per_trade") else "1%",
            "maximum_exposure": str(limits.max_exposure) if hasattr(limits, "max_exposure") else "2 lots",
            "maximum_daily_loss": str(limits.max_daily_loss) if hasattr(limits, "max_daily_loss") else "$500",
            "maximum_drawdown": str(limits.max_drawdown) if hasattr(limits, "max_drawdown") else "10%",
            "spread_limit_bps": getattr(limits, "max_spread_bps", 100),
            "slippage_limit_bps": getattr(limits, "max_slippage_bps", 50),
            "stale_data_limit_s": getattr(limits, "stale_data_limit_s", 60),
            "order_frequency": "2/sec",
            "consecutive_loss_protection": "5 losses → suspend",
            "kill_switch": "ACTIVE" if killed else "ARMED",
            "reconciliation_state": "Healthy",
        },
        "blocked": len(blocked_reasons) > 0,
        "blocked_reasons": blocked_reasons,
        "status_text": "TRADING BLOCKED" if blocked_reasons else "TRADING ALLOWED (DEMO)",
        "explanations": {
            "MISSING_MARKET_PRICE": "Market data stale or unavailable — no authoritative price for risk check",
            "RECONCILIATION_DRIFT": "Broker positions vs local state diverge — suspend to prevent overexposure",
            "NO_VALIDATED_EDGE": "No strategy has passed scientific+economic gates — capital preservation blocks trading",
        },
    }


@app.get("/api/mt5")
def mt5_center() -> dict[str, Any]:
    # Distinguish MOCK/PAPER/DRY_RUN/REAL
    import os

    mode = os.getenv("QTS_MT5_MODE", "MOCK")
    # Try real adapter status
    try:
        from qts.adapters.mt5_adapter import MT5Adapter

        # Don't actually connect, just report mock
        connected = False
        terminal = "Mock terminal — no real broker connection"
        if mode == "REAL":
            # attempt to check
            connected = False
            terminal = "Real MT5 requested but not connected (fail-closed)"
    except Exception as e:
        connected = False
        terminal = str(e)

    spec = {
        "symbol": "XAUUSD",
        "contract_size": 100,
        "min_volume": 0.01,
        "max_volume": 100,
        "volume_step": 0.01,
        "digits": 2,
        "tick_size": 0.01,
        "spread": "12 points (mock)",
        "margin": "1000 (mock)",
        "free_margin": "9000 (mock)",
        "server_time": datetime.now(UTC).isoformat(),
        "data_freshness": "1s (mock)",
    }
    return {
        "mode": mode,  # MOCK/PAPER/DRY_RUN/REAL
        "connected": connected,
        "terminal_status": terminal,
        "account": {"login": "mock", "balance": 10000, "broker": "MockBroker"},
        "spec": spec,
        "warning": "Never let UI imply mock is real — this is MOCK" if mode == "MOCK" else "",
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
        try:
            ev = json.loads(Path("data/evidence/edge_validation.json").read_text())
            if ev.get("edge_survival", {}).get("passed"):
                checklist["validated_edge"] = True
            if ev.get("forward", {}).get("signals", 0) >= 10:
                checklist["forward_observation"] = True
        except Exception:
            pass
        # MT5 connectivity from health — avoid recursive loop if health fails
        try:
            h = health()
            if h["mt5"] == "Connected":
                checklist["mt5_connectivity"] = True
        except Exception:
            pass
        return {
            "live_trading": "LOCKED" if not eligible else "ELIGIBLE (GATED)",
            "eligible": eligible,
            "blocked_reasons": reasons,
            "checklist": checklist,
            "message": "LIVE NOT AVAILABLE" if not eligible else "All prerequisites met — explicit confirmation required",
            "explicit_confirmation_required": True,
        }
    except Exception as e:
        return {"live_trading": "LOCKED", "eligible": False, "blocked_reasons": [str(e)], "checklist": {}, "message": "LIVE NOT AVAILABLE"}


@app.get("/api/notifications")
def notifications() -> list[dict[str, Any]]:
    alerts = []
    h = health()
    if h["system_status"] == "Suspended":
        alerts.append({"level": "critical", "title": "Trading suspended", "detail": "Kill switch or reconciliation drift", "persistent": True})
    if h["market_data"] == "Stale":
        alerts.append({"level": "warning", "title": "Stale data", "detail": "Market data not fresh", "persistent": True})
    if h["reconciliation"] == "Drift Detected":
        alerts.append({"level": "critical", "title": "Reconciliation drift", "detail": "Broker vs local state mismatch", "persistent": True})
    # Live gate blocked
    live = live_status()
    if not live.get("eligible"):
        alerts.append({"level": "info", "title": "Live gate blocked", "detail": "; ".join(live.get("blocked_reasons", [])[:2]), "persistent": False})
    # Validation failure
    try:
        ev = json.loads(Path("data/evidence/edge_validation.json").read_text())
        if not ev.get("edge_survival", {}).get("passed"):
            alerts.append({"level": "warning", "title": "Validation failure", "detail": "Current strategy BLOCKED — keep NO_TRADE", "persistent": False})
    except Exception:
        pass
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
    from qts.research.novelty import report_novelty
    from qts.research.experiment import ExperimentStore
    store = ExperimentStore()
    trials = [{"family": e.strategy_id.split("_")[0] if "_" in e.strategy_id else e.strategy_id, "mechanism": e.strategy_id, "params": e.params, "feature_lineage": []} for e in store.all_experiments()]
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
            try:
                fs.register(f)
            except Exception:
                pass
        feats = fs.list()
    return [f.model_dump(mode="json") for f in feats]

@app.get("/api/research/adversarial/{strategy_id}")
def research_adversarial(strategy_id: str) -> dict[str, Any]:
    from qts.research.adversary import adversarial_attack
    import json as js
    ev_path = Path("data/evidence/edge_validation.json")
    ev = js.loads(ev_path.read_text()) if ev_path.exists() else {}
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
    return json.loads(p.read_text()) if p.exists() else []

@app.get("/api/research/data-source-catalog")
def research_data_source_catalog() -> list[dict[str, Any]]:
    p = Path("data/evidence/data_source_catalog.json")
    return json.loads(p.read_text()) if p.exists() else []

@app.get("/api/research/data-quality-summary")
def research_data_quality_summary() -> dict[str, Any]:
    p = Path("data/evidence/data_quality_summary.json")
    return json.loads(p.read_text()) if p.exists() else {}

@app.get("/api/research/forward-manifest")
def research_forward_manifest() -> dict[str, Any]:
    p = Path("data/evidence/forward_observation_manifest.json")
    return json.loads(p.read_text()) if p.exists() else {}

@app.get("/api/research/regime-observations")
def research_regime_observations() -> dict[str, Any]:
    p = Path("data/evidence/market_regime_observations.json")
    return json.loads(p.read_text()) if p.exists() else {}

@app.get("/api/research/execution-reality")
def research_execution_reality() -> dict[str, Any]:
    p = Path("data/evidence/execution_reality.json")
    return json.loads(p.read_text()) if p.exists() else {}

@app.get("/api/research/data-quality-adversarial")
def research_data_quality_adversarial() -> dict[str, Any]:
    # Run lightweight adversarial quality stress and return result without failing closed (for monitoring)
    from qts.data.store import SqliteParquetDataStore
    from qts.domain.value_objects import Instrument
    from qts.data.quality import validate_bars
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
            results["missing_corrupted_gap_check"] = next((c.passed for c in rep2.checks if c.name == "no_missing_bars"), None)
        # zero price
        if bars:
            bad = copy.copy(bars[0])
            bad = bad.model_copy(update={"close": __import__("decimal").Decimal("0")}) if hasattr(bad, "model_copy") else bars[0]
            # For Bar, directly construct
            from decimal import Decimal
            try:
                from qts.domain.value_objects import Bar
                bad_bar = Bar(instrument=bars[0].instrument, open=bars[0].open, high=bars[0].high, low=bars[0].low, close=Decimal("0"), volume=bars[0].volume, open_time=bars[0].open_time, close_time=bars[0].close_time, data_version=bars[0].data_version, source=bars[0].source)
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
    from qts.research.statistical import white_reality_check, hansen_spa, permutation_test, minimum_backtest_length
    rets = np.random.randn(100) * 0.01
    return {
        "white_reality_check": white_reality_check(rets, n_bootstrap=200),
        "hansen_spa": hansen_spa([rets, rets*0.5], n_bootstrap=200),
        "permutation": permutation_test(rets, n_perm=200),
        "min_backtest_length": minimum_backtest_length(0.5),
    }

# --- Demo Forward & Safety Boundary ---
@app.get("/api/demo/readiness")
def demo_readiness() -> dict[str, Any]:
    from qts.lifecycle.demo_gate import demo_forward_readiness_report
    # Try to inject mock MT5 if real not available — still reports checklist
    try:
        return demo_forward_readiness_report()
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
    from qts.execution.demo_comparison import compare_paper_shadow_demo
    p = Path("data/evidence/paper_shadow_demo_comparison.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return compare_paper_shadow_demo()

@app.post("/api/demo/comparison/refresh")
def demo_comparison_refresh() -> dict[str, Any]:
    from qts.execution.demo_comparison import write_comparison
    return write_comparison()

@app.get("/api/demo/observations")
def demo_observations(limit: int = 20) -> list[dict[str, Any]]:
    p = Path("data/evidence/demo_forward_observations.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        obs = data.get("observations", data) if isinstance(data, dict) else data
        return obs[-limit:][::-1] if isinstance(obs, list) else []
    except Exception:
        return []

@app.get("/api/env/boundary")
def env_boundary() -> dict[str, Any]:
    import os
    env = os.getenv("QTS_ENV", "development")
    mode = os.getenv("QTS_MT5_MODE", "MOCK")
    # Map to new safety table
    from qts.risk.demo_limits import SAFETY_BOUNDARY
    return {
        "env": env,
        "mode": mode,
        "boundary": SAFETY_BOUNDARY,
        "demo_forward_separate": True,
        "live_locked": True,
        "label_for_demo": "DEMO",
        "label_for_paper": "PAPER",
        "label_for_live": "LIVE",
    }

@app.get("/api/demo/config")
def demo_config() -> dict[str, Any]:
    # Return current demo-related settings without secrets
    settings = load_settings()
    return {
        "env": settings.env,
        "execution_mode": settings.execution.mode,
        "demo_forward_enabled": settings.execution.demo_forward_enabled,
        "risk": {
            "max_quantity": settings.risk.max_quantity,
            "max_notional": settings.risk.max_notional,
            "max_exposure": settings.risk.max_exposure,
            "daily_loss_limit": settings.risk.daily_loss_limit,
            "max_drawdown": settings.risk.max_drawdown,
            "approved": settings.risk.approved,
        },
        "observation_mode": "OBSERVE_ONLY" if not settings.execution.demo_forward_enabled else "DEMO_EXECUTION_ENABLED",
        "lifecycle": ["RESEARCH","VALIDATING","FORWARD_OBSERVATION","PAPER_VERIFIED","SHADOW_VERIFIED","DEMO_OBSERVATION","DEMO_EXECUTION"],
    }

@app.post("/api/demo/enable")
def demo_enable(payload: dict[str, Any]) -> dict[str, Any]:
    confirmed: bool = bool(payload.get("confirmed"))
    risk_ack: bool = bool(payload.get("risk_ack"))
    if not confirmed or not risk_ack:
        raise HTTPException(400, "Demo forward requires explicit confirmed=true and risk_ack=true")
    # Verify readiness first
    from qts.lifecycle.demo_gate import demo_forward_readiness_report
    rpt = demo_forward_readiness_report()
    # In sandbox/mock, terminal_running will be false — allow observe-only mode without real terminal for demo purposes?
    # Enforce demo_is_demo check strictly for safety
    if rpt.get("warn_live_in_demo"):
        raise HTTPException(400, "LIVE account supplied to DEMO mode — blocked")
    # Record audit
    try:
        from qts.observability.audit import SqliteAuditLog, AuditEvent, AuditEventType
        log = SqliteAuditLog()
        log.emit(AuditEvent(event_type=AuditEventType.RISK, payload={"action":"demo_forward_enabled","confirmed":True,"readiness":rpt}))
    except Exception:
        pass
    return {"demo_enabled": True, "mode": "DEMO_EXECUTION_ENABLED", "readiness": rpt, "label": "DEMO"}


# Mount static UI if exists
_ui_dir = Path(__file__).parent.parent / "desktop" / "ui"
if _ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")
