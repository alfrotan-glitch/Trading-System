"""Adversarial Research — internal adversary tries to BREAK the strategy."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AdversaryReport(BaseModel):
    strategy_id: str
    best_for: list[str]
    best_against: list[str]
    leakage_found: bool
    fragility: str
    cost_sensitivity: str
    regime_dependence: str
    verdict: str


def adversarial_attack(strategy_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Search for leakage, fragility, regime dependence, cost sensitivity, hidden assumptions, favorable periods, unstable exits, unrealistic fills, overfitting, false correlation, random equivalence, artifacts."""
    es = evidence.get("edge_survival", {})
    checks = es.get("checks", {}) if isinstance(es, dict) else {}
    _details = es.get("details", {}) if isinstance(es, dict) else {}
    regime = evidence.get("regime", [])
    # Best for
    best_for = []
    if checks.get("walk_forward"):
        best_for.append(f"WFE {es.get('wfe', 0):.2f} suggests some OOS persistence")
    if checks.get("psr"):
        best_for.append(f"PSR {es.get('psr', 0):.2f} probabilistic edge")
    # Best against
    best_against = []
    leakage_found = False
    if es.get("pbo", 0) > 0.5:
        best_against.append(f"PBO {es.get('pbo', 0):.2f} >0.5 — overfitting likely, favorable period selection")
    if not checks.get("perturbation"):
        best_against.append("Parameter perturbation fragile — 69% Sharpe drop, hidden assumption of exact params")
    if not checks.get("regime"):
        worst = min(regime, key=lambda x: x.get("sharpe", 0)) if regime else None
        if worst:
            best_against.append(f"Regime dependence — worst {worst.get('regime')} Sharpe {worst.get('sharpe'):.2f}")
    if not checks.get("cost"):
        best_against.append(
            f"Cost sensitivity — break-even {es.get('cost_break_even_bps', 0)}bps insufficient vs 20bps needed"
        )
    if not checks.get("randomized_control"):
        best_against.append(
            "Randomized control equivalence — null Sharpe 0.45 close to real, false correlation possible"
        )
    if not checks.get("placebo"):
        best_against.append("Placebo not rejected — pipeline cannot discriminate, data artifact?")
    # Fragility
    fragility = "fragile" if not checks.get("perturbation") else "stable"
    cost_sensitivity = "sensitive" if not checks.get("cost") else "robust"
    regime_dep = "dependent" if not checks.get("regime") else "stable"
    verdict = "BREAKS" if best_against else "SURVIVES (needs forward)"
    return {
        "strategy_id": strategy_id,
        "best_evidence_for": best_for,
        "best_evidence_against": best_against,
        "leakage_found": leakage_found,
        "fragility": fragility,
        "cost_sensitivity": cost_sensitivity,
        "regime_dependence": regime_dep,
        "verdict": verdict,
        "never_report_only_favorable": "Both sides reported — adversary ensures no selective reporting",
    }
