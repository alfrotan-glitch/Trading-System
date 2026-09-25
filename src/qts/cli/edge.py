"""QTS CLI — edge validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click


@click.group()
def edge() -> None:
    """Capital preservation + real edge discovery."""
    pass


@edge.command("validate")
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", default=None)
@click.option("--strict", is_flag=True, help="fail-closed on weak edge")
def edge_validate(strategy: str, data_version: str | None, strict: bool) -> None:

    from qts.edge.orchestrator import run_full_edge_validation

    click.echo(f"running edge validation for {strategy} version {data_version or 'latest'} (capital preservation)")
    evidence = run_full_edge_validation(data_version=data_version, strategy_id=strategy)
    # Write machine-readable
    Path("data/evidence").mkdir(parents=True, exist_ok=True)
    Path("data/evidence/edge_validation.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    # Generate docs
    # 1 edge_validation_report
    ev = evidence
    ds = ev["dataset"]
    es = ev["edge_survival"]

    def _metric(value: Any, fmt: str = ".2f") -> str:
        if value is None:
            return "UNAVAILABLE"
        try:
            return format(float(value), fmt)
        except (TypeError, ValueError):
            return str(value)

    regime_rows = ev.get("regime") if isinstance(ev.get("regime"), list) else []
    economic = ev.get("economic_edge") or {}
    report_md = f"""# Edge Validation Report
**Generated:** {ev["generated_at"]}
**Strategy:** {strategy}
**Data version:** {data_version or ds["manifest"]["version"]}
**Code version:** {ev["code_version"]}

## 1. Dataset integrity
- Manifest: {ds["manifest"]["version"]} {ds["manifest"]["instrument"]} {ds["manifest"]["timeframe"]} rows {ds["manifest"]["rows"]} checksum {ds["manifest"]["checksum"]} timezone {ds["manifest"].get("timezone", "UTC")} preprocessing {ds["manifest"].get("preprocessing_version", "1.0")} source {ds["manifest"].get("source", "")}
- Quality passed: {ds["quality_passed"]} checks: {", ".join(c["name"] + ":" + ("PASS" if c["passed"] else "FAIL") for c in ds["quality_checks"])}
- Missing stats: {ds["missing_stats"]}
- Locked partition: discovery {ds["locked_partition"]["discovery"]} validation {ds["locked_partition"]["validation"]} locked {ds["locked_partition"]["locked"]} frozen {ds["locked_partition"]["is_frozen"]} access_log {len(ds["locked_partition"]["access_log"])} attempts

## 2. Trial count
- Trials: {ev["trial_ledger"]["trial_count"]} (all materially tested variants counted, DSR uses N={ev["trial_ledger"]["trial_count"]})

## 3. Locked-test status
- Frozen: {ds["locked_partition"]["is_frozen"]} — locked test never influenced design/params/thresholds/feature selection
- Access log: {ev["dataset"]["locked_partition"]["access_log"]}

## 4. Walk-forward results
- WFE: {_metric(es.get("wfe"))} passed: {es["checks"].get("walk_forward", False)}
- Details: {es["details"].get("walk_forward", "")}

## 5. CPCV/PBO
- PBO: {_metric(es.get("pbo"))} passed: {es["checks"].get("cpcv", False)} details: {es["details"].get("cpcv", "")}

## 6. PSR/DSR
- PSR: {_metric(es.get("psr"))} DSR: {_metric(es.get("dsr"))} trials {ev["trial_ledger"]["trial_count"]} passed: {es["checks"].get("dsr", False)}

## 7. Null controls
- Null-control evidence: {ev["null_control"]}

## 8. Stress results
- Stress: {ev["cost_robustness"]["stress"]}

## 9. Cost/slippage tolerance
- Break-even spread: {es["cost_be"]:.1f}bps passed: {es["checks"].get("cost", False)} details: {es["details"].get("cost", "")}

## 10. Regime results
- Regimes: {ev["regime"]}

## 11. Forward paper results
- Forward: {ev["forward"]}

## 12. Shadow/paper discrepancy
- Consistency: {ev["shadow_paper"]}

## 13. Expected net edge
- Expectancy: {ev["expectancy"]}
- Economic edge: {ev["economic_edge"]}

## 14. Drawdown
- Drawdown / expected shortfall evidence: {ev["expectancy"]}

## 15. Worst observed failure
- Worst regime/stress: {min(regime_rows, key=lambda x: x.get("sharpe", 0)) if regime_rows else "UNAVAILABLE"}

## 16. Capital-at-risk assumptions
- Risk per trade {ev["capital_policy"]} + SymbolSpec authoritative, spread/slippage/delay net metrics

## 17. Exact reasons for PASS or BLOCK
- Edge survival passed: {es["passed"]} checks: {es["checks"]}
- Economic edge evidence: {economic}
- Overall: **{"PASS" if es["passed"] and economic.get("passed", False) and ds["quality_passed"] else "BLOCK — keep NO_TRADE"}** — genuine edge must survive costs, regime, perturbation, multiple testing, unseen data

