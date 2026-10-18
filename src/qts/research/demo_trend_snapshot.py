"""Read-only snapshot of seeded completed bars for the DEMO EMA diagnostic.

The registered provider's source file is hash-pinned by its frozen policy.
This sidecar uses its history validator and EMA primitive without changing the
provider, its signal ledger, or its order-generation behavior. Historical
crossovers found in seeded history are facts for display only: they are never
emitted as actionable signals.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from qts.research.demo_trend_tsmom import TrendTimeSeriesMomentum


def completed_bar_snapshot(
    params: dict[str, Any],
    bars: Iterable[tuple[datetime, Decimal | str]],
    *,
    source: str,
) -> dict[str, Any]:
    """Validate and summarize a completed-bar window without generating signals."""
    provider = TrendTimeSeriesMomentum(params=params)
    supplied = list(bars)
    seeded = provider.seed_completed_bars(supplied, source=source)
    required = int(provider.warmup_plan()["bars"])
    timeframe = int(provider.warmup_plan()["timeframe_minutes"])
    snapshot: dict[str, Any] = {
        "status": "WARMING_UP",
        "timeframe_minutes": timeframe,
        "completed_bars": int(seeded.get("bars") or 0),
        "required_bars": required,
        "last_completed_bar": seeded.get("last_bar"),
        "trend_state": "UNAVAILABLE",
        "latest_completed_cross": "UNAVAILABLE",
        "fast_ema": None,
        "slow_ema": None,
        "actionable_signal": False,
        "note": (
            "Read-only completed-bar snapshot. A crossover in seeded history is not emitted; "
            "the live provider only evaluates a future completed-bar boundary."
        ),
    }
    if not seeded.get("accepted"):
        snapshot["status"] = "UNAVAILABLE"
        snapshot["reason"] = str(seeded.get("reason") or "completed-bar history failed validation")
        return snapshot
    if int(seeded.get("bars") or 0) < required:
        snapshot["reason"] = f"waiting for {required - int(seeded.get('bars') or 0)} more completed M{timeframe} bars"
        return snapshot

    window = supplied[-required:]
    closes = [Decimal(str(close)) for _boundary, close in window]
    fast_n = int(params["fast_ema"])
    slow_n = int(params["slow_ema"])
    # Reuse the frozen provider's exact EMA implementation; no second indicator
    # formula or separate execution path is introduced by this presentation aid.
    fast = provider._ema(closes[-fast_n:], fast_n)
    slow = provider._ema(closes[-slow_n:], slow_n)
    previous = closes[:-1]
    previous_fast = provider._ema(previous[-fast_n:], fast_n)
    previous_slow = provider._ema(previous[-slow_n:], slow_n)
    if previous_fast <= previous_slow and fast > slow:
        cross = "BUY"
    elif previous_fast >= previous_slow and fast < slow:
        cross = "SELL"
    else:
        cross = "NONE"

    snapshot.update(
        {
            "status": "AVAILABLE",
            "trend_state": "BULLISH" if fast > slow else "BEARISH" if fast < slow else "NEUTRAL",
            "latest_completed_cross": cross,
            "fast_ema": str(fast),
            "slow_ema": str(slow),
        }
    )
    return snapshot
