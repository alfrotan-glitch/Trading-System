"""Fixed volatility-normalized mean-reversion assay for broker XAUUSD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.quote_cost_attribution import attribute_quote_costs
from qts.research.xauusd_broker_regime import RegimeBars, _contiguous

LOOKBACK_BARS = 48
Z_THRESHOLD = 2.0
PRIMARY_HORIZON = 6
STABILITY_HORIZON = 24
EXTRA_COST_BPS = (0.0, 1.0, 2.0)
MIN_TRADES = 500
BOOTSTRAP_DRAWS = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 42


@dataclass(frozen=True)
class BollingerSamples:
    """Fixed extreme-reversal directions and executable references."""

    signal_index: np.ndarray
    exit_index: np.ndarray
    direction: np.ndarray
    entry_mid: np.ndarray
    pnl_long: np.ndarray
    pnl_short: np.ndarray


def make_samples(bars: RegimeBars, horizon: int = PRIMARY_HORIZON) -> BollingerSamples:
    """Create causal mean-reversion samples from a fixed prior-window z-score."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    close_mid = (bars.close_bid + bars.close_ask) / 2.0
    signal = np.arange(LOOKBACK_BARS, len(close_mid) - horizon, dtype=np.int64)
    means = np.asarray([np.mean(close_mid[index - LOOKBACK_BARS : index]) for index in signal])
    scales = np.asarray([np.std(close_mid[index - LOOKBACK_BARS : index]) for index in signal])
    z_score = np.divide(
        close_mid[signal] - means,
        scales,
        out=np.full_like(means, np.nan),
        where=scales > 0.0,
    )
    direction = np.where(z_score <= -Z_THRESHOLD, 1, np.where(z_score >= Z_THRESHOLD, -1, 0)).astype(np.int8)
    entry = signal + 1
    exit_index = entry + horizon - 1
    valid = direction != 0
    valid &= _contiguous(bars.time_msc, signal - LOOKBACK_BARS, entry)
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
    return BollingerSamples(
        signal_index=signal,
        exit_index=exit_index,
        direction=direction,
        entry_mid=entry_mid,
        pnl_long=bars.close_bid[exit_index] - bars.open_ask[entry],
        pnl_short=bars.open_bid[entry] - bars.close_ask[exit_index],
    )


def _select_nonoverlap(samples: BollingerSamples, mask: np.ndarray) -> np.ndarray:
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


def _metrics(samples: BollingerSamples, selected: np.ndarray) -> dict[str, Any]:
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
    return {
        "n": int(selected.size),
        "costs": costs,
        "quote_attribution": attribute_quote_costs(
            entry_mid, samples.pnl_long[selected], samples.pnl_short[selected], samples.direction[selected]
        ),
    }


def _evaluate_horizon(
    bars: RegimeBars,
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
        folds.append({"fold": fold, "fold_start": start, "fold_end": end, "signal_n": int(mask.sum()), "metrics": _metrics(samples, selected)})
    holdout_metrics = _metrics(samples, _select_nonoverlap(samples, holdout))
    qualifying = [fold for fold in folds if fold["metrics"].get("n", 0) >= MIN_TRADES]
    positive_folds = sum(float(fold["metrics"]["costs"]["2.0"]["mean_net_bps"]) > 0.0 for fold in qualifying)
    holdout_cost = holdout_metrics["costs"]["2.0"]
    holdout_pass = (
        holdout_metrics["n"] >= MIN_TRADES
        and float(holdout_cost.get("mean_net_bps") or -np.inf) > 0.0
        and float((holdout_cost.get("bootstrap") or {}).get("lo") or -np.inf) > 0.0
    )
    return {
        "definition": {"horizon_bars_including_entry": horizon},
        "window": {"time_msc_min": time_min, "time_msc_max": time_max, "cutoff_time_msc": cutoff_time_msc, "warmup_end_time_msc": warmup_end, "sample_count": int(len(samples.signal_index)), "discovery_sample_count": int(discovery.sum()), "holdout_sample_count": int(holdout.sum())},
        "walk_forward": {"folds": folds, "qualifying_folds": len(qualifying), "positive_folds_at_2bps": positive_folds},
        "holdout": holdout_metrics,
        "holdout_primary_pass": holdout_pass,
        "cost_status": {"quoted_bid_ask": "MEASURED", "commission": "UNMEASURED", "slippage": "UNMEASURED", "financing": "NOT MATERIAL FOR INTRADAY HORIZONS; NOT MEASURED"},
    }


def evaluate_bollinger(
    bars: RegimeBars,
    *,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    """Evaluate fixed primary and stability mean-reversion horizons."""
    primary = _evaluate_horizon(bars, horizon=PRIMARY_HORIZON, cutoff_time_msc=cutoff_time_msc, time_min=time_min, time_max=time_max)
    stability = _evaluate_horizon(bars, horizon=STABILITY_HORIZON, cutoff_time_msc=cutoff_time_msc, time_min=time_min, time_max=time_max)
    primary_folds = primary["walk_forward"]["qualifying_folds"] == 5 and primary["walk_forward"]["positive_folds_at_2bps"] >= 4
    stability_folds = stability["walk_forward"]["qualifying_folds"] == 5 and stability["walk_forward"]["positive_folds_at_2bps"] >= 4
    all_gates = primary["holdout_primary_pass"] and stability["holdout_primary_pass"] and primary_folds and stability_folds
    sample_ready = primary["holdout"]["n"] >= MIN_TRADES and stability["holdout"]["n"] >= MIN_TRADES
    decision = "PROMISING_NOT_VALIDATED" if all_gates else "REJECTED" if sample_ready else "INCONCLUSIVE"
    return {
        "schema": "qts.xauusd_broker_bollinger.v1",
        "definition": {"bar_interval_minutes": 5, "lookback_bars": LOOKBACK_BARS, "z_threshold": Z_THRESHOLD, "rule": "fade a close at or beyond the fixed prior-window z-score band", "entry": "next five-minute bar open", "nonoverlap_rule": "next signal starts after prior fixed exit", "extra_round_trip_cost_bps": list(EXTRA_COST_BPS), "primary_horizon_bars_including_entry": PRIMARY_HORIZON, "stability_horizon_bars_including_entry": STABILITY_HORIZON},
        "primary": primary,
        "stability": stability,
        "decision": decision,
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "safety": {"orders_submitted": 0, "order_send_called": False, "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
        "integrity": {"parameter_search": False, "threshold_search": False, "held_out_used_once": True, "repairs_applied": []},
    }
