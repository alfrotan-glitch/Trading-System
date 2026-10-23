"""Fixed compressed-range breakout assay for confirmed broker XAUUSD data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.xauusd_broker_ml import BrokerBars

FIFTEEN_MINUTE_MS = 900_000
ONE_MINUTE_MS = 60_000
COMPRESSION_WINDOW = 32
BASELINE_WINDOW = 256
PRIMARY_HORIZON = 8
STABILITY_HORIZON = 16
EXTRA_COST_BPS = (0.0, 1.0, 2.0)
MIN_TRADES = 500
BOOTSTRAP_DRAWS = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 42


@dataclass(frozen=True)
class CompressionBars:
    """Complete fifteen-minute bars made from the raw bid/ask ledger."""

    time_msc: np.ndarray
    open_bid: np.ndarray
    open_ask: np.ndarray
    high_mid: np.ndarray
    low_mid: np.ndarray
    close_bid: np.ndarray
    close_ask: np.ndarray


@dataclass(frozen=True)
class CompressionSamples:
    """Fixed compression-breakout signals and executable entry/exit references."""

    signal_index: np.ndarray
    exit_index: np.ndarray
    direction: np.ndarray
    entry_mid: np.ndarray
    pnl_long: np.ndarray
    pnl_short: np.ndarray


def aggregate_complete_fifteen_minute(bars: BrokerBars) -> CompressionBars:
    """Keep only complete contiguous groups of fifteen one-minute bars."""
    times = np.asarray(bars.time_msc, dtype=np.int64)
    groups = times // FIFTEEN_MINUTE_MS
    starts = np.concatenate(([0], np.flatnonzero(groups[1:] != groups[:-1]) + 1))
    ends = np.concatenate((starts[1:], [len(times)]))
    kept: list[tuple[int, int]] = []
    for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
        if end - start == 15 and np.all(np.diff(times[start:end]) == ONE_MINUTE_MS):
            kept.append((start, end))
    if not kept:
        raise ValueError("no complete fifteen-minute groups")
    start_indices = np.asarray([start for start, _ in kept], dtype=np.int64)
    end_indices = np.asarray([end - 1 for _, end in kept], dtype=np.int64)
    return CompressionBars(
        time_msc=times[start_indices],
        open_bid=np.asarray(bars.open_bid, dtype=np.float64)[start_indices],
        open_ask=np.asarray(bars.open_ask, dtype=np.float64)[start_indices],
        high_mid=np.asarray(
            [np.max(bars.high_mid[start:end]) for start, end in kept], dtype=np.float64
        ),
        low_mid=np.asarray(
            [np.min(bars.low_mid[start:end]) for start, end in kept], dtype=np.float64
        ),
        close_bid=np.asarray(bars.close_bid, dtype=np.float64)[end_indices],
        close_ask=np.asarray(bars.close_ask, dtype=np.float64)[end_indices],
    )


def _contiguous(times: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    regular = np.diff(times) == FIFTEEN_MINUTE_MS
    gap_prefix = np.concatenate(([0], np.cumsum(~regular, dtype=np.int64)))
    return gap_prefix[right] == gap_prefix[left]


def _causal_features(bars: CompressionBars) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return prior-range medians, baseline medians, prior extrema, and direction."""
    close_mid = (bars.close_bid + bars.close_ask) / 2.0
    bar_range = (bars.high_mid - bars.low_mid) / close_mid
    n = len(close_mid)
    prior_range_median = np.full(n, np.nan, dtype=np.float64)
    trailing_range_median = np.full(n, np.nan, dtype=np.float64)
    prior_high = np.full(n, np.nan, dtype=np.float64)
    prior_low = np.full(n, np.nan, dtype=np.float64)
    for index in range(COMPRESSION_WINDOW, n):
        prior = slice(index - COMPRESSION_WINDOW, index)
        prior_range_median[index] = float(np.median(bar_range[prior]))
        prior_high[index] = float(np.max(bars.high_mid[prior]))
        prior_low[index] = float(np.min(bars.low_mid[prior]))
        baseline_start = index - BASELINE_WINDOW
        baseline_end = index
        if baseline_start >= COMPRESSION_WINDOW:
            trailing_range_median[index] = float(
                np.median(prior_range_median[baseline_start:baseline_end])
            )
    direction = np.zeros(n, dtype=np.int8)
    direction[close_mid > prior_high] = 1
    direction[close_mid < prior_low] = -1
    return prior_range_median, trailing_range_median, direction, close_mid


