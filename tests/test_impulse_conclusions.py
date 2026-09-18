"""Truth-table tests for the deterministic evidence -> conclusion classifier.

Every admissible conclusion must be reachable from constructed evidence, and
the safety properties must hold unconditionally:
* inadequate data ALWAYS blocks real claims (numbers can never override it),
* the best-looking family is never auto-promoted,
* promotion is always blocked and GO is only possible via the full
  OOS+forward path.
"""

from __future__ import annotations

from qts.research.impulse.analysis import FamilyHorizonSplitResult
from qts.research.impulse.conclusions import CONCLUSIONS, classify_conclusion

PRIMARY = 12


def mkres(
    family_id: str = "IMP-RE-B",
    split: str = "pooled",
    horizon: int = PRIMARY,
    p_holm: float = 1.0,
    p_raw: float = 1.0,
    cont: float = 0.5,
    base: float = 0.5,
    diff_ci: tuple[float, float] = (-0.01, 0.01),
    net_mean: float = -3.0,
    net_ci: tuple[float, float] = (-10.0, 5.0),
    gross_mean: float = 0.0,
    regime_breakdown: dict | None = None,
) -> FamilyHorizonSplitResult:
    return FamilyHorizonSplitResult(
        family_id=family_id,
        horizon=horizon,
        split=split,
        p_holm=p_holm,
        p_raw=p_raw,
        continuation_rate=cont,
        baseline_continuation_rate=base,
        diff_ci=diff_ci,
        net_mean_bps=net_mean,
        net_ci=net_ci,
        gross_mean_bps=gross_mean,
        regime_breakdown=regime_breakdown or {},
    )


SENS_ROBUST = {
    "cost_multiplier": {"IMP-RE-B": {"1.0x": 5.0, "1.5x": 3.0, "2.0x": 1.0}},
    "spread_multiplier": {"IMP-RE-B": {"1.0x": 5.0, "1.5x": 3.0, "2.0x": 1.0}},
    "latency_bars": {"IMP-RE-B": {"0": 5.0, "1": 4.0, "2": 3.0}},
}
SENS_NOT_ROBUST = {
    "cost_multiplier": {"IMP-RE-B": {"1.0x": -1.0, "1.5x": -2.0, "2.0x": -3.0}},
    "spread_multiplier": {"IMP-RE-B": {"1.0x": -1.0, "1.5x": -2.0, "2.0x": -3.0}},
    "latency_bars": {"IMP-RE-B": {"0": 1.0, "1": -1.0, "2": -2.0}},
}


class TestBlocked:
    def test_inadequate_data_blocks_regardless_of_numbers(self):
        # even a spectacularly "significant" family cannot produce a real claim
        results = [
            mkres(
                split="discovery", p_holm=0.001, cont=0.9, base=0.5, net_mean=50, net_ci=(30, 70), diff_ci=(0.3, 0.5)
            ),
            mkres(
                split="validation", p_holm=0.001, cont=0.9, base=0.5, net_mean=50, net_ci=(30, 70), diff_ci=(0.3, 0.5)
            ),
            mkres(split="pooled", p_holm=0.001, cont=0.9, base=0.5, net_mean=50, net_ci=(30, 70), diff_ci=(0.3, 0.5)),
        ]
        c = classify_conclusion(results, PRIMARY, False, ["R1: synthetic"], SENS_ROBUST, True)
        assert c.conclusion == "BLOCKED_INSUFFICIENT_DATA"
        assert c.go_block == "BLOCK"
        assert c.real_market_claims_permitted is False
        assert c.mechanism_validation_only is True
        assert "R1" in " ".join(c.reasons)
        assert "BLOCKED" in c.promotion


class TestNoEdge:
    def test_flat_evidence_is_no_edge(self):
        results = [mkres(split=s) for s in ("discovery", "validation", "pooled")]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_NOT_ROBUST, False)
        assert c.conclusion == "NO_EDGE_FOUND"
        assert c.go_block == "BLOCK"
        assert c.conclusion in CONCLUSIONS


class TestEdgeBeforeCostsOnly:
    def test_gross_significant_net_dead(self):
        results = [
            mkres(
                split="pooled",
                p_holm=0.01,
                cont=0.62,
                base=0.5,
                diff_ci=(0.05, 0.19),
                gross_mean=2.0,
                net_mean=-1.4,
                net_ci=(-4.0, 1.0),
            ),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_NOT_ROBUST, False)
        assert c.conclusion == "EDGE_BEFORE_COSTS_ONLY"
        assert c.supporting_family_ids == ("IMP-RE-B",)


