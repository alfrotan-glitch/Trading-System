"""Reproducible spread measurement: sample live quotes, report a distribution.

Per-deal cost evidence (:mod:`qts.execution.cost_capture`) learns what fills
actually cost, but only once orders exist. A spread profile answers the prior
question — what does this venue's XAUUSD quote look like across time — with a
read-only sampler: no order is ever required, submitted, or implied.

Conventions match the rest of the cost pipeline: unavailable quotes are
counted as unavailable, never as zero-spread samples, and every derived
number carries the sample count it came from. Percentiles are linear-
interpolated (numpy ``linear`` method) over the usable samples only.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np

SCHEMA = "qts.spread_profile.v1"


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def spread_bps_samples(samples: list[dict[str, Any]]) -> tuple[list[float], int]:
    """Extract per-sample spread in bps of mid from quote-snapshot dicts.

    Accepts the ``qts.broker_quote_snapshot.v1`` shape (bid/ask strings) and
    the ``qts.broker_symbol_cost_terms.v1`` shape (precomputed
    ``spread_bps_of_mid``). Returns (usable bps values, unavailable count).
    """
    usable: list[float] = []
    unavailable = 0
    for sample in samples:
        bps = _dec(sample.get("spread_bps_of_mid"))
        if bps is None:
            bid, ask = _dec(sample.get("bid")), _dec(sample.get("ask"))
            if bid is not None and ask is not None and ask >= bid and (ask + bid) > 0:
                bps = (ask - bid) / ((ask + bid) / 2) * Decimal("10000")
        if bps is None or bps < 0:
            unavailable += 1
        else:
            usable.append(float(bps))
    return usable, unavailable


def summarize_spread_profile(
    samples: list[dict[str, Any]],
    *,
    symbol: str,
    source: str,
) -> dict[str, Any]:
    """Distribution summary of sampled spreads. Empty input stays empty —
    no percentile is invented from zero observations."""
    bps, unavailable = spread_bps_samples(samples)
    profile: dict[str, Any] = {
        "schema": SCHEMA,
        "symbol": symbol,
        "source": source,
        "generated_at": datetime.now(UTC).isoformat(),
        "samples_total": len(samples),
        "samples_usable": len(bps),
        "samples_unavailable": unavailable,
        "spread_bps": None,
    }
    if bps:
        arr = np.asarray(bps, dtype=float)
        profile["spread_bps"] = {
            "min": round(float(arr.min()), 4),
            "p50": round(float(np.percentile(arr, 50)), 4),
            "p90": round(float(np.percentile(arr, 90)), 4),
            "p95": round(float(np.percentile(arr, 95)), 4),
            "p99": round(float(np.percentile(arr, 99)), 4),
            "max": round(float(arr.max()), 4),
            "mean": round(float(arr.mean()), 4),
        }
    return profile


def collect_spread_profile(
    snapshot_fn: Callable[[], dict[str, Any]],
    *,
    samples: int,
    interval_sec: float,
    symbol: str,
    source: str,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Take ``samples`` quote snapshots ``interval_sec`` apart and summarize.

    ``snapshot_fn``/``sleep`` are injected so the loop is unit-testable
    without a terminal or real time passing. Snapshot exceptions are
    recorded as unavailable samples — a flaky terminal degrades the sample
    count, it never fabricates a quote.
    """
    if samples < 1:
        raise ValueError("samples must be >= 1")
    taken: list[dict[str, Any]] = []
    for i in range(samples):
        try:
            taken.append(snapshot_fn())
        except Exception as exc:  # a failed read is an unavailable sample
            taken.append({"unavailable": True, "error": f"{type(exc).__name__}: {exc}"})
        if i + 1 < samples and interval_sec > 0:
            sleep(interval_sec)
    profile = summarize_spread_profile(taken, symbol=symbol, source=source)
    profile["interval_sec"] = interval_sec
    return profile
