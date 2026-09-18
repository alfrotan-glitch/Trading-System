"""Edge Scorecard — show each dimension independently, no single score hides failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EdgeScorecard:
    strategy_id: str
    data_version: str
    # OOS performance
    oos_sharpe: float | None = None
    oos_return: float | None = None
    is_sharpe: float | None = None
    # Walk-forward
    wfe: float | None = None
    wfe_passed: bool = False
    # CPCV/PBO
    pbo: float | None = None
    pbo_passed: bool = False
    # Statistical
    psr: float | None = None
    dsr: float | None = None
    dsr_trials: int = 0
    psr_passed: bool = False
    dsr_passed: bool = False
    # Risk
    max_drawdown: float | None = None
    max_drawdown_pct: float | None = None
    # Expectancy
    expectancy: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    turnover: int | None = None
    # Cost tolerance
    cost_break_even_bps: float | None = None
    cost_passed: bool = False
    # Slippage tolerance (stress)
    slippage_tolerance: dict[str, Any] = field(default_factory=dict)
    # Regime dependence
    regime_results: list[dict[str, Any]] = field(default_factory=list)
    regime_passed: bool = False
    worst_regime: dict[str, Any] | None = None
    # Perturbation stability
    perturbation_drop_pct: float | None = None
    perturbation_passed: bool = False
    # Null-control separation
    null_control_sharpes: list[float] = field(default_factory=list)
    null_passed: bool = False
    placebo_sharpes: list[float] = field(default_factory=list)
    placebo_passed: bool = False
    # Forward / shadow
    forward_signals: int | None = None
    forward_passed: bool = False
    shadow_paper_diff_bps: float | None = None
    shadow_passed: bool = False
    # Economic edge
    economic_edge_passed: bool = False
    economic_remaining: float | None = None
    # Overall
    checks: dict[str, bool] = field(default_factory=dict)
    overall_passed: bool = False
    blocked_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "data_version": self.data_version,
            "oos_performance": {"oos_sharpe": self.oos_sharpe, "oos_return": self.oos_return, "is_sharpe": self.is_sharpe},
            "wfe": {"value": self.wfe, "passed": self.wfe_passed},
            "pbo": {"value": self.pbo, "passed": self.pbo_passed},
            "psr_dsr": {"psr": self.psr, "dsr": self.dsr, "trials": self.dsr_trials, "psr_passed": self.psr_passed, "dsr_passed": self.dsr_passed},
            "drawdown": {"max_drawdown": self.max_drawdown, "max_drawdown_pct": self.max_drawdown_pct},
            "expectancy": {"expectancy": self.expectancy, "profit_factor": self.profit_factor, "win_rate": self.win_rate, "avg_win": self.avg_win, "avg_loss": self.avg_loss, "turnover": self.turnover},
            "cost_tolerance": {"break_even_bps": self.cost_break_even_bps, "passed": self.cost_passed},
            "slippage_tolerance": self.slippage_tolerance,
            "regime_dependence": {"results": self.regime_results, "passed": self.regime_passed, "worst": self.worst_regime},
            "perturbation_stability": {"drop_pct": self.perturbation_drop_pct, "passed": self.perturbation_passed},
            "null_control_separation": {"null_sharpes": self.null_control_sharpes, "passed": self.null_passed},
            "placebo_control": {"placebo_sharpes": self.placebo_sharpes, "passed": self.placebo_passed},
            "forward_paper": {"signals": self.forward_signals, "passed": self.forward_passed},
            "shadow_paper_execution_discrepancy": {"diff_bps": self.shadow_paper_diff_bps, "passed": self.shadow_passed},
            "economic_edge": {"passed": self.economic_edge_passed, "remaining": self.economic_remaining},
            "checks": self.checks,
            "overall_passed": self.overall_passed,
            "blocked_reasons": self.blocked_reasons,
        }

    @classmethod
    def from_evidence(cls, evidence: dict[str, Any]) -> "EdgeScorecard":
        """Construct scorecard from orchestrator evidence dict."""
        ds = evidence.get("dataset", {})
        es = evidence.get("edge_survival", {})
        exp = evidence.get("expectancy", {})
        econ = evidence.get("economic_edge", {})
        regime = evidence.get("regime", [])
        forward = evidence.get("forward", {})
        shadow = evidence.get("shadow_paper", {})
        checks = es.get("checks", {}) if isinstance(es, dict) else {}
        details = es.get("details", {}) if isinstance(es, dict) else {}
        # expectancy can be dict
        expectancy_val = exp.get("expectancy_per_trade") if isinstance(exp, dict) else None
        profit_factor_val = exp.get("profit_factor") if isinstance(exp, dict) else None
        sc = cls(
            strategy_id=evidence.get("strategy_id", evidence.get("dataset", {}).get("manifest", {}).get("instrument", "unknown")),
            data_version=ds.get("manifest", {}).get("version", "unknown") if isinstance(ds, dict) else "unknown",
        )
        sc.oos_sharpe = details.get("oos_sharpe") if isinstance(details, dict) else None
        sc.wfe = es.get("wfe") if isinstance(es, dict) else None
        sc.wfe_passed = bool(checks.get("walk_forward", False))
        sc.pbo = es.get("pbo") if isinstance(es, dict) else None
        sc.pbo_passed = bool(checks.get("pbo", False)) and bool(checks.get("cpcv", False))
        sc.psr = es.get("psr") if isinstance(es, dict) else None
        sc.dsr = es.get("dsr") if isinstance(es, dict) else None
        sc.dsr_trials = evidence.get("trial_ledger", {}).get("trial_count", 0) if isinstance(evidence.get("trial_ledger"), dict) else 0
        sc.psr_passed = bool(checks.get("psr", False))
        sc.dsr_passed = bool(checks.get("dsr", False))
        sc.max_drawdown = exp.get("max_drawdown") if isinstance(exp, dict) else None
        sc.expectancy = expectancy_val
        sc.profit_factor = profit_factor_val
        sc.win_rate = exp.get("win_rate") if isinstance(exp, dict) else None
        sc.avg_win = exp.get("avg_win") if isinstance(exp, dict) else None
        sc.avg_loss = exp.get("avg_loss") if isinstance(exp, dict) else None
        sc.turnover = exp.get("trades") if isinstance(exp, dict) else None
        sc.cost_break_even_bps = es.get("cost_break_even_bps") if isinstance(es, dict) else es.get("cost_be") if isinstance(es, dict) else None
        sc.cost_passed = bool(checks.get("cost", False))
        sc.slippage_tolerance = evidence.get("cost_robustness", {}).get("stress", {}) if isinstance(evidence.get("cost_robustness"), dict) else {}
        sc.regime_results = regime if isinstance(regime, list) else []
        sc.regime_passed = bool(checks.get("regime", False))
        sc.worst_regime = min(regime, key=lambda x: x.get("sharpe", 0)) if regime else None
        sc.perturbation_passed = bool(checks.get("perturbation", False))
        sc.null_control_sharpes = evidence.get("null_control", {}).get("control_sharpes", []) if isinstance(evidence.get("null_control"), dict) else []
        sc.null_passed = bool(checks.get("randomized_control", False))
        sc.placebo_sharpes = evidence.get("placebo", {}).get("placebo_sharpes", []) if isinstance(evidence.get("placebo"), dict) else []
        sc.placebo_passed = bool(checks.get("placebo", False))
        sc.forward_signals = forward.get("signals") if isinstance(forward, dict) else None
        sc.forward_passed = not forward.get("invalidated", True) if isinstance(forward, dict) else False
        sc.shadow_paper_diff_bps = shadow.get("avg_price_diff_bps") if isinstance(shadow, dict) else None
        # shadow_passed: if discrepancy small
        sc.shadow_passed = (sc.shadow_paper_diff_bps is not None and sc.shadow_paper_diff_bps < 50) if sc.shadow_paper_diff_bps is not None else False
        sc.economic_edge_passed = bool(checks.get("economic_edge", False)) or bool(econ.get("passed", False)) if isinstance(econ, dict) else False
        sc.economic_remaining = econ.get("remaining_edge") if isinstance(econ, dict) else None
        sc.checks = checks if isinstance(checks, dict) else {}
        sc.overall_passed = bool(es.get("passed", False)) if isinstance(es, dict) else False
        # blocked reasons: any failing check
        sc.blocked_reasons = [k for k, v in sc.checks.items() if not v]
        return sc