class TestRegimeDependent:
    def test_regime_concentration(self):
        rb = {
            "HIGH": {"n": 40.0, "net_mean_bps": 12.0, "continuation_rate": 0.7},
            "LOW": {"n": 60.0, "net_mean_bps": -4.0, "continuation_rate": 0.45},
            "MID": {"n": 50.0, "net_mean_bps": -1.0, "continuation_rate": 0.48},
        }
        results = [
            mkres(split="pooled", p_holm=0.8, cont=0.5, base=0.5, net_mean=0.5, net_ci=(-3, 4), regime_breakdown=rb),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_NOT_ROBUST, False)
        assert c.conclusion == "REGIME_DEPENDENT"
        assert c.go_block == "BLOCK"


class TestPromisingInsufficient:
    def test_discovery_only_significance_fails_replication(self):
        results = [
            mkres(
                split="discovery",
                p_holm=0.02,
                cont=0.65,
                base=0.5,
                net_mean=8.0,
                net_ci=(2.0, 14.0),
                diff_ci=(0.05, 0.25),
            ),
            mkres(split="validation", p_holm=0.9, cont=0.5, base=0.5, net_mean=-2.0, net_ci=(-8.0, 4.0)),
            mkres(split="pooled", p_holm=0.4, cont=0.55, base=0.5, net_mean=3.0, net_ci=(-2.0, 8.0)),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_ROBUST, False)
        assert c.conclusion == "PROMISING_INSUFFICIENT"
        assert any("validation" in r for r in c.reasons)

    def test_oos_survivors_without_forward_cannot_claim_survival(self):
        results = [
            mkres(split="discovery", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
            mkres(split="validation", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
            mkres(split="pooled", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_ROBUST, forward_evidence_available=False)
        assert c.conclusion == "PROMISING_INSUFFICIENT"
        assert any("forward" in r.lower() for r in c.reasons)


class TestSurvivesOosAndForward:
    def test_full_path_is_the_only_go(self):
        results = [
            mkres(split="discovery", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
            mkres(split="validation", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
            mkres(split="pooled", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_ROBUST, forward_evidence_available=True)
        assert c.conclusion == "SURVIVES_OOS_AND_FORWARD"
        assert c.go_block == "GO"
        # even a GO never promotes or connects to execution
        assert "BLOCKED" in c.promotion

    def test_not_cost_robust_downgrades(self):
        results = [
            mkres(split="discovery", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
            mkres(split="validation", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
            mkres(split="pooled", p_holm=0.01, cont=0.7, base=0.5, net_mean=10, net_ci=(4, 16), diff_ci=(0.1, 0.3)),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_NOT_ROBUST, forward_evidence_available=True)
        assert c.conclusion != "SURVIVES_OOS_AND_FORWARD"


class TestNoCherryPicking:
    def test_best_looking_family_is_not_selected_when_others_fail(self):
        """One significant family among nulls must not produce a survival claim:
        OOS requires BOTH splits for the SAME family, and conclusions list
        supporting families only as references — never as promotions."""
        results = [
            mkres(
                "IMP-RE-B",
                "discovery",
                p_holm=0.02,
                cont=0.66,
                base=0.5,
                net_mean=9,
                net_ci=(3, 15),
                diff_ci=(0.06, 0.26),
            ),
            mkres("IMP-RE-B", "validation", p_holm=0.6, cont=0.5, base=0.5, net_mean=-1, net_ci=(-7, 5)),
            mkres("IMP-RE-B", "pooled", p_holm=0.2, cont=0.58, base=0.5, net_mean=4, net_ci=(-1, 9)),
            mkres("IMP-RB-B", "discovery"),
            mkres("IMP-RB-B", "validation"),
            mkres("IMP-RB-B", "pooled"),
        ]
        c = classify_conclusion(results, PRIMARY, True, [], SENS_ROBUST, True)
        assert c.conclusion in ("PROMISING_INSUFFICIENT", "NO_EDGE_FOUND", "REGIME_DEPENDENT")
        assert c.conclusion != "SURVIVES_OOS_AND_FORWARD"
        assert "IMP-RB-B" not in c.supporting_family_ids
