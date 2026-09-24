"""FastAPI backend for desktop — reliable local backend, clean API, safe communication."""

from __future__ import annotations

import contextlib
import json
import sqlite3
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


def _connection_adapter(symbol: str | None = None) -> tuple[Any, dict[str, Any]]:
    """The one MT5 connection for API probes (module-level = test injection seam).

    Every broker-facing API probe must use the SAME resolved connection — terminal
    path plus the canonical→venue alias table. Building adapters inline is how two
    endpoints came to ask the broker for ``XAUUSD`` while the DEMO session traded
    ``XAUUSD@``.
    """
    from qts.adapters.mt5_factory import adapter_from_setup

    return adapter_from_setup(symbol)


def _db_path() -> Path:
    """The DEMO state database — the SAME file the CLI reads.

    This used to be the relative literal ``data/sqlite/qts.db``, i.e. resolved
    against the backend process's working directory. The CLI resolves its own
    default the same way, so a backend launched from the repository root and a
    ``qts`` invocation from anywhere else read *different* stage, authority and
    journal state — one half of the reported "UI says DISABLED while CLI says
    AUTHORIZED" contradiction. Both now anchor at the machine-local state root
    (:mod:`qts.config.paths`), and the resolved location is published by
    ``/api/demo/state`` so agreement is checkable.
    """
    from qts.config.paths import artifact_path

    return artifact_path("db")


def _evidence_strategy_id(ev: dict[str, Any]) -> str | None:
    """Strategy identity recorded IN the evidence. Never inferred.

    A caller-supplied id, a URL path, or a matching instrument symbol is not
    attribution. An absent or blank ``strategy_id`` means the file does not
    name a strategy.
    """
    sid = ev.get("strategy_id") if isinstance(ev, dict) else None
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return None


def _evidence_attribution(ev: dict[str, Any], requested: str) -> dict[str, Any]:
    """Whether ``ev`` is validation of ``requested``, and why not if it isn't."""
    found = _evidence_strategy_id(ev)
    if found is None:
        return {
            "attributed": False,
            "requested_strategy_id": requested,
            "evidence_strategy_id": None,
            "reason": (
                "evidence file does not record a strategy_id; it cannot be treated as "
                "validation of the requested strategy"
            ),
        }
    if found != requested:
        return {
            "attributed": False,
            "requested_strategy_id": requested,
            "evidence_strategy_id": found,
            "reason": f"evidence strategy_id={found!r} does not match requested {requested!r}",
        }
    return {
        "attributed": True,
        "requested_strategy_id": requested,
        "evidence_strategy_id": found,
        "reason": "evidence strategy_id matches the request",
    }


