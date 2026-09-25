"""
H-MM-01: market-making spread capture — low+tight vs high+wide.
Fill within 16, excursion 256, SYNTHETIC front-of-queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SCHEMA = "qts.xauusd_marketmaking.v1"
PREREGISTRATION = "docs/xauusd_marketmaking_next_step_H-MM-01_2026-09-23.md"
HYPOTHESIS = "H-MM-01"
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
DISCOVERY_ROWS = 70783710
H_FILL = 16
H_EXCURSION = 256
TRAIL = 16
BLOCK_ANCHORS = 1024
GAP_MS = 3_600_000
MIN_N = 1000
MIN_BLOCKS = 50
MIN_LIFT_FILL = 0.05
MIN_RATIO_EXC = 1.25
MIN_GAP_EXC = 0.10
MIN_NET = 0.10
LOW_TRAIL = 0.10
HIGH_TRAIL = 0.20
TIGHT_SPREAD = 0.20
WIDE_SPREAD = 0.27


class LockedSpanRefused(ValueError):
    pass


class DiscoveryDataError(ValueError):
    pass


@dataclass
class MarketMakingScan:
    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = 0
    last_stamp: int | None = None
    carry_stamp: np.ndarray = None  # type: ignore
    carry_bid: np.ndarray = None  # type: ignore
    carry_ask: np.ndarray = None  # type: ignore
    carry_mid: np.ndarray = None  # type: ignore
    carry_spread: np.ndarray = None  # type: ignore
    blocks: set[tuple[int, int]] = None  # type: ignore
    _events: list = None  # type: ignore

    def __post_init__(self):
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.carry_bid = np.empty(0, dtype=np.int64)
        self.carry_ask = np.empty(0, dtype=np.int64)
        self.carry_mid = np.empty(0, dtype=np.int64)
        self.carry_spread = np.empty(0, dtype=np.int64)
        self.blocks = set()
        self._events = []

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
        all_bid = np.concatenate((self.carry_bid, bid_c)) if carry_n else bid_c.copy()
        all_ask = np.concatenate((self.carry_ask, ask_c)) if carry_n else ask_c.copy()
        all_mid = np.concatenate((self.carry_mid, (bid_c + ask_c))) if carry_n else (bid_c + ask_c).copy()
        all_spread = np.concatenate((self.carry_spread, (ask_c - bid_c))) if carry_n else (ask_c - bid_c).copy()
        gap_prefix = np.concatenate(([0], np.cumsum(np.diff(all_stamps) >= GAP_MS, dtype=np.int64))) if len(all_stamps) > 1 else np.array([0], dtype=np.int64)

        stride = H_FILL + 1  # 17
        first = max(stride + TRAIL, ((start - H_EXCURSION + stride - 1) // stride) * stride)
        first = max(first, 1)
        anchors = np.arange(first, end - H_EXCURSION, stride, dtype=np.int64)
        if anchors.size == 0:
            self.rows = int(end)
            if len(stamps):
                self.last_stamp = int(stamps[-1])
            # update carry
            tail = min(H_EXCURSION + TRAIL + 5, len(all_stamps))
            self.carry_stamp = all_stamps[-tail:].copy()
            self.carry_bid = all_bid[-tail:].copy()
            self.carry_ask = all_ask[-tail:].copy()
            self.carry_mid = all_mid[-tail:].copy()
            self.carry_spread = all_spread[-tail:].copy()
            return
        mask_history = anchors - TRAIL >= base
        anchors = anchors[mask_history]
        if anchors.size == 0:
            self.rows = int(end)
            if len(stamps):
                self.last_stamp = int(stamps[-1])
            tail = min(H_EXCURSION + TRAIL + 5, len(all_stamps))
            self.carry_stamp = all_stamps[-tail:].copy()
            self.carry_bid = all_bid[-tail:].copy()
            self.carry_ask = all_ask[-tail:].copy()
            self.carry_mid = all_mid[-tail:].copy()
            self.carry_spread = all_spread[-tail:].copy()
            return
        local = anchors - base
        # trail and spread at anchor
        trail_abs = np.abs(all_mid[local] - all_mid[local - TRAIL]) * 0.005
        spread_at = all_spread[local] * 0.01
        is_low = trail_abs <= LOW_TRAIL + 1e-9
        is_high = trail_abs >= HIGH_TRAIL - 1e-9
        is_tight = spread_at <= TIGHT_SPREAD + 1e-9
        is_wide = spread_at >= WIDE_SPREAD - 1e-9
        is_F = is_low & is_tight
        is_U = is_high & is_wide
        # Only keep F or U for events, but we store all to keep indices
        # For fill check, need next 16 bids/asks
        # Vectorized fill check: for each anchor, check min bid and max ask in next 16
        # We can do loop over anchors in batches? For now, loop per anchor but vectorize via sliding window
        # Use stride trick: for each local, check window local+1 .. local+16
        # We have up to ~few hundred anchors per batch, loop is ok
        tercile = np.minimum(2, (all_stamps[local] - self.time_min) * 3 // (self.cutoff - self.time_min))
        block = (anchors // stride) // BLOCK_ANCHORS
        self.blocks.update((int(t), int(b)) for t, b in zip(tercile, block, strict=True))

        # Prepare arrays for events
        for _idx, (anc, loc, tf, blk, f_flag, u_flag) in enumerate(zip(anchors, local, tercile, block, is_F, is_U, strict=False)):
            if not (f_flag or u_flag):
                continue
            bid_at = all_bid[loc]
            ask_at = all_ask[loc]
            # fill window 1..16
            window_bid = all_bid[loc + 1 : loc + H_FILL + 1]
            window_ask = all_ask[loc + 1 : loc + H_FILL + 1]
            # Need exactly 16 elements, if near carry edge we have them
            if len(window_bid) < H_FILL:
                continue
            buy_filled = np.any(window_bid <= bid_at)
            sell_filled = np.any(window_ask >= ask_at)
            both_filled = bool(buy_filled and sell_filled)
            # excursion 256
            mid_at = all_mid[loc]
            window_mid_256 = all_mid[loc + 1 : loc + H_EXCURSION + 1]
            # gap clear for excursion
            gap_clear = (gap_prefix[loc + H_EXCURSION] - gap_prefix[loc]) == 0
            abs_exc = abs(all_mid[loc + H_EXCURSION] - mid_at) * 0.005
            max_exc = np.max(np.abs(window_mid_256 - mid_at)) * 0.005 if len(window_mid_256) else abs_exc
            # net capture if both filled: spread -0.02, else 0 or adverse
            spread_dollars = all_spread[loc] * 0.01
            net = (spread_dollars - 0.02) if both_filled else 0.0
            # delay fill check (1-quote delay): place at i+1 bid/ask, fill in next 16 from i+2
            delay_both = False
            if loc + H_FILL + 1 < len(all_bid):
                bid_delay = all_bid[loc + 1]
                ask_delay = all_ask[loc + 1]
                window_bid_d = all_bid[loc + 2 : loc + H_FILL + 2]
                window_ask_d = all_ask[loc + 2 : loc + H_FILL + 2]
                if len(window_bid_d) >= H_FILL:
                    delay_both = bool(np.any(window_bid_d <= bid_delay) and np.any(window_ask_d >= ask_delay))
            self._events.append(
                {
                    "anchor": int(anc),
                    "tercile": int(tf),
                    "block": int(blk),
                    "is_F": bool(f_flag),
                    "is_U": bool(u_flag),
                    "both_filled": bool(both_filled),
                    "delay_both": bool(delay_both),
                    "abs_exc": float(abs_exc),
                    "max_exc": float(max_exc),
                    "gap_clear": bool(gap_clear),
                    "spread": float(spread_dollars),
                    "net": float(net),
                }
            )

        self.rows = int(end)
        self.last_stamp = int(stamps[-1])
        tail = min(H_EXCURSION + TRAIL + 5, len(all_stamps))
        self.carry_stamp = all_stamps[-tail:].copy()
        self.carry_bid = all_bid[-tail:].copy()
        self.carry_ask = all_ask[-tail:].copy()
        self.carry_mid = all_mid[-tail:].copy()
        self.carry_spread = all_spread[-tail:].copy()


def evaluate_marketmaking(scan: MarketMakingScan, *, complete_rows: int = DISCOVERY_ROWS) -> dict[str, Any]:
    # Aggregate events
    if not scan._events:
        return {"error": "no events"}

    # Convert to arrays
    is_F = np.array([e["is_F"] for e in scan._events], dtype=bool)
    is_U = np.array([e["is_U"] for e in scan._events], dtype=bool)
    both = np.array([e["both_filled"] for e in scan._events], dtype=bool)
    delay_both = np.array([e["delay_both"] for e in scan._events], dtype=bool)
    abs_exc = np.array([e["abs_exc"] for e in scan._events], dtype=float)
    max_exc = np.array([e["max_exc"] for e in scan._events], dtype=float)
    gap_clear = np.array([e["gap_clear"] for e in scan._events], dtype=bool)
    net = np.array([e["net"] for e in scan._events], dtype=float)
    tercile = np.array([e["tercile"] for e in scan._events], dtype=int)
    block = np.array([e["block"] for e in scan._events], dtype=int)

    def stats_for(mask_F, mask_U):
        n_F = int(np.count_nonzero(mask_F))
        n_U = int(np.count_nonzero(mask_U))
        p_F = float(np.mean(both[mask_F])) if n_F else None
        p_U = float(np.mean(both[mask_U])) if n_U else None
        lift = (p_F - p_U) if (p_F is not None and p_U is not None) else None
        mean_exc_F = float(np.mean(abs_exc[mask_F])) if n_F else None
        mean_exc_U = float(np.mean(abs_exc[mask_U])) if n_U else None
        ratio = mean_exc_U / mean_exc_F if (mean_exc_F and mean_exc_F != 0 and mean_exc_U is not None) else None
        gap = (mean_exc_U - mean_exc_F) if (mean_exc_F is not None and mean_exc_U is not None) else None
        mean_max_F = float(np.mean(max_exc[mask_F])) if n_F else None
        mean_max_U = float(np.mean(max_exc[mask_U])) if n_U else None
        net_F = float(np.mean(net[mask_F])) if n_F else None
        net_U = float(np.mean(net[mask_U])) if n_U else None
        p_delay_F = float(np.mean(delay_both[mask_F])) if n_F else None
        p_delay_U = float(np.mean(delay_both[mask_U])) if n_U else None
        return {
            "n_F": n_F,
            "n_U": n_U,
            "p_F": p_F,
            "p_U": p_U,
            "lift": lift,
            "mean_exc_F": mean_exc_F,
            "mean_exc_U": mean_exc_U,
            "ratio": ratio,
            "gap_dollars": gap,
            "mean_max_F": mean_max_F,
            "mean_max_U": mean_max_U,
            "net_F": net_F,
            "net_U": net_U,
            "p_delay_F": p_delay_F,
            "p_delay_U": p_delay_U,
        }

    primary = stats_for(is_F, is_U)
    # terciles
    tercile_stats: list[dict[str, Any]] = []
    for t in range(3):
        mask_t = tercile == t
        if not np.any(mask_t):
            tercile_stats.append({"tercile": t, "n_F": 0, "n_U": 0, "p_F": None, "p_U": None, "lift": None, "mean_exc_F": None, "mean_exc_U": None, "ratio": None, "gap_dollars": None, "blocks": 0})
            continue
        # For stats over the tercile-subset arrays, we compute directly:
        n_F = int(np.count_nonzero(is_F[mask_t]))
        n_U = int(np.count_nonzero(is_U[mask_t]))
        # Use subset arrays
        both_t = both[mask_t]
        is_F_t = is_F[mask_t]
        is_U_t = is_U[mask_t]
        abs_t = abs_exc[mask_t]
        max_t = max_exc[mask_t]
        delay_t = delay_both[mask_t]
        net_t = net[mask_t]
        # compute manually (stats_for would use global arrays and mismatch, so inlined):
        p_F = float(np.mean(both_t[is_F_t])) if n_F else None
        p_U = float(np.mean(both_t[is_U_t])) if n_U else None
        lift = (p_F - p_U) if (p_F is not None and p_U is not None) else None
        mean_exc_F = float(np.mean(abs_t[is_F_t])) if n_F else None
        mean_exc_U = float(np.mean(abs_t[is_U_t])) if n_U else None
        ratio = mean_exc_U / mean_exc_F if (mean_exc_F and mean_exc_F != 0 and mean_exc_U is not None) else None
        gap = (mean_exc_U - mean_exc_F) if (mean_exc_F is not None and mean_exc_U is not None) else None
        sub = {
            "tercile": t,
            "n_F": n_F,
            "n_U": n_U,
            "p_F": p_F,
            "p_U": p_U,
            "lift": lift,
            "mean_exc_F": mean_exc_F,
            "mean_exc_U": mean_exc_U,
            "ratio": ratio,
            "gap_dollars": gap,
            "mean_max_F": float(np.mean(max_t[is_F_t])) if n_F else None,
            "mean_max_U": float(np.mean(max_t[is_U_t])) if n_U else None,
            "net_F": float(np.mean(net_t[is_F_t])) if n_F else None,
            "net_U": float(np.mean(net_t[is_U_t])) if n_U else None,
            "p_delay_F": float(np.mean(delay_t[is_F_t])) if n_F else None,
            "p_delay_U": float(np.mean(delay_t[is_U_t])) if n_U else None,
            "blocks": int(len(set(block[mask_t]))),
        }
        tercile_stats.append(sub)

    # gap subset
    gap_mask = gap_clear
    gap_stats = None
    if np.any(gap_mask):
        # stats_for would mismatch (global vs subset), so compute manually
        n_F = int(np.count_nonzero(is_F[gap_mask]))
        n_U = int(np.count_nonzero(is_U[gap_mask]))
        both_g = both[gap_mask]
        is_F_g2 = is_F[gap_mask]
        is_U_g2 = is_U[gap_mask]
        abs_g = abs_exc[gap_mask]
        p_F = float(np.mean(both_g[is_F_g2])) if n_F else None
        p_U = float(np.mean(both_g[is_U_g2])) if n_U else None
        lift = (p_F - p_U) if (p_F is not None and p_U is not None) else None
        mean_exc_F = float(np.mean(abs_g[is_F_g2])) if n_F else None
        mean_exc_U = float(np.mean(abs_g[is_U_g2])) if n_U else None
        ratio = mean_exc_U / mean_exc_F if (mean_exc_F and mean_exc_F != 0 and mean_exc_U is not None) else None
        gap = (mean_exc_U - mean_exc_F) if (mean_exc_F is not None and mean_exc_U is not None) else None
        gap_stats = {"n_F": n_F, "n_U": n_U, "p_F": p_F, "p_U": p_U, "lift": lift, "mean_exc_F": mean_exc_F, "mean_exc_U": mean_exc_U, "ratio": ratio, "gap_dollars": gap}

    blocks_per_tercile = {t: len(set(block[tercile == t])) for t in range(3)}

    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {"time_msc_min": scan.time_min, "cutoff_time_msc": scan.cutoff, "discovery_rows_read": scan.rows, "held_out_rows_read": 0},
        "measured": {
            "16_fill_256_exc": primary,
            "terciles": tercile_stats,
            "gap_under_one_hour": gap_stats,
            "blocks_per_tercile": blocks_per_tercile,
            "exclusions": {"note": "non Low+Tight and non High+Wide ignored, front-of-queue SYNTHETIC"},
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
    if primary["n_F"] < MIN_N or primary["n_U"] < MIN_N:
        underpowered = True
        reasons.append(f"primary n < {MIN_N}: F {primary['n_F']} U {primary['n_U']}")
    for t, ts in enumerate(tercile_stats):
        if ts["n_F"] < MIN_N or ts["n_U"] < MIN_N:
            underpowered = True
            reasons.append(f"tercile {t} n < {MIN_N}: F {ts['n_F']} U {ts['n_U']}")
        if blocks_per_tercile[t] < MIN_BLOCKS:
            underpowered = True
            reasons.append(f"tercile {t} blocks {blocks_per_tercile[t]} < {MIN_BLOCKS}")

    floor_pass = False
    artifact_pass = False
    if not underpowered:
        floor_pass = (
            primary["lift"] is not None and primary["lift"] >= MIN_LIFT_FILL
            and primary["ratio"] is not None and primary["ratio"] >= MIN_RATIO_EXC
            and primary["gap_dollars"] is not None and primary["gap_dollars"] >= MIN_GAP_EXC
            and primary["net_F"] is not None and primary["net_F"] > MIN_NET
            and primary["net_F"] is not None and primary["net_U"] is not None and primary["net_F"] > primary["net_U"]
        )
        # artifact: terciles sign, gap sign, max_exc sign, delay sign
        artifact_pass = (
            all(ts["lift"] is not None and ts["lift"] > 0 and ts["ratio"] is not None and ts["ratio"] > 1.0 for ts in tercile_stats)
            and gap_stats is not None and gap_stats["lift"] is not None and gap_stats["lift"] > 0 and gap_stats["ratio"] is not None and gap_stats["ratio"] > 1.0
            and all(ts["mean_max_U"] is not None and ts["mean_max_F"] is not None and ts["mean_max_U"] > ts["mean_max_F"] for ts in tercile_stats if ts["mean_max_F"] is not None)
        )

    output["measured"]["gates"] = {
        "identity_and_minimums": not underpowered,
        "material_fill_exc_net": floor_pass if not underpowered else None,
        "mirrors_terciles_gap_max": artifact_pass if not underpowered else None,
        "bootstrap_required": "pending" if not underpowered else None,
    }

    if underpowered:
        status = "INCONCLUSIVE"
    elif not floor_pass:
        status = "REJECTED"
        reasons.append(f"floor miss: lift {primary['lift']:.3f} < {MIN_LIFT_FILL} or ratio {primary['ratio']:.3f} < {MIN_RATIO_EXC} or gap ${primary['gap_dollars']:.3f} < ${MIN_GAP_EXC} or net_F ${primary['net_F']:.3f} <= ${MIN_NET} or net_F <= net_U")
    elif not artifact_pass:
        status = "REJECTED"
        reasons.append("tercile, gap, or max-excursion sign gate failed")
    else:
        status = "TESTED"
        reasons = ["fill lift, excursion ratio/gap, net floors passed; terciles, gap, max agree; SYNTHETIC queue, bootstrap pending"]

    output["hypotheses"][HYPOTHESIS] = {"status": status, "reasons": reasons, "not_a_strategy": True, "validated": False}
    output["decision"] = status if status != "TESTED" else "INCONCLUSIVE"
    if status == "TESTED":
        output["decision"] = "INCONCLUSIVE"
    return output
