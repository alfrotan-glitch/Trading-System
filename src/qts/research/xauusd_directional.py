"""H-DIR-01: one preregistered, discovery-only directional falsification.

The contract is docs/xauusd_directional_next_step_2026-09-23.md. This module
accepts only discovery-prefix batches; it never acquires data, submits orders,
opens the locked span, trains a model, or chooses a winning state/horizon/side.
The separate view reader must certify all input parts before any quote is read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from qts.research.impulse.statistics import holm_bonferroni

SCHEMA = "qts.xauusd_directional.v1"
PREREGISTRATION = "docs/xauusd_directional_next_step_2026-09-23.md"
HYPOTHESIS = "H-DIR-01"
TIME_MIN = 1_726_746_013_452
CUTOFF = 1_764_563_969_254
DISCOVERY_ROWS = 70_834_426
SOURCE_ROWS = 139_930_971
SOURCE_ZIP_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
SOURCE_DATASET_SHA256 = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
PRIMARY = 256
STABILITY = 1024
HORIZONS = (PRIMARY, STABILITY)
LOOKBACK = 16
BLOCK_ANCHORS = 1024
GAP_MS = 3_600_000
MIN_N = 1000
MIN_BLOCKS = 50
MIN_EFFECT_DOLLARS = 0.05
N_BOOT = 9999
N_SHUFFLE = 1999
SEED = 20260923
ALPHA = 0.01
CARRY = STABILITY + LOOKBACK + 2  # every used row, i-16 through i+1+1024


class LockedSpanRefused(ValueError):
    """A batch would expose a locked timestamp. No quote in it was processed."""


class DiscoveryDataError(ValueError):
    """Discovery ordering, quote grid, or integrity was invalid; do not repair."""


@dataclass(frozen=True)
class DiscoveryIdentity:
    """Canonical defaults; small test fixtures may supply an explicit identity."""

    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = DISCOVERY_ROWS
    source_rows: int = SOURCE_ROWS
    zip_sha256: str = SOURCE_ZIP_SHA256
    dataset_sha256: str = SOURCE_DATASET_SHA256


@dataclass(frozen=True)
class EventTable:
    anchor: np.ndarray
    tercile: np.ndarray
    block: np.ndarray
    state: np.ndarray  # 0=low, 1=high
    sign: np.ndarray  # +1 or -1
    gross: np.ndarray
    net: np.ndarray
    entry_spread: np.ndarray
    exit_spread: np.ndarray
    gap_clear: np.ndarray

    def __len__(self) -> int:
        return len(self.anchor)

    def take(self, mask: np.ndarray) -> EventTable:
        return EventTable(*(getattr(self, name)[mask] for name in self.__dataclass_fields__))


EVENT_FIELDS = tuple(EventTable.__dataclass_fields__)


def _empty_events() -> EventTable:
    return EventTable(
        np.empty(0, dtype=np.int64),
        np.empty(0, dtype=np.int8),
        np.empty(0, dtype=np.int64),
        np.empty(0, dtype=np.int8),
        np.empty(0, dtype=np.int8),
        np.empty(0),
        np.empty(0),
        np.empty(0),
        np.empty(0),
        np.empty(0, dtype=bool),
    )


class DirectionalScan:
    """Streaming row-order measurement; reject a locked stamp before reading prices.

    add_batch is for *already discovery-only* arrays. The real-data adapter
    validates an independently attested, complete discovery view before it
    reads even a bid/ask column. A bare array is never a provenance certificate.
    """

    def __init__(self, time_min: int = TIME_MIN, cutoff: int = CUTOFF) -> None:
        if cutoff <= time_min:
            raise ValueError("cutoff must follow time_min")
        self.time_min, self.cutoff = int(time_min), int(cutoff)
        self.rows = 0
        self.last_stamp: int | None = None
        self.carry_bid = np.empty(0, dtype=np.int64)
        self.carry_ask = np.empty(0, dtype=np.int64)
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.blocks: set[tuple[int, int]] = set()  # all primary anchors, including unselected
        self.exclusions = {h: {"zero_sign": 0, "middle_state": 0, "anchors": 0} for h in HORIZONS}
        self._events: dict[int, list[EventTable]] = {h: [] for h in HORIZONS}

    def add_batch(self, bid: np.ndarray, ask: np.ndarray, time_msc: np.ndarray) -> None:
        stamps = np.asarray(time_msc, dtype=np.int64)
        if stamps.ndim != 1:
            raise DiscoveryDataError("time_msc must be one-dimensional")
        if np.any(stamps >= self.cutoff):
            raise LockedSpanRefused("batch contains locked time_msc; refused before inspecting bid/ask")
        if stamps.size == 0:
            return
        if np.any(stamps < self.time_min) or np.any(np.diff(stamps) < 0):
            raise DiscoveryDataError("discovery timestamps out of range or decreasing")
        if self.last_stamp is not None and stamps[0] < self.last_stamp:
            raise DiscoveryDataError("discovery timestamps decrease across batches")
        # Only *after* the timestamp/boundary guard may any quote be inspected.
        bids = np.asarray(bid, dtype=np.float64)
        asks = np.asarray(ask, dtype=np.float64)
        if bids.shape != stamps.shape or asks.shape != stamps.shape:
            raise DiscoveryDataError("bid/ask/time_msc lengths disagree")
        if not (np.all(np.isfinite(bids)) and np.all(np.isfinite(asks))):
            raise DiscoveryDataError("non-finite bid or ask")
        if np.any(bids <= 0) or np.any(asks <= 0) or np.any(asks < bids):
            raise DiscoveryDataError("invalid or inverted discovery quote")
        bid_c = np.rint(bids * 100).astype(np.int64)
        ask_c = np.rint(asks * 100).astype(np.int64)
        if np.any(np.abs(bids * 100 - bid_c) > 1e-6) or np.any(np.abs(asks * 100 - ask_c) > 1e-6):
            raise DiscoveryDataError("bid/ask not on observed one-cent grid")
        start, end = self.rows, self.rows + stamps.size
        carry_n = len(self.carry_stamp)
        base = start - carry_n
        all_stamps = np.concatenate((self.carry_stamp, stamps))
        all_bids = np.concatenate((self.carry_bid, bid_c))
        all_asks = np.concatenate((self.carry_ask, ask_c))
        mids = all_bids + all_asks  # integer half-cents: 1 unit = $0.005
        spread = all_asks - all_bids  # integer cents
        gap_prefix = np.concatenate(([0], np.cumsum(np.diff(all_stamps) >= GAP_MS, dtype=np.int64)))
        for h in HORIZONS:
            stride = h + LOOKBACK + 2
            first = max(stride, ((start - h - 1 + stride - 1) // stride) * stride)
            anchors = np.arange(first, end - h - 1, stride, dtype=np.int64)
            if anchors.size == 0:
                continue
            local = anchors - base
            left, entry, exit_ = local - LOOKBACK, local + 1, local + 1 + h
            if np.any(left < 0) or np.any(exit_ >= len(all_stamps)):
                raise DiscoveryDataError("stream carry or global anchor identity was lost")
            tercile = np.minimum(2, (all_stamps[local] - self.time_min) * 3 // (self.cutoff - self.time_min))
            block = (anchors // stride) // BLOCK_ANCHORS
            if h == PRIMARY:
                self.blocks.update((int(t), int(b)) for t, b in zip(tercile, block, strict=True))
            self.exclusions[h]["anchors"] += int(anchors.size)
            past_move = mids[local] - mids[left]
            zero = past_move == 0
            middle = (np.abs(past_move) > 20) & (np.abs(past_move) < 40)
            self.exclusions[h]["zero_sign"] += int(np.count_nonzero(zero))
            self.exclusions[h]["middle_state"] += int(np.count_nonzero(middle))
            eligible = ~(zero | middle)
            if not np.any(eligible):
                continue
            state = (np.abs(past_move[eligible]) >= 40).astype(np.int8)
            sign = np.sign(past_move[eligible]).astype(np.int8)
            forward_move = (mids[exit_[eligible]] - mids[entry[eligible]]) * 0.005
            gross = sign * forward_move
            entry_spread = spread[entry[eligible]] * 0.01
            exit_spread = spread[exit_[eligible]] * 0.01
            cost = (entry_spread + exit_spread) / 2 + 0.02
            gap_clear = (gap_prefix[exit_[eligible]] - gap_prefix[left[eligible]]) == 0
            self._events[h].append(
                EventTable(
                    anchors[eligible],
                    tercile[eligible].astype(np.int8),
                    block[eligible],
                    state,
                    sign,
                    gross,
                    gross - cost,
                    entry_spread,
                    exit_spread,
                    gap_clear,
                )
            )
        self.rows = int(end)
        self.last_stamp = int(stamps[-1])
        tail = min(CARRY, len(all_stamps))
        self.carry_bid, self.carry_ask = all_bids[-tail:].copy(), all_asks[-tail:].copy()
        self.carry_stamp = all_stamps[-tail:].copy()

    def events(self, h: int) -> EventTable:
        if h not in HORIZONS:
            raise ValueError("unregistered horizon")
        chunks = self._events[h]
        if not chunks:
            return _empty_events()
        return EventTable(*(np.concatenate([getattr(c, name) for c in chunks]) for name in EVENT_FIELDS))

    def boundary_exclusions(self, h: int) -> int:
        """Count anchors lacking a full outcome *inside* the discovery prefix."""
        stride = h + LOOKBACK + 2
        if self.rows < LOOKBACK + 1:
            return 0
        anchors = np.arange(stride, self.rows, stride)
        return int(np.count_nonzero(anchors + h + 1 >= self.rows))


def _cells(events: EventTable) -> dict[str, Any]:
    """Sign-balanced estimands; neither sign's prevalence can determine the result."""
    cells: dict[str, dict[str, Any]] = {}
    for state, name in ((1, "high"), (0, "low")):
        cells[name] = {}
        for sign, side in ((1, "up"), (-1, "down")):
            mask = (events.state == state) & (events.sign == sign)
            n = int(np.count_nonzero(mask))
            cells[name][side] = {
                "n": n,
                "mean_gross": float(events.gross[mask].mean()) if n else None,
                "mean_net": float(events.net[mask].mean()) if n else None,
                "entry_spread": float(events.entry_spread[mask].mean()) if n else None,
                "exit_spread": float(events.exit_spread[mask].mean()) if n else None,
                "sign_match_rate": float(np.count_nonzero(events.gross[mask] > 0) / n) if n else None,
            }

    def balanced(field: str, name: str) -> float | None:
        up, down = cells[name]["up"][field], cells[name]["down"][field]
        return (up + down) / 2 if up is not None and down is not None else None

    net_high = balanced("mean_net", "high")
    gross_high = balanced("mean_gross", "high")
    gross_low = balanced("mean_gross", "low")
    return {
        "cells": cells,
        "T1_high_net": net_high,
        "T2_high_minus_low_gross": gross_high - gross_low if gross_high is not None and gross_low is not None else None,
    }


