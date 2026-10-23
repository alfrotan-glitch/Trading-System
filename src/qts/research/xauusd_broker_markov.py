"""Fixed first-order return-sign Markov assay for broker XAUUSD research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.xauusd_broker_regime import RegimeBars, _contiguous

HORIZON_BARS = 3
EXTRA_COST_BPS = (0.0, 1.0, 2.0)
MIN_TRADES = 500
MIN_TRAINING_SAMPLES = 500
BOOTSTRAP_DRAWS = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 42


@dataclass(frozen=True)
class MarkovSamples:
    """Return-sign states and executable entry/exit references."""

    signal_index: np.ndarray
    exit_index: np.ndarray
    state: np.ndarray
    target: np.ndarray
    entry_mid: np.ndarray
    pnl_long: np.ndarray
    pnl_short: np.ndarray


@dataclass(frozen=True)
class MarkovModel:
    """Smoothed positive-target probabilities by prior-return sign."""

    probability_by_state: dict[int, float]


def make_samples(bars: RegimeBars) -> MarkovSamples:
    """Create causal sign-state samples with exact five-minute continuity."""
    close_mid = (bars.close_bid + bars.close_ask) / 2.0
    log_return = np.full(len(close_mid), np.nan, dtype=np.float64)
    log_return[1:] = np.log(close_mid[1:] / close_mid[:-1])
    signal = np.arange(1, len(close_mid) - HORIZON_BARS, dtype=np.int64)
    entry = signal + 1
    exit_index = signal + HORIZON_BARS
    state = np.sign(log_return[signal]).astype(np.int8)
    entry_mid = (bars.open_bid[entry] + bars.open_ask[entry]) / 2.0
    exit_mid = (bars.close_bid[exit_index] + bars.close_ask[exit_index]) / 2.0
    target = (exit_mid > entry_mid).astype(np.int8)
    valid = state != 0
    valid &= _contiguous(bars.time_msc, signal, entry)
    valid &= _contiguous(bars.time_msc, entry, exit_index)
    valid &= np.isfinite(bars.open_bid[entry]) & np.isfinite(bars.open_ask[entry])
    valid &= np.isfinite(bars.close_bid[exit_index]) & np.isfinite(bars.close_ask[exit_index])
    valid &= bars.open_ask[entry] >= bars.open_bid[entry]
    valid &= bars.close_ask[exit_index] >= bars.close_bid[exit_index]
    signal, entry, exit_index = signal[valid], entry[valid], exit_index[valid]
    state, target = state[valid], target[valid]
    entry_mid = (bars.open_bid[entry] + bars.open_ask[entry]) / 2.0
    return MarkovSamples(
        signal_index=signal,
        exit_index=exit_index,
        state=state,
        target=target,
        entry_mid=entry_mid,
        pnl_long=bars.close_bid[exit_index] - bars.open_ask[entry],
        pnl_short=bars.open_bid[entry] - bars.close_ask[exit_index],
    )


def fit_markov(samples: MarkovSamples, mask: np.ndarray) -> MarkovModel:
    """Fit fixed Beta(1,1)-smoothed probabilities on the supplied prefix."""
    if int(mask.sum()) < MIN_TRAINING_SAMPLES:
        raise ValueError("training prefix is below the fixed minimum")
    probabilities: dict[int, float] = {}
    for state in (-1, 1):
        state_mask = mask & (samples.state == state)
        count = int(state_mask.sum())
        if count == 0:
            raise ValueError("training prefix lacks a return-sign state")
        positive = int(samples.target[state_mask].sum())
        probabilities[state] = (positive + 1.0) / (count + 2.0)
    return MarkovModel(probability_by_state=probabilities)


def predict_direction(samples: MarkovSamples, model: MarkovModel) -> np.ndarray:
    """Apply fixed 0.55/0.45 direction gates without fitting or search."""
    positions = np.zeros(len(samples.state), dtype=np.int8)
    for state, probability in model.probability_by_state.items():
        state_mask = samples.state == state
        positions[state_mask & (probability >= 0.55)] = 1
        positions[state_mask & (probability <= 0.45)] = -1
    return positions


def _select_nonoverlap(samples: MarkovSamples, mask: np.ndarray) -> np.ndarray:
    selected: list[int] = []
    last_exit = -1
    for position in np.flatnonzero(mask):
        if int(samples.signal_index[position]) > last_exit:
            selected.append(int(position))
            last_exit = int(samples.exit_index[position])
    return np.asarray(selected, dtype=np.int64)


def _bootstrap(values: np.ndarray) -> dict[str, Any]:
    if len(values) < 2:
        return {"draws": 0, "lo": None, "hi": None, "p_mean_le_zero": None}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    block_count = int(np.ceil(len(values) / BOOTSTRAP_BLOCK))
    means = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    offsets = np.arange(BOOTSTRAP_BLOCK, dtype=np.int64)
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, len(values), size=block_count)
        indices = (starts[:, None] + offsets).reshape(-1)[: len(values)] % len(values)
        means[draw] = float(values[indices].mean())
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_size_trades": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "lo": float(np.quantile(means, 0.025)),
        "hi": float(np.quantile(means, 0.975)),
        "p_mean_le_zero": float(np.mean(means <= 0.0)),
    }


def _metrics(samples: MarkovSamples, positions: np.ndarray, selected: np.ndarray) -> dict[str, Any]:
    if selected.size == 0:
        return {"n": 0, "costs": {str(cost): {"mean_net_bps": None} for cost in EXTRA_COST_BPS}}
    entry_mid = samples.entry_mid[selected]
    gross = np.where(positions[selected] > 0, samples.pnl_long[selected], samples.pnl_short[selected])
    costs: dict[str, Any] = {}
    for extra_cost in EXTRA_COST_BPS:
        net = gross - entry_mid * (extra_cost / 10_000.0)
        net_bps = net / entry_mid * 10_000.0
        costs[str(extra_cost)] = {
            "mean_net_bps": float(net_bps.mean()),
            "median_net_bps": float(np.median(net_bps)),
            "win_rate": float(np.mean(net > 0.0)),
            "bootstrap": _bootstrap(net_bps) if extra_cost == 2.0 else None,
        }
    return {"n": int(selected.size), "costs": costs}


def evaluate_markov(
    bars: RegimeBars,
    *,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    """Run fixed five-fold training-prefix evaluation and one holdout."""
    samples = make_samples(bars)
    signal_time = bars.time_msc[samples.signal_index]
    exit_time = bars.time_msc[samples.exit_index]
    discovery = (signal_time < cutoff_time_msc) & (exit_time < cutoff_time_msc)
    holdout = signal_time >= cutoff_time_msc
    warmup_end = int(time_min + (cutoff_time_msc - time_min) * 0.20)
    edges = np.linspace(warmup_end, cutoff_time_msc, 6, dtype=np.int64)
    folds: list[dict[str, Any]] = []
    for fold in range(5):
        start, end = int(edges[fold]), int(edges[fold + 1])
        train_mask = discovery & (signal_time < start) & (exit_time < start)
        test_mask = discovery & (signal_time >= start) & (signal_time < end) & (exit_time < end)
        if int(train_mask.sum()) < MIN_TRAINING_SAMPLES:
            folds.append({"fold": fold, "status": "INCONCLUSIVE", "train_n": int(train_mask.sum()), "test_signal_n": int(test_mask.sum())})
            continue
        try:
            model = fit_markov(samples, train_mask)
        except ValueError as error:
            folds.append({"fold": fold, "status": "INCONCLUSIVE", "train_n": int(train_mask.sum()), "test_signal_n": int(test_mask.sum()), "reason": str(error)})
            continue
        positions = predict_direction(samples, model)
        selected = _select_nonoverlap(samples, test_mask & (positions != 0))
        folds.append({
            "fold": fold,
            "status": "TESTED",
            "fold_start": start,
            "fold_end": end,
            "train_n": int(train_mask.sum()),
            "test_signal_n": int(test_mask.sum()),
            "probability_by_state": {str(state): probability for state, probability in model.probability_by_state.items()},
            "metrics": _metrics(samples, positions, selected),
        })
    model = fit_markov(samples, discovery)
    positions = predict_direction(samples, model)
    holdout_metrics = _metrics(samples, positions, _select_nonoverlap(samples, holdout & (positions != 0)))
    qualifying = [fold for fold in folds if fold.get("status") == "TESTED" and fold.get("metrics", {}).get("n", 0) >= MIN_TRADES]
    positive_folds = sum(float(fold["metrics"]["costs"]["2.0"]["mean_net_bps"]) > 0.0 for fold in qualifying)
    holdout_cost = holdout_metrics["costs"]["2.0"]
    holdout_pass = (
        holdout_metrics["n"] >= MIN_TRADES
        and float(holdout_cost.get("mean_net_bps") or -np.inf) > 0.0
        and float((holdout_cost.get("bootstrap") or {}).get("lo") or -np.inf) > 0.0
    )
    all_gates = len(qualifying) == 5 and positive_folds >= 4 and holdout_pass
    decision = "PROMISING_NOT_VALIDATED" if all_gates else "REJECTED" if holdout_metrics["n"] >= MIN_TRADES and not holdout_pass else "INCONCLUSIVE"
    return {
        "schema": "qts.xauusd_broker_markov.v1",
        "definition": {
            "bar_interval_minutes": 5,
            "state": "sign of completed five-minute mid log return",
            "target": "positive executable entry-mid to exit-mid move",
            "laplace_beta": [1, 1],
            "long_probability_floor": 0.55,
            "short_probability_ceiling": 0.45,
            "entry_latency_bars": 1,
            "exit_bars_after_entry": HORIZON_BARS,
            "nonoverlap_rule": "next signal starts after prior fixed exit",
            "extra_round_trip_cost_bps": list(EXTRA_COST_BPS),
        },
        "window": {
            "time_msc_min": time_min,
            "time_msc_max": time_max,
            "cutoff_time_msc": cutoff_time_msc,
            "warmup_end_time_msc": warmup_end,
            "sample_count": int(len(samples.signal_index)),
            "discovery_sample_count": int(discovery.sum()),
            "holdout_sample_count": int(holdout.sum()),
        },
        "walk_forward": {"folds": folds, "qualifying_folds": len(qualifying), "positive_folds_at_2bps": positive_folds},
        "holdout": holdout_metrics,
        "cost_status": {
            "quoted_bid_ask": "MEASURED",
            "commission": "UNMEASURED",
            "slippage": "UNMEASURED",
            "financing": "NOT MATERIAL FOR INTRADAY HORIZONS; NOT MEASURED",
        },
        "decision": decision,
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "safety": {"orders_submitted": 0, "order_send_called": False, "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
        "integrity": {"parameter_search": False, "threshold_search": False, "held_out_used_once": True, "repairs_applied": []},
    }
