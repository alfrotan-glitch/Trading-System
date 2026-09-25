"""API routes — research and validation."""

from __future__ import annotations

import contextlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException

from qts.api.deps import (
    _evidence_attribution,
    _evidence_strategy_id,
)
from qts.config.paths import artifact_path

router = APIRouter()


def _bind():
    """Late lookup so tests can patch seams on ``qts.api.server``."""
    import qts.api.server as server

    return server


@router.get("/api/strategies")
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
                ev_path = artifact_path("edge_validation")
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




@router.get("/api/strategies/{strategy_id}")
def get_strategy(strategy_id: str) -> dict[str, Any]:
    from qts.research.registry import StrategyRegistry

    reg = StrategyRegistry()
    rec = reg.get(strategy_id)
    if not rec:
        raise HTTPException(404, f"strategy {strategy_id} not found")
    return rec.model_dump()




@router.get("/api/strategies/{strategy_id}/scorecard")
def strategy_scorecard(strategy_id: str) -> dict[str, Any]:
    ev_path = artifact_path("edge_validation")
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




@router.get("/api/research/campaigns")
def list_campaigns() -> list[dict[str, Any]]:
    from qts.research.campaign import ResearchCampaignStore

    store = ResearchCampaignStore()
    campaigns = store.list_campaigns()
    return [{"id": cid, "config": cfg.model_dump(), "status": status} for cid, cfg, status in campaigns]




@router.post("/api/research/campaigns")
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




@router.get("/api/research/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    from qts.research.campaign import ResearchCampaignStore

    store = ResearchCampaignStore()
    result = store.get_campaign(campaign_id)
    if not result:
        raise HTTPException(404, "campaign not found")
    cfg, status = result
    trials = store.list_trials(campaign_id)
    return {"id": campaign_id, "config": cfg.model_dump(), "status": status, "trials": [t.model_dump() for t in trials]}




@router.get("/api/validation/{strategy_id}")
def validation_detail(strategy_id: str) -> dict[str, Any]:
    ev_path = artifact_path("edge_validation")
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




@router.get("/api/research/thoughts")
def research_thoughts(limit: int = 20) -> list[dict[str, Any]]:
    from qts.research.intelligence import IntelligenceOrchestrator

    intel = IntelligenceOrchestrator()
    thoughts = intel.all_thoughts(limit=limit)
    return [t.model_dump(mode="json") for t in thoughts]




@router.get("/api/research/hypotheses")
def research_hypotheses(limit: int = 20) -> list[dict[str, Any]]:
    from qts.research.intelligence import IntelligenceOrchestrator

    intel = IntelligenceOrchestrator()
    hyps = intel.all_hypotheses(limit=limit)
    return [h.model_dump(mode="json") for h in hyps]




@router.get("/api/research/memory")
def research_memory(limit: int = 20) -> list[dict[str, Any]]:
    from qts.research.memory import ResearchMemory

    mem = ResearchMemory()
    entries = mem.list_failures(limit=limit)
    return [e.model_dump(mode="json") for e in entries]




@router.get("/api/research/novelty")
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




@router.get("/api/research/data-audit")
def research_data_audit() -> dict[str, Any]:
    from qts.data.audit import audit_data_sources

    return audit_data_sources()




@router.get("/api/research/features")
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




@router.get("/api/research/adversarial/{strategy_id}")
def research_adversarial(strategy_id: str) -> dict[str, Any]:
    import json as js

    from qts.research.adversary import adversarial_attack

    ev_path = artifact_path("edge_validation")
    ev = js.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
    return adversarial_attack(strategy_id, ev)




@router.post("/api/research/autonomous")
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




@router.get("/api/research/data-inventory")
def research_data_inventory() -> list[dict[str, Any]]:
    p = artifact_path("data_inventory")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []




@router.get("/api/research/data-source-catalog")
def research_data_source_catalog() -> list[dict[str, Any]]:
    p = artifact_path("data_source_catalog")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []




@router.get("/api/research/data-quality-summary")
def research_data_quality_summary() -> dict[str, Any]:
    p = artifact_path("data_quality_summary")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}




@router.get("/api/research/forward-manifest")
def research_forward_manifest() -> dict[str, Any]:
    p = artifact_path("forward_manifest")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}




@router.get("/api/research/regime-observations")
def research_regime_observations() -> dict[str, Any]:
    p = artifact_path("regime_observations")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}




@router.get("/api/research/data-completeness")
def research_data_completeness() -> dict[str, Any]:
    """Authoritative completeness disposition for the historical dataset.

    Reports exact expected vs observed rows, missing counts/percentages,
    recognized closures, quality gate result, and required action.
    """
    p = artifact_path("completeness_disposition")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {"status": "ERROR", "reason": str(e)}
    return {
        "status": "UNAVAILABLE",
        "reason": "completeness disposition artifact not found",
        "recovery_outcome": "RECOVERABLE ONLY BY NEW ACQUISITION",
    }




@router.get("/api/research/execution-reality")
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




@router.get("/api/research/data-quality-adversarial")
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




@router.get("/api/research/statistical")
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