def _two_from_sums(count: np.ndarray, gross: np.ndarray, net: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Array-leading axes optional; 0=low/1=high, 0=prior-up/1=prior-down."""
    with np.errstate(divide="ignore", invalid="ignore"):
        n_high = (net[..., 1, 0] / count[..., 1, 0] + net[..., 1, 1] / count[..., 1, 1]) / 2
        g_high = (gross[..., 1, 0] / count[..., 1, 0] + gross[..., 1, 1] / count[..., 1, 1]) / 2
        g_low = (gross[..., 0, 0] / count[..., 0, 0] + gross[..., 0, 1] / count[..., 0, 1]) / 2
    return n_high, g_high - g_low


def _block_arrays(
    events: EventTable, blocks: set[tuple[int, int]]
) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray, np.ndarray]:
    pairs = sorted(blocks)
    index = {pair: pos for pos, pair in enumerate(pairs)}
    count = np.zeros((len(pairs), 2, 2), dtype=np.int64)
    gross = np.zeros_like(count, dtype=float)
    net = np.zeros_like(count, dtype=float)
    if len(events):
        block_idx = np.fromiter(
            (index[(int(t), int(b))] for t, b in zip(events.tercile, events.block, strict=True)),
            dtype=np.int64,
            count=len(events),
        )
        sign_idx = np.where(events.sign == 1, 0, 1)
        key = (block_idx, events.state, sign_idx)
        np.add.at(count, key, 1)
        np.add.at(gross, key, events.gross)
        np.add.at(net, key, events.net)
    return pairs, count, gross, net


def block_bootstrap(
    events: EventTable, blocks: set[tuple[int, int]], *, draws: int = N_BOOT, seed: int = SEED
) -> dict[str, Any] | None:
    """Resample joint cells by time block within tercile; no iid tick p-values."""
    pairs, count, gross, net = _block_arrays(events, blocks)
    groups = [np.array([pos for pos, (t, _) in enumerate(pairs) if t == tercile], dtype=int) for tercile in range(3)]
    if any(len(g) == 0 for g in groups):
        return None
    observed_t1, observed_t2 = _two_from_sums(count.sum(axis=0), gross.sum(axis=0), net.sum(axis=0))
    if not np.all(np.isfinite([observed_t1, observed_t2])):
        return None
    rng = np.random.default_rng(seed)
    rep_t1, rep_t2 = [], []
    for start in range(0, draws, 256):
        n = min(256, draws - start)
        counts = np.zeros((n, 2, 2), dtype=np.int64)
        grosses = np.zeros((n, 2, 2))
        nets = np.zeros((n, 2, 2))
        for group in groups:
            selected = group[rng.integers(0, len(group), size=(n, len(group)))]
            counts += count[selected].sum(axis=1)
            grosses += gross[selected].sum(axis=1)
            nets += net[selected].sum(axis=1)
        t1, t2 = _two_from_sums(counts, grosses, nets)
        rep_t1.append(t1)
        rep_t2.append(t2)
    observed = [float(observed_t1), float(observed_t2)]
    replicates = [np.concatenate(rep_t1), np.concatenate(rep_t2)]
    if any(not np.all(np.isfinite(values)) for values in replicates):
        return None
    result = {}
    for name, value, sample in zip(("T1", "T2"), observed, replicates, strict=True):
        centered = sample - value
        result[name] = {
            "p": (1 + int(np.count_nonzero(centered >= value))) / (draws + 1),
            "lower_99": value - float(np.quantile(centered, 0.99)),
        }
    return result


def sign_shuffle(events: EventTable, *, draws: int = N_SHUFFLE, seed: int = SEED) -> dict[str, Any] | None:
    """Shuffle past signs only within fixed time-block/state cells; no label selection."""
    if not len(events):
        return None
    rng = np.random.default_rng(seed)
    keys = np.stack((events.tercile, events.block, events.state), axis=1)
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    changes = np.flatnonzero(np.any(keys[order[1:]] != keys[order[:-1]], axis=1)) + 1
    segments = np.split(order, changes)
    groups = []
    permutable = {0: 0, 1: 0}
    for indices in segments:
        s = int(events.state[indices[0]])
        nplus = int(np.count_nonzero(events.sign[indices] == 1))
        if 0 < nplus < len(indices):
            permutable[s] += 1
        deltas = events.gross[indices] * events.sign[indices]
        costs = events.gross[indices] - events.net[indices]
        groups.append((s, nplus, deltas, costs, float(deltas.sum()), float(costs.sum())))
    if not all(permutable.values()):
        return None
    count = np.zeros((2, 2), dtype=np.int64)
    for s in (0, 1):
        count[s, 0] = int(np.count_nonzero((events.state == s) & (events.sign == 1)))
        count[s, 1] = int(np.count_nonzero((events.state == s) & (events.sign == -1)))
    observed = _cells(events)
    t1, t2 = observed["T1_high_net"], observed["T2_high_minus_low_gross"]
    if t1 is None or t2 is None:
        return None
    exceed = [0, 0]
    for _ in range(draws):
        gross = np.zeros((2, 2))
        net = np.zeros((2, 2))
        for state, nplus, delta, cost, total_delta, total_cost in groups:
            if nplus == 0:
                plus_delta = plus_cost = 0.0
            elif nplus == len(delta):
                plus_delta, plus_cost = total_delta, total_cost
            else:
                sample = rng.permutation(len(delta))[:nplus]
                plus_delta, plus_cost = float(delta[sample].sum()), float(cost[sample].sum())
            gross[state, 0] += plus_delta
            gross[state, 1] += plus_delta - total_delta
            net[state, 0] += plus_delta - plus_cost
            net[state, 1] += plus_delta - total_delta - (total_cost - plus_cost)
        p1, p2 = _two_from_sums(count, gross, net)
        exceed[0] += bool(p1 >= t1)
        exceed[1] += bool(p2 >= t2)
    return {"T1_p": (1 + exceed[0]) / (draws + 1), "T2_p": (1 + exceed[1]) / (draws + 1)}


def evaluate(
    scan: DirectionalScan,
    *,
    complete_rows: int = DISCOVERY_ROWS,
    bootstrap_draws: int = N_BOOT,
    shuffle_draws: int = N_SHUFFLE,
    min_n: int = MIN_N,
    min_blocks: int = MIN_BLOCKS,
) -> dict[str, Any]:
    """Apply the frozen joint gates; override sizes ONLY in synthetic unit tests.

    Production calls with no overrides and only after attested-view preflight.
    A positive discovery verdict is never a strategy, validation, or execution.
    """
    primary = scan.events(PRIMARY)
    longer = scan.events(STABILITY)
    primary_stats, longer_stats = _cells(primary), _cells(longer)
    terciles = [_cells(primary.take(primary.tercile == t)) for t in range(3)]
    gap_events = primary.take(primary.gap_clear)
    gap_stats = _cells(gap_events)
    counts = [
        {
            "tercile": t,
            "blocks": sum(1 for key in scan.blocks if key[0] == t),
            "high_up": terciles[t]["cells"]["high"]["up"]["n"],
            "high_down": terciles[t]["cells"]["high"]["down"]["n"],
            "low_up": terciles[t]["cells"]["low"]["up"]["n"],
            "low_down": terciles[t]["cells"]["low"]["down"]["n"],
        }
        for t in range(3)
    ]
    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {
            "time_msc_min": scan.time_min,
            "cutoff_time_msc": scan.cutoff,
            "discovery_rows_read": scan.rows,
            "held_out_rows_read": 0,
        },
        "measured": {
            "256": primary_stats,
            "1024": longer_stats,
            "terciles": terciles,
            "gap_under_one_hour": gap_stats,
            "tercile_counts": counts,
            "exclusions": {
                str(h): {**scan.exclusions[h], "boundary_outcomes": scan.boundary_exclusions(h)} for h in HORIZONS
            },
        },
        "hypotheses": {},
        "decision": "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "safety": {"DEMO_EXECUTION": "DISABLED", "confirm_live": False, "orders_submitted": 0},
    }
    reasons = []
    underpowered = (
        scan.rows != complete_rows
        or any(value < min_n for row in counts for key, value in row.items() if key not in {"tercile", "blocks"})
        or any(row["blocks"] < min_blocks for row in counts)
    )
    underpowered |= any(
        longer_stats["cells"][state][sign]["n"] < min_n or gap_stats["cells"][state][sign]["n"] < min_n
        for state in ("high", "low")
        for sign in ("up", "down")
    )
    if scan.rows != complete_rows:
        reasons.append("discovery prefix row count does not match registered identity")
    if underpowered:
        reasons.append("registered per-sign/tercile/gap count or block minimum not met")
    inference = None
    if not underpowered:
        bootstrap = block_bootstrap(primary, scan.blocks, draws=bootstrap_draws)
        shuffle = sign_shuffle(primary, draws=shuffle_draws)
        if bootstrap is not None and shuffle is not None:
            raw_p = [bootstrap["T1"]["p"], bootstrap["T2"]["p"], shuffle["T1_p"], shuffle["T2_p"]]
            adjusted = holm_bonferroni(raw_p)
            inference = {
                "bootstrap": bootstrap,
                "shuffle": shuffle,
                "p_raw": dict(zip(("bootstrap_T1", "bootstrap_T2", "shuffle_T1", "shuffle_T2"), raw_p, strict=True)),
                "p_holm": dict(
                    zip(("bootstrap_T1", "bootstrap_T2", "shuffle_T1", "shuffle_T2"), adjusted, strict=True)
                ),
                "holm_family_wise_alpha": ALPHA,
            }
        else:
            reasons.append("block-bootstrap or sign-shuffle check was inapplicable")
    output["measured"]["inference"] = inference

    def positive(stat: Mapping[str, Any], key: str) -> bool:
        return stat[key] is not None and stat[key] > 0

    floor_pass = (
        primary_stats["T1_high_net"] is not None
        and primary_stats["T1_high_net"] >= MIN_EFFECT_DOLLARS
        and primary_stats["T2_high_minus_low_gross"] is not None
        and primary_stats["T2_high_minus_low_gross"] >= MIN_EFFECT_DOLLARS
    )
    artifact_pass = (
        all(
            positive(t, "T1_high_net")
            and positive(t, "T2_high_minus_low_gross")
            and all(
                t["cells"]["high"][sign]["mean_net"] is not None and t["cells"]["high"][sign]["mean_net"] > 0
                for sign in ("up", "down")
            )
            for t in [*terciles, longer_stats]
        )
        and positive(gap_stats, "T1_high_net")
        and positive(gap_stats, "T2_high_minus_low_gross")
    )
    output["measured"]["gates"] = {
        "identity_and_minimums": not underpowered,
        "material_T1_and_T2": floor_pass if not underpowered else None,
        "mirrors_terciles_1024_and_spacing": artifact_pass if not underpowered else None,
        "four_holm_p_below_0_01": (
            all(p < ALPHA for p in inference["p_holm"].values()) if inference is not None else None
        ),
        "both_one_sided_99_lower_bounds_positive": (
            all(inference["bootstrap"][key]["lower_99"] > 0 for key in ("T1", "T2")) if inference is not None else None
        ),
    }
    if not underpowered:
        if not floor_pass:
            reasons.append("a predeclared five-cent economic/interaction floor was missed")
        if not artifact_pass:
            reasons.append("a prespecified sign, tercile, 1024-quote or gap gate disagrees")
    if inference is not None and not output["measured"]["gates"]["four_holm_p_below_0_01"]:
        reasons.append("one or more Holm-adjusted uncertainty/control p-values did not clear 0.01")
    if inference is not None and not output["measured"]["gates"]["both_one_sided_99_lower_bounds_positive"]:
        reasons.append("one or both block-bootstrap lower bounds did not exceed zero")
    if underpowered:
        status = "INCONCLUSIVE"
    elif not floor_pass or not artifact_pass:
        status = "REJECTED"
    elif inference is None or not all(output["measured"]["gates"].values()):
        status = "INCONCLUSIVE"
    else:
        status = "SURVIVED_DISCOVERY_ONLY"
        reasons = ["all frozen discovery-only gates passed; independent validation still required"]
    output["decision"] = "INCONCLUSIVE" if status == "SURVIVED_DISCOVERY_ONLY" else status
    output["hypotheses"][HYPOTHESIS] = {
        "status": status,
        "reasons": reasons,
        "not_a_strategy": True,
        "validated": False,
        "held_out_span_opened": False,
    }
    return output


def render_report(report: Mapping[str, Any]) -> str:
    verdict = (report.get("hypotheses") or {}).get(HYPOTHESIS) or {}
    lines = [
        "# XAUUSD H-DIR-01 discovery-only measurement",
        "",
        f"Status: {verdict.get('status', report.get('status', 'NOT RUN'))}",
        "",
        "A research event study, not a trading strategy, validation, fill or execution authorization.",
        (
            "Held-out boundary VIOLATED: invalidate attempt; locked timestamp observed. Orders: 0. Demo execution: DISABLED."
            if report.get("held_out_span_opened")
            else "Held-out 40%: CLOSED. Orders: 0. Demo execution: DISABLED."
        ),
        "",
    ]
    lines.extend(f"- {reason}" for reason in verdict.get("reasons", [report.get("reason", "not measured")]))
    measured = report.get("measured") or {}
    if measured:
        primary = measured["256"]
        lines.extend(
            [
                "",
                "## Prespecified effect sizes (USD; discovery only)",
                "",
                f"- T1, sign-balanced high-state cost-stressed net: {primary['T1_high_net']}",
                f"- T2, sign-balanced high-minus-low gross: {primary['T2_high_minus_low_gross']}",
                f"- Joint gate results: {measured['gates']}",
                "- Neither a small p-value nor an absolute move is a directional trade.",
            ]
        )
    return "\n".join(lines) + "\n"