def _reconciliation_status() -> tuple[bool, str, str]:
    """(healthy, status, detail) from the DURABLE reconcile-suspension row.

    ``status`` is one of ``Healthy`` | ``Drift Detected`` | ``UNAVAILABLE``.
    A probe that cannot be completed is never reported as Healthy: an
    unmeasurable reconciliation state is not a clean one.

    ONLY a missing ``reconcile_state`` table is benign — it honestly means no
    ExecutionEngine has ever persisted suspension state. A locked, damaged or
    otherwise unreadable store is ``UNAVAILABLE`` and not healthy, matching
    ``ExecutionEngine._load_reconcile_suspend`` and
    ``live_gate.check_reconciliation_health`` so all three readers of the same
    durable row cannot disagree.

    Shared by ``/api/health`` and ``/api/risk`` so both endpoints report the
    same fact and ``/api/risk`` no longer has to invoke the whole health
    report (which re-runs the full live-readiness gate) to read one row.
    """
    from qts.db import connect as db_connect

    try:
        dbp = _db_path()
        if not dbp.exists():
            return True, "Healthy", "no reconcile state"
        with db_connect(dbp) as con:
            try:
                row = con.execute("SELECT suspended FROM reconcile_state WHERE k=1").fetchone()
            except sqlite3.OperationalError as e:
                # ONLY a missing table is benign (nothing was ever persisted).
                # A locked or damaged store is unreadable, and "could not read
                # the suspension flag" must never be reported as "Healthy".
                if "no such table" in str(e).lower():
                    return True, "Healthy", f"no reconcile state recorded ({e})"
                return (
                    False,
                    "UNAVAILABLE",
                    f"reconciliation suspension state unreadable — fail closed ({type(e).__name__}: {e})",
                )
        if row and row[0]:
            return (
                False,
                "Drift Detected",
                "unresolved reconciliation SUSPENDED — broker/local state diverged",
            )
        if row is None:
            return True, "Healthy", "no reconcile state"
        return True, "Healthy", "no unresolved reconciliation suspension"
    except Exception as e:
        return False, "UNAVAILABLE", f"reconciliation health probe failed: {e}"


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
        # Through the one connection factory: an adapter built here without the
        # alias table asks the broker for a symbol that does not exist on this
        # venue (XAUUSD instead of XAUUSD@) and reports UNAVAILABLE.
        adapter, _connection = _connection_adapter()
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
                    # Symbol match is not strategy identity. Metrics are copied
                    # only when the file itself names this strategy_id.
                    if _evidence_strategy_id(ev) == r.strategy_id:
                        es = ev.get("edge_survival", {})
                        d["oos_sharpe"] = es.get("psr")
                        d["dsr"] = es.get("dsr")
                        d["pbo"] = es.get("pbo")
                        d["expectancy"] = ev.get("expectancy", {}).get("expectancy_per_trade")
                        d["cost_tolerance"] = es.get("cost_break_even_bps")
                        d["last_validation"] = ev.get("generated_at")
                        d["decision"] = "BLOCKED" if not es.get("passed") else "VALIDATED"
                        d["evidence_strategy_id"] = r.strategy_id
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
    attribution = _evidence_attribution(ev, strategy_id)
    if not attribution["attributed"]:
        # Do not stamp the URL id onto the file and do not build a scorecard
        # that would present another strategy's (or nobody's) evidence as this
        # strategy's result.
        raise HTTPException(409, attribution)
    from qts.edge.scorecard import EdgeScorecard

    sc = EdgeScorecard.from_evidence(ev)
    out = sc.to_dict()
    out["attribution"] = attribution
    return out


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
    attribution = _evidence_attribution(ev, strategy_id)
    return {
        "evidence": ev,
        "definitions": definitions,
        # An unattributed or mismatched file is disclosed, not hidden, and is
        # not presented as this strategy's scorecard.
        "scorecard": ev.get("edge_survival", {}) if attribution["attributed"] else None,
        "attribution": attribution,
        "decision": "ATTRIBUTED" if attribution["attributed"] else "UNATTRIBUTED",
    }


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
        # Divergence reasons are not inferred. The comparison result does not
        # record why intents and fills differ; inventing "spread limit" / "risk
        # veto" turned every comparison into a fabricated explanation.
        "reasons": {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": "the comparison does not record why intents and fills diverged; reasons are not inferred",
        },
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
            ev = json.loads(Path("data/evidence/edge_validation.json").read_text(encoding="utf-8"))
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
    adapter, connection = _connection_adapter()
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
            ev = json.loads(Path("data/evidence/edge_validation.json").read_text(encoding="utf-8"))
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
    from qts.adapters.mt5_adapter import normalize_terminal_path
    from qts.config.wizard import load_setup

    saved = load_setup()
    sm = saved.get("symbol_map")
    resolved_path = terminal_path or saved.get("terminal_path") or None
    return {
        "terminal_path": normalize_terminal_path(resolved_path),
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


@app.get("/api/runtime/state")
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
    """(canonical, broker) symbol from saved wizard config/env (XAUUSD -> XAUUSD@).

    Returns the CANONICAL name first, whichever spelling the operator saved: an
    observer configured with the venue alias used to return ``XAUUSD@`` as the
    "requested" symbol, from which an empty alias table was then derived — so
    observation recorded a venue spelling as if it were canonical.
    """
    import os

    from qts.adapters.mt5_adapter import broker_symbol as _broker_of
    from qts.adapters.mt5_adapter import canonical_symbol as _canonical_of

    requested = setup_kwargs.get("symbol") or os.getenv("QTS_MT5_SYMBOL", "XAUUSD")
    raw_map = setup_kwargs.get("symbol_map")
    symbol_map = {str(k): str(v) for k, v in raw_map.items()} if isinstance(raw_map, dict) else {}
    canonical = _canonical_of(str(requested), symbol_map)
    return canonical, _broker_of(canonical, symbol_map)


def _build_observe_collector(terminal_path: str | None, requested: str, broker: str, interval_s: float) -> Any:
    """Real collector wiring. Module-level factory = test injection seam."""
    from qts.adapters.market_data import MarketDataProvider
    from qts.adapters.mt5_adapter import MT5Adapter
    from qts.domain.value_objects import Instrument
    from qts.observability.demo_collector import ObservationCollector
    from qts.observability.forward_observatory import ForwardObservatory

    symbol_map = {requested: broker} if broker != requested else {}
    adapter = MT5Adapter(
        config={"path": terminal_path or "", "symbol_map": symbol_map, "symbol": requested}
    )
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
        "demo_execution_disabled": not _demo_policy().enabled,
        "demo_execution_policy": _demo_policy().state,
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


def _demo_policy() -> Any:
    """The resolved DEMO execution policy for this API process.

    Resolved from the recorded owner authorization artifact
    (``qts.lifecycle.demo_authorization``). Without a valid artifact this
    returns ``DEMO_EXECUTION = DISABLED BY POLICY``, which is the shipped
    default; the artifact itself can never permit LIVE.
    """
    from qts.domain.modes import resolve_mode
    from qts.lifecycle.demo_authorization import resolve_demo_execution_policy

    return resolve_demo_execution_policy(mode=resolve_mode().value)


def _demo_session(symbol: str | None = None) -> Any:
    """One wired DEMO session for API calls (same safeguards as the CLI)."""
    from qts.execution.demo_session import DemoSession, DemoSessionConfig
    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    setup = _wizard_setup_kwargs(None, None)
    session = DemoSession(
        DemoSessionConfig(
            symbol=symbol or setup.get("symbol") or "XAUUSD",
            terminal_path=setup.get("terminal_path"),
            symbol_map=setup.get("symbol_map") or {},
            db_path=_db_path(),
            actor="api",
        )
    )
    registry = load_registry()
    entry, _reasons = resolve_entry(registry)
    session._entry = entry
    return session


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
                # Binding the authority to the canonical resolved mode keeps a
                # DEMO_FORWARD (observe-only) process unable to hold execution
                # permission. When no owner authorization is recorded the API
                # stays observation-only, exactly as the product shipped.
                mode=resolve_mode().value if _demo_policy().enabled else "DEMO_FORWARD",
            )
        return _DEMO_AUTHORITY


