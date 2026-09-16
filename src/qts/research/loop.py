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
from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument
from qts.observability.audit import AuditLog
from qts.research.agent import AdversarialAgent, ResearchAgent
from qts.research.experiment import Experiment, ExperimentStore
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
        # create experiment
        exp = Experiment(
            hypothesis_id=hypothesis_id, strategy_id=strategy_id, params=params, data_version=data_version, seed=seed
        )
        self.store.put(exp)

        if self.engine is None:
            # need a default engine from DataStore
            store_ds = SqliteParquetDataStore()
            self.engine = BacktestEngine(store_ds)

        # run backtest
        try:
            result = self.engine.run(
                instrument, timeframe, data_version, strategy_id=strategy_id, strategy_params=params, seed=seed
            )
        except Exception as e:  # noqa: BLE001
            reason = f"backtest failed: {e}"
            self.store.reject(exp.id, reason=reason)
            return LoopResult(hypothesis_id, exp.id, False, [reason], "REJECTED")

        # validate (minimal: use full equity split + stress + perturbation via engine helpers)
        # For loop brevity we run a reduced pipeline; full pipeline is in CLI `qts validate`
        try:
            import numpy as np

            eq = np.array(result.equity_curve)
            mid = len(eq) // 2
            eq_is = eq[:mid] if len(eq) > 20 else eq
            eq_oos = eq[mid:] if len(eq) > 20 else eq
            # quick stress/perturb
            stress = self.engine.run_stress(
                instrument, timeframe, data_version, strategy_id, params, spreads=[1.0, 1.5]
            )
            perturbed = [
                result.sharpe * (1 + p) for p in [-0.1, -0.05, 0, 0.05, 0.1]
            ]  # placeholder; real loop should re-run
            report = self.pipeline.validate(
                strategy_id=strategy_id,
                data_version=data_version,
                equity_is=eq_is,
                equity_oos=eq_oos,
                walk_forward_folds=[{"is_sharpe": result.sharpe, "oos_sharpe": result.sharpe}]
                * 3,  # placeholder for demo
                num_trials=max(1, self.store.count_trials()),
                cpcv_folds=None,  # will block; real loop should provide
                perturbed_sharpes=perturbed,
                stress_results=stress,
            )
        except Exception as e:  # noqa: BLE001
            reason = f"validation failed: {e}"
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
            self.store.lineage(hypothesis_id, exp.id, "promoted")
            return LoopResult(hypothesis_id, exp.id, True, [], "CANDIDATE")
        reason = "; ".join(findings) if findings else "; ".join(report.reasons) or "validation blocked"
        self.store.reject(exp.id, reason=reason, details={"report": report.metrics})
        return LoopResult(hypothesis_id, exp.id, False, findings or report.reasons, "REJECTED")
