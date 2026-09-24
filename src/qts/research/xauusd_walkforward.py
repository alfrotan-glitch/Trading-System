"""
H-ST-02 walk-forward: 5-fold temporal robustness of magnitude clustering
on verifiable Discovery view. Reuses H-ST-02 definitions (high/low terciles
of trailing 16 absolute, 256 horizon, cost+2c). Within each fold, quantiles
are recomputed from that fold's trailing-16 distribution to avoid leakage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SCHEMA = "qts.xauusd_walkforward.v1"
PREREGISTRATION = "docs/xauusd_magnitude_walkforward_H-ST-02WF_2026-09-23.md"
HYPOTHESIS = "H-ST-02WF"
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
DISCOVERY_ROWS = 70783710
HORIZON = 256
TRAIL = 16
FOLDS = 5
BLOCK_ANCHORS = 1024
MIN_N = 1000
MIN_BLOCKS = 50
MIN_RATIO = 1.25
MIN_GAP = 0.10
MIN_LIFT = 0.05

# For simplicity, high/low are defined per-fold as top/bottom tercile of trail abs
# No external quantile file; computed on the fly within each fold's anchors.


class LockedSpanRefused(ValueError):
    pass


@dataclass
class WalkForwardScan:
    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = 0
    last_stamp: int | None = None
    # Store per-fold aggregates after full pass? Instead, accumulate raw events and split by time at eval.
    _events: list = None  # list of dicts per batch

    def __post_init__(self):
        self._events = []

    def add_batch(self, bid: np.ndarray, ask: np.ndarray, time_msc: np.ndarray) -> None:
        stamps = np.asarray(time_msc, dtype=np.int64)
        if np.any(stamps >= self.cutoff):
            raise LockedSpanRefused("locked")
        if stamps.size == 0:
            return
        bids = np.asarray(bid, dtype=np.float64)
        asks = np.asarray(ask, dtype=np.float64)
        bid_c = np.rint(bids * 100).astype(np.int64)
        ask_c = np.rint(asks * 100).astype(np.int64)
        mids_half = bid_c + ask_c  # half-cents
        spreads = ask_c - bid_c  # cents
        start, end = self.rows, self.rows + stamps.size
        # Non-overlapping anchors for H=256: stride 257
        stride = HORIZON + 1
        first = max(stride + TRAIL, ((start - HORIZON + stride - 1) // stride) * stride)
        anchors = np.arange(first, end - HORIZON, stride, dtype=np.int64)
        if anchors.size:
            # Need to handle carry for trailing 16 and exit: we need mids for anchor-TRAIL..anchor and anchor+HORIZON
            # Simplification: require that anchor-TRAIL is within the concatenated batch window.
            # Since we process row-group by row-group, anchors near batch start may lack trailing data.
            # We skip anchors where anchor-TRAIL < start (i.e., insufficient trailing history).
            mask = anchors - TRAIL >= start
            anchors = anchors[mask]
        if anchors.size == 0:
            self.rows = int(end)
            if len(stamps):
                self.last_stamp = int(stamps[-1])
            return
        local = anchors - start
        # trailing 16 absolute
        trail_abs = np.abs(mids_half[local] - mids_half[local - TRAIL]) * 0.005  # dollars
        abs256 = np.abs(mids_half[local + HORIZON] - mids_half[local]) * 0.005
        cost = (spreads[local] + spreads[local + HORIZON]) * 0.01 / 2 + 0.02
        exceed = abs256 > cost
        time_at = stamps[local]
        # block within verifiable view (global)
        block = (anchors // stride) // BLOCK_ANCHORS
        self._events.append(
            {
                "anchor": anchors.copy(),
                "time_msc": time_at.copy(),
                "trail_abs": trail_abs.copy(),
                "abs256": abs256.copy(),
                "exceed": exceed.copy(),
                "block": block.copy(),
            }
        )
        self.rows = int(end)
        if len(stamps):
            self.last_stamp = int(stamps[-1])


def evaluate_walkforward(scan: WalkForwardScan, *, complete_rows: int = DISCOVERY_ROWS) -> dict[str, Any]:
    # Concatenate
    if not scan._events:
        return {"error": "no events"}
    time_msc = np.concatenate([e["time_msc"] for e in scan._events])
    trail_abs = np.concatenate([e["trail_abs"] for e in scan._events])
    abs256 = np.concatenate([e["abs256"] for e in scan._events])
    exceed = np.concatenate([e["exceed"] for e in scan._events])
    block = np.concatenate([e["block"] for e in scan._events])

    fold_width = (scan.cutoff - scan.time_min) // FOLDS
    folds = []
    reasons = []
    for f in range(FOLDS):
        lo = scan.time_min + f * fold_width
        hi = scan.time_min + (f + 1) * fold_width if f < FOLDS - 1 else scan.cutoff
        mask = (time_msc >= lo) & (time_msc < hi)
        n_fold = int(np.count_nonzero(mask))
        if n_fold == 0:
            folds.append({"fold": f, "n": 0, "status": "INCONCLUSIVE"})
            reasons.append(f"fold {f} empty")
            continue
        ta = trail_abs[mask]
        a256 = abs256[mask]
        exc = exceed[mask]
        # quantiles within fold
        q33, q66 = np.quantile(ta, [1/3, 2/3])
        high_mask = ta >= q66
        low_mask = ta <= q33
        n_high = int(np.count_nonzero(high_mask))
        n_low = int(np.count_nonzero(low_mask))
        # blocks per fold
        blocks_fold = len(set(block[mask]))
        # Use set of (fold, block) already unique per global block, but count per fold
        mean_high = float(a256[high_mask].mean()) if n_high else None
        mean_low = float(a256[low_mask].mean()) if n_low else None
        ratio = mean_high / mean_low if (mean_high is not None and mean_low and mean_low != 0) else None
        gap = (mean_high - mean_low) if (mean_high is not None and mean_low is not None) else None
        p_high = float(exc[high_mask].mean()) if n_high else None
        p_low = float(exc[low_mask].mean()) if n_low else None
        lift = (p_high - p_low) if (p_high is not None and p_low is not None) else None
        floor_pass = (
            n_high >= MIN_N
            and n_low >= MIN_N
            and blocks_fold >= MIN_BLOCKS
            and ratio is not None
            and ratio >= MIN_RATIO
            and gap is not None
            and gap >= MIN_GAP
            and lift is not None
            and lift >= MIN_LIFT
        )
        folds.append(
            {
                "fold": int(f),
                "time_lo": int(lo),
                "time_hi": int(hi),
                "n": n_fold,
                "n_high": n_high,
                "n_low": n_low,
                "blocks": int(blocks_fold),
                "q33": float(q33),
                "q66": float(q66),
                "mean_high": mean_high,
                "mean_low": mean_low,
                "ratio": ratio,
                "gap_dollars": gap,
                "p_high": p_high,
                "p_low": p_low,
                "lift": lift,
                "floor_pass": bool(floor_pass),
            }
        )
        if not floor_pass:
            pass  # will be counted as REJECTED below, not INCONCLUSIVE

    # Gates
    all_floors = all(f.get("floor_pass") for f in folds)
    all_sign = all(f.get("ratio") is not None and f["ratio"] > 1.0 and f.get("lift") is not None and f["lift"] > 0 for f in folds if f.get("ratio") is not None)
    ratios = [f["ratio"] for f in folds if f.get("ratio") is not None]
    cv = float(np.std(ratios) / np.mean(ratios)) if len(ratios) == FOLDS and np.mean(ratios) != 0 else None
    ratio_range = (max(ratios) / min(ratios)) if len(ratios) == FOLDS and min(ratios) != 0 else None
    stability = cv is not None and cv < 0.20 and ratio_range is not None and ratio_range < 1.5

    if scan.rows != complete_rows:
        status = "INCONCLUSIVE"
        reasons.append(f"row count {scan.rows} != {complete_rows}")
    elif not all_floors:
        status = "REJECTED"
        reasons.append("one or more folds below floor (ratio 1.25, gap 0.10, lift 0.05, n 1000, blocks 50)")
    elif not all_sign:
        status = "REJECTED"
        reasons.append("sign gate failed (ratio>1 and lift>0 in all 5 folds)")
    elif not stability:
        status = "REJECTED"
        reasons.append(f"stability failed: cv {cv:.3f} or range {ratio_range:.3f} exceeds 0.20/1.5")
    else:
        status = "TESTED"
        reasons = ["all 5 folds passed floors, sign, and stability; bootstrap pending but magnitude survives cost across time"]

    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {"time_msc_min": scan.time_min, "cutoff_time_msc": scan.cutoff, "discovery_rows_read": scan.rows, "held_out_rows_read": 0},
        "measured": {"folds": folds, "cv_ratio": cv, "ratio_range": ratio_range, "all_floors": all_floors, "all_sign": all_sign, "stability": stability},
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
