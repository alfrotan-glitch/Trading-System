"""Phase 13 & 14: Expectancy, not win rate, and minimum economic edge."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ExpectancyReport:
    expectancy_per_trade: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    win_rate: float
    loss_rate: float
    max_drawdown: float
    expected_shortfall: float
    turnover: float
    cost_per_trade: float
    net_expectancy: float
    net_expectancy_after_costs: float
    trades: int


def compute_expectancy(trades_pnl: list[float], costs_per_trade: float = 0.0) -> ExpectancyReport:
    if not trades_pnl:
        return ExpectancyReport(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    arr = np.array(trades_pnl)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    win_rate = len(wins) / len(arr) if len(arr) > 0 else 0
    loss_rate = 1 - win_rate
    avg_win = float(wins.mean()) if len(wins) > 0 else 0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0
    expectancy = win_rate * avg_win + loss_rate * avg_loss
    pf = (
        float(wins.sum() / -losses.sum())
        if len(losses) > 0 and losses.sum() != 0
        else float("inf")
        if wins.sum() > 0
        else 0
    )
    # max drawdown from cumulative
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = float((peak - cum).max()) if len(cum) > 0 else 0
    es = float(np.percentile(arr, 5)) if len(arr) > 5 else float(arr.min()) if len(arr) > 0 else 0
    turnover = float(len(arr))
    cost = costs_per_trade
    net_exp = expectancy - cost
    return ExpectancyReport(
        expectancy, pf, avg_win, avg_loss, win_rate, loss_rate, dd, es, turnover, cost, expectancy, net_exp, len(arr)
    )


@dataclass
class EconomicEdge:
    expected_net_edge: float
    conservative_cost: float
    statistical_uncertainty: float
    model_penalty: float
    remaining_edge: float
    passed: bool
    criterion: str


def evaluate_minimum_economic_edge(
    expectancy: float, cost: float, uncertainty: float, penalty: float, threshold: float = 0.0
) -> EconomicEdge:
    """Documented criterion: remaining_edge = net_edge - cost - uncertainty - penalty must be > threshold (e.g., 0)."""
    remaining = expectancy - cost - uncertainty - penalty
    # Research-based threshold: require at least 0.5*cost margin of safety (Bailey & Lopez de Prado DSR logic)
    # Here we use threshold 0 for minimal, but document that edge must exceed costs by material margin (e.g., 20% of gross)
    passed = remaining > threshold and remaining > cost * 0.2
    criterion = f"remaining = expectancy {expectancy:.4f} - cost {cost:.4f} - uncertainty {uncertainty:.4f} - penalty {penalty:.4f} = {remaining:.4f} > threshold {threshold} and >20% cost"
    return EconomicEdge(expectancy, cost, uncertainty, penalty, remaining, passed, criterion)
