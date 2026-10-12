"""Performance statistics, uncertainty and multiple-testing helpers.

Annualisation uses 252 trading days. Sharpe ratios are on daily returns that
include flat days (zero return), so exposure is not hidden in the statistic.
Deflation reuses :func:`qts.validation.metrics.deflated_sharpe_ratio` rather
than a second implementation.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from scipy import stats as sps

from qts.research.longhistory.engine import RunResult
from qts.validation.metrics import deflated_sharpe_ratio

TRADING_DAYS = 252


def sharpe(returns: np.ndarray, periods_per_year: int = TRADING_DAYS) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd == 0.0 or not math.isfinite(sd):
        return 0.0
    return float(np.mean(r) / sd * math.sqrt(periods_per_year))


def max_drawdown(equity: np.ndarray) -> float:
    e = np.asarray(equity, dtype=float)
    if e.size == 0:
        return 0.0
    peak = np.maximum.accumulate(e)
    return float(np.min(e / peak - 1.0))


def cagr(initial: float, final: float, n_days: int, periods_per_year: int = TRADING_DAYS) -> float:
    if n_days <= 0 or initial <= 0 or final <= 0:
        return 0.0
    return float((final / initial) ** (periods_per_year / n_days) - 1.0)


def circular_block_bootstrap(
    returns: np.ndarray, stat: Callable[[np.ndarray], float], n_boot: int, block: int, seed: int
) -> np.ndarray:
    """Circular block bootstrap distribution of ``stat`` (keeps short-range dependence)."""
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        return np.zeros(n_boot)
    block = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    out = np.empty(n_boot)
    offsets = np.arange(block)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = ((starts[:, None] + offsets[None, :]) % n).ravel()[:n]
        out[b] = stat(r[idx])
    return out


def sharpe_interval(
    returns: np.ndarray,
    n_boot: int = 1000,
    block: int = 20,
    seed: int = 7,
    periods_per_year: int = TRADING_DAYS,
) -> dict[str, float]:
    def stat(x: np.ndarray) -> float:
        return sharpe(x, periods_per_year)

    dist = circular_block_bootstrap(returns, stat, n_boot, block, seed)
    lo, hi = np.percentile(dist, [2.5, 97.5]) if dist.size else (0.0, 0.0)
    return {
        "sharpe": sharpe(returns, periods_per_year),
        "ci95_low": float(lo),
        "ci95_high": float(hi),
        "share_bootstrap_sharpe_positive": float(np.mean(dist > 0)) if dist.size else 0.0,
    }


def mean_p_value_one_sided(returns: np.ndarray, n_boot: int = 2000, block: int = 20, seed: int = 11) -> float:
    """One-sided bootstrap p-value for H0: mean daily return <= 0.

    The series is centred to the null, then block-resampled; the p-value is the
    share of resampled means at least as large as the observed mean.
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 1.0
    observed = float(np.mean(r))
    centred = r - observed
    dist = circular_block_bootstrap(centred, lambda x: float(np.mean(x)), n_boot, block, seed)
    return float(np.mean(dist >= observed))


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values keyed like the input."""
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(items):
        val = min(1.0, (m - rank) * p)
        running = max(running, val)
        adjusted[key] = running
    return adjusted


def deflated_sharpe(returns: np.ndarray, num_trials: int, periods_per_year: int = TRADING_DAYS) -> dict[str, float]:
    r = np.asarray(returns, dtype=float)
    n = int(r.size)
    if n < 30 or num_trials < 1:
        return {
            "dsr": float("nan"),
            "sharpe_annual": sharpe(r, periods_per_year),
            "n": n,
            "num_trials": num_trials,
        }
    skew = float(sps.skew(r, bias=False)) if np.std(r) > 0 else 0.0
    kurt = float(sps.kurtosis(r, fisher=False, bias=False)) if np.std(r) > 0 else 3.0
    sr = sharpe(r, periods_per_year)
    dsr = deflated_sharpe_ratio(sr, num_trials, n, skew, kurt, periods_per_year, True)
    return {"dsr": float(dsr), "sharpe_annual": sr, "n": n, "num_trials": num_trials, "skew": skew, "kurtosis": kurt}


def trade_summary(run: RunResult, periods_per_year: int = TRADING_DAYS) -> dict[str, float | int]:
    trades = run.trades
    nets = np.array([t.net_usd for t in trades], dtype=float)
    grosses = np.array([t.gross_usd for t in trades], dtype=float)
    n = len(trades)
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    gross_win = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(-losses.sum()) if losses.size else 0.0
    years = max(len(run.days), 1) / periods_per_year
    return {
        "round_turns": n,
        "round_turns_per_year": float(n / years) if years > 0 else 0.0,
        "win_rate": float(wins.size / n) if n else 0.0,
        "expectancy_usd": float(nets.mean()) if n else 0.0,
        "avg_win_usd": float(wins.mean()) if wins.size else 0.0,
        "avg_loss_usd": float(losses.mean()) if losses.size else 0.0,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "stop_exit_share": float(np.mean([t.stopped for t in trades])) if n else 0.0,
        "forced_exit_count": int(sum(t.forced_exit for t in trades)),
        "mean_bars_held": float(np.mean([t.bars_held for t in trades])) if n else 0.0,
        "gross_usd_trades": float(grosses.sum()) if n else 0.0,
    }


def summarize(run: RunResult, num_trials: int | None = None, periods_per_year: int = TRADING_DAYS) -> dict[str, object]:
    """Full, JSON-serialisable summary of one engine run."""
    r = run.returns
    years = max(len(run.days), 1) / periods_per_year
    out: dict[str, object] = {
        "start": str(run.days[0].date()) if len(run.days) else None,
        "end": str(run.days[-1].date()) if len(run.days) else None,
        "bars": int(len(run.days)),
        "initial_equity": run.initial_equity,
        "final_equity": round(run.final_equity, 2),
        "net_usd": round(run.net_usd, 2),
        "gross_usd": round(run.gross_usd, 2),
        "cost_usd": round(run.cost_usd, 2),
        "financing_usd": round(run.financing_usd, 2),
        "cost_to_gross": round(run.cost_usd / run.gross_usd, 4) if run.gross_usd > 0 else None,
        "sharpe": round(sharpe(r, periods_per_year), 4),
        "cagr": round(cagr(run.initial_equity, run.final_equity, len(run.days), periods_per_year), 4),
        "max_drawdown": round(max_drawdown(np.concatenate([[run.initial_equity], run.equity])), 4),
        "exposure": round(run.exposure, 4),
        "turnover_per_year": round(run.turnover_fraction / years, 3) if years > 0 else 0.0,
        "cost_basis": run.cost_basis,
    }
    out.update(
        {k: (round(v, 4) if isinstance(v, float) else v) for k, v in trade_summary(run, periods_per_year).items()}
    )
    if num_trials is not None:
        out["deflated"] = {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in deflated_sharpe(r, num_trials, periods_per_year).items()
        }
    return out
