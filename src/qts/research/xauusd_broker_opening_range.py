"""Fixed opening-range breakout/fade assay for broker XAUUSD research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.xauusd_broker_ml import BrokerBars

UTC_DAY_MINUTES = 1_440
EVENT_START_MINUTES = (8 * 60, 13 * 60 + 30)
RANGE_MINUTES = 30
BREAKOUT_WINDOW_MINUTES = 60
HOLD_MINUTES = 30
BAR_MS = 60_000
EXTRA_COST_BPS = (0.0, 1.0, 2.0)
MIN_TRADES = 500
BOOTSTRAP_DRAWS = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 42
HYPOTHESES = {"H-ORB-01-BREAK": 1, "H-ORB-01-FADE": -1}


@dataclass(frozen=True)
class OpeningRangeEvents:
    """Causal opening-range events with executable references."""

    signal_index: np.ndarray
    entry_index: np.ndarray
    exit_index: np.ndarray
    event_start_minute: np.ndarray
    breakout_direction: np.ndarray
    entry_mid: np.ndarray
    pnl_long: np.ndarray
    pnl_short: np.ndarray
    event_count: int
    incomplete_range_count: int
    ambiguous_breakout_count: int
    no_breakout_count: int


@dataclass(frozen=True)
class OpeningRangeSamples:
    """Fixed direction mapping over opening-range events."""

    signal_index: np.ndarray
    exit_index: np.ndarray
    direction: np.ndarray
    entry_mid: np.ndarray
    pnl_long: np.ndarray
    pnl_short: np.ndarray


def _contiguous_minutes(minutes: np.ndarray, left: int, right: int) -> bool:
    return right >= left and bool(np.all(np.diff(minutes[left : right + 1]) == 1))


def extract_events(bars: BrokerBars) -> OpeningRangeEvents:
    """Extract one fixed event per UTC opening and stop at its first breach."""
    times = np.asarray(bars.time_msc, dtype=np.int64)
    minutes = times // BAR_MS
    n = len(minutes)
    if n == 0:
        raise ValueError("opening-range assay requires at least one bar")
    if np.any(np.diff(minutes) <= 0):
        raise ValueError("opening-range assay requires strictly increasing bars")

    signal_indices: list[int] = []
    entry_indices: list[int] = []
    exit_indices: list[int] = []
    event_starts: list[int] = []
    breakout_directions: list[int] = []
    incomplete_range_count = 0
    ambiguous_breakout_count = 0
    no_breakout_count = 0
    day_numbers = np.unique(minutes // UTC_DAY_MINUTES)
    for day in day_numbers.tolist():
        day_start = int(day) * UTC_DAY_MINUTES
        for start_minute in EVENT_START_MINUTES:
            event_start = day_start + start_minute
            range_start = int(np.searchsorted(minutes, event_start))
            range_end = range_start + RANGE_MINUTES - 1
            if range_start >= n or minutes[range_start] != event_start or range_end >= n:
                incomplete_range_count += 1
                continue
            if not _contiguous_minutes(minutes, range_start, range_end):
                incomplete_range_count += 1
                continue
            range_high = float(np.max(bars.high_mid[range_start : range_end + 1]))
            range_low = float(np.min(bars.low_mid[range_start : range_end + 1]))
            breakout_index: int | None = None
            breakout_direction: int | None = None
            search_end = min(range_start + RANGE_MINUTES + BREAKOUT_WINDOW_MINUTES, n)
            for index in range(range_end + 1, search_end):
                if minutes[index] != event_start + (index - range_start):
                    break
                above = bool(bars.high_mid[index] > range_high)
                below = bool(bars.low_mid[index] < range_low)
                if above and below:
                    ambiguous_breakout_count += 1
                    breakout_index = None
                    breakout_direction = None
                    break
                if above or below:
                    breakout_index = index
                    breakout_direction = 1 if above else -1
                    break
            if breakout_index is None or breakout_direction is None:
                no_breakout_count += 1
                continue
            entry = breakout_index + 1
            exit_index = entry + HOLD_MINUTES - 1
            if exit_index >= n or not _contiguous_minutes(minutes, range_start, exit_index):
                incomplete_range_count += 1
                continue
            if not (
                np.isfinite(bars.open_bid[entry])
                and np.isfinite(bars.open_ask[entry])
                and np.isfinite(bars.close_bid[exit_index])
                and np.isfinite(bars.close_ask[exit_index])
                and bars.open_ask[entry] >= bars.open_bid[entry]
                and bars.close_ask[exit_index] >= bars.close_bid[exit_index]
            ):
                incomplete_range_count += 1
                continue
            signal_indices.append(breakout_index)
            entry_indices.append(entry)
            exit_indices.append(exit_index)
            event_starts.append(event_start)
            breakout_directions.append(breakout_direction)

    signal = np.asarray(signal_indices, dtype=np.int64)
    entry_array = np.asarray(entry_indices, dtype=np.int64)
    exit_array = np.asarray(exit_indices, dtype=np.int64)
    direction = np.asarray(breakout_directions, dtype=np.int8)
    entry_mid = (bars.open_bid[entry_array] + bars.open_ask[entry_array]) / 2.0
    return OpeningRangeEvents(
        signal_index=signal,
        entry_index=entry_array,
        exit_index=exit_array,
        event_start_minute=np.asarray(event_starts, dtype=np.int64),
        breakout_direction=direction,
        entry_mid=entry_mid,
        pnl_long=bars.close_bid[exit_array] - bars.open_ask[entry_array],
        pnl_short=bars.open_bid[entry_array] - bars.close_ask[exit_array],
        event_count=int(len(day_numbers) * len(EVENT_START_MINUTES)),
        incomplete_range_count=incomplete_range_count,
        ambiguous_breakout_count=ambiguous_breakout_count,
        no_breakout_count=no_breakout_count,
    )


def make_samples(bars: BrokerBars, direction_multiplier: int) -> OpeningRangeSamples:
    """Apply one of the two fixed breakout direction mappings."""
    if direction_multiplier not in {-1, 1}:
        raise ValueError("direction_multiplier must be -1 or 1")
    events = extract_events(bars)
    return OpeningRangeSamples(
        signal_index=events.signal_index,
        exit_index=events.exit_index,
        direction=(events.breakout_direction * direction_multiplier).astype(np.int8),
        entry_mid=events.entry_mid,
        pnl_long=events.pnl_long,
        pnl_short=events.pnl_short,
    )


def _select_nonoverlap(samples: OpeningRangeSamples, mask: np.ndarray) -> np.ndarray:
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


def _metrics(samples: OpeningRangeSamples, selected: np.ndarray) -> dict[str, Any]:
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


def _evaluate_hypothesis(
    bars: BrokerBars,
    *,
    direction_multiplier: int,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    samples = make_samples(bars, direction_multiplier)
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
    all_gates = len(qualifying) == 5 and positive_folds >= 4 and holdout_pass
    decision = (
        "PROMISING_NOT_VALIDATED"
        if all_gates
        else "REJECTED"
        if holdout_metrics["n"] >= MIN_TRADES and not holdout_pass
        else "INCONCLUSIVE"
    )
    return {
        "definition": {
            "event_utc_starts": ["08:00", "13:30"],
            "opening_range_minutes": RANGE_MINUTES,
            "breakout_window_minutes": BREAKOUT_WINDOW_MINUTES,
            "entry_latency_bars": 1,
            "hold_minutes_including_entry_bar": HOLD_MINUTES,
            "direction_multiplier": direction_multiplier,
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
    }


def evaluate_opening_range(
    bars: BrokerBars,
    *,
    cutoff_time_msc: int,
    time_min: int,
    time_max: int,
) -> dict[str, Any]:
    """Evaluate both predeclared opening-range direction mappings."""
    events = extract_events(bars)
    hypotheses = {
        name: _evaluate_hypothesis(
            bars,
            direction_multiplier=multiplier,
            cutoff_time_msc=cutoff_time_msc,
            time_min=time_min,
            time_max=time_max,
        )
        for name, multiplier in HYPOTHESES.items()
    }
    return {
        "schema": "qts.xauusd_broker_opening_range.v1",
        "event_extraction": {
            "event_count": events.event_count,
            "qualifying_event_count": int(len(events.signal_index)),
            "incomplete_range_count": events.incomplete_range_count,
            "ambiguous_breakout_count": events.ambiguous_breakout_count,
            "no_breakout_count": events.no_breakout_count,
        },
        "hypotheses": hypotheses,
        "decision": "NO_PROMOTION",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "safety": {
            "orders_submitted": 0,
            "order_send_called": False,
            "DEMO_EXECUTION": "DISABLED",
            "LIVE": "LOCKED",
        },
        "integrity": {
            "parameter_search": False,
            "threshold_search": False,
            "held_out_used_once_per_hypothesis": True,
            "repairs_applied": [],
        },
    }
