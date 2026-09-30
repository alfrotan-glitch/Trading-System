"""Impulse continuation research capability (research-only, never live).

See module docstrings for the scientific rules. Public surface:

* ``run_impulse_research`` — fail-closed orchestrator (store -> evidence dict)
* ``render_markdown_report`` — human-readable report from evidence
* ``ImpulseResearchConfig`` / ``CostAssumptions`` — pre-registered design + declared costs
* ``PRE_REGISTERED_FAMILIES`` / ``detect_events`` — causal detectors
* ``MeasurementParams`` / ``measure_event`` — independent post-event measurement
* ``assess_data_adequacy`` — minimum data requirements gate
* ``classify_conclusion`` — deterministic evidence -> admissible conclusion
"""

from qts.research.impulse.adequacy import DataAdequacyReport, assess_data_adequacy
from qts.research.impulse.analysis import (
    ImpulseAnalysisResult,
    ImpulseResearchConfig,
    run_impulse_analysis,
    summarize_event_outcomes,
)
from qts.research.impulse.conclusions import CONCLUSIONS, ResearchConclusion, classify_conclusion
from qts.research.impulse.costs import BASE_COSTS, CostAssumptions
from qts.research.impulse.definitions import (
    PRE_REGISTERED_FAMILIES,
    PRIMARY_HORIZON_BARS,
    WARMUP_BARS,
    ImpulseFamily,
    detect_events,
)
from qts.research.impulse.measurement import (
    EventMeasurement,
    MeasurementParams,
    RaceOutcome,
    causal_vol_regime_labels,
    measure_event,
)
from qts.research.impulse.report import render_markdown_report, run_impulse_research
from qts.research.impulse.statistics import (
    binomial_test_vs_baseline,
    bootstrap_ci_mean,
    holm_bonferroni,
)

__all__ = [
    "BASE_COSTS",
    "CONCLUSIONS",
    "CostAssumptions",
    "DataAdequacyReport",
    "EventMeasurement",
    "ImpulseAnalysisResult",
    "ImpulseFamily",
    "ImpulseResearchConfig",
    "MeasurementParams",
    "PRE_REGISTERED_FAMILIES",
    "PRIMARY_HORIZON_BARS",
    "RaceOutcome",
    "ResearchConclusion",
    "WARMUP_BARS",
    "assess_data_adequacy",
    "binomial_test_vs_baseline",
    "bootstrap_ci_mean",
    "causal_vol_regime_labels",
    "classify_conclusion",
    "detect_events",
    "holm_bonferroni",
    "measure_event",
    "render_markdown_report",
    "run_impulse_analysis",
    "run_impulse_research",
    "summarize_event_outcomes",
]
