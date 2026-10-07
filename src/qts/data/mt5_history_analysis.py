"""Deferred MT5 raw-tick dataset analysis — runs AFTER acquisition, without MT5.

Separation of concerns
----------------------
This module never touches MT5: no ``MetaTrader5`` import, no broker handle, no
network.  It reads the immutable local dataset produced by
:mod:`qts.data.mt5_history_acquisition` (chunk Parquet parts + fsync'd
manifest) and performs the research-quality audit there.  A structural test
imports this module with the ``MetaTrader5`` import blocked and asserts the
same integrity verdict as with acquisition, proving the analysis is runnable
offline with the broker absent.

Design goals
------------
* **Streaming, memory-bounded** — parts are processed one at a time in ledger
  order; cross-part state is a handful of scalars plus at most one deferred
  same-millisecond group.  The only whole-dataset array retained is the
  float64 spread series (8 B/row) so spread quantiles remain exact; this is
  documented in the report.  Nothing constructs per-row JSON or per-row
  hashes.
* **No transformation for the audit** — all counters run on the exact stored
  values.  Provisional UTC interpretations (for coverage/weekend diagnostics)
  are always labelled ``*_if_utc`` and flagged ``provisional`` because the raw
  timestamp basis is unverified.
* **Duplicate semantics preserved** — equal ``time_msc`` rows, same-millisecond
  distinct payloads, and exact full-row repeats are *measured and reported*,
  never collapsed (matching the established probe vocabulary).

The report deliberately contains no raw rows: bounded top-``k`` lists carry
timestamps and derived deltas only, never quote payloads.
"""

from __future__ import annotations

import hashlib
import json
import math
import time as _time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import (
    ACQUISITION_SCHEMA,
    FINAL_STATUSES,
    MANIFEST_FILENAME,
    dataset_digest,
    sha256_file,
)

ANALYSIS_SCHEMA = "qts.mt5_tick_dataset_analysis.v1"

DEFAULT_GAP_THRESHOLDS_S = (1, 5, 30, 60, 300, 3600, 21600, 86400)
DEFAULT_JUMP_THRESHOLDS_BPS = (10, 25, 50, 100, 500)
DEFAULT_TOP_K = 25
QUOTE_STATE_FIELDS = ("bid", "ask", "last", "volume", "volume_real", "flags")

REQUIRED_MANIFEST_KEYS = (
    "schema",
    "status",
    "symbol",
    "environment",
    "observation_mode",
    "request",
    "software",
    "returned_fields",
    "returned_dtype_map",
    "timestamp_basis",
    "timestamp_interpretation_confirmed",
    "acquisition_started_at_utc",
    "acquisition_ended_at_utc",
    "row_count",
    "parts",
    "failed_chunks",
    "dataset_sha256",
    "dataset_files_size_bytes",
    "read_only",
    "orders_submitted",
    "order_send_called",
)

SPREAD_BPS_NOTE = (
    "The float64 spread_bps series (8 bytes/row) is retained during analysis so "
    "min/mean/median/p95/max are exact; no other whole-dataset representation is built."
)

_JUMPS_NOTE = (
    "Price jumps are consecutive-row mid-price changes in bps (mid=(bid+ask)/2 where both quotes are "
    "positive), including rows with equal timestamps; they are diagnostics, not event classifications. "
    "No jump threshold was declared ex ante, so jump counts are reported against recorded diagnostic "
    "buckets only."
)