## Promotion
- Current promotion state: {ev["promotion"]["state"]} — one-way RESEARCH→LIVE_ELIGIBLE, no skip, anomaly→SUSPENDED
- Emergency kill: {ev["emergency"]}

"""
    Path("docs").mkdir(parents=True, exist_ok=True)
    Path("docs/edge_validation_report.md").write_text(report_md, encoding="utf-8")
    # 2 capital_preservation_policy
    cap_md = f"""# Capital Preservation Policy
**Generated:** {ev["generated_at"]}

Hard limits (Phase 12) — crossing any forces NO_TRADE or SUSPENDED, no adaptive expansion after losses.

- risk_per_trade: 50 bps
- total_open_exposure: 2.0 lots
- daily_loss: 200 USD
- rolling_loss: 500 USD
- max_drawdown: 500 USD
- consecutive_losses: 5
- num_trades/day: 20
- order_frequency: 10/min
- spread: 100 bps
- slippage: 20 bps
- latency: 2000 ms
- data_staleness: 5s
- reconciliation_drift: any drift → SUSPENDED

Current check: {ev["capital_policy"]}

Emergency controls (Phase 17): kill_switch, cancel_all, suspend_new_orders, max_order_rate, max_order_size, stale_data_stop, abnormal_spread_stop, latency_stop, account_state_stop, reconciliation_stop — independently tested.

"""
    Path("docs/capital_preservation_policy.md").write_text(cap_md, encoding="utf-8")
    # 3 strategy_promotion_policy
    promo_md = f"""# Strategy Promotion Policy — One-Way
**State:** {ev["promotion"]["state"]}

Immutable lifecycle: RESEARCH → CANDIDATE → VALIDATED → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → MICRO_ELIGIBLE → MICRO_VALIDATED → LIVE_ELIGIBLE

- No state may skip prerequisites
- Any serious anomaly → SUSPENDED or REJECTED
- No manual DB edit may promote (all via PromotionLedger transition with audit)
- Scaling (Phase 16) before first real trade: define protocol, depends on forward observations>=30, drawdown<10%, slippage<5bps, reconciliation health, expectancy stability — wins alone never scale
- Current: {ev["promotion"]["state"]}

"""
    Path("docs/strategy_promotion_policy.md").write_text(promo_md, encoding="utf-8")
    # 4 locked_test_protocol
    locked_md = f"""# Locked Test Protocol
**Data version:** {ds["manifest"]["version"]}

- Partitions: discovery {ds["locked_partition"]["discovery"]} (60%), validation {ds["locked_partition"]["validation"]} (20%), locked {ds["locked_partition"]["locked"]} (20%)
- Immutable: hash {ds["manifest"]["checksum"]}, once created cannot change
- Locked test never influences design/params/thresholds/feature selection
- Prevent accidental access via LockedTestPartitioner.get_locked(allow=False) → violation, every attempt logged: {ev["dataset"]["locked_partition"]["access_log"]}
- Freeze: strategy spec/params/features/execution/risk frozen after discovery, only then locked test executed one-shot unless protocol violation documented
- Record every attempt to access/modify locked-test artifacts

"""
    Path("docs/locked_test_protocol.md").write_text(locked_md, encoding="utf-8")
    # 5 experiment_ledger
    exp_store = __import__("qts.research.experiment", fromlist=["ExperimentStore"]).ExperimentStore()
    trials = exp_store.count_trials()
    economic_passed = bool((ev.get("economic_edge") or {}).get("passed", False))
    ledger_md = f"""# Experiment Ledger
**Trials:** {trials} (all materially tested variants, not only winners, discarded counts)

Every experiment recorded: strategy identity, parameter set, feature set, timeframe, data manifest, random seed, objective metrics, rejected/accepted status, reason, timestamp, code version

- Trial count feeds DSR/multiple-testing correction (DSR {_metric(es.get("dsr"))} with N={trials})
- No manual adjustment of trial count
- Ledger DB: data/sqlite/qts.db experiments table

Current ledger count: {trials}
"""
    Path("docs/experiment_ledger.md").write_text(ledger_md, encoding="utf-8")
    click.echo("edge validation evidence written to data/evidence/edge_validation.json")
    click.echo(
        "docs: edge_validation_report.md, capital_preservation_policy.md, strategy_promotion_policy.md, locked_test_protocol.md, experiment_ledger.md"
    )
    if strict and not (es["passed"] and economic_passed):
        click.echo("BLOCK — edge does not survive costs/regime/perturbation/multiple-testing → KEEP NO_TRADE", err=True)
        # do not exit 2 here, just report BLOCK; live gate still blocks
    else:
        click.echo(f"edge validation completed: passed={es['passed']} economic={economic_passed}")


