"""Phase 7: Cost and execution robustness — net performance and break-even cost."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CostScenario:
    spread_bps: float
    commission_per_lot: float
    slippage_bps: float
    delay_ms: int


@dataclass
class CostRobustnessResult:
    gross_sharpe: float
    net_sharpe: float
    net_pf: float
    break_even_spread_bps: float
    break_even_slippage_bps: float
    max_tolerable_deterioration_bps: float
    passed: bool
    details: str


def evaluate_cost_robustness(
    equity_gross: np.ndarray, equity_net: np.ndarray, trades: int, avg_spread_bps: float = 3.0
) -> CostRobustnessResult:
    """Compare gross vs net, find break-even cost."""

    def sharpe(eq):
        if len(eq) < 2:
            return 0.0
        rets = np.diff(eq) / eq[:-1]
        if np.std(rets) == 0:
            return 0.0
        return float(np.mean(rets) / np.std(rets) * np.sqrt(252 * 6.5))  # 1H approx

    gross_sharpe = sharpe(equity_gross)
    net_sharpe = sharpe(equity_net)
    # profit factor net
    rets_net = np.diff(equity_net) / equity_net[:-1] if len(equity_net) > 1 else np.array([0])
    wins = rets_net[rets_net > 0].sum()
    losses = -rets_net[rets_net < 0].sum()
    pf = float(wins / losses) if losses > 0 else float("inf") if wins > 0 else 0.0
    # break-even: linear interpolation where sharpe crosses 0
    # assume spread cost proportional: net = gross - cost * trades
    # Find max spread where net still >0
    # Simplified: if net_sharpe <0, break_even is current spread * (1 + net_sharpe/gross_sharpe) etc
    # For now, estimate break-even as avg_spread * (1 + net_sharpe/max(0.1,gross_sharpe)) if gross>0
    if gross_sharpe > 0.1:
        be_spread = avg_spread_bps * (1 + net_sharpe / gross_sharpe) if net_sharpe > 0 else avg_spread_bps * 0.5
    else:
        be_spread = avg_spread_bps
    max_tol = max(0.0, be_spread - avg_spread_bps)
    passed = net_sharpe > 0.2 and pf > 1.0 and max_tol > 0.5
    details = f"net_sharpe {net_sharpe:.2f} pf {pf:.2f} be_spread {be_spread:.1f}bps tol {max_tol:.1f}bps"
    return CostRobustnessResult(gross_sharpe, net_sharpe, pf, be_spread, be_spread, max_tol, passed, details)


def run_conservative_cost_scenarios(backtest_engine, instrument, timeframe, data_version, strategy_id, params):
    """Run actual spread scenarios through the engine's stress rerun.

    The old implementation reran the baseline and labelled its Sharpe as a
    stressed result (and wrote zero on exceptions).  This accessor now refuses
    to infer a scenario from a baseline.  A BacktestEngine exposes
    ``run_stress``; other engines return an explicit unavailable record.
    """
    spreads = [1.0, 1.5, 2.0]
    runner = getattr(backtest_engine, "run_stress", None)
    if not callable(runner):
        return {
            "status": "NOT_IMPLEMENTED",
            "reason": "cost scenario engine does not expose provenance-preserving stress reruns",
        }
    try:
        measured = runner(
            instrument,
            timeframe,
            data_version,
            strategy_id,
            params,
            spreads=spreads,
        )
    except Exception as exc:  # preserve failure; do not turn it into zero
        return {"status": "UNAVAILABLE", "reason": f"cost stress rerun failed: {type(exc).__name__}: {exc}"}
    return {
        "status": "MEASURED",
        "scenarios": {f"spread_{s}x": measured[s] for s in spreads if s in measured},
        "source": "BacktestEngine.run_stress actual reruns",
    }
