"""Discovery-window tests for the canonical XAUUSD tick archive.

Inventory of the whole archive is a data fact. Predictive tests use only the
preregistered discovery span: the first 60 percent of the raw ``time_msc``
range. The last 40 percent is not aggregated. No row is repaired. A result
here is not a strategy and is not ``VALIDATED``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.research.impulse.statistics import binomial_test_vs_baseline, bootstrap_ci_mean

SCHEMA = "qts.xauusd_tick_discovery.v1"
DISCOVERY_NUMERATOR = 60
DISCOVERY_DENOMINATOR = 100
GAP_SENSITIVITY_MS = 1_000
NON_OVERLAP_CENTER_STEP = 3
BOOTSTRAP_CAP = 100_000
BOOTSTRAP_SEED = 42
BOOTSTRAP_DRAWS = 2_000
SPREAD_STORE_CAP = 120_000_000


def discovery_cutoff(time_msc_min: int, time_msc_max: int) -> int:
    """First raw stamp of the locked validation span.

    Discovery observations satisfy ``time_msc < cutoff``. The split is on the
    raw span, not on row count. Integer arithmetic keeps the cut reproducible.
    """
    if time_msc_max < time_msc_min:
        raise ValueError("time_msc_max is before time_msc_min")
    span = time_msc_max - time_msc_min
    return time_msc_min + (span * DISCOVERY_NUMERATOR) // DISCOVERY_DENOMINATOR


def _finite(values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


@dataclass
class _Carry:
    bid: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    ask: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    stamp: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    last: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    volume: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    time_sec: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    flags: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    has_last: bool = False
    has_volume: bool = False
    has_time_sec: bool = False
    has_flags: bool = False

    def append_tail(self, bid: np.ndarray, ask: np.ndarray, stamp: np.ndarray, **optional: np.ndarray) -> None:
        self.bid = np.concatenate((self.bid, bid))[-2:]
        self.ask = np.concatenate((self.ask, ask))[-2:]
        self.stamp = np.concatenate((self.stamp, stamp))[-2:]
        if self.has_last:
            self.last = np.concatenate((self.last, optional["last"]))[-2:]
        if self.has_volume:
            self.volume = np.concatenate((self.volume, optional["volume"]))[-2:]
        if self.has_time_sec:
            self.time_sec = np.concatenate((self.time_sec, optional["time_sec"]))[-2:]
        if self.has_flags:
            self.flags = np.concatenate((self.flags, optional["flags"]))[-2:]


@dataclass
class _Hms01:
    events: int = 0
    reversals: int = 0
    continuations: int = 0
    flat_next: int = 0
    net_price_sum: float = 0.0
    net_bps_sum: float = 0.0
    net_positive: int = 0
    gap_events: int = 0
    gap_reversals: int = 0
    gap_net_bps_sum: float = 0.0
    delay_events: int = 0
    delay_net_bps_sum: float = 0.0
    nonoverlap_events: int = 0
    nonoverlap_reversals: int = 0
    nonoverlap_continuations: int = 0
    nonoverlap_net_bps_sum: float = 0.0
    nonoverlap_net_positive: int = 0
    excluded_validation_touch: int = 0
    inverted_events: int = 0
    inverted_net_bps_sum: float = 0.0
    nonoverlap_inverted_events: int = 0
    nonoverlap_inverted_net_bps_sum: float = 0.0
    nonoverlap_gap_events: int = 0
    nonoverlap_gap_net_bps_sum: float = 0.0
    nonoverlap_sample: list[np.ndarray] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        directional = self.reversals + self.continuations
        non_directional = self.nonoverlap_reversals + self.nonoverlap_continuations
        sample = np.concatenate(self.nonoverlap_sample) if self.nonoverlap_sample else np.empty(0, dtype=np.float64)
        if sample.size > BOOTSTRAP_CAP:
            rng = np.random.default_rng(BOOTSTRAP_SEED)
            sample = sample[rng.choice(sample.size, size=BOOTSTRAP_CAP, replace=False)]
            ci_note = f"seeded subsample of {BOOTSTRAP_CAP}; mean uses the full non-overlapping count"
        else:
            ci_note = "bootstrap uses the full non-overlapping sample"
        mean, lo, hi = bootstrap_ci_mean(sample, n_boot=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED)
        return {
            "events": self.events,
            "reversals": self.reversals,
            "continuations": self.continuations,
            "flat_next": self.flat_next,
            "reversal_frequency_among_directional": (self.reversals / directional) if directional else None,
            "directional_n": directional,
            "mean_net_price": (self.net_price_sum / self.events) if self.events else None,
            "mean_net_bps": (self.net_bps_sum / self.events) if self.events else None,
            "net_positive_frequency": (self.net_positive / self.events) if self.events else None,
            "dependent_sample_binomial_p_vs_half": (
                binomial_test_vs_baseline(self.reversals, directional, 0.5) if directional else None
            ),
            "dependent_p_value_status": "NOT INFERENTIAL — adjacent events share quotes",
            "gap_sensitivity_ms": GAP_SENSITIVITY_MS,
            "gap_events": self.gap_events,
            "gap_reversal_frequency": (self.gap_reversals / self.gap_events) if self.gap_events else None,
            "gap_mean_net_bps": (self.nonoverlap_gap_net_bps_sum / self.nonoverlap_gap_events) if self.nonoverlap_gap_events else None,
            "overlapping_gap_mean_net_bps": (self.gap_net_bps_sum / self.gap_events) if self.gap_events else None,
            "one_quote_delay_events": self.delay_events,
            "one_quote_delay_mean_net_bps": (self.delay_net_bps_sum / self.delay_events) if self.delay_events else None,
            "one_quote_delay_status": "EXECUTION STRESS, not a separate hypothesis",
            "nonoverlap_events": self.nonoverlap_events,
            "nonoverlap_reversals": self.nonoverlap_reversals,
            "nonoverlap_continuations": self.nonoverlap_continuations,
            "nonoverlap_reversal_frequency": (self.nonoverlap_reversals / non_directional) if non_directional else None,
            "nonoverlap_directional_n": non_directional,
            "nonoverlap_mean_net_bps": (self.nonoverlap_net_bps_sum / self.nonoverlap_events) if self.nonoverlap_events else None,
            "nonoverlap_net_positive_frequency": (
                (self.nonoverlap_net_positive / self.nonoverlap_events) if self.nonoverlap_events else None
            ),
            "nonoverlap_binomial_p_vs_half": (
                binomial_test_vs_baseline(self.nonoverlap_reversals, non_directional, 0.5) if non_directional else None
            ),
            "nonoverlap_mean_net_bps_bootstrap": {"mean": mean, "lo": lo, "hi": hi, "note": ci_note},
            "excluded_triples_touching_validation_span": self.excluded_validation_touch,
            "inverted_events": self.inverted_events,
            "inverted_mean_net_bps": (self.inverted_net_bps_sum / self.inverted_events) if self.inverted_events else None,
            "nonoverlap_inverted_events": self.nonoverlap_inverted_events,
            "nonoverlap_inverted_mean_net_bps": (
                (self.nonoverlap_inverted_net_bps_sum / self.nonoverlap_inverted_events) if self.nonoverlap_inverted_events else None
            ),
            "inferential_sample": "discovery events whose global center row is divisible by 3; selected quotes do not overlap",
        }


@dataclass
class _Facts:
    rows: int = 0
    time_msc_min: int | None = None
    time_msc_max: int | None = None
    time_equals_msc_div_1000: int = 0
    time_compared: int = 0
    msc_mod_1000_zero: int = 0
    msc_mod_100_zero: int = 0
    msc_mod_10_zero: int = 0
    bid_on_0_01: int = 0
    bid_on_0_001: int = 0
    bid_checked: int = 0
    volume_zero: int = 0
    volume_positive: int = 0
    volume_compared: int = 0
    last_zero: int = 0
    last_eq_bid: int = 0
    last_eq_ask: int = 0
    last_strictly_inside: int = 0
    last_outside: int = 0
    last_compared: int = 0
    bid_only_changes: int = 0
    ask_only_changes: int = 0
    both_changes: int = 0
    neither_changes: int = 0
    adjacent_pairs: int = 0
    min_positive_bid_change: float | None = None
    positive_bid_changes: int = 0
    bid_change_eq_0_01: int = 0
    flag_counts: dict[int, int] = field(default_factory=dict)
    flags_truncated: bool = False
    bin_rows: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0])
    bin_spread_sum: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
    bin_spread_n: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0])
    discovery_rows: int = 0
    validation_rows: int = 0


def _on_grid(values: np.ndarray, step: float) -> np.ndarray:
    quantized = np.round(values / step) * step
    return np.abs(values - quantized) <= 1e-8


def _update_flags(facts: _Facts, flags: np.ndarray) -> None:
    values, counts = np.unique(flags.astype(np.int64, copy=False), return_counts=True)
    for value, count in zip(values.tolist(), counts.tolist(), strict=True):
        if value in facts.flag_counts:
            facts.flag_counts[value] += int(count)
        elif len(facts.flag_counts) < 64:
            facts.flag_counts[value] = int(count)
        else:
            facts.flags_truncated = True


def _bin_index(stamps: np.ndarray, time_min: int, span: int) -> np.ndarray:
    if span <= 0:
        return np.zeros(stamps.shape, dtype=np.int64)
    idx = ((stamps - time_min) * 5) // span
    return np.clip(idx, 0, 4)


def measure_batch(
    facts: _Facts,
    hms: _Hms01,
    carry: _Carry,
    *,
    bid: np.ndarray,
    ask: np.ndarray,
    stamp: np.ndarray,
    cutoff: int,
    time_min: int,
    span: int,
    last: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    time_sec: np.ndarray | None = None,
    flags: np.ndarray | None = None,
) -> None:
    """Update data facts and H-MS-01. Does not store validation-window outcomes."""
    bid = _finite(bid)
    ask = _finite(ask)
    stamp = np.asarray(stamp, dtype=np.int64)
    n = int(bid.shape[0])
    if n == 0:
        return
    facts.rows += n
    facts.time_msc_min = int(stamp.min()) if facts.time_msc_min is None else min(facts.time_msc_min, int(stamp.min()))
    facts.time_msc_max = int(stamp.max()) if facts.time_msc_max is None else max(facts.time_msc_max, int(stamp.max()))
    facts.discovery_rows += int(np.count_nonzero(stamp < cutoff))
    facts.validation_rows += int(np.count_nonzero(stamp >= cutoff))
    facts.msc_mod_1000_zero += int(np.count_nonzero(stamp % 1000 == 0))
    facts.msc_mod_100_zero += int(np.count_nonzero(stamp % 100 == 0))
    facts.msc_mod_10_zero += int(np.count_nonzero(stamp % 10 == 0))
    facts.bid_checked += n
    facts.bid_on_0_01 += int(np.count_nonzero(_on_grid(bid, 0.01)))
    facts.bid_on_0_001 += int(np.count_nonzero(_on_grid(bid, 0.001)))
    if time_sec is not None:
        sec = np.asarray(time_sec, dtype=np.int64)
        facts.time_compared += n
        facts.time_equals_msc_div_1000 += int(np.count_nonzero(sec == stamp // 1000))
    if volume is not None:
        vol = _finite(volume)
        facts.volume_compared += n
        facts.volume_zero += int(np.count_nonzero(vol == 0))
        facts.volume_positive += int(np.count_nonzero(vol > 0))
    if last is not None:
        last_a = _finite(last)
        facts.last_compared += n
        facts.last_zero += int(np.count_nonzero(last_a == 0))
        facts.last_eq_bid += int(np.count_nonzero(last_a == bid))
        facts.last_eq_ask += int(np.count_nonzero(last_a == ask))
        inside = (last_a > bid) & (last_a < ask)
        facts.last_strictly_inside += int(np.count_nonzero(inside))
        outside = (last_a != 0) & (last_a != bid) & (last_a != ask) & ~inside
        facts.last_outside += int(np.count_nonzero(outside))
    if flags is not None:
        _update_flags(facts, flags)
    if span > 0:
        bins = _bin_index(stamp, time_min, span)
        spread = ask - bid
        valid = (bid > 0) & (ask > 0) & (spread >= 0)
        for bin_id in range(5):
            mask = bins == bin_id
            facts.bin_rows[bin_id] += int(np.count_nonzero(mask))
            use = mask & valid
            facts.bin_spread_n[bin_id] += int(np.count_nonzero(use))
            if use.any():
                facts.bin_spread_sum[bin_id] += float(spread[use].sum())

    prev_n = int(carry.stamp.shape[0])
    series_bid = np.concatenate((carry.bid, bid)) if prev_n else bid
    series_ask = np.concatenate((carry.ask, ask)) if prev_n else ask
    series_stamp = np.concatenate((carry.stamp, stamp)) if prev_n else stamp
    _quote_changes(facts, series_bid, series_ask, prev_n)
    rows_before_batch = facts.rows - n
    _hms01_events(
        hms,
        series_bid,
        series_ask,
        series_stamp,
        cutoff,
        new_start=prev_n,
        global_base=rows_before_batch - prev_n,
    )
    optional: dict[str, np.ndarray] = {}
    if last is not None:
        carry.has_last = True
        optional["last"] = _finite(last)
    if volume is not None:
        carry.has_volume = True
        optional["volume"] = _finite(volume)
    if time_sec is not None:
        carry.has_time_sec = True
        optional["time_sec"] = np.asarray(time_sec, dtype=np.int64)
    if flags is not None:
        carry.has_flags = True
        optional["flags"] = np.asarray(flags, dtype=np.int64)
    carry.append_tail(bid, ask, stamp, **optional)


def _quote_changes(facts: _Facts, bid: np.ndarray, ask: np.ndarray, prev_n: int) -> None:
    if bid.shape[0] < 2:
        return
    # The pair that ends at the first new row is new. Earlier pairs were counted.
    start = max(prev_n - 1, 0)
    left_bid = bid[start:-1]
    right_bid = bid[start + 1 :]
    left_ask = ask[start:-1]
    right_ask = ask[start + 1 :]
    bid_changed = right_bid != left_bid
    ask_changed = right_ask != left_ask
    facts.adjacent_pairs += int(bid_changed.shape[0])
    facts.both_changes += int(np.count_nonzero(bid_changed & ask_changed))
    facts.bid_only_changes += int(np.count_nonzero(bid_changed & ~ask_changed))
    facts.ask_only_changes += int(np.count_nonzero(~bid_changed & ask_changed))
    facts.neither_changes += int(np.count_nonzero(~bid_changed & ~ask_changed))
    delta = right_bid - left_bid
    positive = delta[delta > 1e-12]
    facts.positive_bid_changes += int(positive.shape[0])
    if positive.size:
        lo = float(positive.min())
        facts.min_positive_bid_change = lo if facts.min_positive_bid_change is None else min(facts.min_positive_bid_change, lo)
        facts.bid_change_eq_0_01 += int(np.count_nonzero(np.abs(positive - 0.01) <= 1e-8))


def _hms01_events(
    hms: _Hms01,
    bid: np.ndarray,
    ask: np.ndarray,
    stamp: np.ndarray,
    cutoff: int,
    new_start: int,
    global_base: int,
) -> None:
    n = int(bid.shape[0])
    if n < 3:
        return
    # Centers i where the triple (i-1, i, i+1) includes at least one new row.
    first_center = max(1, new_start - 1)
    last_center = n - 2
    if first_center > last_center:
        return
    idx = np.arange(first_center, last_center + 1)
    prev, cur, nxt = idx - 1, idx, idx + 1
    positive = (bid[prev] > 0) & (ask[prev] > 0) & (bid[cur] > 0) & (ask[cur] > 0) & (bid[nxt] > 0) & (ask[nxt] > 0)
    mid_prev = (bid[prev] + ask[prev]) / 2.0
    mid_cur = (bid[cur] + ask[cur]) / 2.0
    mid_nxt = (bid[nxt] + ask[nxt]) / 2.0
    spread_prev = ask[prev] - bid[prev]
    spread_cur = ask[cur] - bid[cur]
    move = mid_cur - mid_prev
    nxt_move = mid_nxt - mid_cur
    # Inverted quotes stay in the primary. Dropping them is a recorded sensitivity.
    event = positive & (np.abs(move) > spread_prev) & (move != 0)
    in_discovery = (stamp[prev] < cutoff) & (stamp[cur] < cutoff) & (stamp[nxt] < cutoff)
    hms.excluded_validation_touch += int(np.count_nonzero(event & ~in_discovery))
    use = event & in_discovery
    if not use.any():
        return
    sign_move = np.sign(move[use])
    sign_next = np.sign(nxt_move[use])
    reversal = sign_next == -sign_move
    continuation = sign_next == sign_move
    flat = sign_next == 0
    net_price = (-sign_move * nxt_move[use]) - spread_cur[use]
    mid = mid_cur[use]
    net_bps = np.where(mid > 0, net_price / mid * 10000.0, np.nan)
    hms.events += int(use.sum())
    hms.reversals += int(np.count_nonzero(reversal))
    hms.continuations += int(np.count_nonzero(continuation))
    hms.flat_next += int(np.count_nonzero(flat))
    hms.net_price_sum += float(np.nansum(net_price))
    hms.net_bps_sum += float(np.nansum(net_bps))
    hms.net_positive += int(np.count_nonzero(net_price > 0))
    inverted = (spread_prev[use] < 0) | (spread_cur[use] < 0) | ((ask[nxt] - bid[nxt])[use] < 0)
    hms.inverted_events += int(np.count_nonzero(inverted))
    if inverted.any():
        hms.inverted_net_bps_sum += float(np.nansum(net_bps[inverted]))
    gap_ok = (stamp[nxt][use] - stamp[cur][use]) <= GAP_SENSITIVITY_MS
    hms.gap_events += int(np.count_nonzero(gap_ok))
    hms.gap_reversals += int(np.count_nonzero(reversal & gap_ok))
    if gap_ok.any():
        hms.gap_net_bps_sum += float(np.nansum(net_bps[gap_ok]))
    delay_center = idx[use]
    delay_ok = delay_center + 2 < n
    if delay_ok.any():
        centers = delay_center[delay_ok]
        t2 = centers + 2
        t2_bid = bid[t2]
        t2_ask = ask[t2]
        t2_valid = (t2_bid > 0) & (t2_ask > 0) & (stamp[t2] < cutoff) & (stamp[centers] < cutoff)
        if t2_valid.any():
            c = centers[t2_valid]
            mid_t = (bid[c] + ask[c]) / 2.0
            mid_t2 = (bid[c + 2] + ask[c + 2]) / 2.0
            sign_t = np.sign(mid_t - (bid[c - 1] + ask[c - 1]) / 2.0)
            delay_net = (-sign_t * (mid_t2 - mid_t)) - (ask[c] - bid[c])
            delay_bps = np.where(mid_t > 0, delay_net / mid_t * 10000.0, np.nan)
            hms.delay_events += int(t2_valid.sum())
            hms.delay_net_bps_sum += float(np.nansum(delay_bps))
    gidx = global_base + idx
    selected = (gidx[use] % NON_OVERLAP_CENTER_STEP) == 0
    if selected.any():
        hms.nonoverlap_events += int(np.count_nonzero(selected))
        hms.nonoverlap_reversals += int(np.count_nonzero(reversal & selected))
        hms.nonoverlap_continuations += int(np.count_nonzero(continuation & selected))
        hms.nonoverlap_net_bps_sum += float(np.nansum(net_bps[selected]))
        hms.nonoverlap_net_positive += int(np.count_nonzero(net_price[selected] > 0))
        chosen = np.asarray(net_bps[selected], dtype=np.float64)
        finite = chosen[np.isfinite(chosen)]
        if finite.size:
            hms.nonoverlap_sample.append(finite)
        inv_sel = inverted & selected
        hms.nonoverlap_inverted_events += int(np.count_nonzero(inv_sel))
        if inv_sel.any():
            hms.nonoverlap_inverted_net_bps_sum += float(np.nansum(net_bps[inv_sel]))
        gap_sel = selected & gap_ok
        hms.nonoverlap_gap_events += int(np.count_nonzero(gap_sel))
        if gap_sel.any():
            hms.nonoverlap_gap_net_bps_sum += float(np.nansum(net_bps[gap_sel]))


def hms01_verdict(stats: dict[str, Any]) -> dict[str, Any]:
    """Apply the preregistered falsification rule. Does not promote a strategy."""
    freq = stats.get("nonoverlap_reversal_frequency")
    mean_net = stats.get("nonoverlap_mean_net_bps")
    gap_mean = stats.get("gap_mean_net_bps")
    n = stats.get("nonoverlap_events") or 0
    if n < 100 or freq is None or mean_net is None:
        return {"result": "INCONCLUSIVE", "reason": "non-overlapping discovery sample is below 100 events or undefined"}
    ci = stats.get("nonoverlap_mean_net_bps_bootstrap") or {}
    lo = ci.get("lo")
    hi = ci.get("hi")
    residual_crosses_zero = lo is None or hi is None or lo <= 0 <= hi
    gap_flips = gap_mean is not None and ((mean_net > 0 and gap_mean <= 0) or (mean_net < 0 and gap_mean >= 0))
    inverted_n = stats.get("inverted_events") or 0
    inverted_mean = stats.get("inverted_mean_net_bps")
    clean_mean = mean_net
    if inverted_n and inverted_n < n and inverted_mean is not None:
        # Primary includes inverted rows. Reconstruct the excluded-inverted mean.
        clean_sum = mean_net * n - inverted_mean * inverted_n
        clean_mean = clean_sum / (n - inverted_n)
    inverted_flips = inverted_n > 0 and clean_mean is not None and (
        (mean_net > 0 and clean_mean <= 0) or (mean_net < 0 and clean_mean >= 0)
    )
    if freq <= 0.5 or mean_net <= 0 or residual_crosses_zero or gap_flips or inverted_flips:
        reason = []
        if freq <= 0.5:
            reason.append("non-overlapping reversal frequency is not above 0.5")
        if mean_net <= 0:
            reason.append("mean residual after one spread is not positive")
        if residual_crosses_zero:
            reason.append("bootstrap interval for the residual includes zero")
        if gap_flips:
            reason.append("excluding gaps above 1s flips the residual sign")
        if inverted_flips:
            reason.append("excluding inverted quotes flips the residual sign")
        return {"result": "REJECTED", "reason": "; ".join(reason), "promoted": False}
    return {
        "result": "DISCOVERY_SURVIVED",
        "reason": "non-overlapping reversal frequency and residual survived the pre-declared checks",
        "promoted": False,
        "not_validated": True,
    }


def hms02_verdict(stats: dict[str, Any]) -> dict[str, Any]:
    diff = stats.get("nonoverlap_mean_scaled_difference_wide_minus_narrow")
    n_wide = stats.get("nonoverlap_wide_n") or 0
    n_narrow = stats.get("nonoverlap_narrow_n") or 0
    if diff is None or n_wide < 100 or n_narrow < 100:
        return {"result": "INCONCLUSIVE", "reason": "a discovery half has fewer than 100 non-overlapping observations"}
    if diff <= 0:
        return {
            "result": "REJECTED",
            "reason": "wide-spread half does not have a larger spread-scaled next absolute move",
            "promoted": False,
        }
    return {
        "result": "DISCOVERY_SURVIVED",
        "reason": "pre-declared median split shows a positive wide-minus-narrow difference on non-overlapping quotes",
        "promoted": False,
        "not_validated": True,
        "not_a_strategy": True,
    }


def _column(batch: Any, name: str) -> np.ndarray | None:
    if name not in batch.schema.names:
        return None
    return batch.column(name).to_numpy(zero_copy_only=False)


def scan_dataset(dataset_dir: Path) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    parts = manifest.get("parts") or []
    stamps_min: int | None = None
    stamps_max: int | None = None
    for part in parts:
        print(f"stamp-pass {part['part']}", flush=True)
        path = dataset_dir / "parts" / part["part"]
        if not path.exists():
            raise FileNotFoundError(f"ledgered part missing: {part['part']}")
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc"]):
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            if stamp.size == 0:
                continue
            lo = int(stamp.min())
            hi = int(stamp.max())
            stamps_min = lo if stamps_min is None else min(stamps_min, lo)
            stamps_max = hi if stamps_max is None else max(stamps_max, hi)
    if stamps_min is None or stamps_max is None:
        raise ValueError("no time_msc values")
    cutoff = discovery_cutoff(stamps_min, stamps_max)
    span = stamps_max - stamps_min
    facts = _Facts()
    hms = _Hms01()
    carry = _Carry()
    discovery_spreads: list[np.ndarray] = []
    stored = 0
    store_truncated = False
    for part in parts:
        print(f"discovery-pass {part['part']}", flush=True)
        path = dataset_dir / "parts" / part["part"]
        parquet = pq.ParquetFile(path)
        columns = ["time_msc", "bid", "ask", "last", "volume", "volume_real", "time", "flags"]
        present = [name for name in columns if name in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(batch_size=500_000, columns=present):
            bid = _column(batch, "bid")
            ask = _column(batch, "ask")
            stamp = _column(batch, "time_msc")
            if bid is None or ask is None or stamp is None:
                raise ValueError("bid, ask, and time_msc are required")
            volume = _column(batch, "volume_real")
            if volume is None:
                volume = _column(batch, "volume")
            measure_batch(
                facts,
                hms,
                carry,
                bid=bid,
                ask=ask,
                stamp=stamp,
                cutoff=cutoff,
                time_min=stamps_min,
                span=span,
                last=_column(batch, "last"),
                volume=volume,
                time_sec=_column(batch, "time"),
                flags=_column(batch, "flags"),
            )
            spread = _finite(ask) - _finite(bid)
            keep = (stamp < cutoff) & (_finite(bid) > 0) & (_finite(ask) > 0) & (spread > 0)
            if keep.any() and not store_truncated:
                chunk = spread[keep]
                room = SPREAD_STORE_CAP - stored
                if chunk.size > room:
                    chunk = chunk[:room]
                    store_truncated = True
                discovery_spreads.append(np.asarray(chunk, dtype=np.float64))
                stored += int(chunk.size)
    spreads = np.concatenate(discovery_spreads) if discovery_spreads else np.empty(0, dtype=np.float64)
    median_n = int(spreads.size)
    median = float(np.median(spreads)) if median_n else None
    del discovery_spreads, spreads
    hms02 = _hms02(dataset_dir, parts, cutoff, median)
    hms02["median_store_truncated"] = store_truncated
    report = _report(manifest, facts, hms, hms02, cutoff, stamps_min, stamps_max, median, median_n, store_truncated)
    return report


def _hms02(dataset_dir: Path, parts: list[dict[str, Any]], cutoff: int, median: float | None) -> dict[str, Any]:
    if median is None:
        return {"status": "UNAVAILABLE", "reason": "no positive discovery-window spreads"}
    wide_sum = narrow_sum = 0.0
    wide_n = narrow_n = tie_n = 0
    non_wide_sum = non_narrow_sum = 0.0
    non_wide_n = non_narrow_n = 0
    absolute_index = 0
    carry_bid = np.empty(0, dtype=np.float64)
    carry_ask = np.empty(0, dtype=np.float64)
    carry_stamp = np.empty(0, dtype=np.int64)
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc", "bid", "ask"]):
            bid = _finite(batch.column("bid").to_numpy(zero_copy_only=False))
            ask = _finite(batch.column("ask").to_numpy(zero_copy_only=False))
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            prev_n = int(carry_stamp.shape[0])
            series_bid = np.concatenate((carry_bid, bid)) if prev_n else bid
            series_ask = np.concatenate((carry_ask, ask)) if prev_n else ask
            series_stamp = np.concatenate((carry_stamp, stamp)) if prev_n else stamp
            n = int(series_bid.shape[0])
            if n >= 2:
                first = max(prev_n - 1, 0)
                idx = np.arange(first, n - 1)
                cur, nxt = idx, idx + 1
                spread = series_ask[cur] - series_bid[cur]
                valid = (
                    (series_bid[cur] > 0)
                    & (series_ask[cur] > 0)
                    & (spread > 0)
                    & (series_bid[nxt] > 0)
                    & (series_ask[nxt] > 0)
                    & (series_ask[nxt] >= series_bid[nxt])
                    & (series_stamp[cur] < cutoff)
                    & (series_stamp[nxt] < cutoff)
                )
                if valid.any():
                    mid = (series_bid[cur] + series_ask[cur]) / 2.0
                    next_mid = (series_bid[nxt] + series_ask[nxt]) / 2.0
                    scaled = np.abs(next_mid - mid) / spread
                    wide = valid & (spread > median)
                    narrow = valid & (spread < median)
                    tie = valid & (spread == median)
                    wide_n += int(np.count_nonzero(wide))
                    narrow_n += int(np.count_nonzero(narrow))
                    tie_n += int(np.count_nonzero(tie))
                    if wide.any():
                        wide_sum += float(scaled[wide].sum())
                    if narrow.any():
                        narrow_sum += float(scaled[narrow].sum())
                    global_idx = absolute_index - prev_n + idx
                    selected = valid & ((global_idx % NON_OVERLAP_CENTER_STEP) == 0)
                    sel_wide = selected & (spread > median)
                    sel_narrow = selected & (spread < median)
                    non_wide_n += int(np.count_nonzero(sel_wide))
                    non_narrow_n += int(np.count_nonzero(sel_narrow))
                    if sel_wide.any():
                        non_wide_sum += float(scaled[sel_wide].sum())
                    if sel_narrow.any():
                        non_narrow_sum += float(scaled[sel_narrow].sum())
            absolute_index += int(bid.shape[0])
            carry_bid = np.concatenate((carry_bid, bid))[-2:]
            carry_ask = np.concatenate((carry_ask, ask))[-2:]
            carry_stamp = np.concatenate((carry_stamp, stamp))[-2:]
    diff = None
    if wide_n and narrow_n:
        diff = (wide_sum / wide_n) - (narrow_sum / narrow_n)
    non_diff = None
    if non_wide_n and non_narrow_n:
        non_diff = (non_wide_sum / non_wide_n) - (non_narrow_sum / non_narrow_n)
    return {
        "status": "MEASURED",
        "median_spread_price": median,
        "tie_rule": "spread equal to the median is in neither half",
        "wide_n": wide_n,
        "narrow_n": narrow_n,
        "tie_n": tie_n,
        "wide_mean_scaled": (wide_sum / wide_n) if wide_n else None,
        "narrow_mean_scaled": (narrow_sum / narrow_n) if narrow_n else None,
        "mean_scaled_difference_wide_minus_narrow": diff,
        "dependent_sample_status": "NOT INFERENTIAL",
        "nonoverlap_wide_n": non_wide_n,
        "nonoverlap_narrow_n": non_narrow_n,
        "nonoverlap_wide_mean_scaled": (non_wide_sum / non_wide_n) if non_wide_n else None,
        "nonoverlap_narrow_mean_scaled": (non_narrow_sum / non_narrow_n) if non_narrow_n else None,
        "nonoverlap_mean_scaled_difference_wide_minus_narrow": non_diff,
    }


def _report(
    manifest: dict[str, Any],
    facts: _Facts,
    hms: _Hms01,
    hms02: dict[str, Any],
    cutoff: int,
    time_min: int,
    time_max: int,
    median: float | None,
    median_n: int,
    store_truncated: bool,
) -> dict[str, Any]:
    hms_stats = hms.as_dict()
    hms01 = hms01_verdict(hms_stats)
    hms02_result = hms02_verdict(hms02)
    clock_confirmed = manifest.get("timestamp_interpretation_confirmed") is True
    return {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "release": "dataset-xauusd-730d-20260919",
            "asset": "XAUUSD_730d_20260919T114013Z.zip",
            "expected_zip_sha256": "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723",
            "manifest_dataset_sha256": manifest.get("dataset_sha256"),
            "manifest_symbol": manifest.get("symbol"),
            "manifest_timestamp_basis": manifest.get("timestamp_basis"),
            "timestamp_interpretation_confirmed": clock_confirmed,
        },
        "code_identity": {
            "git_sha": os.environ.get("GITHUB_SHA", "UNAVAILABLE"),
            "execution_host": os.environ.get("QTS_DISCOVERY_EXECUTION_HOST", "UNAVAILABLE"),
            "module": "qts.research.xauusd_tick_discovery",
        },
        "separation": {
            "data_facts": "measured counts and ranges; not predictions",
            "research_assumptions": [
                "next quote means the next row in ledger order, not the next distinct timestamp",
                "prevailing spread is the spread of the quote before the move",
                "one spread cost is the spread at the event quote, subtracted in price",
                "discovery is time_msc < min + (span * 60) // 100",
                "a triple touching the validation span is excluded, not repaired",
                "iid binomial p-values on adjacent events are not inferential",
            ],
            "derived_features": ["mid", "spread", "next mid change", "spread-scaled absolute next mid change"],
            "hypotheses": ["H-MS-01", "H-MS-02"],
            "blocked": [] if clock_confirmed else ["H-TOD-01", "hour-of-day", "session", "day-of-week"],
        },
        "window": {
            "time_msc_min": time_min,
            "time_msc_max": time_max,
            "cutoff_time_msc": cutoff,
            "rule": "discovery: time_msc < cutoff; validation span is not aggregated by the hypothesis tests",
            "discovery_rows": facts.discovery_rows,
            "validation_rows_counted_as_data_fact_only": facts.validation_rows,
        },
        "data_facts": {
            "rows": facts.rows,
            "time_msc_min": facts.time_msc_min,
            "time_msc_max": facts.time_msc_max,
            "time_equals_time_msc_div_1000": facts.time_equals_msc_div_1000,
            "time_compared": facts.time_compared,
            "time_msc_second_aligned": facts.msc_mod_1000_zero,
            "time_msc_mod_100_zero": facts.msc_mod_100_zero,
            "time_msc_mod_10_zero": facts.msc_mod_10_zero,
            "bid_on_0_01_grid": facts.bid_on_0_01,
            "bid_on_0_001_grid": facts.bid_on_0_001,
            "bid_checked": facts.bid_checked,
            "volume_zero": facts.volume_zero,
            "volume_positive": facts.volume_positive,
            "volume_compared": facts.volume_compared,
            "last_zero": facts.last_zero,
            "last_eq_bid": facts.last_eq_bid,
            "last_eq_ask": facts.last_eq_ask,
            "last_strictly_inside_spread": facts.last_strictly_inside,
            "last_outside_spread": facts.last_outside,
            "last_compared": facts.last_compared,
            "adjacent_quote_pairs": facts.adjacent_pairs,
            "bid_only_changes": facts.bid_only_changes,
            "ask_only_changes": facts.ask_only_changes,
            "both_bid_and_ask_changed": facts.both_changes,
            "neither_bid_nor_ask_changed": facts.neither_changes,
            "min_positive_bid_change": facts.min_positive_bid_change,
            "positive_bid_changes": facts.positive_bid_changes,
            "positive_bid_changes_equal_0_01": facts.bid_change_eq_0_01,
            "flag_counts": {str(k): v for k, v in sorted(facts.flag_counts.items())},
            "flag_counts_truncated": facts.flags_truncated,
            "equal_time_span_bins": [
                {
                    "bin": i,
                    "rows": facts.bin_rows[i],
                    "mean_spread_price": (facts.bin_spread_sum[i] / facts.bin_spread_n[i]) if facts.bin_spread_n[i] else None,
                    "uses_validation_span": i >= 3,
                    "role": "DATA FACT only; not a hypothesis test",
                }
                for i in range(5)
            ],
            "timezone": "UNAVAILABLE" if not clock_confirmed else "CONFIRMED",
            "session_calendar": "UNAVAILABLE" if not clock_confirmed else "CONFIRMED",
            "repairs_applied": [],
        },
        "hypotheses": {
            "H-MS-01": {
                "id": "H-MS-01",
                "operational_definition": (
                    "event when abs(mid_t - mid_t-1) > spread_t-1; reversal when the next row's mid change "
                    "has the opposite sign; net = -sign(move) * next_mid_change - spread_t"
                ),
                "population": "discovery window only; triples touching the validation span excluded",
                "statistics": hms_stats,
                "verdict": hms01,
            },
            "H-MS-02": {
                "id": "H-MS-02",
                "operational_definition": (
                    "median of positive discovery-window spreads; compare mean abs(next mid change)/spread "
                    "above versus below that median; ties excluded"
                ),
                "median_n": median_n,
                "median_store_truncated": store_truncated,
                "statistics": hms02,
                "verdict": hms02_result,
            },
            "H-TOD-01": {
                "id": "H-TOD-01",
                "result": "NOT TESTED",
                "reason": "BLOCKED — timestamp basis is not confirmed" if not clock_confirmed else "NOT RUN",
            },
        },
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "decision": "INCONCLUSIVE",
        "decision_reason": (
            "Hypothesis-level results are not a validated or executable edge. "
            "Clock-dependent families were not tested. No strategy was constructed."
        ),
        "safety": {
            "confirm_live": False,
            "orders_submitted": 0,
            "DEMO_EXECUTION": "DISABLED",
        },
    }


def render_research_state(report: dict[str, Any]) -> str:
    """Render the measured report. This does not add a result that was not measured."""
    facts = report.get("data_facts") or {}
    window = report.get("window") or {}
    separation = report.get("separation") or {}
    hypotheses = report.get("hypotheses") or {}
    h1 = hypotheses.get("H-MS-01") or {}
    h2 = hypotheses.get("H-MS-02") or {}
    h1s = h1.get("statistics") or {}
    h2s = h2.get("statistics") or {}
    lines = [
        "# XAUUSD research state",
        "",
        f"Decision: {report.get('decision')}",
        "",
        "No strategy was promoted. A hypothesis result is not a validation pass and is not Demo-ready.",
        "",
        "## DATA FACTS",
        "",
        f"- Rows measured: {facts.get('rows')}",
        f"- Raw time_msc range: {facts.get('time_msc_min')} .. {facts.get('time_msc_max')}",
        f"- `time` equal to `time_msc // 1000`: {facts.get('time_equals_time_msc_div_1000')} of {facts.get('time_compared')}",
        f"- `time_msc` divisible by 1000: {facts.get('time_msc_second_aligned')}",
        f"- Bid on a 0.01 grid: {facts.get('bid_on_0_01_grid')} of {facts.get('bid_checked')}",
        f"- Bid on a 0.001 grid: {facts.get('bid_on_0_001_grid')} of {facts.get('bid_checked')}",
        f"- Volume zero / positive: {facts.get('volume_zero')} / {facts.get('volume_positive')}",
        f"- Last zero / equal bid / equal ask / inside spread / outside spread: "
        f"{facts.get('last_zero')} / {facts.get('last_eq_bid')} / {facts.get('last_eq_ask')} / "
        f"{facts.get('last_strictly_inside_spread')} / {facts.get('last_outside_spread')}",
        f"- Adjacent quote changes, bid only / ask only / both / neither: "
        f"{facts.get('bid_only_changes')} / {facts.get('ask_only_changes')} / "
        f"{facts.get('both_bid_and_ask_changed')} / {facts.get('neither_bid_nor_ask_changed')}",
        f"- Minimum positive adjacent bid change: {facts.get('min_positive_bid_change')}",
        f"- Timezone: {facts.get('timezone')}",
        f"- Session calendar: {facts.get('session_calendar')}",
        "- Equal raw-span bins are data facts. Bins 3 and 4 overlap the locked span and were not used to fit a hypothesis.",
        "- Repairs applied: none",
    ]
    for item in facts.get("equal_time_span_bins") or []:
        lines.append(
            f"- Bin {item.get('bin')}: rows {item.get('rows')}, mean spread {item.get('mean_spread_price')}, "
            f"locked-span overlap {item.get('uses_validation_span')}"
        )
    lines.extend(["", "## RESEARCH ASSUMPTIONS", ""])
    for item in separation.get("research_assumptions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## DERIVED FEATURES", ""])
    for item in separation.get("derived_features") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## HYPOTHESES",
            "",
            f"- Discovery cutoff time_msc: {window.get('cutoff_time_msc')}",
            f"- Discovery rows: {window.get('discovery_rows')}",
            f"- Locked-span rows, counted only as a data fact: {window.get('validation_rows_counted_as_data_fact_only')}",
            f"- H-MS-01 result: {(h1.get('verdict') or {}).get('result')} — {(h1.get('verdict') or {}).get('reason')}",
            f"- H-MS-01 non-overlapping reversal frequency: {h1s.get('nonoverlap_reversal_frequency')}",
            f"- H-MS-01 non-overlapping mean residual bps: {h1s.get('nonoverlap_mean_net_bps')}",
            f"- H-MS-02 result: {(h2.get('verdict') or {}).get('result')} — {(h2.get('verdict') or {}).get('reason')}",
            f"- H-MS-02 median spread: {h2s.get('median_spread_price')}",
            f"- H-MS-02 non-overlapping wide-minus-narrow difference: {h2s.get('nonoverlap_mean_scaled_difference_wide_minus_narrow')}",
            f"- H-TOD-01: {(hypotheses.get('H-TOD-01') or {}).get('result')} — {(hypotheses.get('H-TOD-01') or {}).get('reason')}",
            "",
            "## BLOCKED",
            "",
        ]
    )
    for item in separation.get("blocked") or ["none"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## NOT TESTED",
            "",
            "- Regimes, event/state sequences, and cross-feature conditionals beyond H-MS-01 and H-MS-02.",
            "- No machine-learning model was fit.",
            "",
            f"Edge claim: {report.get('edge_claim')}",
            f"Orders submitted: {(report.get('safety') or {}).get('orders_submitted')}",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
