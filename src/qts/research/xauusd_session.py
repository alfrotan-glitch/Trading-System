"""Fixed UTC session-conditioned XAUUSD tick strategy assay.

This is a research assay, not an execution path. It uses only raw bid/ask
quotes, measured UTC historical timestamps, and three fixed four-hour session
hypotheses. No threshold or session boundary is searched.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.data.mt5_timestamp_basis import timestamp_basis_assessment
from qts.research.xauusd_tick_discovery import discovery_cutoff

SCHEMA = "qts.xauusd_session.v1"
BUCKET_MS = 15 * 60 * 1000
LOOKBACK_MS = 4 * 60 * 60 * 1000
SESSION_TOLERANCE_MS = 30 * 60 * 1000
EXTRA_ROUND_TRIP_COSTS_BPS = (0.0, 1.0, 2.0)
SPECS: tuple[dict[str, Any], ...] = (
    {"id": "H-SES-ASIA-REV-4H", "start_minute": 0, "end_minute": 240, "sign": -1},
    {"id": "H-SES-LDN-MOM-4H", "start_minute": 480, "end_minute": 720, "sign": 1},
    {"id": "H-SES-NY-MOM-4H", "start_minute": 810, "end_minute": 1050, "sign": 1},
)
REVERSAL_SPECS: tuple[dict[str, Any], ...] = (
    {"id": "H-SES-LDN-REV-4H", "start_minute": 480, "end_minute": 720, "sign": -1},
    {"id": "H-SES-NY-REV-4H", "start_minute": 810, "end_minute": 1050, "sign": -1},
)


@dataclass
class Bar:
    bucket: int
    first_time: int
    first_bid: float
    first_ask: float
    last_time: int
    last_bid: float
    last_ask: float


def _valid_quote(bid: np.ndarray, ask: np.ndarray) -> np.ndarray:
    return np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)


def _consume_batch(
    bars: list[Bar],
    stamp: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    last_stamp: int | None,
) -> int | None:
    if stamp.size == 0:
        return last_stamp
    if last_stamp is not None and int(stamp[0]) < last_stamp:
        raise ValueError("raw time_msc moved backward; refusing to repair or reorder")
    if np.any(np.diff(stamp) < 0):
        raise ValueError("raw time_msc moved backward inside a batch")
    valid = _valid_quote(bid, ask)
    bucket = (stamp // BUCKET_MS) * BUCKET_MS
    starts = np.r_[0, np.flatnonzero(bucket[1:] != bucket[:-1]) + 1]
    ends = np.r_[starts[1:], stamp.size]
    for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
        valid_slice = valid[start:end]
        if not valid_slice.any():
            continue
        first_offset = int(np.flatnonzero(valid_slice)[0]) + start
        last_offset = int(np.flatnonzero(valid_slice)[-1]) + start
        current = int(bucket[first_offset])
        if bars and bars[-1].bucket == current:
            bar = bars[-1]
            bar.last_time = int(stamp[last_offset])
            bar.last_bid = float(bid[last_offset])
            bar.last_ask = float(ask[last_offset])
        else:
            bars.append(
                Bar(
                    bucket=current,
                    first_time=int(stamp[first_offset]),
                    first_bid=float(bid[first_offset]),
                    first_ask=float(ask[first_offset]),
                    last_time=int(stamp[last_offset]),
                    last_bid=float(bid[last_offset]),
                    last_ask=float(ask[last_offset]),
                )
            )
    return int(stamp[-1])


def _load_bars(dataset_dir: Path) -> tuple[dict[str, Any], list[Bar], int]:
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    bars: list[Bar] = []
    last_stamp: int | None = None
    for part in manifest.get("parts") or []:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc", "bid", "ask"]):
            last_stamp = _consume_batch(
                bars,
                np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64),
                np.asarray(batch.column("bid").to_numpy(zero_copy_only=False), dtype=np.float64),
                np.asarray(batch.column("ask").to_numpy(zero_copy_only=False), dtype=np.float64),
                last_stamp,
            )
    return manifest, bars, int(last_stamp or 0)


def _before(bars: list[Bar], target: int) -> tuple[int, float, float] | None:
    candidates = [bar for bar in bars if bar.last_time < target]
    if not candidates:
        return None
    bar = candidates[-1]
    return bar.last_time, bar.last_bid, bar.last_ask


def _after(bars: list[Bar], target: int) -> tuple[int, float, float] | None:
    for bar in bars:
        if bar.first_time >= target:
            return bar.first_time, bar.first_bid, bar.first_ask
    return None


def _mid(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0


def _event(bars: list[Bar], day_value: date, spec: dict[str, Any]) -> dict[str, Any] | None:
    day_start = int(datetime(day_value.year, day_value.month, day_value.day, tzinfo=UTC).timestamp() * 1000)
    start = day_start + int(spec["start_minute"]) * 60_000
    end = day_start + int(spec["end_minute"]) * 60_000
    reference = _before(bars, start - LOOKBACK_MS)
    signal_quote = _before(bars, start)
    entry = _after(bars, start)
    exit_quote = _after(bars, end)
    if reference is None or signal_quote is None or entry is None or exit_quote is None:
        return None
    if (
        signal_quote[0] - reference[0] < LOOKBACK_MS - SESSION_TOLERANCE_MS
        or entry[0] - start > SESSION_TOLERANCE_MS
        or exit_quote[0] - end > SESSION_TOLERANCE_MS
    ):
        return None
    signal_return = _mid(signal_quote[1], signal_quote[2]) - _mid(reference[1], reference[2])
    signal = 1 if signal_return > 0 else -1 if signal_return < 0 else 0
    if signal == 0:
        return None
    position = signal * int(spec["sign"])
    entry_price = entry[2] if position > 0 else entry[1]
    exit_price = exit_quote[1] if position > 0 else exit_quote[2]
    entry_mid = _mid(entry[1], entry[2])
    quote_only_bps = (exit_price - entry_price) / entry_mid * 10_000.0
    return {
        "date": day_value.isoformat(),
        "hypothesis": spec["id"],
        "position": "LONG" if position > 0 else "SHORT",
        "signal_return_price": signal_return,
        "entry_time_msc": entry[0],
        "exit_time_msc": exit_quote[0],
        "quote_only_return_bps": quote_only_bps,
        "entry_spread_bps": (entry[2] - entry[1]) / entry_mid * 10_000.0,
        "exit_spread_bps": (exit_quote[2] - exit_quote[1]) / _mid(exit_quote[1], exit_quote[2]) * 10_000.0,
    }


def _stats(events: list[dict[str, Any]], cost_bps: float) -> dict[str, Any]:
    values = np.asarray([float(event["quote_only_return_bps"]) - cost_bps for event in events], dtype=np.float64)
    n = int(values.size)
    mean = float(values.mean()) if n else None
    std = float(values.std(ddof=1)) if n > 1 else None
    t_stat = mean / (std / math.sqrt(n)) if mean is not None and std and n > 1 else None
    return {
        "n": n,
        "mean_net_bps": mean,
        "median_net_bps": float(np.median(values)) if n else None,
        "std_net_bps": std,
        "t_stat": t_stat,
        "positive_fraction": float(np.mean(values > 0)) if n else None,
        "total_net_bps": float(values.sum()) if n else None,
        "min_net_bps": float(values.min()) if n else None,
        "max_net_bps": float(values.max()) if n else None,
    }


def _split(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    dates = sorted({event["date"] for event in events})
    n = len(dates)
    discovery_end = max(1, int(n * 0.60))
    validation_end = max(discovery_end + 1, int(n * 0.80))
    cut_dates = {
        "discovery": set(dates[:discovery_end]),
        "validation": set(dates[discovery_end:validation_end]),
        "holdout": set(dates[validation_end:]),
    }
    return {name: [event for event in events if event["date"] in selected] for name, selected in cut_dates.items()}


def _verdict(split_stats: dict[str, dict[str, Any]]) -> str:
    if any((split_stats[name]["n"] or 0) < 20 for name in ("discovery", "validation", "holdout")):
        return "INCONCLUSIVE"
    if any((split_stats[name]["mean_net_bps"] or 0.0) <= 0 for name in ("discovery", "validation", "holdout")):
        return "REJECTED"
    if (split_stats["holdout"]["t_stat"] or 0.0) < 2.0:
        return "TESTED"
    return "PROMISING"


def scan_dataset(
    dataset_dir: Path,
    timestamp_evidence: dict[str, Any] | None = None,
    specs: tuple[dict[str, Any], ...] = SPECS,
) -> dict[str, Any]:
    manifest, bars, last_stamp = _load_bars(Path(dataset_dir))
    basis = timestamp_basis_assessment(manifest, timestamp_evidence)
    if not bars:
        raise ValueError("no usable quote bars")
    first_date = datetime.fromtimestamp(bars[0].first_time / 1000, UTC).date()
    last_date = datetime.fromtimestamp(bars[-1].last_time / 1000, UTC).date()
    events: list[dict[str, Any]] = []
    day_value = first_date
    while day_value <= last_date:
        for spec in specs:
            event = _event(bars, day_value, spec)
            if event is not None:
                events.append(event)
        day_value += timedelta(days=1)
    hypotheses: dict[str, Any] = {}
    for spec in specs:
        selected = [event for event in events if event["hypothesis"] == spec["id"]]
        splits = _split(selected)
        stats_by_cost: dict[str, Any] = {}
        for cost in EXTRA_ROUND_TRIP_COSTS_BPS:
            stats_by_cost[str(cost)] = {name: _stats(rows, cost) for name, rows in splits.items()}
        verdict = _verdict(stats_by_cost["1.0"])
        if basis["status"] != "CONFIRMED":
            verdict = "INCONCLUSIVE"
        hypotheses[spec["id"]] = {
            "id": spec["id"],
            "operational_definition": "sign of the preceding fixed four-hour UTC return, held for the fixed four-hour UTC session",
            "direction_rule": "momentum" if spec["sign"] > 0 else "reversal",
            "sessions_utc": {"start_minute": spec["start_minute"], "end_minute": spec["end_minute"]},
            "splits": stats_by_cost,
            "verdict": verdict,
            "promoted": False,
            "strategy_executable": False,
        }
    return {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "manifest_dataset_sha256": manifest.get("dataset_sha256"),
            "rows": manifest.get("row_count"),
            "bars_15m": len(bars),
            "first_raw_time_msc": bars[0].first_time,
            "last_raw_time_msc": last_stamp,
            "discovery_cutoff_time_msc": discovery_cutoff(bars[0].first_time, last_stamp),
        },
        "timestamp_basis": basis,
        "research_design": {
            "hypotheses": [spec["id"] for spec in specs],
            "split": "chronological 60/20/20 by UTC calendar date, shared across hypotheses",
            "entry": "first valid quote at or after fixed session start",
            "exit": "first valid quote at or after fixed session end",
            "quote_cost": "actual bid/ask side selection per event",
            "additional_round_trip_cost_stress_bps": list(EXTRA_ROUND_TRIP_COSTS_BPS),
            "parameter_search": False,
            "raw_rows_repaired": False,
        },
        "events": {"total": len(events), "by_hypothesis": {key: sum(event["hypothesis"] == key for event in events) for key in hypotheses}},
        "hypotheses": hypotheses,
        "decision": "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "safety": {"confirm_live": False, "orders_submitted": 0, "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
    }


def render_session_report(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD fixed UTC session assay",
        "",
        f"Decision: {report.get('decision')}",
        "",
        "No strategy was promoted. Quote-only results are not execution validation.",
        "",
        f"Timestamp basis: {(report.get('timestamp_basis') or {}).get('status')}",
        f"Events: {(report.get('events') or {}).get('total')}",
        "",
        "| Hypothesis | Discovery mean @1bp | Validation mean @1bp | Holdout mean @1bp | Holdout t | Verdict |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for hypothesis, result in (report.get("hypotheses") or {}).items():
        splits = result.get("splits", {}).get("1.0", {})
        lines.append(
            f"| {hypothesis} | {splits.get('discovery', {}).get('mean_net_bps')} | "
            f"{splits.get('validation', {}).get('mean_net_bps')} | {splits.get('holdout', {}).get('mean_net_bps')} | "
            f"{splits.get('holdout', {}).get('t_stat')} | {result.get('verdict')} |"
        )
    lines.extend(["", "Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`."])
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
