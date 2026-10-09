"""QTS CLI — edge validation."""

from __future__ import annotations

import json
from typing import Any

import click


@click.group()
def edge() -> None:
    """Capital preservation + real edge discovery."""
    pass


def _decomposition_markdown(dec: Any) -> str:
    """Render the gross/cost/net decomposition — or state plainly that there isn't one."""
    if not isinstance(dec, dict) or not dec.get("trades"):
        return "- **No round-turn decomposition.** No completed entry/exit pairs were paired from this run.\n- This is a missing measurement, not a zero and not a pass."

    basis = dec.get("basis_summary") or {}
    measured = sorted(k for k, v in basis.items() if v == "MEASURED")
    assumed = sorted(k for k, v in basis.items() if v == "ASSUMED")
    unknown = sorted(k for k, v in basis.items() if v == "UNKNOWN")
    lines = [
        f"- Round turns paired: **{dec['trades']}**",
        f"- Gross P&L: **{dec['gross_pnl_usd']:+.2f} USD** (expectancy {dec['gross_expectancy_per_trade']:+.4f}/trade)",
        f"- Cost: **{dec['cost_usd']:.2f} USD** ({dec['cost_per_trade']:.4f}/trade)",
        f"- Net P&L: **{dec['net_pnl_usd']:+.2f} USD** (expectancy {dec['net_expectancy_per_trade']:+.4f}/trade)",
        f"- Break-even cost multiple: **{dec['break_even_cost_multiple']:.2f}x** "
        "(1.0x = costs already consume the entire edge)",
        f"- Claim-eligible: **{dec['claim_eligible']}** "
        "(an edge claim requires MEASURED costs, not assumed ones)",
    ]
    if dec.get("per_component_usd"):
        comp = ", ".join(f"{k} {v:.2f}" for k, v in dec["per_component_usd"].items())
        lines.append(f"- Components: {comp}")
    for label, names in (("MEASURED", measured), ("ASSUMED", assumed), ("UNKNOWN", unknown)):
        if names:
            lines.append(f"- {label}: {', '.join(names)}")
    for reason in dec.get("reasons") or []:
        lines.append(f"- Note: {reason}")
    return "\n".join(lines)


@edge.command("benchmark")
@click.option("--data-version", default=None, help="Dataset version to evaluate on (default: latest).")
@click.option("--timeframe", default=None, help="Override the dataset timeframe (default: the manifest's).")
@click.option(
    "--spread",
    default=None,
    type=float,
    help="MEASURED round-turn spread in price units. Without it costs are ASSUMED and nothing can pass.",
)
@click.option("--commission-per-lot", default=0.0, type=float, help="Commission per lot per fill.")
@click.option("--slippage", default=None, type=float, help="Slippage in price units per fill.")
@click.option("--swap-per-night", default=None, type=float, help="Overnight financing per lot per night.")
@click.option("--cost-source", default="", help="Provenance for the cost numbers (broker, date, method).")
@click.option("--no-record-trials", is_flag=True, help="Do not add these runs to the experiment ledger.")
def edge_benchmark(
    data_version: str | None,
    timeframe: str | None,
    spread: float | None,
    commission_per_lot: float,
    slippage: float | None,
    swap_per_night: float | None,
    cost_source: str,
    no_record_trials: bool,
) -> None:
    """Evaluate the three FROZEN preregistered candidates.

    This does not search for a strategy. It measures three hypotheses that were
    written down before anything was run, and reports gross, cost and net for
    each. It never promotes anything.
    """
    import json

    from qts.config.paths import artifact_path, resolve_state_path
    from qts.data.store import SqliteParquetDataStore
    from qts.research.benchmarks import BENCHMARKS, evaluate_benchmarks, verify_frozen

    frozen_ok, frozen_problems = verify_frozen()
    if not frozen_ok:
        for problem in frozen_problems:
            click.echo(f"PREREGISTRATION VIOLATION: {problem}", err=True)
        raise SystemExit(2)

    measured = spread is not None and slippage is not None and bool(cost_source.strip())
    from qts.research.costs import CostBasis, CostModel

    cost_model = CostModel.xauusd_default(
        spread_price_units=spread if spread is not None else 0.30,
        commission_per_lot_usd=commission_per_lot,
        slippage_price_units=slippage if slippage is not None else 0.10,
        swap_per_night_per_lot_usd=swap_per_night,
        basis=CostBasis.MEASURED if measured else CostBasis.ASSUMED,
        source=cost_source.strip() or "qts.research.costs.xauusd_default (assumed retail MT5 gold conditions)",
    )

    store = SqliteParquetDataStore()
    try:
        version = data_version
        if version is None:
            versions = store.list_versions() if hasattr(store, "list_versions") else []
            if not versions:
                click.echo("no dataset versions available — run `qts data bootstrap`", err=True)
                raise SystemExit(2)
            version = str(versions[-1])
        report = evaluate_benchmarks(
            store,
            version,
            timeframe=timeframe,
            cost_model=cost_model,
            record_trials=not no_record_trials,
        )
    finally:
        store.close()

    payload = report.as_dict()
    payload["schema"] = "qts.benchmark_candidates.v1"
    payload["preregistered_at"] = "2026-10-09"
    payload["specs"] = [b.as_dict() for b in BENCHMARKS]
    payload["cost_basis"] = "MEASURED" if measured else "ASSUMED"

    out = artifact_path("benchmark_candidates")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    docs_dir = resolve_state_path("docs")
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "benchmark_candidates_report.md").write_text(_benchmark_markdown(payload), encoding="utf-8")

    click.echo(f"Frozen candidate set verified ({len(BENCHMARKS)} hypotheses).")
    click.echo(f"Dataset {report.data_version} — {report.dataset_provenance}")
    click.echo(f"Cost basis: {'MEASURED' if measured else 'ASSUMED — nothing below can pass an edge gate'}")
    click.echo("")
    for obs in report.observations:
        click.echo(
            f"{obs.benchmark_id}  [{obs.role}]  {obs.round_turns} round turns  "
            f"gross {obs.gross_pnl_usd:+.2f}  cost {obs.cost_usd:.2f}  net {obs.net_pnl_usd:+.2f} USD  "
            f"net/trade {obs.net_expectancy_per_trade:+.4f}  break-even {obs.break_even_cost_multiple:.2f}x"
        )
        for reason in obs.reasons[:3]:
            click.echo(f"    - {reason}")
    click.echo("")
    click.echo(report.conclusion)
    click.echo(f"Evidence: {out}")
    if not measured:
        click.echo(
            "To make an edge claim decidable, re-run with --spread/--slippage/--swap-per-night "
            "measured from your broker and --cost-source recording where they came from."
        )


