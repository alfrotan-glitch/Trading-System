"""Phase 5 & 14: Edge survival test A-O + minimum economic edge — comprehensive validator."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qts.edge.cost_robustness import evaluate_cost_robustness
from qts.edge.expectancy import compute_expectancy, evaluate_minimum_economic_edge
from qts.edge.regime_stability import evaluate_regime_stability
from qts.research.costs import CostDecomposition, CostModel, TradeRecord, decompose_costs
from qts.validation.metrics import deflated_sharpe_ratio, periods_per_year_for_timeframe, probabilistic_sharpe_ratio
from qts.validation.pipeline import ValidatorPipeline


@dataclass
class EdgeSurvivalResult:
    passed: bool
    checks: dict[str, bool]
    details: dict[str, str]
    psr: float | None
    dsr: float | None
    pbo: float | None
    wfe: float
    cost_break_even_bps: float
    regime_dependent: bool
    null_rejected: bool
    placebo_rejected: bool
    cost_decomposition: CostDecomposition | None = None


def validate_edge_survival(
    strategy_id: str,
    data_version: str,
    equity_is: np.ndarray,
    equity_oos: np.ndarray,
    equity_gross: np.ndarray | None,
    equity_net: np.ndarray | None,
    walk_forward_folds: list[dict],
    cpcv_folds: list[dict],
    perturbed_sharpes: list[float],
    stress_results: dict,
    num_trials: int,
    control_sharpes: list[float],
    placebo_sharpes: list[float],
    bars: list,
    trades_pnl: list[float],
    timeframe: str = "1H",
    cost_model: CostModel | None = None,
    trade_records: list[TradeRecord] | None = None,
) -> EdgeSurvivalResult:
    """Evaluate every survival gate.

    ``cost_model`` + ``trade_records`` turn a gross trade list into a real
    gross/net decomposition. Without them the ``cost`` and ``economic_edge``
    gates stay blocked (``NOT_IMPLEMENTED``), and — critically — the
    ``expectancy`` gate is evaluated on GROSS P&L and labelled as such: it is
    never presented as a net expectation it did not measure.
    """
    pipeline = ValidatorPipeline()
    # A decomposition is only built when the caller supplied both halves of it.
    # A model without trades (or trades without a model) is not evidence.
    decomposition: CostDecomposition | None = None
    if cost_model is not None and trade_records is not None:
        decomposition = decompose_costs(list(trade_records), cost_model)
    # A-O checks
    checks = {}
    details = {}
    # A. Base performance via pipeline walk_forward + oos
    wf_checks = pipeline.validate_real_walk_forward(
        strategy_id, data_version, equity_is, equity_oos, walk_forward_folds, num_trials
    )
    checks["walk_forward"] = all(c.passed for c in wf_checks)
    details["walk_forward"] = "; ".join(f"{c.name}={c.passed}" for c in wf_checks)
    wfe = next((c.metric for c in wf_checks if c.name == "walk_forward_wfe"), 0) or 0
    # B-D. Realistic spread/slippage/latency via stress
    stress_1_5 = stress_results.get(1.5) if isinstance(stress_results, dict) else None
    try:
        spread_ok = stress_1_5 is not None and np.isfinite(float(stress_1_5)) and float(stress_1_5) >= 1.0
    except (TypeError, ValueError):
        spread_ok = False
    checks["spread"] = spread_ok
    details["spread"] = (
        f"spread 1.5x pf {stress_1_5}"
        if spread_ok
        else "spread stress missing, unavailable, or below threshold"
    )
    # E. Worse-than-expected fills via cost robustness.  A backtest that only
    # produced net equity is not allowed to masquerade as gross-vs-net cost
    # evidence.
    if equity_gross is None or equity_net is None:
        if decomposition is not None and decomposition.trades >= 2:
            # The caller gave a cost model and real trades — build the curves
            # here so the gate is decidable instead of permanently blocked.
            import numpy as _np

            equity_gross = _np.asarray(decomposition.equity_gross, dtype=float)
            equity_net = _np.asarray(decomposition.equity_net, dtype=float)
            cost_res = evaluate_cost_robustness(equity_gross, equity_net, decomposition.trades)
            checks["cost"] = bool(cost_res.passed) and decomposition.claim_eligible
            details["cost"] = (
                f"{cost_res.details}; break-even cost multiple "
                f"{decomposition.break_even_cost_multiple:.2f}x; "
                f"claim_eligible={decomposition.claim_eligible}"
            )
        else:
            cost_res = None
            checks["cost"] = False
            details["cost"] = "gross/net cost decomposition NOT_IMPLEMENTED — blocks"
    else:
        cost_res = evaluate_cost_robustness(equity_gross, equity_net, len(trades_pnl))
        checks["cost"] = cost_res.passed
        details["cost"] = cost_res.details
    # F. Parameter perturbation
    pert_checks = pipeline.validate_perturbation(
        float(np.mean(perturbed_sharpes)) if perturbed_sharpes else 0, perturbed_sharpes
    )
    checks["perturbation"] = all(c.passed for c in pert_checks)
    details["perturbation"] = "; ".join(c.details for c in pert_checks)
    # G. Time-window perturbation (same as walk_forward time variation)
    checks["time_window"] = checks["walk_forward"]
    details["time_window"] = details["walk_forward"]
    # H. Regime perturbation.  A missing bar/equity population is not a
    # stable regime result.
    if not bars or len(equity_oos) < 2:
        regime_results = []
        regime_dependent = True
        checks["regime"] = False
        details["regime"] = "regime evidence unavailable — BLOCKS"
    else:
        regime_results = evaluate_regime_stability(bars, equity_oos)
        regime_dependent = any(not r.passed for r in regime_results)
        checks["regime"] = bool(regime_results) and not regime_dependent
        details["regime"] = f"{len(regime_results)} regimes, dependent={regime_dependent}"
    # I. Randomized/no-edge control
    control_ok = bool(control_sharpes) and all(s < 0.3 for s in control_sharpes)
    checks["randomized_control"] = control_ok
    details["randomized_control"] = (
        f"controls {control_sharpes}" if control_sharpes else "randomized control was not executed — NOT_IMPLEMENTED"
    )
    # J. Bootstrap (approx via dsr)
    # K. Walk-forward already
    checks["walk_forward_K"] = checks["walk_forward"]
    # L. CPCV/CSCV
    pbo_checks = pipeline.validate_cpcv_pbo(cpcv_folds, num_trials)
    checks["cpcv"] = all(c.passed for c in pbo_checks)
    details["cpcv"] = "; ".join(c.details for c in pbo_checks)
    pbo = pbo_checks[0].metric if pbo_checks and pbo_checks[0].metric is not None else None
    if pbo is None:
        details["pbo"] = "PBO UNAVAILABLE because CPCV was not executed"
    # M. PBO (same)
    checks["pbo"] = checks["cpcv"]
    # N/O. PSR and DSR require observed OOS returns.  Never substitute a
    # synthetic observation count, zero returns, or a guessed annualization.
    if len(equity_oos) < 2 or not walk_forward_folds:
        psr = None
        dsr = None
        checks["psr"] = False
        checks["dsr"] = False
        details["psr"] = "PSR UNAVAILABLE — no observed OOS return vector"
        details["dsr"] = "DSR UNAVAILABLE — no observed OOS return vector"
    else:
        oos_sharpe = float(np.mean([f.get("oos_sharpe", 0) for f in walk_forward_folds]))
        P = periods_per_year_for_timeframe(timeframe)
        n = len(equity_oos) - 1
        rets = np.diff(equity_oos) / np.where(equity_oos[:-1] == 0, 1, equity_oos[:-1])
        rets = rets[np.isfinite(rets)]
        if len(rets) < 2:
            psr = None
            dsr = None
            checks["psr"] = False
            checks["dsr"] = False
            details["psr"] = "PSR UNAVAILABLE — insufficient finite OOS returns"
            details["dsr"] = "DSR UNAVAILABLE — insufficient finite OOS returns"
        else:
            skew = float(__import__("scipy").stats.skew(rets)) if len(rets) > 2 else 0.0
            kurt = float(__import__("scipy").stats.kurtosis(rets, fisher=False)) if len(rets) > 3 else 3.0
            psr = probabilistic_sharpe_ratio(
                oos_sharpe, n, skewness=skew, kurtosis=kurt, benchmark=0.0, periods_per_year=P, annualized=True
            )
            dsr = deflated_sharpe_ratio(
                oos_sharpe, num_trials, n, skewness=skew, kurtosis=kurt, periods_per_year=P, annualized=True
            )
            checks["psr"] = psr > 0.5
            checks["dsr"] = dsr > 0.5
            details["psr"] = f"psr {psr:.2f}"
            details["dsr"] = f"dsr {dsr:.2f} trials {num_trials}"
    # 6. Stress already B
    # 7. Cost already
    # Placebo
    placebo_ok = bool(placebo_sharpes) and all(s < 0.3 for s in placebo_sharpes)
    checks["placebo"] = placebo_ok
    details["placebo"] = (
        f"placebo {placebo_sharpes}" if placebo_sharpes else "placebo control was not executed — NOT_IMPLEMENTED"
    )
    # Expectancy and economic edge.
    #
    # The cost per trade comes from the decomposition when one exists. Calling
    # this with ``costs_per_trade=0.0`` used to make "net expectancy" equal to
    # gross expectancy, which is exactly the confusion a cost model exists to
    # prevent. When no cost is modelled the result is reported as GROSS and the
    # gate fails instead of passing on an uncosted number.
    modelled_cost_per_trade = decomposition.cost_per_trade if decomposition is not None else 0.0
    # When trade records were supplied they are the authoritative P&L vector:
    # mixing them with a separately-passed ``trades_pnl`` could charge costs
    # against a different set of trades than the ones that were costed.
    pnl_vector = [t.gross_pnl_usd for t in trade_records] if trade_records else list(trades_pnl)
    exp_report = compute_expectancy(pnl_vector, costs_per_trade=modelled_cost_per_trade)
    cost_is_modelled = decomposition is not None and decomposition.trades > 0
    checks["expectancy"] = bool(cost_is_modelled and exp_report.net_expectancy_after_costs > 0)
    details["expectancy"] = (
        f"net_exp {exp_report.net_expectancy_after_costs:.4f} (gross {exp_report.expectancy_per_trade:.4f} "
        f"- cost {modelled_cost_per_trade:.4f}/trade) pf {exp_report.profit_factor:.2f}"
        if cost_is_modelled
        else (
            f"GROSS exp {exp_report.expectancy_per_trade:.4f} pf {exp_report.profit_factor:.2f} — "
            "no cost model supplied, net expectancy was NOT measured (blocks)"
        )
    )
    # The economic-edge criterion subtracts the cost actually modelled, not a
    # number reverse-engineered from a break-even spread in different units.
    econ_cost = (
        decomposition.cost_per_trade
        if decomposition is not None
        else (cost_res.break_even_spread_bps / 10000 * 1000 if cost_res else 0)
    )
    econ = evaluate_minimum_economic_edge(
        exp_report.net_expectancy_after_costs,
        econ_cost,
        0.02,
        0.01,
    )
    checks["economic_edge"] = bool(
        (cost_res is not None or decomposition is not None) and econ.passed and cost_is_modelled
    )
    details["economic_edge"] = (
        econ.criterion if cost_res is not None else "economic edge blocked: cost decomposition unavailable"
    )
    passed = all(checks.values())
    return EdgeSurvivalResult(
        passed,
        checks,
        details,
        psr,
        dsr,
        float(pbo) if pbo is not None else None,
        float(wfe),
        cost_res.break_even_spread_bps if cost_res else 0,
        regime_dependent,
        control_ok,
        placebo_ok,
        decomposition,
    )