def make_samples(bars: CompressionBars, horizon: int = PRIMARY_HORIZON) -> CompressionSamples:
    """Create the fixed compressed-range breakout samples for one horizon."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    prior_range, baseline_range, breakout_direction, close_mid = _causal_features(bars)
    signal = np.arange(BASELINE_WINDOW + COMPRESSION_WINDOW, len(close_mid) - horizon, dtype=np.int64)
    entry = signal + 1
    exit_index = entry + horizon - 1
    quiet = prior_range[signal] < baseline_range[signal]
    direction = breakout_direction[signal]
    valid = quiet & (direction != 0)
    valid &= _contiguous(bars.time_msc, signal, entry)
    valid &= _contiguous(bars.time_msc, entry, exit_index)
    valid &= np.isfinite(bars.open_bid[entry]) & np.isfinite(bars.open_ask[entry])
    valid &= np.isfinite(bars.close_bid[exit_index]) & np.isfinite(bars.close_ask[exit_index])
    valid &= bars.open_ask[entry] >= bars.open_bid[entry]
    valid &= bars.close_ask[exit_index] >= bars.close_bid[exit_index]
    signal = signal[valid]
    entry = entry[valid]
    exit_index = exit_index[valid]
    direction = direction[valid]
    entry_mid = (bars.open_bid[entry] + bars.open_ask[entry]) / 2.0
    return CompressionSamples(
        signal_index=signal,
        exit_index=exit_index,
        direction=direction,
        entry_mid=entry_mid,
        pnl_long=bars.close_bid[exit_index] - bars.open_ask[entry],
        pnl_short=bars.open_bid[entry] - bars.close_ask[exit_index],
    )


def _select_nonoverlap(samples: CompressionSamples, mask: np.ndarray) -> np.ndarray:
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


def _metrics(samples: CompressionSamples, selected: np.ndarray) -> dict[str, Any]:
    if selected.size == 0:
        return {"n": 0, "costs": {str(cost): {"mean_net_bps": None} for cost in EXTRA_COST_BPS}}
    entry_mid = samples.entry_mid[selected]
    gross = np.where(samples.direction[selected] > 0, samples.pnl_long[selected], samples.pnl_short[selected])
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


def _evaluate_horizon(
    bars: CompressionBars,
    *,
    horizon: int,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    samples = make_samples(bars, horizon)
    signal_time = bars.time_msc[samples.signal_index]
    exit_time = bars.time_msc[samples.exit_index]
    discovery = (signal_time < cutoff_time_msc) & (exit_time < cutoff_time_msc)
    holdout = signal_time >= cutoff_time_msc
    warmup_end = int(time_min + (cutoff_time_msc - time_min) * 0.20)
    edges = np.linspace(warmup_end, cutoff_time_msc, 6, dtype=np.int64)
    folds: list[dict[str, Any]] = []
    for fold in range(5):
        start, end = int(edges[fold]), int(edges[fold + 1])
        mask = discovery & (signal_time >= start) & (signal_time < end) & (exit_time < end)
        selected = _select_nonoverlap(samples, mask)
        folds.append(
            {
                "fold": fold,
                "fold_start": start,
                "fold_end": end,
                "signal_n": int(mask.sum()),
                "metrics": _metrics(samples, selected),
            }
        )
    holdout_metrics = _metrics(samples, _select_nonoverlap(samples, holdout))
    qualifying = [fold for fold in folds if fold["metrics"].get("n", 0) >= MIN_TRADES]
    positive_folds = sum(
        float(fold["metrics"]["costs"]["2.0"]["mean_net_bps"]) > 0.0 for fold in qualifying
    )
    holdout_cost = holdout_metrics["costs"]["2.0"]
    holdout_pass = (
        holdout_metrics["n"] >= MIN_TRADES
        and float(holdout_cost.get("mean_net_bps") or -np.inf) > 0.0
        and float((holdout_cost.get("bootstrap") or {}).get("lo") or -np.inf) > 0.0
    )
    return {
        "definition": {"horizon_bars_including_entry": horizon},
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
        "holdout_primary_pass": holdout_pass,
        "cost_status": {
            "quoted_bid_ask": "MEASURED",
            "commission": "UNMEASURED",
            "slippage": "UNMEASURED",
            "financing": "NOT MATERIAL FOR INTRADAY HORIZONS; NOT MEASURED",
        },
    }


def evaluate_compression(
    bars: CompressionBars,
    *,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    """Evaluate the corrected fixed compression-breakout rule."""
    primary = _evaluate_horizon(
        bars,
        horizon=PRIMARY_HORIZON,
        cutoff_time_msc=cutoff_time_msc,
        time_min=time_min,
        time_max=time_max,
    )
    stability = _evaluate_horizon(
        bars,
        horizon=STABILITY_HORIZON,
        cutoff_time_msc=cutoff_time_msc,
        time_min=time_min,
        time_max=time_max,
    )
    primary_folds = primary["walk_forward"]["positive_folds_at_2bps"] >= 4 and primary["walk_forward"]["qualifying_folds"] == 5
    stability_folds = stability["walk_forward"]["positive_folds_at_2bps"] >= 4 and stability["walk_forward"]["qualifying_folds"] == 5
    all_gates = primary["holdout_primary_pass"] and stability["holdout_primary_pass"] and primary_folds and stability_folds
    sample_ready = primary["holdout"]["n"] >= MIN_TRADES and stability["holdout"]["n"] >= MIN_TRADES
    decision = "PROMISING_NOT_VALIDATED" if all_gates else "REJECTED" if sample_ready else "INCONCLUSIVE"
    return {
        "schema": "qts.xauusd_broker_compression.v1",
        "definition": {
            "bar_interval_minutes": 15,
            "compression_window_bars": COMPRESSION_WINDOW,
            "baseline_window_bars": BASELINE_WINDOW,
            "compression_rule": "median of prior 32 bar ranges is below median of the prior 256 prior-32 medians",
            "breakout_rule": "completed close exceeds prior 32-bar high or falls below prior 32-bar low",
            "entry": "next fifteen-minute bar open",
            "nonoverlap_rule": "next signal starts after prior fixed exit",
            "extra_round_trip_cost_bps": list(EXTRA_COST_BPS),
            "primary_horizon_bars_including_entry": PRIMARY_HORIZON,
            "stability_horizon_bars_including_entry": STABILITY_HORIZON,
        },
        "primary": primary,
        "stability": stability,
        "decision": decision,
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "safety": {"orders_submitted": 0, "order_send_called": False, "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
        "integrity": {"parameter_search": False, "threshold_search": False, "held_out_used_once": True, "repairs_applied": []},
    }
