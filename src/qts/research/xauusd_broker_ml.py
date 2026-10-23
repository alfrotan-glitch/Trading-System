"""Fixed causal quote-only ML assay for broker XAUUSD research.

The model is deliberately small and frozen by preregistration.  It is a
research engine, not an execution strategy or promotion authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

FEATURE_NAMES = (
    "return_1",
    "return_3",
    "return_5",
    "return_15",
    "return_60",
    "abs_return_mean_5",
    "abs_return_mean_15",
    "abs_return_mean_60",
    "spread_bps",
)
BAR_MS = 60_000
PRIMARY_HORIZON = 5
STABILITY_HORIZON = 15
EXTRA_COST_BPS = (0.0, 1.0, 2.0)
MIN_TRADES = 500
BOOTSTRAP_DRAWS = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 42


@dataclass(frozen=True)
class BrokerBars:
    """One-minute bars made from the raw bid/ask ledger."""

    time_msc: np.ndarray
    open_bid: np.ndarray
    open_ask: np.ndarray
    high_mid: np.ndarray
    low_mid: np.ndarray
    close_bid: np.ndarray
    close_ask: np.ndarray
    mean_spread: np.ndarray


@dataclass(frozen=True)
class Samples:
    """Causal model rows and executable entry/exit references."""

    signal_index: np.ndarray
    entry_index: np.ndarray
    exit_index: np.ndarray
    features: np.ndarray
    target: np.ndarray
    entry_mid: np.ndarray
    pnl_long: np.ndarray
    pnl_short: np.ndarray


@dataclass(frozen=True)
class _LogisticModel:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray


def build_features(bars: BrokerBars) -> tuple[np.ndarray, np.ndarray]:
    """Build fixed features using only the current and earlier bars."""
    close_mid = (bars.close_bid + bars.close_ask) / 2.0
    n = close_mid.size
    returns = np.full(n, np.nan, dtype=np.float64)
    returns[1:] = np.log(close_mid[1:] / close_mid[:-1])
    features = np.full((n, len(FEATURE_NAMES)), np.nan, dtype=np.float64)
    for column, lag in enumerate((1, 3, 5, 15, 60)):
        features[lag:, column] = np.log(close_mid[lag:] / close_mid[:-lag])
    abs_returns = np.abs(returns)
    for column, window in enumerate((5, 15, 60), start=5):
        cumulative = np.concatenate(([0.0], np.cumsum(np.nan_to_num(abs_returns, nan=0.0))))
        features[window - 1 :, column] = (
            cumulative[window:] - cumulative[:-window]
        ) / window
    mid = close_mid
    features[:, 8] = bars.mean_spread / mid * 10_000.0
    valid = np.isfinite(features).all(axis=1) & np.isfinite(close_mid)
    return features, valid


def _contiguous(times: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    regular = np.diff(times) == BAR_MS
    gap_prefix = np.concatenate(([0], np.cumsum(~regular, dtype=np.int64)))
    return gap_prefix[right] == gap_prefix[left]


def make_samples(bars: BrokerBars, horizon: int) -> Samples:
    """Create fixed-latency samples, excluding gaps and unavailable endpoints."""
    features, feature_valid = build_features(bars)
    n = len(bars.time_msc)
    signal = np.arange(0, n - horizon, dtype=np.int64)
    entry = signal + 1
    exit_index = signal + horizon
    valid = feature_valid[signal]
    valid &= _contiguous(bars.time_msc, signal, entry)
    valid &= _contiguous(bars.time_msc, entry, exit_index)
    valid &= np.isfinite(bars.open_bid[entry]) & np.isfinite(bars.open_ask[entry])
    valid &= np.isfinite(bars.close_bid[exit_index]) & np.isfinite(bars.close_ask[exit_index])
    valid &= bars.open_ask[entry] >= bars.open_bid[entry]
    valid &= bars.close_ask[exit_index] >= bars.close_bid[exit_index]
    signal = signal[valid]
    entry = entry[valid]
    exit_index = exit_index[valid]
    entry_mid = (bars.open_bid[entry] + bars.open_ask[entry]) / 2.0
    exit_mid = (bars.close_bid[exit_index] + bars.close_ask[exit_index]) / 2.0
    target = (exit_mid > entry_mid).astype(np.int8)
    pnl_long = bars.close_bid[exit_index] - bars.open_ask[entry]
    pnl_short = bars.open_bid[entry] - bars.close_ask[exit_index]
    return Samples(
        signal_index=signal,
        entry_index=entry,
        exit_index=exit_index,
        features=features[signal],
        target=target,
        entry_mid=entry_mid,
        pnl_long=pnl_long,
        pnl_short=pnl_short,
    )


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit_logistic(features: np.ndarray, target: np.ndarray, *, alpha: float = 0.01) -> _LogisticModel:
    if len(features) == 0 or np.unique(target).size < 2:
        raise ValueError("training prefix must contain both target classes")
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (features - mean) / scale
    design = np.column_stack((np.ones(len(standardized)), standardized))
    weights = np.zeros(design.shape[1], dtype=np.float64)
    target_float = target.astype(np.float64)
    regularizer = np.eye(design.shape[1], dtype=np.float64) * alpha
    regularizer[0, 0] = 0.0
    for _ in range(50):
        probability = _sigmoid(design @ weights)
        residual = probability - target_float
        gradient = (design.T @ residual) / len(design) + regularizer @ weights
        curvature = probability * (1.0 - probability)
        hessian = (design.T * curvature) @ design / len(design) + regularizer
        hessian.flat[:: hessian.shape[0] + 1] += 1e-10
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        if float(np.linalg.norm(step, ord=np.inf)) < 1e-8:
            break
    return _LogisticModel(mean=mean, scale=scale, weights=weights)


def _predict(model: _LogisticModel, features: np.ndarray) -> np.ndarray:
    standardized = (features - model.mean) / model.scale
    design = np.column_stack((np.ones(len(standardized)), standardized))
    return _sigmoid(design @ model.weights)


def _select_nonoverlap(samples: Samples, mask: np.ndarray) -> np.ndarray:
    selected: list[int] = []
    last_exit = -1
    for position in np.flatnonzero(mask):
        exit_index = int(samples.exit_index[position])
        if int(samples.signal_index[position]) > last_exit:
            selected.append(int(position))
            last_exit = exit_index
    return np.asarray(selected, dtype=np.int64)


def _bootstrap(values: np.ndarray) -> dict[str, Any]:
    if values.size < 2:
        return {"draws": 0, "mean": None, "lo": None, "hi": None, "p_mean_le_zero": None}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    block_count = int(np.ceil(values.size / BOOTSTRAP_BLOCK))
    means = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    offsets = np.arange(BOOTSTRAP_BLOCK, dtype=np.int64)
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, values.size, size=block_count)
        indices = (starts[:, None] + offsets).reshape(-1)[: values.size] % values.size
        means[draw] = float(values[indices].mean())
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_size_trades": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "mean": float(values.mean()),
        "lo": float(np.quantile(means, 0.025)),
        "hi": float(np.quantile(means, 0.975)),
        "p_mean_le_zero": float(np.mean(means <= 0.0)),
    }


def _metrics(samples: Samples, positions: np.ndarray, selected: np.ndarray) -> dict[str, Any]:
    if selected.size == 0:
        return {"n": 0, "costs": {str(cost): {"mean_net_bps": None} for cost in EXTRA_COST_BPS}}
    entry_mid = samples.entry_mid[selected]
    gross = np.where(positions[selected] > 0, samples.pnl_long[selected], samples.pnl_short[selected])
    costs: dict[str, Any] = {}
    for extra_cost in EXTRA_COST_BPS:
        net = gross - entry_mid * (extra_cost / 10_000.0)
        net_bps = net / entry_mid * 10_000.0
        costs[str(extra_cost)] = {
            "mean_net_price": float(net.mean()),
            "mean_net_bps": float(net_bps.mean()),
            "median_net_bps": float(np.median(net_bps)),
            "win_rate": float(np.mean(net > 0.0)),
            "std_net_bps": float(net_bps.std(ddof=1)) if len(net_bps) > 1 else None,
            "t_stat_naive": float(net_bps.mean() / (net_bps.std(ddof=1) / np.sqrt(len(net_bps))))
            if len(net_bps) > 1 and float(net_bps.std(ddof=1)) > 0.0
            else None,
            "bootstrap": _bootstrap(net_bps) if extra_cost == 2.0 else None,
        }
    return {"n": int(selected.size), "costs": costs}


def _evaluate_predictions(samples: Samples, probabilities: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    positions = np.where(probabilities >= 0.5, 1, -1).astype(np.int8)
    selected = _select_nonoverlap(samples, mask)
    return _metrics(samples, positions, selected)


def evaluate_broker_ml(
    bars: BrokerBars,
    *,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    """Run the preregistered walk-forward and frozen-holdout assay."""
    primary = make_samples(bars, PRIMARY_HORIZON)
    stability = make_samples(bars, STABILITY_HORIZON)
    signal_time = bars.time_msc[primary.signal_index]
    exit_time = bars.time_msc[primary.exit_index]
    discovery_mask = (signal_time < cutoff_time_msc) & (exit_time < cutoff_time_msc)
    holdout_mask = signal_time >= cutoff_time_msc
    discovery_times = np.asarray([time_min, cutoff_time_msc], dtype=np.int64)
    warmup_end = int(time_min + (cutoff_time_msc - time_min) * 0.20)
    fold_edges = np.linspace(warmup_end, cutoff_time_msc, 6, dtype=np.int64)
    folds: list[dict[str, Any]] = []
    for fold in range(5):
        fold_start, fold_end = int(fold_edges[fold]), int(fold_edges[fold + 1])
        train_mask = discovery_mask & (signal_time < fold_start) & (exit_time < fold_start)
        test_mask = discovery_mask & (signal_time >= fold_start) & (signal_time < fold_end) & (exit_time < fold_end)
        if int(np.count_nonzero(train_mask)) < MIN_TRADES or int(np.unique(primary.target[train_mask]).size) < 2:
            folds.append({"fold": fold, "status": "INCONCLUSIVE", "train_n": int(train_mask.sum()), "test_n": int(test_mask.sum()), "reason": "training minimum or class diversity failed"})
            continue
        model = _fit_logistic(primary.features[train_mask], primary.target[train_mask])
        probabilities = _predict(model, primary.features)
        metrics = _evaluate_predictions(primary, probabilities, test_mask)
        folds.append({"fold": fold, "status": "TESTED", "fold_start": fold_start, "fold_end": fold_end, "train_n": int(train_mask.sum()), "test_signal_n": int(test_mask.sum()), "metrics": metrics})
    train_mask = discovery_mask
    model = _fit_logistic(primary.features[train_mask], primary.target[train_mask])
    probabilities = _predict(model, primary.features)
    holdout_metrics = _evaluate_predictions(primary, probabilities, holdout_mask)
    stability_signal_time = bars.time_msc[stability.signal_index]
    stability_mask = stability_signal_time >= cutoff_time_msc
    stability_probabilities = _predict(model, stability.features)
    stability_metrics = _evaluate_predictions(stability, stability_probabilities, stability_mask)
    qualifying = [fold for fold in folds if fold.get("status") == "TESTED" and fold.get("metrics", {}).get("n", 0) >= MIN_TRADES]
    positive_folds = sum(
        float(fold["metrics"]["costs"]["2.0"]["mean_net_bps"]) > 0.0 for fold in qualifying
    )
    holdout_cost = holdout_metrics.get("costs", {}).get("2.0", {})
    holdout_pass = (
        holdout_metrics.get("n", 0) >= MIN_TRADES
        and float(holdout_cost.get("mean_net_bps") or -np.inf) > 0.0
        and float((holdout_cost.get("bootstrap") or {}).get("lo") or -np.inf) > 0.0
    )
    all_gates = len(qualifying) == 5 and positive_folds >= 4 and holdout_pass
    if all_gates:
        decision = "PROMISING_NOT_VALIDATED"
    elif holdout_metrics.get("n", 0) >= MIN_TRADES and not holdout_pass:
        decision = "REJECTED"
    else:
        decision = "INCONCLUSIVE"
    return {
        "schema": "qts.xauusd_broker_ml.v1",
        "definition": {
            "features": list(FEATURE_NAMES),
            "model": "ridge logistic regression; alpha=0.01; Newton iterations=50",
            "primary_horizon_minutes": PRIMARY_HORIZON,
            "stability_horizon_minutes": STABILITY_HORIZON,
            "entry_latency_bars": 1,
            "nonoverlap_rule": "next signal starts after prior fixed exit",
            "extra_round_trip_cost_bps": list(EXTRA_COST_BPS),
        },
        "window": {
            "time_msc_min": time_min,
            "time_msc_max": time_max,
            "cutoff_time_msc": cutoff_time_msc,
            "warmup_end_time_msc": warmup_end,
            "primary_rows": int(len(primary.signal_index)),
            "discovery_samples": int(discovery_mask.sum()),
            "holdout_samples": int(holdout_mask.sum()),
            "stability_holdout_samples": int(stability_mask.sum()),
        },
        "walk_forward": {"folds": folds, "qualifying_folds": len(qualifying), "positive_folds_at_2bps": positive_folds},
        "holdout": holdout_metrics,
        "stability_holdout": stability_metrics,
        "cost_status": {
            "quoted_bid_ask": "MEASURED",
            "commission": "UNMEASURED",
            "slippage": "UNMEASURED",
            "financing": "NOT MATERIAL FOR INTRADAY HORIZONS; NOT MEASURED",
            "note": "0 bps includes the observed broker quote sides; 1/2 bps are extra round-trip stress assumptions.",
        },
        "decision": decision,
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "safety": {"orders_submitted": 0, "order_send_called": False, "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
        "integrity": {"held_out_used_once_after_freeze": True, "feature_search": False, "parameter_search": False, "repairs_applied": []},
        "_discovery_times": discovery_times.tolist(),
    }
