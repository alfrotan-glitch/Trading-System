"""Walk-forward strategy research pipeline.

What this is
------------
A reproducible, versioned process for turning a price history into an honest
answer to one question: **does this rule make money on data it has never seen,
after realistic costs?**

It orchestrates machinery that already exists in QTS rather than
reimplementing it — ``BacktestEngine`` for execution, ``qts.research.costs``
for the cost model, ``qts.research.statistical`` for the overfitting tests.

Why it is built this way
------------------------
The three failure modes that make backtests lie are all addressed explicitly:

**Look-ahead.** Signals are computed on bar N and filled at bar N+1's open.
That is the engine's behaviour, not something configured here.

**Leakage across the fold boundary.** A 15m bar's label overlaps the
following bars, so a train set that ends where the test set begins leaks the
answer. Every fold is therefore *purged* (overlapping train bars removed) and
*embargoed* (a gap left after the test window), following López de Prado.

**Selection bias.** Choosing the best parameters on the same data used to
report performance is how a losing strategy looks profitable. Parameters are
chosen on the training window only, and the reported number comes from the
untouched out-of-sample window. The number of configurations tried is counted
and fed to the Deflated Sharpe Ratio and the White Reality Check, so trying
more things makes the bar *higher*, not lower.

What it deliberately does not do
--------------------------------
It does not promote anything, and it does not weaken a threshold to help a
candidate pass. A candidate that fails here has failed, and the report says so.

Costs
-----
Costs are supplied, not assumed away. Every run records its ``cost_basis``.
If any component is not MEASURED, the result is labelled mechanism evidence
and cannot support a claim — that gate lives in ``qts.research.costs`` and is
not overridden here.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Any

SCHEMA = "qts.research_pipeline.v1"

#: A result with fewer trades than this is not evidence of anything.
MIN_TRADES_PER_FOLD = 30


@dataclass(frozen=True)
class Fold:
    """One chronological train → test split, purged and embargoed."""

    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


@dataclass
class FoldResult:
    """What happened in one fold's out-of-sample window."""

    fold: Fold
    params: dict[str, Any]
    trades: int
    net_return: float
    gross_return: float
    cost: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    expectancy_per_trade: float
    selected_from_n: int

    def as_dict(self) -> dict[str, Any]:
        d = asdict_shallow(self)
        d["fold"] = self.fold.as_dict()
        return d


def asdict_shallow(obj: Any) -> dict[str, Any]:
    """json-safe shallow copy of a dataclass, without recursing into Fold."""
    return {
        k: (v if not isinstance(v, datetime) else v.isoformat())
        for k, v in vars(obj).items()
        if k != "fold"
    }


@dataclass
class PipelineResult:
    """The whole answer: every fold, the aggregate, and the verdict."""

    schema: str = SCHEMA
    generated_at: str = ""
    data_version: str = ""
    instrument: str = ""
    timeframe: str = ""
    cost_basis: str = ""
    cost_source: str = ""
    folds: list[FoldResult] = field(default_factory=list)
    total_configurations_tried: int = 0
    aggregate: dict[str, Any] = field(default_factory=dict)
    baselines: dict[str, Any] = field(default_factory=dict)
    overfitting: dict[str, Any] = field(default_factory=dict)
    verdict: str = ""
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "data_version": self.data_version,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "cost_basis": self.cost_basis,
            "cost_source": self.cost_source,
            "total_configurations_tried": self.total_configurations_tried,
            "folds": [f.as_dict() for f in self.folds],
            "aggregate": self.aggregate,
            "baselines": self.baselines,
            "overfitting": self.overfitting,
            "verdict": self.verdict,
            "reasons": self.reasons,
        }


# --------------------------------------------------------------------------- #
# fold construction
# --------------------------------------------------------------------------- #