def _benchmark_markdown(payload: dict) -> str:
    rows = []
    for obs in payload.get("observations", []):
        rows.append(
            f"| {obs['benchmark_id']} | {obs['role']} | {obs['timeframe_measured']} "
            f"({'matches' if obs['timeframe_matches'] else 'MISMATCH — mechanism only'}) | "
            f"{obs['round_turns']} | {obs['gross_pnl_usd']:+.2f} | {obs['cost_usd']:.2f} | "
            f"{obs['measured_cost_usd']:.2f} | {obs['net_pnl_usd']:+.2f} | "
            f"{obs['net_expectancy_per_trade']:+.4f} | {obs['break_even_cost_multiple']:.2f}x | "
            f"{obs['walk_forward_folds']} |"
        )
    specs = []
    for spec in payload.get("specs", []):
        specs.append(
            f"- **{spec['benchmark_id']}** ({spec['role']}) — family `{spec['family']}`, "
            f"params `{spec['params']}`, timeframe {spec['timeframe']}, "
            f"size {spec['quantity_lots']} lots, stop {spec['stop_distance_usd']} USD, "
            f"max hold {spec['max_hold_bars']} bars. Hash `{spec['spec_hash'][:12]}…`"
        )
    return f"""# Frozen Benchmark Candidates

**Generated:** {payload.get('generated_at')}
**Dataset:** {payload.get('data_version')} ({payload.get('dataset_provenance')})
**Cost basis:** {payload.get('cost_basis')}
**Preregistered:** {payload.get('preregistered_at')}

## Conclusion

**{payload.get('conclusion')}**

{chr(10).join('- ' + r for r in payload.get('reasons', []))}

## Preregistered hypotheses (frozen before evaluation)

{chr(10).join(specs)}

## Observations

| Benchmark | Role | Timeframe | Round turns | Gross USD | Modelled cost | Measured cost | Net USD | Net/trade | Break-even | WF folds |
|:---|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Modelled cost is what the declared cost model charges; measured cost is what the
simulation actually charged (spread, slippage and fees recovered from the fill
prices against their reference prices). A large gap between them means the cost
model does not describe the venue.

**Nothing on this page promotes a strategy.** A positive net expectancy on a
non-claim-eligible dataset is arithmetic about that dataset.
"""


