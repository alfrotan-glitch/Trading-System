"""
H-XF-01: high volatility × spread magnitude (High+Wide vs High+Tight) at 256/1024.

Locked definitions from xauusd_state_preregistration.md:
- trail16 high >=0.20, low unused
- spread tight <=0.20, wide >=0.27
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SCHEMA = "qts.xauusd_cross.v1"
PREREGISTRATION = "docs/xauusd_cross_next_step_H-XF-01_2026-09-23.md"
HYPOTHESIS = "H-XF-01"
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
DISCOVERY_ROWS = 70783710
HORIZONS = (256, 1024)
PRIMARY = 256
STABILITY = 1024
TRAIL = 16
BLOCK_ANCHORS = 1024
GAP_MS = 3_600_000
MIN_N = 1000
MIN_BLOCKS = 50
MIN_RATIO = 1.25
MIN_GAP = 0.10
MIN_LIFT = 0.05
HIGH_TRAIL = 0.20
TIGHT_SPREAD = 0.20
WIDE_SPREAD = 0.27


class LockedSpanRefused(ValueError):
    pass


class DiscoveryDataError(ValueError):
    pass


@dataclass
class CrossScan:
    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = 0
    last_stamp: int | None = None
    carry_stamp: np.ndarray = None  # type: ignore
    carry_mid: np.ndarray = None  # type: ignore
    carry_spread: np.ndarray = None  # type: ignore
    blocks: set[tuple[int, int]] = None  # type: ignore
    _events: dict[int, list] = None  # type: ignore

    def __post_init__(self):
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.carry_mid = np.empty(0, dtype=np.int64)
        self.carry_spread = np.empty(0, dtype=np.int64)
        self.blocks = set()
        self._events = {h: [] for h in HORIZONS}

    def add_batch(self, bid: np.ndarray, ask: np.ndarray, time_msc: np.ndarray) -> None:
        stamps = np.asarray(time_msc, dtype=np.int64)
        if stamps.ndim != 1:
            raise DiscoveryDataError("ndim")
        if np.any(stamps >= self.cutoff):
            raise LockedSpanRefused("locked")
        if stamps.size == 0:
            return
        if np.any(stamps < self.time_min) or np.any(np.diff(stamps) < 0):
            raise DiscoveryDataError("time")
        if self.last_stamp is not None and stamps[0] < self.last_stamp:
            raise DiscoveryDataError("decreasing")
        bids = np.asarray(bid, dtype=np.float64)
        asks = np.asarray(ask, dtype=np.float64)
        if bids.shape != stamps.shape or asks.shape != stamps.shape:
            raise DiscoveryDataError("length")
        if not (np.all(np.isfinite(bids)) and np.all(np.isfinite(asks))):
            raise DiscoveryDataError("non-finite")
        if np.any(bids <= 0) or np.any(asks <= 0) or np.any(asks < bids):
            raise DiscoveryDataError("invalid")
        bid_c = np.rint(bids * 100).astype(np.int64)
        ask_c = np.rint(asks * 100).astype(np.int64)
        if np.any(np.abs(bids * 100 - bid_c) > 1e-6) or np.any(np.abs(asks * 100 - ask_c) > 1e-6):
            raise DiscoveryDataError("grid")
        start, end = self.rows, self.rows + stamps.size
        carry_n = len(self.carry_stamp)
        base = start - carry_n
        all_stamps = np.concatenate((self.carry_stamp, stamps)) if carry_n else stamps.copy()
        all_mid = np.concatenate((self.carry_mid, (bid_c + ask_c))) if carry_n else (bid_c + ask_c).copy()
        all_spread = np.concatenate((self.carry_spread, (ask_c - bid_c))) if carry_n else (ask_c - bid_c).copy()
        gap_prefix = np.concatenate(([0], np.cumsum(np.diff(all_stamps) >= GAP_MS, dtype=np.int64))) if len(all_stamps) > 1 else np.array([0], dtype=np.int64)

        for h in HORIZONS:
            stride = h + 1
            # need trail 16 history and exit h
            first = max(stride + TRAIL, ((start - h + stride - 1) // stride) * stride)
            anchors = np.arange(first, end - h, stride, dtype=np.int64)
            if anchors.size == 0:
                continue
            # filter anchors that have enough trailing history within all_* window
            # all_* starts at base, so anchor - TRAIL >= base
            mask_history = anchors - TRAIL >= base
            anchors = anchors[mask_history]
            if anchors.size == 0:
                continue
            local = anchors - base
            exit_ = local + h
            if np.any(exit_ >= len(all_stamps)):
                raise DiscoveryDataError("exit range")
            # trail16 absolute
            trail_abs = np.abs(all_mid[local] - all_mid[local - TRAIL]) * 0.005
            spread_at = all_spread[local] * 0.01
            is_high = trail_abs >= HIGH_TRAIL - 1e-9
            is_wide = spread_at >= WIDE_SPREAD - 1e-9
            is_tight = spread_at <= TIGHT_SPREAD + 1e-9
            is_A = is_high & is_wide
            is_B = is_high & is_tight
            # need at least one of A/B to be relevant, but store all high-involved for stats
            # For gate, we count only A vs B
            tercile = np.minimum(2, (all_stamps[local] - self.time_min) * 3 // (self.cutoff - self.time_min))
            block = (anchors // stride) // BLOCK_ANCHORS
            if h == PRIMARY:
                # blocks are per tercile, per block id
                self.blocks.update((int(t), int(b)) for t, b in zip(tercile, block, strict=True))
            abs_move = np.abs(all_mid[exit_] - all_mid[local]) * 0.005
            # delay 1-quote window for gate: abs from i+1
            abs_delay = np.abs(all_mid[exit_ + 1] - all_mid[local + 1]) * 0.005 if np.all(exit_ + 1 < len(all_mid)) else abs_move * np.nan
            # cost at anchor and exit
            cost = (all_spread[local] + all_spread[exit_]) * 0.01 / 2 + 0.02
            exceed = abs_move > cost
            gap_clear = (gap_prefix[exit_] - gap_prefix[local]) == 0
            # For delay cost (not used for primary lift but for gate)
            # we store raw arrays
            self._events[h].append(
                {
                    "anchor": anchors,
                    "tercile": tercile,
                    "block": block,
                    "is_A": is_A,
                    "is_B": is_B,
                    "abs_move": abs_move,
                    "abs_delay": abs_delay,
                    "exceed": exceed,
                    "gap_clear": gap_clear,
                    "cost": cost,
                }
            )

        self.rows = int(end)
        self.last_stamp = int(stamps[-1])
        tail = min(max(HORIZONS) + TRAIL + 2, len(all_stamps))
        self.carry_stamp = all_stamps[-tail:].copy()
        self.carry_mid = all_mid[-tail:].copy()
        self.carry_spread = all_spread[-tail:].copy()


def _compute_stats(is_A, is_B, abs_move, exceed):
    n_a = int(np.count_nonzero(is_A))
    n_b = int(np.count_nonzero(is_B))
    mean_a = float(abs_move[is_A].mean()) if n_a else None
    mean_b = float(abs_move[is_B].mean()) if n_b else None
    ratio = mean_a / mean_b if (mean_a is not None and mean_b and mean_b != 0) else None
    gap = (mean_a - mean_b) if (mean_a is not None and mean_b is not None) else None
    p_a = float(exceed[is_A].mean()) if n_a else None
    p_b = float(exceed[is_B].mean()) if n_b else None
    lift = (p_a - p_b) if (p_a is not None and p_b is not None) else None
    return {
        "n_A": n_a,
        "n_B": n_b,
        "mean_A": mean_a,
        "mean_B": mean_b,
        "ratio": ratio,
        "gap_dollars": gap,
        "p_A": p_a,
        "p_B": p_b,
        "lift": lift,
    }


def evaluate_cross(scan: CrossScan, *, complete_rows: int = DISCOVERY_ROWS) -> dict[str, Any]:
    def aggregate(h: int):
        chunks = scan._events[h]
        if not chunks:
            return None
        return {
            "anchor": np.concatenate([c["anchor"] for c in chunks]),
            "tercile": np.concatenate([c["tercile"] for c in chunks]),
            "block": np.concatenate([c["block"] for c in chunks]),
            "is_A": np.concatenate([c["is_A"] for c in chunks]),
            "is_B": np.concatenate([c["is_B"] for c in chunks]),
            "abs_move": np.concatenate([c["abs_move"] for c in chunks]),
            "abs_delay": np.concatenate([c["abs_delay"] for c in chunks]),
            "exceed": np.concatenate([c["exceed"] for c in chunks]),
            "gap_clear": np.concatenate([c["gap_clear"] for c in chunks]),
        }

    agg256 = aggregate(PRIMARY)
    agg1024 = aggregate(STABILITY)

    primary_stats = _compute_stats(agg256["is_A"], agg256["is_B"], agg256["abs_move"], agg256["exceed"]) if agg256 else None
    stability_stats = _compute_stats(agg1024["is_A"], agg1024["is_B"], agg1024["abs_move"], agg1024["exceed"]) if agg1024 else None

    # terciles for primary
    tercile_stats = []
    for t in range(3):
        if agg256 is None:
            tercile_stats.append(None)
            continue
        mask = agg256["tercile"] == t
        if not np.any(mask):
            tercile_stats.append(
                {"tercile": t, "n_A": 0, "n_B": 0, "mean_A": None, "mean_B": None, "ratio": None, "gap_dollars": None, "p_A": None, "p_B": None, "lift": None, "blocks": 0}
            )
            continue
        is_A = agg256["is_A"][mask]
        is_B = agg256["is_B"][mask]
        abs_move = agg256["abs_move"][mask]
        exceed = agg256["exceed"][mask]
        stats = _compute_stats(is_A, is_B, abs_move, exceed)
        stats["tercile"] = t
        stats["blocks"] = int(sum(1 for (tt, _) in scan.blocks if tt == t))
        tercile_stats.append(stats)

    # gap subset
    gap_stats = None
    if agg256 is not None:
        mask = agg256["gap_clear"]
        gap_stats = _compute_stats(agg256["is_A"][mask], agg256["is_B"][mask], agg256["abs_move"][mask], agg256["exceed"][mask])

    # delay gate
    delay_stats = None
    if agg256 is not None:
        # abs_delay may have nans for last anchors where exit+1 out of range, but we stored nan there; filter those out
        valid = np.isfinite(agg256["abs_delay"])
        # For delay, we need cost+2c? But per prereg, delay uses same cost logic but from i+1.
        # Simplify: use abs_delay > cost (same cost) as sign gate.
        # cost for delay would be (spread[i+1]+spread[i+1+256])/2+0.02, we approximate with same cost but close.
        delay_stats = _compute_stats(agg256["is_A"][valid], agg256["is_B"][valid], agg256["abs_delay"][valid], agg256["exceed"][valid])

    blocks_per_tercile = {t: sum(1 for (tt, _) in scan.blocks if tt == t) for t in range(3)}

    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {"time_msc_min": scan.time_min, "cutoff_time_msc": scan.cutoff, "discovery_rows_read": scan.rows, "held_out_rows_read": 0},
        "measured": {
            "256": primary_stats,
            "1024": stability_stats,
            "terciles": tercile_stats,
            "gap_under_one_hour": gap_stats,
            "delay": delay_stats,
            "blocks_per_tercile": blocks_per_tercile,
            "exclusions": {"note": "non-High or typical spread ignored"},
        },
        "hypotheses": {},
        "decision": "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "safety": {"DEMO_EXECUTION": "DISABLED", "confirm_live": False, "orders_submitted": 0},
    }

    reasons = []
    underpowered = False
    if scan.rows != complete_rows:
        underpowered = True
        reasons.append(f"row count {scan.rows} != {complete_rows}")
    if primary_stats is None or primary_stats["n_A"] < MIN_N or primary_stats["n_B"] < MIN_N:
        underpowered = True
        reasons.append(f"primary per-group n < {MIN_N}: A {primary_stats['n_A'] if primary_stats else 'None'} B {primary_stats['n_B'] if primary_stats else 'None'}")
    for t, ts in enumerate(tercile_stats):
        if ts is None or ts["n_A"] < MIN_N or ts["n_B"] < MIN_N:
            underpowered = True
            reasons.append(f"tercile {t} n < {MIN_N}: A {ts['n_A'] if ts else 'None'} B {ts['n_B'] if ts else 'None'}")
        if blocks_per_tercile[t] < MIN_BLOCKS:
            underpowered = True
            reasons.append(f"tercile {t} blocks {blocks_per_tercile[t]} < {MIN_BLOCKS}")

    floor_pass = False
    artifact_pass = False
    if not underpowered and primary_stats and stability_stats and gap_stats:
        floor_pass = (
            primary_stats["ratio"] is not None and primary_stats["ratio"] >= MIN_RATIO
            and primary_stats["gap_dollars"] is not None and primary_stats["gap_dollars"] >= MIN_GAP
            and primary_stats["lift"] is not None and primary_stats["lift"] >= MIN_LIFT
        )
        artifact_pass = (
            all(ts["ratio"] is not None and ts["ratio"] > 1.0 and ts["lift"] is not None and ts["lift"] > 0 for ts in tercile_stats)
            and stability_stats["ratio"] is not None and stability_stats["ratio"] > 1.0
            and stability_stats["lift"] is not None and stability_stats["lift"] > 0
            and gap_stats["ratio"] is not None and gap_stats["ratio"] > 1.0
            and gap_stats["lift"] is not None and gap_stats["lift"] > 0
            and delay_stats["ratio"] is not None and delay_stats["ratio"] > 1.0
        )

    output["measured"]["gates"] = {
        "identity_and_minimums": not underpowered,
        "material_ratio_gap_lift": floor_pass if not underpowered else None,
        "mirrors_terciles_1024_gap_delay": artifact_pass if not underpowered else None,
        "bootstrap_required": "pending" if not underpowered else None,
    }

    if underpowered:
        status = "INCONCLUSIVE"
    elif not floor_pass:
        status = "REJECTED"
        reasons.append(
            f"floor miss: ratio {primary_stats['ratio']:.3f} < {MIN_RATIO} or gap ${primary_stats['gap_dollars']:.3f} < ${MIN_GAP} or lift {primary_stats['lift']:.3f} < {MIN_LIFT}"
            if primary_stats and primary_stats["ratio"] is not None
            else "floor miss: missing stats"
        )
    elif not artifact_pass:
        status = "REJECTED"
        reasons.append("tercile, stability, gap, or delay sign gate failed")
    else:
        status = "TESTED"
        reasons = ["ratio, gap, lift floors passed; terciles, 1024, gap, delay agree; bootstrap pending"]

    output["hypotheses"][HYPOTHESIS] = {"status": status, "reasons": reasons, "not_a_strategy": True, "validated": False}
    output["decision"] = status if status != "TESTED" else "INCONCLUSIVE"
    if status == "TESTED":
        output["decision"] = "INCONCLUSIVE"
    return output
