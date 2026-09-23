"""
Temporal descriptive discovery on verifiable tick view.

Measures raw time_msc intraday distribution, gap and spread by raw hour,
without claiming UTC. This is a data-fact, not a hypothesis test, to inform
a future preregistered temporal hypothesis once clock basis is confirmed.

Blocked clock means hour labels are provisional raw-millisecond-of-day, not UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class TemporalFacts:
    time_msc_min: int
    time_msc_max: int
    discovery_rows: int
    gap_histogram: list[int]
    gap_edges_ms: list[int]
    spread_by_raw_hour: list[dict[str, Any]]
    ticks_by_raw_hour: list[int]
    mean_abs_16_by_raw_hour: list[float]


def discover_temporal(time_msc: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> dict[str, Any]:
    """
    Descriptive only. time_msc is raw int64, bid/ask are float.
    Computes raw hour-of-day as (time_msc % 86400000)//3600000, without UTC claim.
    """
    time_msc = np.asarray(time_msc, dtype=np.int64)
    bid = np.asarray(bid, dtype=np.float64)
    ask = np.asarray(ask, dtype=np.float64)
    n = len(time_msc)
    if n == 0:
        return {"error": "empty"}

    # Gaps
    gaps = np.diff(time_msc).astype(np.int64)
    # gap histogram edges as in microstructure
    edges = [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, 300000, 3600000, 86400000]
    hist, _ = np.histogram(gaps, bins=edges)

    # Raw hour
    raw_ms_of_day = time_msc % 86400000
    raw_hour = (raw_ms_of_day // 3600000).astype(np.int64)
    ticks_by_hour = [int(np.count_nonzero(raw_hour == h)) for h in range(24)]

    # Spread by raw hour
    spread = ask - bid
    spread_by_hour = []
    for h in range(24):
        mask = raw_hour == h
        if np.any(mask):
            spread_by_hour.append(
                {"raw_hour": int(h), "n": int(np.count_nonzero(mask)), "mean_spread": float(spread[mask].mean()), "median_spread": float(np.median(spread[mask]))}
            )
        else:
            spread_by_hour.append({"raw_hour": int(h), "n": 0, "mean_spread": None, "median_spread": None})

    # Mean absolute 16-quote mid change by raw hour (descriptive, overlapping, not inferential)
    mids = (bid + ask) / 2
    abs_16 = np.abs(mids[16:] - mids[:-16]) if n > 16 else np.array([])
    # Align raw_hour for the later point (i+16)
    raw_hour_16 = raw_hour[16:] if n > 16 else np.array([])
    mean_abs_16_by_hour = []
    for h in range(24):
        mask = raw_hour_16 == h
        if np.any(mask):
            mean_abs_16_by_hour.append(float(abs_16[mask].mean()))
        else:
            mean_abs_16_by_hour.append(0.0)

    return {
        "schema": "qts.xauusd_temporal_discovery.v1",
        "time_msc_min": int(time_msc.min()),
        "time_msc_max": int(time_msc.max()),
        "discovery_rows": int(n),
        "gap_histogram": hist.tolist(),
        "gap_edges_ms": edges,
        "ticks_by_raw_hour": ticks_by_hour,
        "spread_by_raw_hour": spread_by_hour,
        "mean_abs_16_by_raw_hour": mean_abs_16_by_hour,
        "note": "raw_hour is time_msc % 86400000 // 3600000, no UTC claim, descriptive only",
    }
