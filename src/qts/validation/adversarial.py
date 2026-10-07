"""Adversarial validators — actively try to break strategies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AdversarialFinding:
    check: str
    severity: str  # low/medium/high
    detail: str


def check_lookahead(feature_uses_future: bool) -> AdversarialFinding | None:
    if feature_uses_future:
        return AdversarialFinding("lookahead", "high", "Feature uses future bar (close of same bar to trade same bar)")
    return None


def check_spread_sensitivity(pf_at_1x: float, pf_at_1_5x: float, pf_at_2x: float) -> list[AdversarialFinding]:
    findings: list[AdversarialFinding] = []
    if pf_at_1_5x < 1.0:
        findings.append(
            AdversarialFinding(
                "spread_sensitivity",
                "high",
                f"PF 1.5x spread {pf_at_1_5x:.2f} <1.0 — edge destroyed by realistic spread",
            )
        )
    if pf_at_2x < 0.8:
        findings.append(AdversarialFinding("spread_sensitivity", "medium", f"PF 2x {pf_at_2x:.2f} fragile"))
    return findings


def check_parameter_fragility(sharpes: list[float]) -> AdversarialFinding | None:
    if not sharpes:
        return None
    # sharpes for perturbed params ±10%, ±20%
    base = sharpes[len(sharpes) // 2]
    worst = min(sharpes)
    if base != 0 and (base - worst) / abs(base) > 0.3:
        return AdversarialFinding(
            "parameter_fragility",
            "high",
            f"Sharpe drops {(base - worst) / abs(base):.1%} under perturbation — fragile thresholds",
        )
    return None


def check_regime_dependence(regime_sharpes: dict[str, float]) -> list[AdversarialFinding]:
    findings: list[AdversarialFinding] = []
    vals = list(regime_sharpes.values())
    if vals and max(vals) > 0 and min(vals) < -0.2:
        findings.append(
            AdversarialFinding(
                "regime_dependence",
                "medium",
                f"Sharpe varies {regime_sharpes} — edge only in one regime, needs regime filter",
            )
        )
    return findings


def check_overfitting(wfe: float, pbo: float, dsr: float) -> list[AdversarialFinding]:
    findings: list[AdversarialFinding] = []
    if wfe < 0.3:
        findings.append(AdversarialFinding("overfitting", "high", f"WFE {wfe:.2f} <0.3 — heavy overfit"))
    if pbo > 0.5:
        findings.append(AdversarialFinding("overfitting", "high", f"PBO {pbo:.2f} >0.5 — more likely than not overfit"))
    if dsr < 0.95:
        findings.append(
            AdversarialFinding(
                "deflated_sharpe",
                "medium",
                f"DSR {dsr:.2f} <0.95 — not significant after multiple testing",
            )
        )
    return findings
