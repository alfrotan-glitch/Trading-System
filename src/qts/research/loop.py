"""Research loop — IDEA → HYPOTHESIS → EXPERIMENT → VALIDATE → REVIEW.

This is the AI-measurable seam: AI proposes hypotheses, but promotion is gated
by real ValidationReport + AdversarialAgent review. No AI output bypasses the
gates; if validation fails the hypothesis is REJECTED with lineage.

Loop is deterministic when Agent is NullAgent; swap to LLM agent behind same
ResearchAgent protocol for real generation.

Flow:
    hypotheses = agent.propose(n, context)
    for h in hypotheses:
        store.put_hypothesis(h)
        exp = Experiment(hypothesis_id=h.id, strategy_id=..., params=..., data_version=..., seed=...)
        store.put(exp)
        backtest_result = engine.run(...)
        report = pipeline.validate(...)
        findings = adversary.review(report)
        if report.passed and not findings: promote to CANDIDATE
        else: store.reject(exp.id, reason=findings)
        audit.emit(...)

The loop itself is auditable; every decision carries hypothesis_id + experiment_id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from qts.backtest.engine import BacktestEngine
from qts.data.bootstrap import classify_source
from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument
from qts.observability.audit import AuditLog
from qts.research.agent import AdversarialAgent, ResearchAgent
from qts.research.experiment import Experiment, ExperimentStore
from qts.research.readiness import ResearchDataRequirements, assess_bars
from qts.validation.pipeline import ValidatorPipeline

logger = logging.getLogger(__name__)


@dataclass
class LoopResult:
    hypothesis_id: str
    experiment_id: str
    validation_passed: bool
    adversarial_findings: list[str]
    action: str  # CANDIDATE | REJECTED | RESEARCH


class ResearchLoop:
    def __init__(
        self,
        agent: ResearchAgent,
        adversary: AdversarialAgent | None = None,
        store: ExperimentStore | None = None,
        engine: BacktestEngine | None = None,
        pipeline: ValidatorPipeline | None = None,
        audit: AuditLog | None = None,
    ):
        self.agent = agent
        self.adversary = adversary or AdversarialAgent()
        self.store = store or ExperimentStore()
        self.engine = engine  # caller injects with real DataStore
        self.pipeline = pipeline or ValidatorPipeline()
        self.audit = audit

    def propose(self, n: int = 3, context: str = "") -> list[str]:
        hyps = self.agent.propose(n=n, context=context)
        ids: list[str] = []
        for h in hyps:
            self.store.put_hypothesis(h)
            ids.append(h.id)
            logger.info("proposed %s: %s", h.id, h.statement)
        return ids

    def run_experiment(
        self,
        hypothesis_id: str,
        strategy_id: str,
        params: dict[str, Any],
        data_version: str,
        instrument: Instrument,
        timeframe: str = "1H",
        seed: int = 42,
    ) -> LoopResult:
        """Run one reproducible experiment or persist why it cannot run.

        This method deliberately does not manufacture folds, nulls, controls,
        or parameter stability from a baseline score.  Missing evidence is a
        durable BLOCKED/REJECTED outcome in the experiment ledger.
        """
        hypothesis = self.store.get_hypothesis(hypothesis_id)
        if self.engine is None:
            self.engine = BacktestEngine(SqliteParquetDataStore())
        data_store = getattr(self.engine, "data_store", None)
        manifest = data_store.manifest(data_version) if data_store is not None else None
        bars = (
            data_store.read_bars(instrument, timeframe, version=data_version)
            if data_store is not None and manifest is not None
            else []
        )
        provenance = getattr(manifest, "provenance_class", None) or classify_source(
            getattr(manifest, "source", "") if manifest else ""
        )
        manifest_hash = getattr(manifest, "checksum", "") if manifest else ""
        from qts.observability.lineage import code_version

        exp = Experiment(
            hypothesis_id=hypothesis_id,
            strategy_id=strategy_id,
            params=params,
            data_version=data_version,
            dataset_provenance=provenance,
            dataset_manifest_hash=manifest_hash,
            code_version=code_version(),
            seed=seed,
            split_definition={"method": "chronological_walk_forward", "timeframe": timeframe},
            cost_assumptions={"status": "DECLARED_BY_ENGINE", "source": "BacktestEngine matching configuration"},
            exclusions=["CPCV/null/placebo unavailable unless separately executed"],
        )
        self.store.put(exp)

        reasons: list[str] = []
        if hypothesis is None:
            reasons.append("HYPOTHESIS_UNAVAILABLE: hypothesis was not found in the ledger")
        elif hypothesis.missing_specification():
            reasons.append("HYPOTHESIS_INCOMPLETE: " + ", ".join(hypothesis.missing_specification()))
        readiness = assess_bars(
            bars,
            data_version=data_version,
            source_label=getattr(manifest, "source", "") if manifest else None,
            requirements=ResearchDataRequirements(),
        )
        if readiness.status != "READY":
            reasons.extend(readiness.reasons)
        if reasons:
            body = {"readiness": readiness.as_dict(), "reasons": reasons}
            self.store.complete(
                exp.id,
                results=body,
                conclusion="BLOCKED_INSUFFICIENT_DATA",
                failure_reason="; ".join(reasons),
            )
            return LoopResult(hypothesis_id, exp.id, False, reasons, "RESEARCH")

        try:
            import numpy as np

            result = self.engine.run(
                instrument, timeframe, data_version, strategy_id=strategy_id, strategy_params=params, seed=seed
            )
            eq = np.asarray(result.equity_curve, dtype=float)
            if len(eq) < 20:
                raise ValueError("insufficient equity observations for an out-of-sample split")
            mid = len(eq) // 2
            eq_is = eq[:mid]
            eq_oos = eq[mid:]

            # Independent chronological reruns.  Each fold is measured from
            # its own train and test interval; no copies of the full-run score.
            train = max(100, len(bars) // 3)
            test = max(20, len(bars) // 10)
            folds: list[dict[str, float]] = []
            for train_start, train_end, test_start, test_end in self.pipeline.walk_forward_splits(
                len(bars), train=train, test=test, step=test
            ):
                train_result = self.engine.run(
                    instrument,
                    timeframe,
                    data_version,
                    strategy_id=strategy_id,
                    strategy_params=params,
                    seed=seed,
                    start=bars[train_start].open_time,
                    end=bars[train_end - 1].close_time,
                )
                test_result = self.engine.run(
                    instrument,
                    timeframe,
                    data_version,
                    strategy_id=strategy_id,
                    strategy_params=params,
                    seed=seed,
                    start=bars[test_start].open_time,
                    end=bars[test_end - 1].close_time,
                )
                folds.append({"is_sharpe": float(train_result.sharpe), "oos_sharpe": float(test_result.sharpe)})

            # Rerun numeric parameter perturbations.  A non-numeric-only
            # strategy has no stability evidence and is blocked by the pipeline.
            perturbed: list[float] = []
            for key, value in params.items():
                if not isinstance(value, (int, float)) or key.startswith("_"):
                    continue
                for factor in (0.8, 0.9, 1.1, 1.2):
                    variant = dict(params)
                    variant[key] = type(value)(value * factor)
                    variant_result = self.engine.run(
                        instrument,
                        timeframe,
                        data_version,
                        strategy_id=strategy_id,
                        strategy_params=variant,
                        seed=seed,
                    )
                    perturbed.append(float(variant_result.sharpe))

            stress = self.engine.run_stress(
                instrument, timeframe, data_version, strategy_id, params, spreads=[1.0, 1.5, 2.0]
            )
            # CPCV/null/placebo and gross-vs-net decomposition are not
            # implemented by this loop.  The ValidatorPipeline marks those
            # absent inputs NOT_IMPLEMENTED and blocks the result.
            report = self.pipeline.validate(
                strategy_id=strategy_id,
                data_version=data_version,
                equity_is=eq_is,
                equity_oos=eq_oos,
                walk_forward_folds=folds,
                num_trials=max(1, self.store.count_trials()),
                cpcv_folds=[],
                perturbed_sharpes=perturbed,
                stress_results=stress,
                timeframe=timeframe,
            )
        except Exception as e:  # noqa: BLE001 — failure is persisted, never hidden
            reason = f"experiment execution/validation failed: {type(e).__name__}: {e}"
            self.store.reject(exp.id, reason=reason)
            return LoopResult(hypothesis_id, exp.id, False, [reason], "REJECTED")

        findings = self.adversary.review(
            {
                "wfe": report.metrics.get("wfe", 0),
                "dsr_prob": report.metrics.get("dsr_prob", 0),
                "pbo": report.metrics.get("pbo", 1),
                "spread_pf_1_5x": stress.get(1.5, 0) if stress else 0,
                "oos_sharpe": report.metrics.get("sharpe_oos", 0),
            }
        )
        if report.passed and not findings:
            # This is a research candidate only.  No promotion to execution is
            # performed here; any future claim still needs forward evidence.
            self.store.complete(
                exp.id,
                results={"validation": report.metrics, "checks": [c.__dict__ for c in report.checks]},
                conclusion="PROMISING_INSUFFICIENT",
            )
            self.store.lineage(hypothesis_id, exp.id, "candidate")
            return LoopResult(hypothesis_id, exp.id, True, [], "CANDIDATE")
        reason = "; ".join(findings) if findings else "; ".join(report.reasons) or "validation blocked"
        self.store.reject(exp.id, reason=reason, details={"report": report.metrics})
        return LoopResult(hypothesis_id, exp.id, False, findings or report.reasons, "REJECTED")
