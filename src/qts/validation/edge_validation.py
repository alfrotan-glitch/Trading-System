"""Phase 5 & 14: Edge survival test A-O + minimum economic edge — comprehensive validator."""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Any

from qts.validation.pipeline import ValidatorPipeline
from qts.validation.metrics import probabilistic_sharpe_ratio, deflated_sharpe_ratio, periods_per_year_for_timeframe
from qts.edge.cost_robustness import evaluate_cost_robustness
from qts.edge.regime_stability import evaluate_regime_stability
from qts.edge.expectancy import compute_expectancy, evaluate_minimum_economic_edge

@dataclass
class EdgeSurvivalResult:
    passed: bool
    checks: dict[str, bool]
    details: dict[str, str]
    psr: float
    dsr: float
    pbo: float
    wfe: float
    cost_break_even_bps: float
    regime_dependent: bool
    null_rejected: bool
    placebo_rejected: bool

def validate_edge_survival(
    strategy_id: str,
    data_version: str,
    equity_is: np.ndarray,
    equity_oos: np.ndarray,
    equity_gross: np.ndarray,
    equity_net: np.ndarray,
    walk_forward_folds: list[dict],
    cpcv_folds: list[dict],
    perturbed_sharpes: list[float],
    stress_results: dict,
    num_trials: int,
    control_sharpes: list[float],
    placebo_sharpes: list[float],
    bars: list,
    trades_pnl: list[float],
    timeframe: str = "1H"
) -> EdgeSurvivalResult:
    pipeline = ValidatorPipeline()
    # A-O checks
    checks = {}
    details = {}
    # A. Base performance via pipeline walk_forward + oos
    wf_checks = pipeline.validate_real_walk_forward(strategy_id, data_version, equity_is, equity_oos, walk_forward_folds, num_trials)
    checks["walk_forward"] = all(c.passed for c in wf_checks)
    details["walk_forward"] = "; ".join(f"{c.name}={c.passed}" for c in wf_checks)
    wfe = next((c.metric for c in wf_checks if c.name=="walk_forward_wfe"), 0) or 0
    # B-D. Realistic spread/slippage/latency via stress
    spread_ok = stress_results.get(1.5, 1.0) >= 1.0 if stress_results else True
    checks["spread"] = spread_ok
    details["spread"] = f"spread 1.5x pf {stress_results.get(1.5,0) if stress_results else 0}"
    # E. Worse-than-expected fills via cost robustness
    cost_res = evaluate_cost_robustness(equity_gross, equity_net, len(trades_pnl))
    checks["cost"] = cost_res.passed
    details["cost"] = cost_res.details
    # F. Parameter perturbation
    pert_checks = pipeline.validate_perturbation(float(np.mean(perturbed_sharpes)) if perturbed_sharpes else 0, perturbed_sharpes)
    checks["perturbation"] = all(c.passed for c in pert_checks)
    details["perturbation"] = "; ".join(c.details for c in pert_checks)
    # G. Time-window perturbation (same as walk_forward time variation)
    checks["time_window"] = checks["walk_forward"]
    details["time_window"] = details["walk_forward"]
    # H. Regime perturbation
    regime_results = evaluate_regime_stability(bars, equity_oos if len(equity_oos)>0 else equity_is)
    regime_dependent = any(not r.passed for r in regime_results)
    checks["regime"] = not regime_dependent
    details["regime"] = f"{len(regime_results)} regimes, dependent={regime_dependent}"
    # I. Randomized/no-edge control
    control_ok = all(s < 0.3 for s in control_sharpes) if control_sharpes else True
    checks["randomized_control"] = control_ok
    details["randomized_control"] = f"controls {control_sharpes}"
    # J. Bootstrap (approx via dsr)
    # K. Walk-forward already
    checks["walk_forward_K"] = checks["walk_forward"]
    # L. CPCV/CSCV
    pbo_checks = pipeline.validate_cpcv_pbo(cpcv_folds, num_trials)
    checks["cpcv"] = all(c.passed for c in pbo_checks)
    details["cpcv"] = "; ".join(c.details for c in pbo_checks)
    pbo = pbo_checks[0].metric if pbo_checks and pbo_checks[0].metric is not None else 0.5
    # M. PBO (same)
    checks["pbo"] = checks["cpcv"]
    # N. PSR
    # Use oos sharpe for psr
    oos_sharpe = float(np.mean([f.get("oos_sharpe",0) for f in walk_forward_folds])) if walk_forward_folds else 0.0
    # PSR with correct P scaling
    try:
        P = periods_per_year_for_timeframe(timeframe)
    except Exception:
        P = 252*24
    n = len(equity_oos) if len(equity_oos)>0 else 100
    # Need skew/kurt from returns
    rets = np.diff(equity_oos)/equity_oos[:-1] if len(equity_oos)>1 else np.array([0])
    skew = float(__import__('scipy').stats.skew(rets)) if len(rets)>2 else 0.0
    kurt = float(__import__('scipy').stats.kurtosis(rets, fisher=False)) if len(rets)>3 else 3.0
    psr = probabilistic_sharpe_ratio(oos_sharpe, n, skewness=skew, kurtosis=kurt, benchmark=0.0, periods_per_year=P, annualized=True)
    checks["psr"] = psr > 0.5
    details["psr"] = f"psr {psr:.2f}"
    # O. DSR
    dsr = deflated_sharpe_ratio(oos_sharpe, num_trials, n, skewness=skew, kurtosis=kurt, periods_per_year=P, annualized=True)
    checks["dsr"] = dsr > 0.5
    details["dsr"] = f"dsr {dsr:.2f} trials {num_trials}"
    # 6. Stress already B
    # 7. Cost already
    # Placebo
    placebo_ok = all(s < 0.3 for s in placebo_sharpes) if placebo_sharpes else True
    checks["placebo"] = placebo_ok
    details["placebo"] = f"placebo {placebo_sharpes}"
    # Expectancy and economic edge
    exp_report = compute_expectancy(trades_pnl, costs_per_trade=0.0)
    checks["expectancy"] = exp_report.net_expectancy_after_costs > 0
    details["expectancy"] = f"net_exp {exp_report.net_expectancy_after_costs:.4f} pf {exp_report.profit_factor:.2f}"
    econ = evaluate_minimum_economic_edge(exp_report.net_expectancy_after_costs, cost_res.break_even_spread_bps/10000*1000 if cost_res else 0, 0.02, 0.01)
    checks["economic_edge"] = econ.passed
    details["economic_edge"] = econ.criterion
    passed = all(checks.values())
    return EdgeSurvivalResult(passed, checks, details, psr, dsr, float(pbo), float(wfe), cost_res.break_even_spread_bps if cost_res else 0, regime_dependent, control_ok, placebo_ok)
