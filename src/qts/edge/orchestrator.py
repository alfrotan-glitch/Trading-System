"""Capital-preservation edge validation orchestrator.

This module coordinates measurable backtest evidence and records missing
controls explicitly.  It never creates placebo scores, synthetic gross/net
curves, account state, forward observations, or trial rows merely to make a
report look complete.  DEMO observation and LIVE execution remain outside
this research-only path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from qts.data.locked_test import LockedTestPartitioner
from qts.data.store import SqliteParquetDataStore
from qts.edge.emergency import EmergencyControls
from qts.edge.promotion import PromotionLedger
from qts.research.experiment import ConclusionCode, Experiment, ExperimentStore, Hypothesis
from qts.research.readiness import ResearchDataRequirements, assess_dataset
from qts.validation.edge_validation import validate_edge_survival


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}


def _not_implemented(reason: str) -> dict[str, Any]:
    return {"status": "NOT_IMPLEMENTED", "value": None, "reason": reason}


def run_full_edge_validation(data_version: str | None = None, strategy_id: str = "sma_breakout") -> dict[str, Any]:
    """Run the research validation path and return a fail-closed evidence object.

    A strategy may be backtested on an available fixture for mechanism
    inspection, but claim eligibility is separately gated by provenance,
depth/span, quality, costs, controls, and forward evidence.
    """
    store = SqliteParquetDataStore()
    if data_version is None:
        versions = store.list_versions()
        data_version = versions[-1] if versions else None
    if not data_version:
        return {"error": "no data version", "conclusion": ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value}

    manifest = store.manifest(data_version)
    if manifest is None:
        return {"error": f"data version {data_version} not found", "conclusion": ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value}
    readiness = assess_dataset(
        store,
        data_version,
        requirements=ResearchDataRequirements(),
    )
    # ``Manifest`` rows from older checkouts may not persist the class; the
    # readiness assessment is the canonical inferred value and must be used
    # consistently in experiment and exported evidence provenance.
    manifest_data_class = readiness.data_class
    from qts.domain.value_objects import Instrument

    instr = Instrument(symbol=manifest.instrument, venue=manifest.venue)
    bars = store.read_bars(instr, manifest.timeframe, version=data_version) if store.version_usable(data_version) else []
    from qts.data.quality import dataset_missing_stats, validate_bars

    dq = validate_bars(bars) if bars else None
    missing = dataset_missing_stats(bars, manifest.timeframe) if bars else _unavailable("no readable bars")

    # The locked partition is an actual partition/access record.  It is not a
    # substitute for forward observations and is never relabelled as one.
    partitioner = LockedTestPartitioner()
    parts = partitioner.partition(bars, data_version) if bars else {"discovery": [], "validation": [], "locked": []}
    is_frozen = partitioner.is_frozen(data_version) if bars else False
    access_log = partitioner.access_log(data_version) if bars else []

    exp_store = ExperimentStore()
    hypothesis = Hypothesis(
        statement=f"{strategy_id} has a durable, cost-adjusted edge on {manifest.instrument} {manifest.timeframe}",
        question=f"Does {strategy_id} predict out-of-sample returns beyond a declared null after costs?",
        mechanism="strategy-defined signal mechanism; mechanism-specific interpretation remains bounded to the strategy code",
        prediction="The pre-registered strategy must pass independent walk-forward, stress, control, and forward gates.",
        null_hypothesis="The strategy has no incremental predictive or economic value beyond the baseline after costs.",
        competing_explanations=[
            "multiple-testing or selection artifact",
            "regime/sample dependence",
            "unmeasured spread, slippage, latency, or fill behavior",
        ],
        falsification_criteria=[
            "out-of-sample or walk-forward gate fails",
            "cost stress or gross/net decomposition is unavailable or fails",
            "CPCV/null/placebo/forward evidence is unavailable or fails",
        ],
        required_data={
            "data_version": data_version,
            "manifest_checksum": manifest.checksum,
            "instrument": manifest.instrument,
            "timeframe": manifest.timeframe,
            "minimum_bars": 5_000,
            "minimum_span_days": 180.0,
        },
        intended_horizon="the exact chronological dataset partition declared below",
        intended_population=f"{manifest.instrument} {manifest.timeframe} bars in manifest {data_version}",
        intended_regime="all observed regimes; regime stability must be measured, not assumed",
        rationale="Registered by run_full_edge_validation so this attempt and its negative result remain in experiment memory.",
    )
    exp_store.put_hypothesis(hypothesis)
    params = {"fast": 10, "slow": 20, "quantity": 0.1}
    from qts.observability.lineage import code_version

    exp = Experiment(
        hypothesis_id=hypothesis.id,
        strategy_id=strategy_id,
        params=params,
        data_version=data_version,
        dataset_provenance=manifest_data_class,
        dataset_manifest_hash=manifest.checksum,
        code_version=code_version(),
        seed=42,
        split_definition={
            "partitioner": "LockedTestPartitioner",
            "discovery_rows": len(parts["discovery"]),
            "validation_rows": len(parts["validation"]),
            "locked_rows": len(parts["locked"]),
            "locked_frozen": is_frozen,
        },
        cost_assumptions={"status": "ENGINE_DECLARED", "source": "BacktestEngine matching configuration"},
        exclusions=[
            "CPCV not implemented in this orchestrator",
            "randomized null/placebo not executed",
            "gross/net decomposition not available from BacktestResult",
            "forward broker observations not part of this call",
        ],
    )
    exp_store.put(exp)

    # Base and sensitivity reruns are real when readable bars exist.  They are
    # still mechanism evidence if the readiness report is not claim-eligible.
    from qts.backtest.engine import BacktestEngine
    from qts.validation.pipeline import ValidatorPipeline

    engine = BacktestEngine(store)
    eq_is = np.asarray([], dtype=float)
    eq_oos = np.asarray([], dtype=float)
    full = None
    folds: list[dict[str, float]] = []
    perturbed: list[float] = []
    stress: dict[float, float] = {}
    run_error: str | None = None
    if bars:
        try:
            full = engine.run(instr, manifest.timeframe, data_version, strategy_id=strategy_id, strategy_params=params, seed=42)
            equity = np.asarray(full.equity_curve, dtype=float)
            mid = len(equity) // 2
            eq_is, eq_oos = equity[:mid], equity[mid:]
            pipeline = ValidatorPipeline()
            train = max(100, len(bars) // 3)
            test = max(20, len(bars) // 10)
            for ts, te, vs, ve in pipeline.walk_forward_splits(len(bars), train=train, test=test, step=test):
                train_run = engine.run(
                    instr,
                    manifest.timeframe,
                    data_version,
                    strategy_id=strategy_id,
                    strategy_params=params,
                    seed=42,
                    start=bars[ts].open_time,
                    end=bars[te - 1].close_time,
                )
                test_run = engine.run(
                    instr,
                    manifest.timeframe,
                    data_version,
                    strategy_id=strategy_id,
                    strategy_params=params,
                    seed=42,
                    start=bars[vs].open_time,
                    end=bars[ve - 1].close_time,
                )
                folds.append({"is_sharpe": float(train_run.sharpe), "oos_sharpe": float(test_run.sharpe)})
            numeric_keys = [k for k, v in params.items() if isinstance(v, (int, float))]
            for key in numeric_keys:
                for factor in (0.8, 0.9, 1.1, 1.2):
                    variant = dict(params)
                    variant[key] = type(params[key])(params[key] * factor)
                    variant_run = engine.run(
                        instr,
                        manifest.timeframe,
                        data_version,
                        strategy_id=strategy_id,
                        strategy_params=variant,
                        seed=42,
                    )
                    perturbed.append(float(variant_run.sharpe))
            stress = engine.run_stress(instr, manifest.timeframe, data_version, strategy_id, params, spreads=[1.0, 1.5, 2.0])
        except Exception as exc:  # preserve the failed attempt, do not fill metrics
            run_error = f"{type(exc).__name__}: {exc}"

    # No control scores are supplied: NullControl cannot be applied to this
    # engine without executing a separately specified signal model.  Empty
    # inputs intentionally make the control/placebo gates fail.
    edge = validate_edge_survival(
        strategy_id,
        data_version,
        eq_is,
        eq_oos,
        None,
        eq_oos if len(eq_oos) else None,
        folds,
        [],
        perturbed,
        stress,
        max(1, exp_store.count_trials()),
        [],
        [],
        bars,
        [],  # BacktestResult exposes fills, not realized trade PnL attribution
        timeframe=manifest.timeframe,
    )
    claim_blocked = readiness.status != "READY"
    conclusion = (
        ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value
        if claim_blocked
        else (ConclusionCode.NO_EDGE_FOUND.value if not edge.passed else ConclusionCode.PROMISING_INSUFFICIENT.value)
    )
    exp_store.complete(
        exp.id,
        results={
            "readiness": readiness.as_dict(),
            "edge_checks": edge.checks,
            "edge_details": edge.details,
            "walk_forward_folds": folds,
            "run_error": run_error,
        },
        conclusion=conclusion,
        failure_reason=("; ".join(readiness.reasons) if claim_blocked else run_error),
    )

    # Forward evidence is read only from the canonical observation store when
    # it exists; locked historical rows are not counted as forward observations.
    forward_path = Path("data/sqlite/forward_observatory.db")
    if forward_path.exists():
        from qts.observability.forward_observatory import ForwardObservatory

        real_forward_count = ForwardObservatory(forward_path).real_observation_count(symbol=manifest.instrument)
        forward_obs: dict[str, Any] = {
            "status": "MEASURED" if real_forward_count else "INSUFFICIENT_EVIDENCE",
            "real_observations": real_forward_count,
            "note": "observation count only; divergence/realized PnL requires a bound session export",
        }
    else:
        forward_obs = _unavailable("canonical forward observation store does not exist")

    promo_state = PromotionLedger().get_state(strategy_id).value
    emergency = EmergencyControls()
    evidence = {
        "dataset": {
            "manifest": {
                **(manifest.model_dump() if hasattr(manifest, "model_dump") else manifest.dict()),
                "provenance_class": manifest_data_class,
            },
            "readiness": readiness.as_dict(),
            "quality_passed": dq.passed if dq else None,
            "quality_checks": (
                [{"name": c.name, "passed": c.passed, "details": c.details} for c in dq.checks] if dq else []
            ),
            "missing_stats": missing,
            "locked_partition": {
                "discovery": len(parts["discovery"]),
                "validation": len(parts["validation"]),
                "locked": len(parts["locked"]),
                "is_frozen": is_frozen,
                "access_log": access_log[:5],
            },
        },
        "trial_ledger": {
            "trial_count": exp_store.count_trials(),
            "experiment_id": exp.id,
            "configuration_hash": exp.configuration_hash,
            "cumulative": True,
        },
        "edge_survival": {
            "passed": edge.passed and not claim_blocked,
            "checks": edge.checks,
            "details": edge.details,
            "psr": edge.psr,
            "dsr": edge.dsr,
            "pbo": edge.pbo,
            "wfe": edge.wfe,
            "cost_be": edge.cost_break_even_bps,
            "conclusion": conclusion,
        },
        "null_control": _not_implemented("separate randomized signal model was not executed"),
        "placebo": _not_implemented("placebo signal model was not executed"),
        "cost_robustness": {"status": "MEASURED", "stress": stress} if stress else _unavailable("stress rerun unavailable"),
        "regime": _unavailable("regime result is not separately bound in this evidence object; edge details contain the gate"),
        "forward": forward_obs,
        "shadow_paper": _unavailable("shadow/paper artifacts are not bound to this experiment"),
        "capital_policy": _unavailable("authoritative account state is unavailable in research mode"),
        "expectancy": _unavailable("realized trade PnL attribution is unavailable from BacktestResult fills"),
        "economic_edge": _unavailable("gross/net cost decomposition is unavailable"),
        "promotion": {"state": promo_state, "advanced": False},
        "emergency": {"kill_switch": emergency.is_killed(), "execution_enabled": False},
        "order_check": {"status": "NOT_RUN", "ok": False, "reason": "research orchestrator has no order path"},
        "code_version": code_version(),
        "generated_at": datetime.now(UTC).isoformat(),
        "conclusion": conclusion,
    }
    return evidence
