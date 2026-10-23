"""Diagnose whether quote spread or mid-price direction explains a trade result.

Research-only. Mid-to-mid movement assumes impossible mid fills and must never be
reported as an executable strategy return or used for strategy promotion.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def attribute_quote_costs(
    entry_mid: np.ndarray,
    pnl_long: np.ndarray,
    pnl_short: np.ndarray,
    direction: np.ndarray,
) -> dict[str, Any]:
    """Decompose signed executable quote P&L into mid movement and quote cost.

    Long and short P&L must use the *same* entry/exit bid/ask snapshots:
    long = exit_bid - entry_ask; short = entry_bid - exit_ask.
    Thus -(long + short)/2 equals half the entry-plus-exit spreads.
    """
    mid = np.asarray(entry_mid, dtype=np.float64)
    long = np.asarray(pnl_long, dtype=np.float64)
    short = np.asarray(pnl_short, dtype=np.float64)
    side = np.asarray(direction)
    if mid.ndim != 1 or any(a.shape != mid.shape for a in (long, short, side)):
        raise ValueError("quote attribution inputs must be equal-length 1D arrays")
    if mid.size == 0:
        return {"n": 0, "mean_mid_move_bps": None, "mean_quote_cost_bps": None,
                "mean_executable_quote_net_bps": None, "mid_is_executable": False}
    if (not np.isfinite(mid).all() or not np.isfinite(long).all()
            or not np.isfinite(short).all() or (mid <= 0).any()
            or not np.isin(side, [-1, 1]).all()):
        raise ValueError("quote attribution inputs contain invalid prices or directions")
    quote_cost = -(long + short) / 2.0
    if (quote_cost < -1e-9).any():
        raise ValueError("quote attribution requires a nonnegative entry/exit spread")
    quote_cost = np.maximum(quote_cost, 0.0)
    executable_pnl = np.where(side > 0, long, short)
    mid_move = executable_pnl + quote_cost
    scale = 10_000.0 / mid
    return {
        "n": int(mid.size),
        "mean_mid_move_bps": float(np.mean(mid_move * scale)),
        "mean_quote_cost_bps": float(np.mean(quote_cost * scale)),
        "mean_executable_quote_net_bps": float(np.mean(executable_pnl * scale)),
        "mid_is_executable": False,
    }
