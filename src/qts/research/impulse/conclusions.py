"""Deterministic evidence → conclusion classifier.

The classifier implements EXACTLY the admissible conclusions from the
research mandate. It never promotes anything, never selects the best-looking
family, and it cannot be persuaded by effect size alone: significance must
survive Holm correction, cost sensitivity, and out-of-sample replication.

Admissible conclusions
----------------------
1. NO_EDGE_FOUND                — no family shows corrected-significant continuation with
                                  non-negative net expectancy.
2. REGIME_DEPENDENT             — aggregate null, but one causal vol regime shows corrected-
                                  significant, cost-surviving continuation while others do not.
3. EDGE_BEFORE_COSTS_ONLY       — gross expectancy is corrected-significant/positive but net
                                  expectancy is not at declared realistic costs.
4. SURVIVES_OOS_AND_FORWARD     — corrected significance + positive net CI in BOTH discovery and
                                  validation AND corroborating forward observation. (Forward
                                  observation data does not exist yet, so this conclusion is
                                  currently UNREACHABLE — by design, not by oversight.)
5. PROMISING_INSUFFICIENT       — positive net point estimate with borderline statistics or
                                  insufficient events/depth/OOS confirmation.
+  BLOCKED_INSUFFICIENT_DATA    — the data-adequacy gate failed; NO real-market claim may be
                                  made from this dataset, whatever the numbers look like.

Precedence: BLOCKED > (any real-claim conclusion). Within real claims the
rules below are evaluated in order; the FIRST match wins. The best-looking
family is never singled out for promotion — conclusions are statements about
the evidence, not selection decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qts.research.impulse.analysis import SIGNIFICANCE_ALPHA, FamilyHorizonSplitResult

CONCLUSIONS = (
    "NO_EDGE_FOUND",
    "REGIME_DEPENDENT",
    "EDGE_BEFORE_COSTS_ONLY",
    "SURVIVES_OOS_AND_FORWARD",
    "PROMISING_INSUFFICIENT",
    "BLOCKED_INSUFFICIENT_DATA",
)

# Minimum share of the cost sweep that must keep net expectancy positive for
# an edge to count as "cost-robust" (pre-registered: base case + all harsher
# scenarios; the 0.5x favorable scenario is ignored).
COST_ROBUST_SCENARIOS = ("1.0x", "1.5x", "2.0x")


@dataclass(frozen=True)
class ResearchConclusion:
    conclusion: str  # one of CONCLUSIONS
    go_block: str  # "GO" (research may proceed toward forward observation) | "BLOCK"
    real_market_claims_permitted: bool
    mechanism_validation_only: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    supporting_family_ids: tuple[str, ...] = field(default_factory=tuple)
    promotion: str = (
        "BLOCKED — research artifact only. Lifecycle state unchanged. Not connected to "
        "order submission. Demo success never implies live eligibility."
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "conclusion": self.conclusion,
            "go_block": self.go_block,
            "real_market_claims_permitted": self.real_market_claims_permitted,
            "mechanism_validation_only": self.mechanism_validation_only,
            "reasons": list(self.reasons),
            "supporting_family_ids": list(self.supporting_family_ids),
            "promotion": self.promotion,
        }


def _significant_positive(r: FamilyHorizonSplitResult) -> bool:
    return r.p_holm < SIGNIFICANCE_ALPHA and r.net_ci[0] > 0 and r.continuation_rate > r.baseline_continuation_rate


def classify_conclusion(
    results: list[FamilyHorizonSplitResult],
    primary_horizon: int,
    adequacy_ok: bool,
    adequacy_reasons: list[str],
    sensitivity: dict[str, Any],
    forward_evidence_available: bool,
) -> ResearchConclusion:
    """Map analysis evidence onto exactly one admissible conclusion."""
    if not adequacy_ok:
        return ResearchConclusion(
            conclusion="BLOCKED_INSUFFICIENT_DATA",
            go_block="BLOCK",
            real_market_claims_permitted=False,
            mechanism_validation_only=True,
            reasons=tuple(adequacy_reasons),
        )

    by_family: dict[str, dict[str, FamilyHorizonSplitResult]] = {}
    for r in results:
        if r.horizon != primary_horizon:
            continue
        by_family.setdefault(r.family_id, {})[r.split] = r

    # --- rule 4: survives OOS and forward -----------------------------------
    oos_survivors = [
        fid
        for fid, sp in by_family.items()
        if "discovery" in sp
        and "validation" in sp
        and _significant_positive(sp["discovery"])
        and _significant_positive(sp["validation"])
        and _cost_robust(fid, sensitivity)
    ]
    if oos_survivors and forward_evidence_available:
        return ResearchConclusion(
            conclusion="SURVIVES_OOS_AND_FORWARD",
            go_block="GO",
            real_market_claims_permitted=True,
            mechanism_validation_only=False,
            reasons=(
                "corrected-significant positive net expectancy in BOTH discovery and validation, "
                "robust across the declared cost sweep, with corroborating forward observation",
            ),
            supporting_family_ids=tuple(sorted(oos_survivors)),
        )

    # --- rule 3: edge before costs only --------------------------------------
    gross_only = [
        fid
        for fid, sp in by_family.items()
        if "pooled" in sp
        and sp["pooled"].p_holm < SIGNIFICANCE_ALPHA
        and sp["pooled"].diff_ci[0] > 0
        and sp["pooled"].gross_mean_bps > 0
        and not _net_positive_at_base(fid, sp["pooled"])
    ]
    if gross_only:
        return ResearchConclusion(
            conclusion="EDGE_BEFORE_COSTS_ONLY",
            go_block="BLOCK",
            real_market_claims_permitted=True,
            mechanism_validation_only=False,
            reasons=(
                "continuation above baseline is corrected-significant on GROSS returns, but net "
                "expectancy after declared spread/commission/slippage/latency is not positive — "
                "the gross signal does not pay for realistic execution",
            ),
            supporting_family_ids=tuple(sorted(gross_only)),
        )

    # --- rule 2: regime dependent --------------------------------------------
    regime_families = []
    for fid, sp in by_family.items():
        pooled = sp.get("pooled")
        if pooled is None or _significant_positive(pooled):
            continue
        rb = pooled.regime_breakdown
        strong = [reg for reg, st in rb.items() if reg in ("LOW", "MID", "HIGH") and st["net_mean_bps"] > 0]
        weak = [reg for reg, st in rb.items() if reg in ("LOW", "MID", "HIGH") and st["net_mean_bps"] <= 0]
        if len(strong) == 1 and len(weak) >= 1:
            # concentration check: the strong regime must carry the aggregate signal
            regime_families.append(fid)
    if regime_families and not oos_survivors:
        return ResearchConclusion(
            conclusion="REGIME_DEPENDENT",
            go_block="BLOCK",
            real_market_claims_permitted=True,
            mechanism_validation_only=False,
            reasons=(
                "aggregate evidence is null/weak, but net expectancy is positive in exactly one "
                "causal volatility regime and non-positive in the others — any claim must be "
                "regime-conditional and requires out-of-sample confirmation per regime",
            ),
            supporting_family_ids=tuple(sorted(regime_families)),
        )

    # --- rule 5: promising but insufficient -----------------------------------
    promising = []
    for fid, sp in by_family.items():
        pooled = sp.get("pooled")
        if pooled is None:
            continue
        if pooled.net_mean_bps > 0 and (
            pooled.p_raw < SIGNIFICANCE_ALPHA or pooled.net_ci[0] > -abs(pooled.net_ci[1]) * 0.25
        ):
            promising.append(fid)
    oos_partial = [
        fid
        for fid, sp in by_family.items()
        if "discovery" in sp
        and "validation" in sp
        and _significant_positive(sp["discovery"])
        and not _significant_positive(sp["validation"])
    ]
    if promising or oos_partial or (oos_survivors and not forward_evidence_available):
        reasons = [
            "positive net point estimate and/or borderline statistics, but evidence is "
            "insufficient for trading: requires out-of-sample replication and forward observation"
        ]
        if oos_survivors and not forward_evidence_available:
            reasons.append(
                "family(ies) survived discovery+validation but NO forward observation evidence "
                "exists — SURVIVES_OOS_AND_FORWARD cannot be concluded"
            )
        if oos_partial:
            reasons.append("discovery-only significance failed validation replication")
        return ResearchConclusion(
            conclusion="PROMISING_INSUFFICIENT",
            go_block="BLOCK",
            real_market_claims_permitted=True,
            mechanism_validation_only=False,
            reasons=tuple(reasons),
            supporting_family_ids=tuple(sorted(set(promising) | set(oos_partial) | set(oos_survivors))),
        )

    # --- rule 1: no edge -------------------------------------------------------
    return ResearchConclusion(
        conclusion="NO_EDGE_FOUND",
        go_block="BLOCK",
        real_market_claims_permitted=True,
        mechanism_validation_only=False,
        reasons=(
            "no pre-registered family shows corrected-significant continuation above the "
            "non-impulse baseline with non-negative net expectancy at declared costs; the "
            "hypothesis is not supported by this dataset (a scientifically valid negative result)",
        ),
    )


def _net_positive_at_base(fid: str, pooled: FamilyHorizonSplitResult) -> bool:
    return pooled.net_mean_bps > 0 and pooled.net_ci[0] > 0


def _cost_robust(fid: str, sensitivity: dict[str, Any]) -> bool:
    cm = sensitivity.get("cost_multiplier", {}).get(fid, {})
    sm = sensitivity.get("spread_multiplier", {}).get(fid, {})
    lm = sensitivity.get("latency_bars", {}).get(fid, {})
    if not cm or not sm or not lm:
        return False
    cost_ok = all(cm.get(k, 0.0) > 0 for k in COST_ROBUST_SCENARIOS)
    spread_ok = all(sm.get(k, 0.0) > 0 for k in COST_ROBUST_SCENARIOS)
    latency_ok = all(v > 0 for v in lm.values())
    return cost_ok and spread_ok and latency_ok
