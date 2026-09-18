"""Edge Discovery Pipeline — staged, no bypass, golden principle: survive attempts to disprove."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qts.edge.scorecard import EdgeScorecard


STAGES = [
    "DATA_QUALITY",
    "DISCOVERY",
    "IN_SAMPLE",
    "WALK_FORWARD",
    "CPCV",
    "PBO",
    "PSR",
    "DSR",
    "COST_STRESS",
    "PERTURBATION",
    "REGIME",
    "NULL_CONTROL",
    "PLACEBO_CONTROL",
    "EXPECTANCY",
    "ECONOMIC_EDGE",
    "FORWARD_PAPER",
    "SHADOW",
    "PROMOTION_DECISION",
]


@dataclass
class PipelineResult:
    stage: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


class DiscoveryPipeline:
    """Enforces stage order, records each gate independently, no single score hides failures."""

    def __init__(self):
        self.stages_executed: list[str] = []
        self.results: dict[str, PipelineResult] = {}

    def _require_prior(self, stage: str):
        idx = STAGES.index(stage)
        for prior in STAGES[:idx]:
            if prior not in self.stages_executed:
                raise ValueError(f"stage {stage} bypassed prior {prior} — pipeline must run in order, no bypass")
    def execute(self, stage: str, passed: bool, details: dict[str, Any] | None = None) -> PipelineResult:
        self._require_prior(stage)
        if stage in self.results:
            raise ValueError(f"stage {stage} already executed — no re-entry without new trial")
        res = PipelineResult(stage=stage, passed=passed, details=details or {})
        self.results[stage] = res
        self.stages_executed.append(stage)
        return res

    def is_complete(self) -> bool:
        return len(self.stages_executed) == len(STAGES)

    def overall_passed(self) -> bool:
        mandatory = ["DATA_QUALITY","WALK_FORWARD","CPCV","PBO","PSR","DSR","COST_STRESS","PERTURBATION","REGIME","NULL_CONTROL","PLACEBO_CONTROL","EXPECTANCY","ECONOMIC_EDGE","FORWARD_PAPER","SHADOW"]
        return all(self.results.get(s, PipelineResult(s, False)).passed for s in mandatory)

    def scorecard(self, strategy_id: str, data_version: str, evidence: dict[str, Any]) -> EdgeScorecard:
        if not self.is_complete():
            raise ValueError(f"pipeline not complete — missing {set(STAGES) - set(self.stages_executed)} — cannot promote")
        sc = EdgeScorecard.from_evidence(evidence)
        sc.strategy_id = strategy_id
        sc.data_version = data_version
        return sc