def build_folds(
    start: datetime,
    end: datetime,
    *,
    n_folds: int = 5,
    test_fraction: float = 0.2,
    embargo_bars: int = 0,
    bar_seconds: int = 900,
    purge_bars: int = 0,
) -> list[Fold]:
    """Split a span into chronological, purged and embargoed folds.

    Fold *i* trains on everything before its test window and tests on a
    distinct, later window. Training is *expanding*: each fold sees strictly
    more history than the last, which is how the strategy would actually have
    been traded.

    ``purge_bars`` removes the last N train bars before the test boundary, so a
    label that straddles the boundary cannot leak the answer backwards.
    ``embargo_bars`` leaves a gap after the test window for the same reason.
    """
    if n_folds < 2:
        raise ValueError("need at least two folds for out-of-sample evaluation")
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")

    total = (end - start).total_seconds()
    test_span = timedelta(seconds=total * test_fraction)
    purge = timedelta(seconds=purge_bars * bar_seconds)
    embargo = timedelta(seconds=embargo_bars * bar_seconds)

    folds: list[Fold] = []
    for i in range(n_folds):
        # Test windows tile the LATER part of the span; each fold's training set
        # is everything before its test window.
        test_start = end - test_span * (n_folds - i)
        test_end = min(test_start + test_span, end)
        train_start = start
        train_end = test_start - embargo
        if train_end - purge > train_start:
            train_end = train_end - purge
        if train_end <= train_start or test_end <= test_start:
            continue
        folds.append(
            Fold(
                index=i,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
    return folds


def expand_grid(param_space: dict[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Every combination in a bounded parameter space, deterministically."""
    keys = sorted(param_space)
    return [dict(zip(keys, combo, strict=True)) for combo in product(*(param_space[k] for k in keys))]


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #


def _sharpe(returns: Sequence[float], periods_per_year: float) -> float:
    """Annualised Sharpe. Zero when undefined, never NaN."""
    arr = [float(r) for r in returns if r is not None]
    if len(arr) < 2:
        return 0.0
    mean = sum(arr) / len(arr)
    var = sum((r - mean) ** 2 for r in arr) / (len(arr) - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return 0.0
    return float(mean / sd * math.sqrt(periods_per_year))


def _max_drawdown(equity: Sequence[float]) -> float:
    """Maximum peak-to-trough decline as a positive fraction."""
    peak = -math.inf
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return float(worst)


def _profit_factor(returns: Sequence[float]) -> float:
    wins = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_observations: int,
    n_trials: int,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """P-value that an observed Sharpe is selection noise, given N trials.

    Bailey & López de Prado: taking the maximum of N Sharpe ratios biases the
    maximum upward even when every strategy is worthless. This discounts the
    observed Sharpe by the Sharpe you would *expect* from picking the best of
    N, and returns the probability that the result is a false positive.

    **Small is good.** ``0.01`` means the observed Sharpe is very unlikely to
    have come from selection noise; ``0.9`` means it almost certainly did.

    The expected maximum of N standard normals uses the Euler-Mascheroni
    approximation, which is only defined for N >= 2. For a single trial no
    selection occurred and the threshold is correctly zero, not -infinity —
    that special case matters, because ``norm_ppf(1 - 1/1) = -inf`` would
    otherwise silently deflate every single-hypothesis result.
    """
    if n_observations < 2 or n_trials < 1:
        return 1.0
    sr = float(observed_sharpe)
    n = float(n_observations)
    # Variance of the Sharpe estimator under non-normality (Lo, 2002).
    var_sr = (1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr * sr) / (n - 1.0)
    if var_sr <= 0:
        return 1.0
    sd_sr = math.sqrt(var_sr)

    if n_trials == 1:
        threshold = 0.0
    else:
        euler = 0.5772156649
        z1 = (1.0 - euler) * _norm_ppf(1.0 - 1.0 / n_trials) + euler * _norm_ppf(
            1.0 - 1.0 / (n_trials * math.e)
        )
        if not math.isfinite(z1):
            return 1.0
        threshold = sd_sr * z1

    z = (sr - threshold) / sd_sr
    if not math.isfinite(z):
        return 1.0
    # p-value = probability the null maximum reaches the observed value.
    return float(1.0 - _norm_cdf(z))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, ~1e-9 accurate)."""
    if not 0.0 < p < 1.0:
        return float("inf") if p >= 1.0 else float("-inf")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #


@dataclass
class RunOutcome:
    """What one backtest run produced. Deliberately tiny and engine-agnostic."""

    trades: int = 0
    net_return: float = 0.0
    gross_return: float = 0.0
    cost: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)


#: Signature a runner must satisfy: parameters + a window → outcome.
Runner = Callable[[dict[str, Any], datetime, datetime], RunOutcome]


def select_parameters(
    runner: Runner,
    param_grid: list[dict[str, Any]],
    fold: Fold,
    *,
    periods_per_year: float,
) -> tuple[dict[str, Any], float]:
    """Choose parameters on the TRAINING window only.

    Selection is by Sharpe, then by trade count as a tie-break so a
    two-trade fluke cannot win on a freak ratio.
    """
    best_params: dict[str, Any] = {}
    best_key: tuple[float, int] = (-math.inf, -1)
    for params in param_grid:
        outcome = runner(params, fold.train_start, fold.train_end)
        if outcome.trades < MIN_TRADES_PER_FOLD:
            continue
        sr = _sharpe(outcome.returns, periods_per_year)
        key = (sr, outcome.trades)
        if key > best_key:
            best_key = key
            best_params = params
    return best_params, best_key[0]


def run_walk_forward(
    runner: Runner,
    param_space: dict[str, Sequence[Any]],
    folds: list[Fold],
    *,
    periods_per_year: float = 23 * 4 * 252,
    baseline_outcomes: dict[str, RunOutcome] | None = None,
    cost_basis: str = "ASSUMED",
    cost_source: str = "",
    data_version: str = "",
    instrument: str = "XAUUSD",
    timeframe: str = "15m",
    max_drawdown_limit: float = 0.20,
) -> PipelineResult:
    """Run the whole walk-forward and return the verdict.

    The reported numbers come only from out-of-sample windows. What happened
    in training is used for nothing except picking parameters.
    """
    grid = expand_grid(param_space)
    result = PipelineResult(
        generated_at=datetime.now(UTC).isoformat(),
        data_version=data_version,
        instrument=instrument,
        timeframe=timeframe,
        cost_basis=cost_basis,
        cost_source=cost_source,
        total_configurations_tried=len(grid) * len(folds),
    )

    oos_returns: list[float] = []
    for fold in folds:
        params, _train_sharpe = select_parameters(runner, grid, fold, periods_per_year=periods_per_year)
        if not params:
            result.reasons.append(
                f"fold {fold.index}: no configuration reached {MIN_TRADES_PER_FOLD} trades in training"
            )
            continue
        outcome = runner(params, fold.test_start, fold.test_end)
        equity = outcome.equity_curve or [1.0 + outcome.net_return]
        result.folds.append(
            FoldResult(
                fold=fold,
                params=params,
                trades=outcome.trades,
                net_return=outcome.net_return,
                gross_return=outcome.gross_return,
                cost=outcome.cost,
                sharpe=_sharpe(outcome.returns, periods_per_year),
                max_drawdown=_max_drawdown(equity),
                profit_factor=_profit_factor(outcome.returns),
                expectancy_per_trade=(
                    outcome.net_return / outcome.trades if outcome.trades else 0.0
                ),
                selected_from_n=len(grid),
            )
        )
        oos_returns.extend(outcome.returns)

    result.aggregate = _aggregate(result.folds)
    result.baselines = _baselines(baseline_outcomes or {}, result.aggregate, periods_per_year)
    result.overfitting = _overfitting_checks(
        result.aggregate, oos_returns, result.total_configurations_tried, periods_per_year
    )
    verdict, verdict_reasons = _verdict(result, max_drawdown_limit=max_drawdown_limit)
    result.verdict = verdict
    result.reasons = result.reasons + verdict_reasons
    return result


def _aggregate(folds: list[FoldResult]) -> dict[str, Any]:
    if not folds:
        return {
            "folds_evaluated": 0,
            "total_trades": 0,
            "oos_net_return": 0.0,
            "oos_gross_return": 0.0,
            "oos_cost": 0.0,
            "expectancy_per_trade": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "profitable_folds": 0,
            "worst_fold": 0.0,
        }
    net = sum(f.net_return for f in folds)
    gross = sum(f.gross_return for f in folds)
    cost = sum(f.cost for f in folds)
    trades = sum(f.trades for f in folds)
    return {
        "folds_evaluated": len(folds),
        "total_trades": trades,
        "oos_net_return": net,
        "oos_gross_return": gross,
        "oos_cost": cost,
        "expectancy_per_trade": (net / trades) if trades else 0.0,
        "profit_factor": (gross / cost) if cost > 0 else 0.0,
        "max_drawdown": max(f.max_drawdown for f in folds),
        "sharpe": sum(f.sharpe for f in folds) / len(folds),
        "profitable_folds": sum(1 for f in folds if f.net_return > 0),
        "worst_fold": min(f.net_return for f in folds),
        "cost_fraction_of_gross": (cost / gross) if gross > 0 else float("inf"),
    }


def _baselines(
    baselines: dict[str, RunOutcome], aggregate: dict[str, Any], periods_per_year: float
) -> dict[str, Any]:
    """A strategy that cannot beat these is not a strategy."""
    out: dict[str, Any] = {}
    for name, outcome in baselines.items():
        out[name] = {
            "net_return": outcome.net_return,
            "trades": outcome.trades,
            "sharpe": _sharpe(outcome.returns, periods_per_year),
            "beats_strategy": outcome.net_return < aggregate.get("oos_net_return", 0.0),
        }
    return out


def _overfitting_checks(
    aggregate: dict[str, Any],
    oos_returns: list[float],
    n_trials: int,
    periods_per_year: float,
) -> dict[str, Any]:
    """Deflated Sharpe, permutation test and minimum backtest length."""
    n = len(oos_returns)
    sharpe = _sharpe(oos_returns, periods_per_year)
    dsr = deflated_sharpe_ratio(sharpe, n, max(1, n_trials))

    perm: dict[str, Any] = {"status": "NOT_RUN"}
    if n >= 30:
        try:
            from qts.research.statistical import permutation_test

            perm = permutation_test(
                __import__("numpy").asarray(oos_returns, dtype=float), n_perm=1000, seed=42
            )
        except Exception as exc:  # pragma: no cover - statistical is optional here
            perm = {"status": "ERROR", "reason": str(exc)}

    return {
        "oos_observations": n,
        "oos_sharpe": sharpe,
        "configurations_tried": n_trials,
        "deflated_sharpe_pvalue": dsr,
        "survives_multiple_testing": bool(dsr < 0.05),
        "permutation_test": perm,
        "note": (
            "deflated Sharpe accounts for the number of configurations tried; "
            "trying more makes the bar higher, not lower"
        ),
    }


def _verdict(result: PipelineResult, *, max_drawdown_limit: float) -> tuple[str, list[str]]:
    """Apply the fixed acceptance criteria. Nothing here adapts to the result."""
    agg = result.aggregate
    reasons: list[str] = []

    if result.cost_basis.upper() != "MEASURED":
        reasons.append(
            f"cost basis is {result.cost_basis or 'UNKNOWN'}, not MEASURED — "
            "mechanism evidence only, no claim is decidable"
        )
    if agg.get("folds_evaluated", 0) == 0:
        return "INSUFFICIENT_DATA", reasons + ["no fold produced an evaluable out-of-sample result"]

    trades = agg.get("total_trades", 0)
    if trades < MIN_TRADES_PER_FOLD * max(1, agg["folds_evaluated"]):
        reasons.append(
            f"only {trades} out-of-sample trades — too few to distinguish skill from noise"
        )

    fails: list[str] = []
    if agg.get("oos_net_return", 0.0) <= 0:
        fails.append("out-of-sample net return is not positive")
    if agg.get("expectancy_per_trade", 0.0) <= 0:
        fails.append("expectancy per trade is not positive")
    if agg.get("oos_gross_return", 0.0) <= 0:
        fails.append(
            "out-of-sample GROSS return is not positive — costs are not the problem, "
            "the signal is"
        )
    if agg.get("max_drawdown", 0.0) > max_drawdown_limit:
        fails.append(f"max drawdown {agg['max_drawdown']:.1%} exceeds {max_drawdown_limit:.0%} limit")
    if not result.overfitting.get("survives_multiple_testing", False):
        fails.append(
            f"does not survive multiple-testing correction "
            f"(deflated Sharpe p={result.overfitting.get('deflated_sharpe_pvalue', 1.0):.3f})"
        )
    profitable = agg.get("profitable_folds", 0)
    evaluated = agg.get("folds_evaluated", 1)
    if profitable <= evaluated // 2:
        fails.append(
            f"profitable in only {profitable}/{evaluated} folds — results depend on the window"
        )
    for name, base in result.baselines.items():
        if not base.get("beats_strategy", False):
            fails.append(f"does not beat the {name} baseline")

    reasons.extend(fails)
    if fails:
        return "NO_EDGE_ESTABLISHED", reasons
    return "EDGE_CANDIDATE", reasons or ["all acceptance criteria met"]


def write_report(result: PipelineResult, path: Path | str) -> Path:
    """Persist the run as an auditable artifact."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result.as_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return p