@app.post("/api/demo/enable")
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

    decision = _demo_authority().enable(
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
    out["demo_execution_disabled"] = not _demo_policy().enabled
    out["demo_execution_policy"] = _demo_policy().state
    out["policy_reasons"] = list(_demo_policy().reasons)
    return out


@app.post("/api/demo/disable")
def demo_disable() -> dict[str, Any]:
    decision = _demo_authority().disable(reason="operator requested via API")
    return decision.as_dict()


@app.get("/api/demo/authorization")
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


@app.get("/api/demo/stage")
def demo_stage() -> dict[str, Any]:
    """DEMO execution stage machine (staged progression, never a jump)."""
    return _demo_session().stage.as_dict()


@app.get("/api/demo/preflight")
@app.post("/api/demo/preflight")
def demo_preflight(side: str = "BUY", lots: str | None = None, stop_loss: str | None = None) -> dict[str, Any]:
    """Run the DEMO pre-trade gate for a would-be order — submits nothing."""
    from decimal import Decimal

    session = _demo_session()
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


@app.post("/api/demo/order")
def demo_order(payload: dict[str, Any]) -> Any:
    """Submit ONE DEMO order through the gate (409 on any failed safeguard)."""
    from decimal import Decimal

    side = str(payload.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(400, "side must be BUY or SELL")
    if not payload.get("confirmed") or not payload.get("risk_ack"):
        raise HTTPException(400, "DEMO order requires explicit confirmed=true and risk_ack=true")

    session = _demo_session(payload.get("symbol"))
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


@app.post("/api/demo/kill")
def demo_kill(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Raise the durable kill switch and halt the DEMO stage machine."""
    reason = str((payload or {}).get("reason") or "operator kill via API")
    return _demo_session().raise_kill_switch(reason)


@app.get("/api/demo/journal")
def demo_journal(limit: int = 50) -> dict[str, Any]:
    """Forward-observation audit trail for DEMO orders."""
    from qts.execution.demo_journal import summarize

    session = _demo_session()
    return {
        "summary": summarize(session.journal).as_dict(),
        "orders": session.journal.list_orders(limit=limit),
        "label": "RESEARCH_DEMO_ORDER",
        "capital_class": "DEMO",
    }


# Mount static UI if exists
_ui_dir = Path(__file__).parent.parent / "desktop" / "ui"
if _ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")