_GAPS_NOTE = (
    "Gaps are consecutive-row time_msc deltas. No fixed tick schedule exists for ticks, so a gap is a "
    "spacing observation, not evidence of missing data; weekend/holiday closure overlap is reported "
    "under the provisional UTC interpretation only and is NOT a classification."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(ms_epoch: Any) -> str | None:
    """Provisional UTC ISO rendering of an epoch-millisecond value (diagnostic)."""
    try:
        return datetime.fromtimestamp(float(ms_epoch) / 1000.0, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def _columns_of(table: Any) -> dict[str, np.ndarray]:
    return {name: np.asarray(table.column(name).to_numpy(zero_copy_only=False)) for name in table.column_names}


def _structured_view(columns: Mapping[str, np.ndarray], n: int) -> np.ndarray:
    dtype = [(name, np.asarray(arr).dtype) for name, arr in columns.items()]
    view = np.empty(n, dtype=dtype)
    for name, arr in columns.items():
        view[name] = arr
    return view


# ---------------------------------------------------------------------------
# Streaming accumulator
# ---------------------------------------------------------------------------


class _Accumulator:
    """Per-part streaming accumulation with exact cross-part boundary handling."""

    def __init__(
        self,
        fields: list[str],
        *,
        gap_thresholds_s: tuple[int, ...],
        jump_thresholds_bps: tuple[int, ...],
        top_k: int,
    ) -> None:
        self.fields = list(fields)
        self.gap_thresholds_ms = np.asarray([t * 1000 for t in gap_thresholds_s], dtype=np.int64)
        self.jump_thresholds_bps = tuple(float(t) for t in jump_thresholds_bps)
        self.top_k = int(top_k)

        self.total_rows = 0
        self.time_min: int | None = None
        self.time_max: int | None = None
        self.time_msc_min: int | None = None
        self.time_msc_max: int | None = None
        self.non_monotonic = 0
        self.max_backward_step_ms = 0

        # grouping / duplicates
        self.total_runs = 0
        self.same_time_msc_groups = 0
        self.same_time_msc_excess_rows = 0
        self.same_time_msc_distinct_payload_rows = 0
        self.identical_full_row_excess = 0
        self._carry_rows: np.ndarray | None = None  # deferred trailing same-ms group

        # consecutive quote states
        self.consecutive_identical_quote_state = 0
        self.quote_state_fields = [f for f in QUOTE_STATE_FIELDS if f in self.fields]

        # validity / spread
        self.invalid_bid = 0
        self.invalid_ask = 0
        self.ask_below_bid = 0
        self.zero_spread = 0
        self.negative_spread = 0
        self._spread_chunks: list[np.ndarray] = []

        # gaps
        self.gap_counts = {int(t): 0 for t in gap_thresholds_s}
        self._gap_records: list[tuple[int, int, int]] = []  # (gap_ms, start_msc, end_msc)

        # jumps (streaming Welford + thresholds + top-k)
        self.jump_threshold_counts = {int(t): 0 for t in jump_thresholds_bps}
        self.jump_count = 0
        self.jump_mean = 0.0
        self.jump_m2 = 0.0
        self.jump_min: float | None = None
        self.jump_max: float | None = None
        self._jump_records: list[tuple[float, int, float]] = []  # (abs_bps, msc_of_target, delta_bps)

        # timestamp-basis forensics
        self.time_equals_msc_div1000 = 0
        self.msc_second_aligned = 0

        # provisional coverage
        self._rows_per_day: dict[int, int] = {}

        self._prev_stamp: int | None = None
        self._prev_quote: dict[str, Any] | None = None
        self._prev_mid: float | None = None

    # -- main per-part update -------------------------------------------------

    def update(self, columns: Mapping[str, np.ndarray]) -> None:
        n = int(len(columns[self.fields[0]])) if self.fields else 0
        if n == 0:
            return
        self.total_rows += n
        stamps = np.asarray(columns["time_msc"], dtype=np.int64) if "time_msc" in columns else None
        secs = np.asarray(columns["time"], dtype=np.int64) if "time" in columns else None
        if secs is not None:
            self.time_min = int(secs.min()) if self.time_min is None else int(min(self.time_min, secs.min()))
            self.time_max = int(secs.max()) if self.time_max is None else int(max(self.time_max, secs.max()))
        if stamps is not None:
            self.time_msc_min = int(stamps.min()) if self.time_msc_min is None else int(min(self.time_msc_min, stamps.min()))
            self.time_msc_max = int(stamps.max()) if self.time_msc_max is None else int(max(self.time_msc_max, stamps.max()))
            self._basis_forensics(stamps, secs)
            self._timestamp_ordering(stamps)
            self._groups(stamps, columns)
            self._coverage(stamps)
        self._quote_states(columns)
        self._spread(columns)
        self._jumps(columns)

    # -- sections --------------------------------------------------------------

    def _basis_forensics(self, stamps: np.ndarray, secs: np.ndarray | None) -> None:
        self.msc_second_aligned += int(np.count_nonzero(stamps % 1000 == 0))
        if secs is not None:
            self.time_equals_msc_div1000 += int(np.count_nonzero(stamps // 1000 == secs))

    def _timestamp_ordering(self, stamps: np.ndarray) -> None:
        n = int(stamps.shape[0])
        if n == 0:
            return
        if self._prev_stamp is not None:
            # deltas[i] = step into part row i (row 0 steps from the previous part's tail)
            deltas = np.diff(np.concatenate(([np.int64(self._prev_stamp)], stamps)))
            start_stamps = np.concatenate(([np.int64(self._prev_stamp)], stamps))[:-1]
            end_stamps = stamps
        elif n >= 2:
            # deltas[i] = step into part row i+1
            deltas = np.diff(stamps)
            start_stamps = stamps[:-1]
            end_stamps = stamps[1:]
        else:
            self._prev_stamp = int(stamps[-1])
            return
        backward = deltas < 0
        self.non_monotonic += int(np.count_nonzero(backward))
        if backward.any():
            self.max_backward_step_ms = int(max(self.max_backward_step_ms, -int(deltas[backward].min())))
        above = self.gap_thresholds_ms[None, :] <= deltas[:, None]
        counts = above.sum(axis=0)
        for threshold, count in zip(self.gap_thresholds_ms.tolist(), counts.tolist(), strict=True):
            self.gap_counts[int(threshold // 1000)] += int(count)
        # top-k gap candidates from this part
        if deltas.size:
            k = min(self.top_k, deltas.size)
            idx = np.argpartition(-deltas, k - 1)[:k]
            for i in idx.tolist():
                if deltas[i] <= 0:
                    continue
                self._gap_records.append((int(deltas[i]), int(start_stamps[i]), int(end_stamps[i])))
        self._prev_stamp = int(stamps[-1])

    def _credit_group(self, view: np.ndarray) -> None:
        """Accumulate one same-time_msc group (exact, in-memory slice)."""
        size = int(view.shape[0])
        self.total_runs += 1
        self.same_time_msc_excess_rows += size - 1
        if size < 2:
            return
        self.same_time_msc_groups += 1
        _, counts = np.unique(view, return_counts=True)
        # exact full-row repeats: every row beyond the first occurrence of its payload
        self.identical_full_row_excess += size - int(counts.size)
        first = view[0:1]
        equal_to_first = np.ones(size, dtype=bool)
        for name in view.dtype.names or ():
            equal_to_first &= view[name] == first[name][0]
        equal_to_first[0] = False  # the reference row itself is not an "extra" row
        self.same_time_msc_distinct_payload_rows += int(size - 1 - int(np.count_nonzero(equal_to_first)))

    def _flush_carry(self) -> None:
        if self._carry_rows is not None:
            self._credit_group(self._carry_rows)
            self._carry_rows = None

    def _groups(self, stamps: np.ndarray, columns: Mapping[str, np.ndarray]) -> None:
        """Same-time_msc run accounting.

        Vectorized fast path: run boundaries come from one ``np.diff``; only
        multi-row runs (rare timestamp collisions) are materialized, so a
        millions-row part costs a handful of tiny ``np.unique`` calls rather
        than a Python loop over its rows.
        """
        n = int(stamps.shape[0])
        if n == 0:
            return
        starts = np.r_[0, np.flatnonzero(stamps[1:] != stamps[:-1]) + 1]
        ends = np.r_[starts[1:], n]
        sizes = ends - starts
        n_runs = int(starts.shape[0])
        trailing = n_runs - 1
        multi = np.flatnonzero(sizes >= 2)

        view: np.ndarray | None = None

        def slice_view(start: int, end: int) -> np.ndarray:
            nonlocal view
            if view is None:
                view = _structured_view(columns, n)
            return view[start:end]

        first_merged = False
        if self._carry_rows is not None:
            carry, self._carry_rows = self._carry_rows, None
            if int(carry["time_msc"][0]) == int(stamps[starts[0]]):
                if n_runs == 1:
                    # whole part continues the deferred group; keep deferring
                    self._carry_rows = np.concatenate([carry, slice_view(int(starts[0]), int(ends[0]))])
                    return
                merged = np.concatenate([carry, slice_view(int(starts[0]), int(ends[0]))])
                self._credit_group(merged)
                first_merged = True
            else:
                self._credit_group(carry)

        closed_multi = multi if not first_merged else multi[multi > 0]
        credited = 0
        for i in closed_multi.tolist():
            if i == 0 and first_merged:
                continue
            if i >= trailing:
                continue  # trailing run is deferred below
            self._credit_group(slice_view(int(starts[i]), int(ends[i])))
            credited += 1
        # every run is counted exactly once: multi groups inside _credit_group,
        # the merged first run above, the carry flush above, the rest here.
        closed_runs = trailing  # runs [0, trailing) are closed by a following stamp
        singleton_closed = closed_runs - credited - (1 if first_merged else 0)
        self.total_runs += singleton_closed
        # the trailing run is deferred: it may continue in the next part
        self._carry_rows = slice_view(int(starts[trailing]), int(ends[trailing]))

    def _quote_states(self, columns: Mapping[str, np.ndarray]) -> None:
        if not self.quote_state_fields:
            return
        n = int(len(columns[self.fields[0]]))
        equal = np.ones(n, dtype=bool)
        for name in self.quote_state_fields:
            arr = np.asarray(columns[name])
            if self._prev_quote is not None:
                prev_equal_first = arr[0] == np.asarray(self._prev_quote[name])
                rest = arr[1:] == arr[:-1]
                field_equal = np.concatenate(([bool(prev_equal_first)], rest))
            else:
                field_equal = np.concatenate(([False], arr[1:] == arr[:-1]))
            equal &= field_equal
        self.consecutive_identical_quote_state += int(np.count_nonzero(equal))
        self._prev_quote = {name: np.asarray(columns[name])[-1].copy() for name in self.quote_state_fields}

    def _spread(self, columns: Mapping[str, np.ndarray]) -> None:
        bid = np.asarray(columns["bid"], dtype=np.float64) if "bid" in columns else None
        ask = np.asarray(columns["ask"], dtype=np.float64) if "ask" in columns else None
        if bid is None and ask is None:
            return
        if bid is not None:
            self.invalid_bid += int(np.count_nonzero(bid <= 0))
        if ask is not None:
            self.invalid_ask += int(np.count_nonzero(ask <= 0))
        if bid is None or ask is None:
            return
        self.ask_below_bid += int(np.count_nonzero(ask < bid))
        spread = ask - bid
        self.zero_spread += int(np.count_nonzero(spread == 0))
        self.negative_spread += int(np.count_nonzero(spread < 0))
        valid = (bid > 0) & (ask > 0) & (spread >= 0)
        if valid.any():
            mid = (bid[valid] + ask[valid]) / 2.0
            positive = mid > 0
            if positive.any():
                self._spread_chunks.append((spread[valid][positive] / mid[positive]) * 10000.0)

    def _jumps(self, columns: Mapping[str, np.ndarray]) -> None:
        if "bid" not in columns or "ask" not in columns:
            self._prev_mid = None
            return
        bid = np.asarray(columns["bid"], dtype=np.float64)
        ask = np.asarray(columns["ask"], dtype=np.float64)
        valid = (bid > 0) & (ask > 0)
        mid = np.where(valid, (bid + ask) / 2.0, np.nan)
        part_stamps = np.asarray(columns["time_msc"], dtype=np.int64) if "time_msc" in columns else None
        with np.errstate(invalid="ignore", divide="ignore"):
            if self._prev_mid is not None:
                # delta[i] is the change into part row i (row 0 jumps from the previous part's tail)
                delta = np.diff(np.concatenate(([self._prev_mid], mid)))
                target_stamps = part_stamps
            else:
                # delta[i] is the change into part row i+1
                delta = np.diff(mid)
                target_stamps = part_stamps[1:] if part_stamps is not None else None
        finite = np.isfinite(delta)
        if finite.any():
            values = delta[finite]
            absvals = np.abs(values)
            for t in self.jump_thresholds_bps:
                self.jump_threshold_counts[int(t)] += int(np.count_nonzero(absvals > t))
            # streaming Welford merge (vector-chunked, exact up to float addition order)
            cnt = int(values.size)
            batch_mean = float(values.mean())
            batch_m2 = float(((values - batch_mean) ** 2).sum())
            total = self.jump_count + cnt
            delta_mean = batch_mean - self.jump_mean
            self.jump_mean += delta_mean * cnt / total
            self.jump_m2 += batch_m2 + delta_mean * delta_mean * self.jump_count * cnt / total
            self.jump_count = total
            mn = float(values.min())
            mx = float(values.max())
            self.jump_min = mn if self.jump_min is None else min(self.jump_min, mn)
            self.jump_max = mx if self.jump_max is None else max(self.jump_max, mx)
            if target_stamps is not None:
                k = min(self.top_k, int(values.size))
                finite_idx = np.flatnonzero(finite)
                top_local = np.argpartition(-absvals, k - 1)[:k]
                for j in top_local.tolist():
                    i = int(finite_idx[j])
                    if 0 <= i < target_stamps.size:
                        self._jump_records.append((float(absvals[j]), int(target_stamps[i]), float(values[j])))
        last_finite = np.flatnonzero(np.isfinite(mid))
        self._prev_mid = float(mid[last_finite[-1]]) if last_finite.size else self._prev_mid

    def _coverage(self, stamps: np.ndarray) -> None:
        days = stamps // 86_400_000
        uniq, counts = np.unique(days, return_counts=True)
        for day, cnt in zip(uniq.tolist(), counts.tolist(), strict=True):
            self._rows_per_day[int(day)] = self._rows_per_day.get(int(day), 0) + int(cnt)

    # -- finalization -----------------------------------------------------------

    def finish(self) -> dict[str, Any]:
        self._flush_carry()
        spreads = np.concatenate(self._spread_chunks) if self._spread_chunks else np.empty(0, dtype=np.float64)
        spread_stats: dict[str, Any] = {
            "count": int(spreads.size),
            "min_bps": float(spreads.min()) if spreads.size else None,
            "mean_bps": float(spreads.mean()) if spreads.size else None,
            "median_bps": float(np.median(spreads)) if spreads.size else None,
            "p95_bps": float(np.quantile(spreads, 0.95, method="linear")) if spreads.size else None,
            "max_bps": float(spreads.max()) if spreads.size else None,
            "quantile_method": "numpy.quantile(method='linear')",
            "memory_note": SPREAD_BPS_NOTE,
        }
        gaps = sorted(self._gap_records, key=lambda r: -r[0])[: self.top_k]
        gap_rows = [
            {
                "gap_ms": gap,
                "gap_seconds": round(gap / 1000.0, 3),
                "start_time_msc_raw": start,
                "end_time_msc_raw": end,
                "start_utc_if_utc": _utc_iso(start),
                "end_utc_if_utc": _utc_iso(end),
                "overlaps_utc_weekend_if_utc": _weekend_overlap(start, end),
                "provisional_timestamp_basis": True,
            }
            for gap, start, end in gaps
        ]
        jumps = sorted(self._jump_records, key=lambda r: -r[0])[: self.top_k]
        jump_rows = [
            {
                "time_msc_of_target_row_raw": stamp,
                "time_utc_of_target_row_if_utc": _utc_iso(stamp),
                "delta_bps": round(delta, 6),
                "abs_delta_bps": round(ab, 6),
                "provisional_timestamp_basis": True,
            }
            for ab, stamp, delta in jumps
        ]
        day_counts = sorted(self._rows_per_day.values())
        jump_std = math.sqrt(self.jump_m2 / self.jump_count) if self.jump_count else None
        return {
            "row_count": int(self.total_rows),
            "raw_time_min": self.time_min,
            "raw_time_max": self.time_max,
            "raw_time_msc_min": self.time_msc_min,
            "raw_time_msc_max": self.time_msc_max,
            "non_monotonic_time_msc_count": int(self.non_monotonic),
            "max_backward_step_ms": self.max_backward_step_ms if self.non_monotonic else 0,
            "monotonicity_statement": (
                "time_msc is monotonically non-decreasing across the whole dataset"
                if self.non_monotonic == 0
                else f"{self.non_monotonic} rows regress in time_msc; group/duplicate counters remain "
                "valid within adjacent runs only"
            ),
            "duplicate_scope_statement": (
                "COMPLETE: time_msc is monotonic, so every equal-timestamp group is adjacent and was measured exactly"
                if self.non_monotonic == 0
                else "ADJACENT_RUNS_ONLY: non-monotonic rows present; equal-timestamp groups are measured within adjacent runs"
            ),
            "same_time_msc_groups": int(self.same_time_msc_groups),
            "same_time_msc_excess_rows": int(self.same_time_msc_excess_rows),
            "same_time_msc_distinct_payload_rows": int(self.same_time_msc_distinct_payload_rows),
            "identical_full_row_excess_count": int(self.identical_full_row_excess),
            "duplicate_semantics": {
                "identical_full_row_excess_count": "exact canonical row repeats within an equal-time_msc run; retained, never discarded",
                "same_time_msc_excess_rows": "rows beyond the first sharing one millisecond; not automatically duplicates",
                "same_time_msc_distinct_payload_rows": "equal-time_msc rows whose full payload differs from the run's first row",
                "consecutive_identical_quote_state_excess_rows": "adjacent repeated bid/ask/etc. state; standing-quote candidate, never a duplicate tick",
            },
            "consecutive_identical_quote_state_excess_rows": int(self.consecutive_identical_quote_state),
            "consecutive_identical_quote_state_fields": self.quote_state_fields,
            "invalid_bid_count": int(self.invalid_bid),
            "invalid_ask_count": int(self.invalid_ask),
            "ask_below_bid_count": int(self.ask_below_bid),
            "zero_spread_count": int(self.zero_spread),
            "negative_spread_count": int(self.negative_spread),
            "spread_bps": spread_stats,
            "gap_counts_by_threshold_s": {str(k): int(v) for k, v in self.gap_counts.items()},
            "largest_gaps_top_k": gap_rows,
            "gap_assessment": _GAPS_NOTE,
            "price_jump_diagnostics": {
                "count": int(self.jump_count),
                "mean_bps": float(self.jump_mean) if self.jump_count else None,
                "std_bps": float(jump_std) if jump_std is not None else None,
                "min_bps": self.jump_min,
                "max_bps": self.jump_max,
                "counts_above_threshold_bps": {str(k): int(v) for k, v in self.jump_threshold_counts.items()},
                "largest_abs_jumps_top_k": jump_rows,
                "assessment": _JUMPS_NOTE,
            },
            "timestamp_basis_investigation": {
                "rows_where_time_equals_time_msc_div_1000": int(self.time_equals_msc_div1000),
                "rows_with_second_aligned_time_msc": int(self.msc_second_aligned),
                "sub_second_resolution_present": bool(self.msc_second_aligned < self.total_rows),
                "raw_fields": [f for f in ("time", "time_msc") if f in self.fields],
                "statement": (
                    "time/time_msc are used exactly as stored (epoch seconds / milliseconds by MT5 "
                    "convention); the direct server/UTC basis of historical rows remains UNVERIFIED and no "
                    "normalization was applied"
                ),
            },
            "coverage_if_utc": {
                "first_time_msc_utc_if_utc": _utc_iso(self.time_msc_min),
                "last_time_msc_utc_if_utc": _utc_iso(self.time_msc_max),
                "distinct_days_with_rows": len(self._rows_per_day),
                "rows_per_day_min": int(day_counts[0]) if day_counts else None,
                "rows_per_day_median": int(np.median(np.asarray(day_counts))) if day_counts else None,
                "rows_per_day_max": int(day_counts[-1]) if day_counts else None,
                "provisional_timestamp_basis": True,
            },
        }


def _weekend_overlap(start_ms: int, end_ms: int) -> bool | None:
    """Provisional diagnostic: does [start,end] include a UTC Saturday/Sunday day?"""
    if _utc_iso(start_ms) is None or _utc_iso(end_ms) is None:
        return None
    start_dt = datetime.fromtimestamp(start_ms / 1000.0, tz=UTC)
    end_dt = datetime.fromtimestamp(end_ms / 1000.0, tz=UTC)
    days = (end_dt.date() - start_dt.date()).days
    if days > 9:
        return True  # any span beyond 9 days necessarily includes a weekend
    return any((start_dt.date() + timedelta(days=offset)).weekday() >= 5 for offset in range(days + 1))


# ---------------------------------------------------------------------------
# Integrity / provenance validation
# ---------------------------------------------------------------------------


def validate_dataset_integrity(dataset_dir: Path, *, recompute_hashes: bool = True) -> dict[str, Any]:
    """Recompute file hashes and cross-check the acquisition manifest."""
    dataset_dir = Path(dataset_dir)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    manifest_path = dataset_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        check("manifest_present", False, f"{manifest_path} missing")
        return {
            "overall": "FAIL",
            "checks": checks,
            "statement": "no acquisition manifest; dataset provenance cannot be validated",
        }
    check("manifest_present", True, str(manifest_path))
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing_keys = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
    check("manifest_required_keys", not missing_keys, f"missing={missing_keys}" if missing_keys else "all present")
    check(
        "manifest_schema",
        manifest.get("schema") == ACQUISITION_SCHEMA,
        f"schema={manifest.get('schema')!r}",
    )
    status = manifest.get("status")
    check(
        "manifest_status_final",
        status in FINAL_STATUSES,
        f"status={status!r} ({'final' if status in FINAL_STATUSES else 'NOT final — partial/in-progress data must not be analyzed as complete'})",
    )
    check(
        "read_only_flags",
        bool(manifest.get("read_only")) and manifest.get("orders_submitted") == 0 and manifest.get("order_send_called") is False,
        f"read_only={manifest.get('read_only')} orders_submitted={manifest.get('orders_submitted')}",
    )

    parts = manifest.get("parts") or []
    parts_dir = dataset_dir / "parts"
    on_disk = {p.name for p in parts_dir.glob("*.parquet")} if parts_dir.exists() else set()
    ledgered = {p["part"] for p in parts}
    unrecorded = sorted(on_disk - ledgered)
    missing_files = sorted(ledgered - on_disk)
    check("no_unrecorded_part_files", not unrecorded, f"unrecorded={unrecorded}" if unrecorded else "none")
    check("all_ledgered_parts_present", not missing_files, f"missing={missing_files}" if missing_files else "all present")

    hash_failures: list[str] = []
    missing_for_hash: list[str] = []
    file_hashes: dict[str, str] = {}
    if recompute_hashes:
        for part in parts:
            path = dataset_dir / "parts" / part["part"]
            if not path.exists():
                missing_for_hash.append(part["part"])
                continue
            digest = sha256_file(path)
            file_hashes[part["part"]] = digest
            if digest != part.get("sha256"):
                hash_failures.append(part["part"])
        hash_ok = not hash_failures and not missing_for_hash
        check(
            "part_sha256_match",
            hash_ok,
            "all part file hashes match the ledger"
            if hash_ok
            else f"mismatch={hash_failures[:10]} missing_count={len(missing_for_hash)}",
        )
        file_digest = dataset_digest(file_hashes) if file_hashes and not missing_for_hash else None
        check(
            "dataset_digest_match",
            file_digest is not None and file_digest == manifest.get("dataset_sha256"),
            f"file_digest={file_digest}",
        )
    row_sum = sum(int(p.get("rows", 0)) for p in parts)
    parquet_rows = _parquet_row_total(dataset_dir, parts)
    check(
        "row_count_matches_parts",
        row_sum == int(manifest.get("row_count", -1)) and row_sum == parquet_rows,
        f"ledger_rows={row_sum} manifest_row_count={manifest.get('row_count')} parquet_rows={parquet_rows}",
    )
    overall = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    return {
        "overall": overall,
        "checks": checks,
        "manifest_status": status,
        "statement": (
            "integrity validation recomputes hashes and ledger arithmetic from disk; "
            "a PARTIAL dataset is valid evidence for its committed chunks but must never be read as complete"
        ),
    }


def _parquet_row_total(dataset_dir: Path, parts: list[dict[str, Any]]) -> int:
    total = 0
    for part in parts:
        path = dataset_dir / "parts" / part["part"]
        if path.exists():
            total += int(pq.read_metadata(path).num_rows)
    return total


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def analyze_columns(
    columns: Mapping[str, np.ndarray],
    *,
    gap_thresholds_s: tuple[int, ...] = DEFAULT_GAP_THRESHOLDS_S,
    jump_thresholds_bps: tuple[int, ...] = DEFAULT_JUMP_THRESHOLDS_BPS,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """Analyze one in-memory column mapping (used for small fixtures/tests)."""
    fields = list(columns.keys())
    acc = _Accumulator(fields, gap_thresholds_s=gap_thresholds_s, jump_thresholds_bps=jump_thresholds_bps, top_k=top_k)
    if fields:
        acc.update(columns)
    return acc.finish()


def analyze_dataset(
    dataset_dir: str | Path,
    *,
    gap_thresholds_s: tuple[int, ...] = DEFAULT_GAP_THRESHOLDS_S,
    jump_thresholds_bps: tuple[int, ...] = DEFAULT_JUMP_THRESHOLDS_BPS,
    top_k: int = DEFAULT_TOP_K,
    recompute_hashes: bool = True,
) -> dict[str, Any]:
    """Analyze one immutable raw tick dataset directory.

    Reads only local files: parquet parts (in ledger order) + manifest.  No
    MT5 import, no network.  Returns the machine-readable analysis report.
    """
    started = _time.monotonic()
    dataset_dir = Path(dataset_dir)
    generated_at = datetime.now(UTC).isoformat()
    manifest_path = dataset_dir / MANIFEST_FILENAME
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    integrity = validate_dataset_integrity(dataset_dir, recompute_hashes=recompute_hashes)

    parts = (manifest or {}).get("parts") or []
    manifest_fields = (manifest or {}).get("returned_fields") or []
    manifest_dtype_map = (manifest or {}).get("returned_dtype_map") or {}

    schema_checks: list[dict[str, Any]] = []
    fields_seen: list[str] | None = None
    acc: _Accumulator | None = None
    per_part: list[dict[str, Any]] = []
    for part in parts:
        path = dataset_dir / "parts" / part["part"]
        if not path.exists():
            continue
        table = pq.read_table(path)
        columns = _columns_of(table)
        if fields_seen is None:
            fields_seen = list(table.column_names)
            acc = _Accumulator(
                fields_seen,
                gap_thresholds_s=gap_thresholds_s,
                jump_thresholds_bps=jump_thresholds_bps,
                top_k=top_k,
            )
        else:
            if list(table.column_names) != fields_seen:
                schema_checks.append(
                    {"check": f"part_field_order:{part['part']}", "status": "FAIL", "detail": "field order drift across parts"}
                )
        if acc is None:  # pragma: no cover - defensive (fields_seen and acc are set together)
            raise RuntimeError("analysis accumulator missing despite committed parts")
        acc.update(columns)
        per_part.append(
            {
                "part": part["part"],
                "rows": int(table.num_rows),
                "sha256_matches_ledger": sha256_file(path) == part.get("sha256") if recompute_hashes else None,
            }
        )
        del table, columns

    metrics = acc.finish() if acc is not None else {"row_count": 0}

    if fields_seen is not None and manifest_fields:
        schema_checks.append(
            {
                "check": "fields_match_manifest",
                "status": "PASS" if list(fields_seen) == list(manifest_fields) else "FAIL",
                "detail": f"dataset_fields={fields_seen}",
            }
        )
    dtype_map_seen: dict[str, str] = {}
    if fields_seen is not None:
        first_part = dataset_dir / "parts" / parts[0]["part"] if parts else None
        if first_part is not None and first_part.exists():
            schema = pq.read_schema(first_part)
            dtype_map_seen = {field.name: str(schema.field(field.name).type) for field in schema}
    if dtype_map_seen and manifest_dtype_map:
        schema_checks.append(
            {
                "check": "dtype_inventory_recorded",
                "status": "PASS",
                "detail": (
                    f"manifest numpy dtype map={manifest_dtype_map}; "
                    f"parquet physical types={dtype_map_seen}; mapping is the documented "
                    "numpy->arrow lossless type correspondence (no value transformation)"
                ),
            }
        )

    schema_integrity = {
        "fields": fields_seen,
        "field_count": len(fields_seen or []),
        "manifest_fields": manifest_fields,
        "arrow_physical_types_first_part": dtype_map_seen,
        "checks": schema_checks,
        "future_field_handling": (
            "the acquisition layer preserves whatever fields MT5 returns (structured dtype captured per "
            "response); this report lists the exact inventory rather than assuming a fixed schema"
        ),
    }

    request = (manifest or {}).get("request") or {}
    report: dict[str, Any] = {
        "schema": ANALYSIS_SCHEMA,
        "generated_at_utc": generated_at,
        "analysis_duration_seconds": round(_time.monotonic() - started, 3),
        "analysis_independence": {
            "mt5_package_present_in_process": "MetaTrader5" in _loaded_modules(),
            "statement": (
                "analysis ran entirely from the stored local dataset; the MetaTrader5 package is never "
                "imported by the analysis module and no broker connection is required or attempted, even "
                "when the package happens to be present in the host process (e.g. the acquisition driver)"
            ),
        },
        "dataset": {
            "path": str(dataset_dir),
            "acquisition_schema": (manifest or {}).get("schema"),
            "acquisition_status": (manifest or {}).get("status"),
            "dataset_sha256_manifest": (manifest or {}).get("dataset_sha256"),
            "dataset_files_size_bytes": (manifest or {}).get("dataset_files_size_bytes"),
            "requested_window": {
                "start_utc": request.get("start_utc"),
                "end_utc": request.get("end_utc"),
                "window_days": request.get("window_days"),
            },
            "symbol": (manifest or {}).get("symbol"),
            "environment": (manifest or {}).get("environment"),
            "observation_mode": (manifest or {}).get("observation_mode"),
            "timestamp_interpretation_confirmed": (manifest or {}).get("timestamp_interpretation_confirmed"),
            "parts_committed": len(parts),
            "parts_failed": len((manifest or {}).get("failed_chunks") or []),
            "resumed_from_previous_run": (manifest or {}).get("resumed_from_previous_run"),
        },
        "analysis_parameters": {
            "gap_thresholds_s": list(gap_thresholds_s),
            "jump_thresholds_bps": list(jump_thresholds_bps),
            "top_k": top_k,
            "recompute_hashes": recompute_hashes,
            "tool_versions": _tool_versions(),
        },
        "provenance_validation": integrity,
        "schema_integrity": schema_integrity,
        "per_part_row_counts": per_part,
        "content": metrics,
        "bounded_payload_policy": (
            "this report contains no raw tick rows; top-k lists carry raw timestamps and derived deltas "
            "only (no bid/ask payloads), capped at top_k entries"
        ),
    }
    return report


def _loaded_modules() -> set[str]:
    import sys

    return set(sys.modules)


def _tool_versions() -> dict[str, Any]:
    import platform

    import pyarrow as pa

    from qts import __version__ as qts_version

    return {
        "analyzer": "qts.data.mt5_history_analysis",
        "qts_version": qts_version,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pyarrow_version": pa.__version__,
        "hashlib": "sha256" if hashlib.sha256() else "unknown",
    }