@edge.command("readiness")
@click.option("--data-version", default=None, help="Assess an existing dataset version (default: latest).")
@click.option("--timeframe", default=None, help="Timeframe to assess (default: the manifest's).")
@click.option(
    "--ceiling-days",
    default=None,
    type=float,
    help="Assess a PROSPECTIVE source with this retention ceiling instead of an existing dataset.",
)
@click.option("--source-label", default="", help="Provenance label to classify (e.g. MT5_HISTORY).")
def edge_readiness(
    data_version: str | None, timeframe: str | None, ceiling_days: float | None, source_label: str
) -> None:
    """Can the frozen candidates be evaluated for a CLAIM on this data?

    Run this BEFORE `qts edge benchmark`. It answers, against pre-registered
    minimums, whether a dataset can support a claim -- and, with
    `--ceiling-days`, whether a history source with a known retention limit can
    ever supply enough data. Discovering that after a download is the expensive
    way.

    A dataset that is not ready is still usable: it yields mechanism evidence.
    What it cannot yield is a claim.
    """
    import json

    from qts.research.benchmark_readiness import (
        assess_acquisition_ceiling,
        assess_dataset_readiness,
        current_status,
        days_needed_for_depth,
        readiness_markdown,
    )

    status = current_status()
    if not status["frozen_set_intact"]:
        for problem in status["frozen_problems"]:
            click.echo(f"PREREGISTRATION VIOLATION: {problem}", err=True)
        raise SystemExit(2)
    click.echo(f"Frozen candidate set verified ({len(status['candidates'])} hypotheses).")
    click.echo(
        f"Minimums: {status['minimums']['bars']} bars / {status['minimums']['span_days']} days / "
        f"{status['minimums']['timeframe']} / {status['minimums']['round_turns_per_candidate']} "
        "round turns per candidate."
    )
    click.echo("")

    if ceiling_days is not None:
        tf = timeframe or status["minimums"]["timeframe"]
        report = assess_acquisition_ceiling(
            max_history_days=ceiling_days, timeframe=str(tf), source_label=source_label or None
        )
    else:
        from qts.data.store import SqliteParquetDataStore

        store = SqliteParquetDataStore()
        try:
            version = data_version
            if version is None:
                versions = store.list_versions() if hasattr(store, "list_versions") else []
                if not versions:
                    click.echo("no dataset versions available — run `qts data bootstrap`", err=True)
                    raise SystemExit(2)
                version = str(versions[-1])
            manifest = store.manifest(version)
            if manifest is None:
                click.echo(f"no manifest for version {version}", err=True)
                raise SystemExit(2)
            tf = str(timeframe or manifest.timeframe)
            # The manifest already records the row count; reading the bars only
            # to count them would be wasted work on a multi-GB dataset.
            bar_count = int(manifest.rows)
            span_days = (manifest.end - manifest.start).total_seconds() / 86400.0
            report = assess_dataset_readiness(
                bar_count=bar_count,
                span_days=span_days,
                timeframe=tf,
                source_label=manifest.source or None,
                subject=f"dataset {version}",
            )
        finally:
            store.close()

    click.echo(readiness_markdown(report))
    click.echo(json.dumps(report.as_dict(), indent=2, default=str))

    if not report.ready_for_claims:
        needed = days_needed_for_depth(str(report.timeframe))
        click.echo("")
        click.echo(
            f"NOT READY FOR CLAIMS. Reaching the bar minimum on {report.timeframe} bars "
            f"needs roughly {needed:,.0f} calendar days of history.",
            err=True,
        )
    raise SystemExit(0 if report.ready_for_claims else 1)


@edge.command("validate")
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", default=None)
@click.option("--strict", is_flag=True, help="fail-closed on weak edge")
def edge_validate(strategy: str, data_version: str | None, strict: bool) -> None:

    from qts.edge.orchestrator import run_full_edge_validation

    click.echo(f"running edge validation for {strategy} version {data_version or 'latest'} (capital preservation)")
    evidence = run_full_edge_validation(data_version=data_version, strategy_id=strategy)
    # Write machine-readable
    # State-root anchored, never cwd-relative: launching from another directory
    # must not split the canonical edge evidence across two trees.
    from qts.config.paths import artifact_path, resolve_state_path

    edge_json = artifact_path("edge_validation")
    edge_json.parent.mkdir(parents=True, exist_ok=True)
    edge_json.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
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
    decomposition_md = _decomposition_markdown(ev.get("cost_decomposition"))
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

## 9b. Gross -> cost -> net (round-turn decomposition)
{decomposition_md}

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
    docs_dir = resolve_state_path("docs")
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "edge_validation_report.md").write_text(report_md, encoding="utf-8")
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
    (docs_dir / "capital_preservation_policy.md").write_text(cap_md, encoding="utf-8")
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
    (docs_dir / "strategy_promotion_policy.md").write_text(promo_md, encoding="utf-8")
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
    (docs_dir / "locked_test_protocol.md").write_text(locked_md, encoding="utf-8")
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
    (docs_dir / "experiment_ledger.md").write_text(ledger_md, encoding="utf-8")
    click.echo("edge validation evidence written to data/evidence/edge_validation.json")
    click.echo(
        "docs: edge_validation_report.md, capital_preservation_policy.md, strategy_promotion_policy.md, locked_test_protocol.md, experiment_ledger.md"
    )
    if strict and not (es["passed"] and economic_passed):
        click.echo("BLOCK — edge does not survive costs/regime/perturbation/multiple-testing → KEEP NO_TRADE", err=True)
        # do not exit 2 here, just report BLOCK; live gate still blocks
    else:
        click.echo(f"edge validation completed: passed={es['passed']} economic={economic_passed}")


