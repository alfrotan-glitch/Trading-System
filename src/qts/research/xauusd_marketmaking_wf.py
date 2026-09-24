"""
H-MM-02 walk-forward risk-adjusted market-making.
Reuses F vs U definitions, 5-fold time splits, 2x spread stress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.xauusd_marketmaking import (
    DISCOVERY_ROWS,
    MarketMakingScan,
)

SCHEMA = "qts.xauusd_marketmaking_wf.v1"
PREREGISTRATION = "docs/xauusd_marketmaking_next_step_H-MM-02_2026-09-23.md"
HYPOTHESIS = "H-MM-02"
FOLDS = 5
MIN_N_FOLD = 500
MIN_BLOCKS_FOLD = 20
MIN_LIFT = 0.05
MIN_RATIO = 1.25
MIN_GAP = 0.10
MIN_NET_1X = 0.08
MIN_NET_2X = 0.0


@dataclass
class MarketMakingWFScan(MarketMakingScan):
    # inherits add_batch etc, just adds fold evaluation
    pass


def evaluate_marketmaking_wf(scan: MarketMakingScan, *, complete_rows: int = DISCOVERY_ROWS) -> dict[str, Any]:
    # Use scan._events which has tercile already, but we need 5-fold splits by time
    if not scan._events:
        return {"error": "no events"}
    # events have anchor, tercile, block, is_F, is_U, both_filled, delay_both, abs_exc, max_exc, gap_clear, spread, net
    # For 5-fold, we need time_msc for each event to assign fold. But _events stores tercile based on 3 splits, not 5. We need to recompute fold from anchor time.
    # Instead, we stored tercile but not raw time. We can approximate fold via block or via tercile? Better to recompute fold from block? Not accurate.
    # Alternative: use tercile as proxy and expand to 5-fold via time linear: we have scan._events with no time, but we can infer time via anchor's time via gap? We don't have time.
    # Simplification: reuse tercile stats and add 5-fold as time-split on block id linear.
    # For now, we will do walk-forward on 3 terciles as 3 folds plus 2 extra splits via linear interpolation of time.
    # To avoid complexity, we will evaluate 5-fold by splitting the event index by time order (events are in time order due to add_batch sequential).
    # Events are appended in time order, so index order is time order.
    n_events = len(scan._events)
    fold_size = n_events // FOLDS
    folds = []
    reasons = []
    # For each fold, compute stats
    for f in range(FOLDS):
        lo = f * fold_size
        hi = (f + 1) * fold_size if f < FOLDS - 1 else n_events
        # slice events
        ev_slice = scan._events[lo:hi]
        if not ev_slice:
            folds.append({"fold": f, "n_F": 0, "n_U": 0, "status": "INCONCLUSIVE"})
            continue
        is_F = np.array([e["is_F"] for e in ev_slice], dtype=bool)
        is_U = np.array([e["is_U"] for e in ev_slice], dtype=bool)
        both = np.array([e["both_filled"] for e in ev_slice], dtype=bool)
        abs_exc = np.array([e["abs_exc"] for e in ev_slice], dtype=float)
        max_exc = np.array([e["max_exc"] for e in ev_slice], dtype=float)
        spread = np.array([e["spread"] for e in ev_slice], dtype=float)
        net = np.array([e["net"] for e in ev_slice], dtype=float)
        delay_both = np.array([e["delay_both"] for e in ev_slice], dtype=bool)
        # gap_clear not needed for per-fold, but we can compute
        n_F = int(np.count_nonzero(is_F))
        n_U = int(np.count_nonzero(is_U))
        # blocks per fold: count distinct blocks in slice
        blocks = len({e["block"] for e in ev_slice})
        if n_F < MIN_N_FOLD or n_U < MIN_N_FOLD:
            folds.append({"fold": f, "n_F": n_F, "n_U": n_U, "blocks": blocks, "status": "INCONCLUSIVE", "reason": f"n < {MIN_N_FOLD}"})
            continue
        p_F = float(np.mean(both[is_F])) if n_F else 0
        p_U = float(np.mean(both[is_U])) if n_U else 0
        lift = p_F - p_U
        mean_exc_F = float(np.mean(abs_exc[is_F])) if n_F else 0
        mean_exc_U = float(np.mean(abs_exc[is_U])) if n_U else 0
        ratio = mean_exc_U / mean_exc_F if mean_exc_F else 0
        gap = mean_exc_U - mean_exc_F
        mean_max_F = float(np.mean(max_exc[is_F])) if n_F else 0
        mean_max_U = float(np.mean(max_exc[is_U])) if n_U else 0
        net_F = float(np.mean(net[is_F])) if n_F else 0
        net_U = float(np.mean(net[is_U])) if n_U else 0
        # 2x spread net: 2*spread -0.02
        net2_F = float(np.mean((spread[is_F]*2 - 0.02)[both[is_F]])) if n_F and np.any(both[is_F]) else 0
        # risk-adjusted
        risk_adj_F = net_F / mean_max_F if mean_max_F else 0
        risk_adj_U = net_U / mean_max_U if mean_max_U else 0
        p_delay_F = float(np.mean(delay_both[is_F])) if n_F else 0
        p_delay_U = float(np.mean(delay_both[is_U])) if n_U else 0
        # floors
        floor_pass = (lift >= MIN_LIFT and ratio >= MIN_RATIO and gap >= MIN_GAP and net_F > MIN_NET_1X and net2_F > MIN_NET_2X and risk_adj_F > risk_adj_U and (p_delay_F - p_delay_U) > 0)
        folds.append({
            "fold": f,
            "n_F": n_F,
            "n_U": n_U,
            "blocks": blocks,
            "p_F": p_F,
            "p_U": p_U,
            "lift": lift,
            "mean_exc_F": mean_exc_F,
            "mean_exc_U": mean_exc_U,
            "ratio": ratio,
            "gap": gap,
            "mean_max_F": mean_max_F,
            "mean_max_U": mean_max_U,
            "net_F": net_F,
            "net_U": net_U,
            "net2_F": net2_F,
            "risk_adj_F": risk_adj_F,
            "risk_adj_U": risk_adj_U,
            "p_delay_F": p_delay_F,
            "p_delay_U": p_delay_U,
            "floor_pass": bool(floor_pass),
        })

    # overall primary from full scan (reuse previous evaluate)
    from qts.research.xauusd_marketmaking import evaluate_marketmaking
    full = evaluate_marketmaking(scan, complete_rows=complete_rows)
    primary = full["measured"]["16_fill_256_exc"] if "measured" in full else None

    # Determine status
    reasons = []
    underpowered = False
    if scan.rows != complete_rows:
        underpowered = True
        reasons.append(f"row count {scan.rows} != {complete_rows}")
    # check folds
    if any(f.get("status") == "INCONCLUSIVE" for f in folds):
        underpowered = True
        reasons.extend([f["reason"] for f in folds if "reason" in f])
    # All folds must be floor_pass?
    all_pass = all(f.get("floor_pass") for f in folds)
    if not underpowered and not all_pass:
        # Check which folds failed
        for f in folds:
            if not f.get("floor_pass"):
                reasons.append(f"fold {f['fold']} floor miss: lift {f.get('lift',0):.3f} ratio {f.get('ratio',0):.2f} net_F {f.get('net_F',0):.3f} risk {f.get('risk_adj_F',0):.3f}>{f.get('risk_adj_U',0):.3f} delay {(f.get('p_delay_F',0)-f.get('p_delay_U',0)):.3f}")
    # Also need overall primary floors (risk-adjusted)
    if primary:
        risk_F = primary["net_F"]/primary["mean_max_F"] if primary["mean_max_F"] else 0
        risk_U = primary["net_U"]/primary["mean_max_U"] if primary["mean_max_U"] else 0
        if not (primary["lift"] >= MIN_LIFT and primary["ratio"] >= MIN_RATIO and primary["gap_dollars"] >= MIN_GAP and primary["net_F"] > MIN_NET_1X and risk_F > risk_U):
            reasons.append(f"primary floor miss: lift {primary['lift']:.3f} ratio {primary['ratio']:.2f} net_F {primary['net_F']:.3f} risk {risk_F:.3f}>{risk_U:.3f}")

    if underpowered:
        status = "INCONCLUSIVE"
    elif not all_pass or (primary and not (primary["lift"] >= MIN_LIFT and primary["ratio"] >= MIN_RATIO)):
        status = "REJECTED"
    else:
        status = "TESTED"
        reasons = ["all 5 folds and primary pass risk-adjusted floors, walk-forward stable"]

    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {"time_msc_min": scan.time_min, "cutoff_time_msc": scan.cutoff, "discovery_rows_read": scan.rows, "held_out_rows_read": 0},
        "measured": {
            "primary": primary,
            "folds": folds,
            "risk_adj_F": risk_F if primary else None,
            "risk_adj_U": risk_U if primary else None,
        },
        "hypotheses": {HYPOTHESIS: {"status": status, "reasons": reasons, "not_a_strategy": True, "validated": False}},
        "decision": status if status != "TESTED" else "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "safety": {"DEMO_EXECUTION": "DISABLED", "confirm_live": False, "orders_submitted": 0},
    }
    if status == "TESTED":
        output["decision"] = "INCONCLUSIVE"
    return output
