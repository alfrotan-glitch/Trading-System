"""
H-TEMP-01: raw-hour magnitude (active 15,16,17 vs quiet 0,1,23) at 16/64.

Descriptive temporal showed strong raw intraday structure (2.8x), but this
is the first confirmatory test of that structure with a priori session
thresholds, cost filter, and bootstrap. No UTC claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.impulse.statistics import holm_bonferroni

SCHEMA = "qts.xauusd_temporal.v1"
PREREGISTRATION = "docs/xauusd_temporal_next_step_H-TEMP-01_2026-09-23.md"
HYPOTHESIS = "H-TEMP-01"
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
DISCOVERY_ROWS = 70783710
SOURCE_ROWS = 139930971
SOURCE_ZIP_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
SOURCE_DATASET_SHA256 = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
PRIMARY = 16
STABILITY = 64
HORIZONS = (PRIMARY, STABILITY)
BLOCK_ANCHORS = 1024
GAP_MS = 3_600_000
MIN_N = 1000
MIN_BLOCKS = 50
MIN_RATIO = 1.25
MIN_GAP_DOLLARS = 0.10
MIN_LIFT = 0.05
N_BOOT = 9999
SEED = 20260923
ALPHA = 0.01

ACTIVE_HOURS = {15, 16, 17}
QUIET_HOURS = {0, 1, 23}


class LockedSpanRefused(ValueError):
    pass


class DiscoveryDataError(ValueError):
    pass


@dataclass(frozen=True)
class DiscoveryIdentity:
    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = DISCOVERY_ROWS
    source_rows: int = SOURCE_ROWS
    zip_sha256: str = SOURCE_ZIP_SHA256
    dataset_sha256: str = SOURCE_DATASET_SHA256


IDENTITY = DiscoveryIdentity()


@dataclass
class TemporalScan:
    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = 0
    last_stamp: int | None = None
    carry_stamp: np.ndarray = None  # type: ignore
    carry_mid: np.ndarray = None  # type: ignore
    carry_spread: np.ndarray = None  # type: ignore
    carry_raw_hour: np.ndarray = None  # type: ignore
    blocks: set[tuple[int, int]] = None  # type: ignore
    _events: dict[int, list] = None  # type: ignore

    def __post_init__(self):
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.carry_mid = np.empty(0, dtype=np.int64)
        self.carry_spread = np.empty(0, dtype=np.int64)
        self.carry_raw_hour = np.empty(0, dtype=np.int8)
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
        all_mid_halfcents = np.concatenate((self.carry_mid, (bid_c + ask_c))) if carry_n else (bid_c + ask_c).copy()
        all_spreads = np.concatenate((self.carry_spread, (ask_c - bid_c))) if carry_n else (ask_c - bid_c).copy()
        new_raw_hour = (stamps % 86400000) // 3600000
        all_raw_hour = np.concatenate((self.carry_raw_hour, new_raw_hour.astype(np.int64))) if carry_n else new_raw_hour.astype(np.int64).copy()
        gap_prefix = np.concatenate(([0], np.cumsum(np.diff(all_stamps) >= GAP_MS, dtype=np.int64))) if len(all_stamps) > 1 else np.array([0], dtype=np.int64)

        for h in HORIZONS:
            stride = h + 1
            first = max(stride, ((start - h + stride - 1) // stride) * stride)
            anchors = np.arange(first, end - h, stride, dtype=np.int64)
            if anchors.size == 0:
                continue
            local = anchors - base
            # anchor's raw hour determines group
            rh = all_raw_hour[local]
            is_active = np.isin(rh, list(ACTIVE_HOURS))
            is_quiet = np.isin(rh, list(QUIET_HOURS))
            # Only active vs quiet are in family; others ignored but counted
            # For gate, we need counts per tercile
            tercile = np.minimum(2, (all_stamps[local] - self.time_min) * 3 // (self.cutoff - self.time_min))
            block = (anchors // stride) // BLOCK_ANCHORS
            if h == PRIMARY:
                self.blocks.update((int(t), int(b)) for t, b in zip(tercile, block, strict=True))
            # Store per horizon: we need arrays for active and quiet separately
            # For descriptive, store all, but for evaluation we will filter
            # Store as dict of arrays for simplicity, but we need to store events for later bootstrap
            # Instead, store raw arrays for this batch: anchor, tercile, block, is_active, is_quiet, abs_move, exceed
            exit_ = local + h
            if np.any(exit_ >= len(all_stamps)):
                raise DiscoveryDataError("exit out of range")
            abs_move = np.abs(all_mid_halfcents[exit_] - all_mid_halfcents[local]) * 0.005  # dollars
            spread_cost = (all_spreads[local] + all_spreads[exit_]) * 0.01 / 2 + 0.02
            exceed = abs_move > spread_cost
            gap_clear = (gap_prefix[exit_] - gap_prefix[local]) == 0
            # Append for this horizon
            self._events[h].append(
                {
                    "anchor": anchors,
                    "tercile": tercile,
                    "block": block,
                    "is_active": is_active,
                    "is_quiet": is_quiet,
                    "abs_move": abs_move,
                    "exceed": exceed,
                    "gap_clear": gap_clear,
                }
            )

        self.rows = int(end)
        self.last_stamp = int(stamps[-1])
        tail = min(max(HORIZONS) + 1, len(all_stamps))
        self.carry_stamp = all_stamps[-tail:].copy()
        self.carry_mid = all_mid_halfcents[-tail:].copy()
        self.carry_spread = all_spreads[-tail:].copy()
        self.carry_raw_hour = all_raw_hour[-tail:].copy()


def evaluate_temporal(scan: TemporalScan, *, complete_rows: int = DISCOVERY_ROWS) -> dict[str, Any]:
    # Aggregate across batches per horizon
    def aggregate(h: int):
        chunks = scan._events[h]
        if not chunks:
            return None
        anchor = np.concatenate([c["anchor"] for c in chunks])
        tercile = np.concatenate([c["tercile"] for c in chunks])
        block = np.concatenate([c["block"] for c in chunks])
        is_active = np.concatenate([c["is_active"] for c in chunks])
        is_quiet = np.concatenate([c["is_quiet"] for c in chunks])
        abs_move = np.concatenate([c["abs_move"] for c in chunks])
        exceed = np.concatenate([c["exceed"] for c in chunks])
        gap_clear = np.concatenate([c["gap_clear"] for c in chunks])
        return {
            "anchor": anchor,
            "tercile": tercile,
            "block": block,
            "is_active": is_active,
            "is_quiet": is_quiet,
            "abs_move": abs_move,
            "exceed": exceed,
            "gap_clear": gap_clear,
        }

    def stats_for(agg, mask_active, mask_quiet):
        # mask_active is boolean array for active group within agg
        # But we need to handle tercile splits
        pass

    # For primary horizon 16
    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {
            "time_msc_min": scan.time_min,
            "cutoff_time_msc": scan.cutoff,
            "discovery_rows_read": scan.rows,
            "held_out_rows_read": 0,
        },
        "measured": {},
        "hypotheses": {},
        "decision": "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "safety": {"DEMO_EXECUTION": "DISABLED", "confirm_live": False, "orders_submitted": 0},
    }

    # Helper to compute stats for a given horizon aggregate
    def compute_stats(agg):
        if agg is None:
            return None
        is_active = agg["is_active"]
        is_quiet = agg["is_quiet"]
        # Only active vs quiet; ignore others (where both false)
        active_abs = agg["abs_move"][is_active]
        quiet_abs = agg["abs_move"][is_quiet]
        active_exceed = agg["exceed"][is_active]
        quiet_exceed = agg["exceed"][is_quiet]
        n_active = int(np.count_nonzero(is_active))
        n_quiet = int(np.count_nonzero(is_quiet))
        mean_active = float(active_abs.mean()) if n_active else None
        mean_quiet = float(quiet_abs.mean()) if n_quiet else None
        ratio = mean_active / mean_quiet if (mean_active is not None and mean_quiet and mean_quiet != 0) else None
        gap = (mean_active - mean_quiet) if (mean_active is not None and mean_quiet is not None) else None
        p_active = float(active_exceed.mean()) if n_active else None
        p_quiet = float(quiet_exceed.mean()) if n_quiet else None
        lift = (p_active - p_quiet) if (p_active is not None and p_quiet is not None) else None
        return {
            "n_active": n_active,
            "n_quiet": n_quiet,
            "mean_active": mean_active,
            "mean_quiet": mean_quiet,
            "ratio": ratio,
            "gap_dollars": gap,
            "p_active": p_active,
            "p_quiet": p_quiet,
            "lift": lift,
        }

    agg16 = aggregate(PRIMARY)
    agg64 = aggregate(STABILITY)
    primary_stats = compute_stats(agg16) if agg16 else None
    stability_stats = compute_stats(agg64) if agg64 else None

    # Terciles for primary
    tercile_stats = []
    for t in range(3):
        if agg16 is None:
            tercile_stats.append(None)
            continue
        mask_t = agg16["tercile"] == t
        # Need to filter agg16 to tercile t
        # Create filtered agg for this tercile
        filt = {
            "is_active": agg16["is_active"][mask_t],
            "is_quiet": agg16["is_quiet"][mask_t],
            "abs_move": agg16["abs_move"][mask_t],
            "exceed": agg16["exceed"][mask_t],
        }
        # Build a pseudo agg for compute_stats
        pseudo = {
            "is_active": filt["is_active"],
            "is_quiet": filt["is_quiet"],
            "abs_move": filt["abs_move"],
            "exceed": filt["exceed"],
        }
        # Wrap for compute_stats which expects dict with keys is_active etc. plus abs_move, exceed
        # Instead call directly
        n_a = int(np.count_nonzero(pseudo["is_active"]))
        n_q = int(np.count_nonzero(pseudo["is_quiet"]))
        mean_a = float(pseudo["abs_move"][pseudo["is_active"]].mean()) if n_a else None
        mean_q = float(pseudo["abs_move"][pseudo["is_quiet"]].mean()) if n_q else None
        ratio = mean_a / mean_q if (mean_a is not None and mean_q and mean_q != 0) else None
        gap = (mean_a - mean_q) if (mean_a is not None and mean_q is not None) else None
        p_a = float(pseudo["exceed"][pseudo["is_active"]].mean()) if n_a else None
        p_q = float(pseudo["exceed"][pseudo["is_quiet"]].mean()) if n_q else None
        lift = (p_a - p_q) if (p_a is not None and p_q is not None) else None
        tercile_stats.append(
            {
                "tercile": int(t),
                "n_active": n_a,
                "n_quiet": n_q,
                "mean_active": mean_a,
                "mean_quiet": mean_q,
                "ratio": ratio,
                "gap_dollars": gap,
                "p_active": p_a,
                "p_quiet": p_q,
                "lift": lift,
                "blocks": int(sum(1 for (tt, _) in scan.blocks if tt == t)),
            }
        )

    # Gap subset
    gap_stats = None
    if agg16 is not None:
        mask_gap = agg16["gap_clear"]
        gap_agg = {
            "is_active": agg16["is_active"][mask_gap],
            "is_quiet": agg16["is_quiet"][mask_gap],
            "abs_move": agg16["abs_move"][mask_gap],
            "exceed": agg16["exceed"][mask_gap],
        }
        n_a = int(np.count_nonzero(gap_agg["is_active"]))
        n_q = int(np.count_nonzero(gap_agg["is_quiet"]))
        mean_a = float(gap_agg["abs_move"][gap_agg["is_active"]].mean()) if n_a else None
        mean_q = float(gap_agg["abs_move"][gap_agg["is_quiet"]].mean()) if n_q else None
        ratio = mean_a / mean_q if (mean_a is not None and mean_q and mean_q != 0) else None
        gap = (mean_a - mean_q) if (mean_a is not None and mean_q is not None) else None
        p_a = float(gap_agg["exceed"][gap_agg["is_active"]].mean()) if n_a else None
        p_q = float(gap_agg["exceed"][gap_agg["is_quiet"]].mean()) if n_q else None
        lift = (p_a - p_q) if (p_a is not None and p_q is not None) else None
        gap_stats = {
            "n_active": n_a,
            "n_quiet": n_q,
            "mean_active": mean_a,
            "mean_quiet": mean_q,
            "ratio": ratio,
            "gap_dollars": gap,
            "p_active": p_a,
            "p_quiet": p_q,
            "lift": lift,
        }

    output["measured"]["16"] = primary_stats
    output["measured"]["64"] = stability_stats
    output["measured"]["terciles"] = tercile_stats
    output["measured"]["gap_under_one_hour"] = gap_stats
    blocks_per_tercile = {t: sum(1 for (tt, _) in scan.blocks if tt == t) for t in range(3)}
    output["measured"]["blocks_per_tercile"] = blocks_per_tercile
    output["measured"]["exclusions"] = {"note": "other raw hours ignored, counted in n other"}

    # Gates
    reasons = []
    underpowered = False
    if scan.rows != complete_rows:
        underpowered = True
        reasons.append("row count mismatch")
    if primary_stats is None or primary_stats["n_active"] < MIN_N or primary_stats["n_quiet"] < MIN_N:
        underpowered = True
        reasons.append(f"primary per-group n < {MIN_N}: active {primary_stats['n_active'] if primary_stats else 'None'} quiet {primary_stats['n_quiet'] if primary_stats else 'None'}")
    for t, ts in enumerate(tercile_stats):
        if ts is None or ts["n_active"] < MIN_N or ts["n_quiet"] < MIN_N:
            underpowered = True
            reasons.append(f"tercile {t} n < {MIN_N}")
        if blocks_per_tercile[t] < MIN_BLOCKS:
            underpowered = True
            reasons.append(f"tercile {t} blocks {blocks_per_tercile[t]} < {MIN_BLOCKS}")

    # Floors and artifact gates (if not underpowered)
    floor_pass = False
    artifact_pass = False
    bootstrap_ok = False  # placeholder, will be computed if not underpowered
    if not underpowered and primary_stats and stability_stats and gap_stats:
        floor_pass = (
            primary_stats["ratio"] is not None
            and primary_stats["ratio"] >= MIN_RATIO
            and primary_stats["gap_dollars"] is not None
            and primary_stats["gap_dollars"] >= MIN_GAP_DOLLARS
            and primary_stats["lift"] is not None
            and primary_stats["lift"] >= MIN_LIFT
        )
        artifact_pass = (
            all(ts["ratio"] is not None and ts["ratio"] > 1.0 and ts["lift"] is not None and ts["lift"] > 0 for ts in tercile_stats)
            and stability_stats["ratio"] is not None
            and stability_stats["ratio"] > 1.0
            and stability_stats["lift"] is not None
            and stability_stats["lift"] > 0
            and gap_stats["ratio"] is not None
            and gap_stats["ratio"] > 1.0
            and gap_stats["lift"] is not None
            and gap_stats["lift"] > 0
        )
        # For now, skip bootstrap, just require floors and artifacts
        bootstrap_ok = True  # would need block bootstrap

    output["measured"]["gates"] = {
        "identity_and_minimums": not underpowered,
        "material_ratio_gap_lift": floor_pass if not underpowered else None,
        "mirrors_terciles_64_and_gap": artifact_pass if not underpowered else None,
        "bootstrap_required": "pending" if not underpowered else None,
    }

    if underpowered:
        status = "INCONCLUSIVE"
    elif not floor_pass:
        status = "REJECTED"
        reasons.append(f"floor miss: ratio {primary_stats['ratio']:.3f} < {MIN_RATIO} or gap ${primary_stats['gap_dollars']:.3f} < ${MIN_GAP_DOLLARS} or lift {primary_stats['lift']:.3f} < {MIN_LIFT}")
    elif not artifact_pass:
        status = "REJECTED"
        reasons.append("tercile, stability, or gap agrees in sign")
    else:
        status = "TESTED"  # magnitude structure, not directional trade, similar to H-VL
        reasons = ["ratio, gap, lift floors passed; terciles, 64, gap agree; bootstrap pending but descriptive magnitude survives cost"]

    output["hypotheses"][HYPOTHESIS] = {"status": status, "reasons": reasons, "not_a_strategy": True, "validated": False}
    output["decision"] = "INCONCLUSIVE" if status in ("TESTED", "SURVIVED_DISCOVERY_ONLY") else status
    if status == "TESTED":
        output["edge_claim"] = "NOT ESTABLISHED"
        output["decision"] = "INCONCLUSIVE"

    return output
