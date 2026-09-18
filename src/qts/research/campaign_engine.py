"""Autonomous Campaign Engine — 11 steps, budget, never LIVE, self-audit."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.data.audit import audit_data_sources
from qts.research.campaign import CampaignConfig, run_campaign
from qts.research.intelligence import IntelligenceOrchestrator
from qts.research.memory import ResearchMemory
from qts.research.novelty import report_novelty


def run_autonomous_campaign(
    name: str,
    symbol: str = "XAUUSD",
    timeframe: str = "1H",
    data_version: str | None = None,
    max_trials: int = 20,
    max_runtime_s: float = 120,
    seed: int = 42,
) -> dict[str, Any]:
    """11 steps:
    1 review data, 2 review prior failures, 3 generate bounded plan, 4 create hypotheses,
    5 execute experiments, 6 store results, 7 attack candidates, 8 eliminate weak,
    9 refine surviving, 10 re-test, 11 produce evidence portfolio. Never moves to LIVE.
    """
    from qts.data.store import SqliteParquetDataStore

    store = SqliteParquetDataStore()
    if data_version is None:
        versions = store.list_versions()
        data_version = versions[-1] if versions else ""

    intel = IntelligenceOrchestrator()
    mem = ResearchMemory()

    # 1 review available data
    data_review = intel.inspect_data()
    # 1b data source audit
    data_audit = audit_data_sources()

    # 2 review prior failed hypotheses
    _prior_failures = mem.list_failures(limit=10)
    weaknesses = intel.inspect_evidence()["weaknesses"]

    # 3 generate bounded research plan
    plan = {
        "name": name,
        "data_version": data_version,
        "weaknesses": weaknesses,
        "data_limitation": data_review["limitation"],
        "budget": {
            "max_trials": max_trials,
            "max_runtime_s": max_runtime_s,
            "max_feature_count": 6,
            "max_param_combinations": max_trials,
            "max_mutation_depth": 2,
            "max_retries": 1,
            "max_data_scope": data_version,
            "seed": seed,
        },
        "mechanisms": [
            "trend persistence",
            "breakout failure",
            "volatility expansion",
            "range compression",
            "time-of-day",
            "event shock",
        ],
    }

    # 4 create hypotheses
    hyps = intel.generate_mechanism_hypotheses(
        mechanism_pool=plan["mechanisms"],
        symbol=symbol,
        timeframe=timeframe,
        data_description=data_review.get("limitation"),
    )

    # 5 execute experiments — run bounded campaign per family
    # Use existing campaign infra: run one campaign per hypothesis family batch
    cfg = CampaignConfig(
        name=name,
        symbol=symbol,
        timeframe=timeframe,
        data_version=data_version,
        family="trend",
        max_trials=min(6, max_trials),
        max_runtime_s=max_runtime_s / 2,
        max_param_combinations=min(6, max_trials),
        seed=seed,
    )
    # For autonomous, we run multiple families if budget allows
    # Here run just one for demo, but track as autonomous
    summary = run_campaign(cfg)
    # Also run one invented strategy family if budget remains
    if max_trials > 6:
        cfg2 = CampaignConfig(
            name=name + "-invented",
            symbol=symbol,
            timeframe=timeframe,
            data_version=data_version,
            family="volatility",
            max_trials=min(6, max_trials - 6),
            max_runtime_s=max_runtime_s / 2,
            max_param_combinations=min(6, max_trials - 6),
            seed=seed + 1,
        )
        summary2 = run_campaign(cfg2)
        # Merge
        summary["second_batch"] = summary2
        total_trials = summary["total_trials"] + summary2["total_trials"]
        passed = summary["passed"] + summary2["passed"]
        failed = summary["failed"] + summary2["failed"]
        summary["total_trials"] = total_trials
        summary["passed"] = passed
        summary["failed"] = failed

    # 6 store all results already via run_campaign

    # 7 attack candidates.  A campaign summary alone is not trial-bound
    # edge evidence, so no stale global JSON is reused as if it belonged to
    # these trials.
    attacks: dict[str, dict[str, Any]] = {}
    for trial in summary.get("trials", [])[:3]:
        sid = trial.get("strategy_id", "unknown")
        attacks[sid] = {
            "status": "UNAVAILABLE",
            "reason": "trial-bound edge-validation artifact was not produced by this campaign",
            "best_evidence_for": [],
            "best_evidence_against": ["missing trial-bound adversarial inputs"],
        }

    # 8 eliminate weak candidates
    surviving = [t for t in summary.get("trials", []) if t.get("passed")]
    eliminated = [t for t in summary.get("trials", []) if not t.get("passed")]

    # 9/10: do not claim a refinement was tested unless a new immutable
    # experiment was actually executed.  Keep a plan-only record for audit.
    refinements = []
    for s in surviving[:2]:
        refinements.append(
            {
                "original": s["strategy_id"],
                "status": "PLANNED_NOT_EXECUTED",
                "reason": "survivor refinement requires a separately persisted experiment and budget",
            }
        )
    _retest_summary = {
        "retested": 0,
        "planned": len(refinements),
        "status": "NOT_EXECUTED",
        "reason": "no refinement rerun was performed by this bounded campaign",
    }

    # 11 produce evidence portfolio
    trials_for_novelty = [
        {
            "family": t.get("strategy_id", "").split("_")[0],
            "mechanism": t.get("strategy_id", ""),
            "params": t.get("params", {}),
            "feature_lineage": [],
        }
        for t in summary.get("trials", [])
    ]
    novelty = report_novelty(trials_for_novelty)

    # White/Hansen tests require observed return vectors bound to this
    # campaign's immutable experiments.  No such vectors are returned by the
    # bounded campaign API, so preserve the missing evidence explicitly.
    wrc = {
        "status": "UNAVAILABLE",
        "reason": "campaign did not produce trial-bound return vectors for White reality check",
    }
    spa = {
        "status": "UNAVAILABLE",
        "reason": "campaign did not produce trial-bound return vectors for Hansen SPA",
    }
    # Self-audit is derived from this run, not a pre-written success story.
    total_trials = len(summary.get("trials", []))
    blocked_trials = sum(
        1
        for t in summary.get("trials", [])
        if t.get("conclusion") == "BLOCKED_INSUFFICIENT_DATA"
        or "BLOCKED" in " ".join(t.get("reasons", []))
    )
    missing_evidence = (
        blocked_trials > 0
        or summary.get("conclusion") == "BLOCKED_INSUFFICIENT_DATA"
        or summary.get("status") == "BLOCKED_INSUFFICIENT_DATA"
    )
    self_audit = {
        "did_we_leak": "NOT_PROVEN — campaign-level leakage audit is not implemented",
        "did_we_cherry_pick": f"MEASURED — {total_trials} trial records returned; no records were removed by this runner",
        "did_we_over_search": f"MEASURED — requested max_trials={max_trials}, executed_records={total_trials}",
        "did_we_reset_trial_count": "MEASURED — delegated to append-only experiment ledger",
        "did_we_reuse_test_set": "NOT_PROVEN — campaign-level frozen-test audit is not implemented",
        "did_we_overfit_params": "INSUFFICIENT_EVIDENCE — no trial-bound perturbation report",
        "did_we_under_model_costs": "INSUFFICIENT_EVIDENCE — no trial-bound gross/net cost report",
        "did_we_assume_unrealistic_fills": "INSUFFICIENT_EVIDENCE — no trial-bound execution/fill report",
        "did_we_confuse_correlation": "INSUFFICIENT_EVIDENCE — no trial-bound null/placebo report",
        "did_we_repeatedly_test_same_idea": f"MEASURED — novelty distinct={novelty['distinct_hypotheses']} of {total_trials} records",
        "did_we_suppress_failures": "MEASURED — failed/blocked trial records are retained by the campaign ledger",
        "verdict": "BLOCK — missing evidence is fail-closed" if missing_evidence else "BLOCK — independent audit gates remain unproven",
    }
    _block = True

    evidence_portfolio = {
        "generated_at": datetime.now(UTC).isoformat(),
        "research_question": f"Search for durable {symbol} edge under conservative execution assumptions",
        "hypotheses": [h.model_dump(mode="json") for h in hyps[:3]],
        "mechanism": "autonomous intelligence generated 3-6 falsifiable hypotheses",
        "data_used": data_audit,
        "trial_count": summary["total_trials"],
        "distinct_hypotheses": novelty["distinct_hypotheses"],
        "strategies_tested": len(summary.get("trials", [])),
        "failed_candidates": len(eliminated),
        "surviving_candidates": len(surviving),
        "strongest_for": list(attacks.values())[0].get("best_evidence_for") if attacks else [],
        "strongest_against": list(attacks.values())[0].get("best_evidence_against") if attacks else [],
        "DSR": {"status": "UNAVAILABLE", "reason": "no trial-bound multiple-testing report"},
        "PBO": {"status": "UNAVAILABLE", "reason": "no trial-bound probability-of-backtest-overfit report"},
        "white_reality_check": wrc,
        "hansen_spa": spa,
        "cost_sensitivity": {"status": "UNAVAILABLE", "reason": "no trial-bound gross/net cost decomposition"},
        "execution_sensitivity": {"status": "UNAVAILABLE", "reason": "no execution or fill observations in campaign"},
        "regime_behavior": {"status": "UNAVAILABLE", "reason": "no trial-bound regime report"},
        "robustness": {"status": "UNAVAILABLE", "reason": "no trial-bound perturbation report"},
        "forward_evidence": {"status": "UNAVAILABLE", "reason": "no forward observation evidence bound to campaign trials"},
        "unresolved_uncertainty": [
            data_review.get("limitation", "data limitation unavailable"),
            "campaign-level leakage/frozen-test audit is not implemented",
            "null, placebo, cost, execution, and forward evidence are not trial-bound",
        ],
        "never_winner_by_return": "No winner declared; campaign conclusion is fail-closed",
        "candidate_survival_standard": "No promotion without OOS, multiple testing, costs, perturbation, regime, null/placebo, expectancy, forward, and execution evidence",
        "self_audit": self_audit,
        "retest_summary": _retest_summary,
        "live_safety": "RESEARCH→VALIDATION→FORWARD→PAPER→SHADOW→MICRO→LIVE_ELIGIBLE never skipped, no LIVE move",
        "overall": "BLOCK — keep NO_TRADE",
    }

    # Persist research memory entries for failures
    for t in eliminated[:5]:
        from qts.research.memory import MemoryEntry

        entry = MemoryEntry(
            hypothesis_id=t.get("trial_id", ""),
            strategy_id=t.get("strategy_id", ""),
            family=t.get("strategy_id", "").split("_")[0],
            mechanism="autonomous",
            params=t.get("params", {}),
            failed_stage="DSR/PBO",
            reason=";".join(attacks.get(t.get("strategy_id", ""), {}).get("best_evidence_against", [])[:2])[:200]
            if t.get("strategy_id") in attacks
            else "scientific gate failure",
        )
        mem.remember(entry)

    # Write machine-readable
    Path("data/evidence/autonomous_campaign.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "plan": plan,
                "data_review": data_review,
                "evidence_portfolio": evidence_portfolio,
                "novelty": novelty,
                "attacks": attacks,
                "self_audit": self_audit,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {
        "plan": plan,
        "summary": summary,
        "evidence_portfolio": evidence_portfolio,
        "novelty": novelty,
        "self_audit": self_audit,
    }
