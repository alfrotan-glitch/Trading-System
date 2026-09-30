"""Contracts for the deferred MT5 raw tick analysis layer.

The analysis layer reads ONLY the stored local dataset (Parquet parts +
manifest); it must run identically with no MetaTrader5 package present, never
touch the broker, and produce the full research-quality audit the old
in-acquisition ``_audit_rows`` used to compute — but after acquisition, from
local evidence, vectorized.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fakes_mt5 import TICK_DTYPE, FakeMT5, generate_chunk_rows

from qts.data.mt5_history_acquisition import acquire_window
from qts.data.mt5_history_analysis import (
    _Accumulator,
    analyze_columns,
    analyze_dataset,
)

END = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


def _columns(rows: list[dict]) -> dict[str, np.ndarray]:
    fields = rows[0].keys()
    out: dict[str, np.ndarray] = {}
    for field in fields:
        if field in {"time", "time_msc"}:
            out[field] = np.array([r[field] for r in rows], dtype=np.int64)
        else:
            out[field] = np.array([r[field] for r in rows], dtype=np.float64)
    return out


def _acquired_dataset(tmp_path: Path, *, days: int = 2, chunk_hours: float = 6.0, **fake_kwargs) -> Path:
    fake = FakeMT5(**fake_kwargs)
    dataset_dir = tmp_path / "dataset"
    acquire_window(
        fake,
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment={"environment": "DEMO", "server": "WMMarkets-Demo", "is_demo": True},
        start_utc=END - timedelta(days=days),
        end_utc=END,
        dataset_dir=dataset_dir,
        flags=fake.COPY_TICKS_ALL,
        chunk=timedelta(hours=chunk_hours),
        min_chunk=timedelta(minutes=60),
    )
    return dataset_dir


# ---------------------------------------------------------------------------
# Hand-computed semantics (previously pinned by the probe's _audit_rows tests)
# ---------------------------------------------------------------------------


def test_equal_millisecond_rows_are_not_automatically_duplicates() -> None:
    columns = _columns(
        [
            {"time": 1, "time_msc": 1000, "bid": 2000.0, "ask": 2000.5},
            {"time": 1, "time_msc": 1000, "bid": 2000.1, "ask": 2000.6},
            {"time": 1, "time_msc": 1000, "bid": 2000.1, "ask": 2000.6},
            {"time": 1, "time_msc": 1001, "bid": 2000.1, "ask": 2000.6},
        ]
    )
    result = analyze_columns(columns)
    assert result["row_count"] == 4
    assert result["same_time_msc_groups"] == 1
    assert result["same_time_msc_excess_rows"] == 2
    assert result["same_time_msc_distinct_payload_rows"] == 2
    assert result["identical_full_row_excess_count"] == 1
    assert result["consecutive_identical_quote_state_excess_rows"] == 2
    assert result["non_monotonic_time_msc_count"] == 0
    assert result["duplicate_scope_statement"].startswith("COMPLETE")
    assert result["zero_spread_count"] == 0
    assert result["negative_spread_count"] == 0
    assert result["spread_bps"]["count"] == 4


def test_validity_spread_and_monotonicity_counters() -> None:
    columns = _columns(
        [
            {"time": 2, "time_msc": 2000, "bid": 2000.0, "ask": 2000.5},
            {"time": 1, "time_msc": 1000, "bid": 2000.0, "ask": 1999.0},  # backward step + ask<bid
            {"time": 3, "time_msc": 3000, "bid": 0.0, "ask": 0.0},  # invalid quotes
        ]
    )
    result = analyze_columns(columns)
    assert result["non_monotonic_time_msc_count"] == 1
    assert result["max_backward_step_ms"] == 1000
    assert "ADJACENT_RUNS_ONLY" in result["duplicate_scope_statement"]
    assert result["ask_below_bid_count"] == 1
    assert result["negative_spread_count"] == 1
    assert result["invalid_bid_count"] == 1  # only the 0.0 bid is invalid (<= 0)
    assert result["invalid_ask_count"] == 1
    assert result["spread_bps"]["count"] == 1  # only row 1 has positive bid/ask with spread >= 0
    assert result["zero_spread_count"] == 1


def test_cross_part_same_ms_group_is_merged_exactly() -> None:
    """A same-ms group split across part boundaries must be counted once, whole."""
    acc = _Accumulator(
        ["time", "time_msc", "bid", "ask"],
        gap_thresholds_s=(1, 60),
        jump_thresholds_bps=(10,),
        top_k=5,
    )
    part1 = _columns(
        [
            {"time": 0, "time_msc": 100, "bid": 1.0, "ask": 1.5},
            {"time": 0, "time_msc": 100, "bid": 1.0, "ask": 1.5},
            {"time": 0, "time_msc": 200, "bid": 2.0, "ask": 2.5},
        ]
    )
    part2 = _columns(
        [
            {"time": 0, "time_msc": 200, "bid": 9.0, "ask": 9.5},
            {"time": 0, "time_msc": 300, "bid": 3.0, "ask": 3.5},
        ]
    )
    acc.update(part1)
    acc.update(part2)
    result = acc.finish()
    # groups: @100 (identical pair), @200 (cross-part, distinct payloads), @300 singleton
    assert result["row_count"] == 5
    assert result["same_time_msc_groups"] == 2
    assert result["same_time_msc_excess_rows"] == 2
    assert result["identical_full_row_excess_count"] == 1
    assert result["same_time_msc_distinct_payload_rows"] == 1


def test_gap_weekend_overlap_diagnostic_is_provisional() -> None:
    friday = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)  # Friday evening
    monday = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    columns = _columns(
        [
            {"time": int(friday.timestamp()), "time_msc": int(friday.timestamp() * 1000), "bid": 1.0, "ask": 1.1},
            {"time": int(monday.timestamp()), "time_msc": int(monday.timestamp() * 1000), "bid": 2.0, "ask": 2.1},
        ]
    )
    result = analyze_columns(columns)
    gaps = result["largest_gaps_top_k"]
    assert len(gaps) == 1
    assert gaps[0]["overlaps_utc_weekend_if_utc"] is True
    assert gaps[0]["provisional_timestamp_basis"] is True
    assert "NOT a classification" in result["gap_assessment"]


# ---------------------------------------------------------------------------
# Dataset-level analysis against acquired raw datasets
# ---------------------------------------------------------------------------


def _reference_python_counts(expected: np.ndarray) -> dict[str, int]:
    """Independent pure-python recount of the generator's edge-case rows."""
    groups: dict[int, list[int]] = {}
    for idx, stamp in enumerate(expected["time_msc"].tolist()):
        groups.setdefault(stamp, []).append(idx)
    group_count = excess = distinct_payload = identical_excess = 0
    rows = expected
    for _stamp, idxs in groups.items():
        if len(idxs) < 2:
            continue
        group_count += 1
        excess += len(idxs) - 1
        first = idxs[0]
        seen: set[tuple] = set()
        first_payload = tuple(rows[name][first].item() for name in rows.dtype.names or ())
        for i in idxs:
            payload = tuple(rows[name][i].item() for name in rows.dtype.names or ())
            seen.add(payload)
            if i != first and payload != first_payload:
                distinct_payload += 1
        identical_excess += len(idxs) - len(seen)
    return {
        "groups": group_count,
        "excess": excess,
        "distinct_payload": distinct_payload,
        "identical_excess": identical_excess,
    }


def test_dataset_analysis_matches_independent_recount(tmp_path: Path) -> None:
    dataset_dir = _acquired_dataset(tmp_path, days=2, chunk_hours=6.0)
    report = analyze_dataset(dataset_dir)
    assert report["schema"] == "qts.mt5_tick_dataset_analysis.v1"
    assert report["provenance_validation"]["overall"] == "PASS"
    assert report["dataset"]["acquisition_status"] == "COMPLETE"
    content = report["content"]

    expected = np.concatenate(
        [
            generate_chunk_rows(
                END - timedelta(days=2) + timedelta(hours=6 * k),
                min(END - timedelta(days=2) + timedelta(hours=6 * (k + 1)), END),
            )
            for k in range(8)
        ]
    )
    assert content["row_count"] == len(expected)
    assert content["raw_time_msc_min"] == int(expected["time_msc"].min())
    assert content["raw_time_msc_max"] == int(expected["time_msc"].max())
    assert content["non_monotonic_time_msc_count"] == 0

    reference = _reference_python_counts(expected)
    assert content["same_time_msc_groups"] == reference["groups"]
    assert content["same_time_msc_excess_rows"] == reference["excess"]
    assert content["same_time_msc_distinct_payload_rows"] == reference["distinct_payload"]
    assert content["identical_full_row_excess_count"] == reference["identical_excess"]

    # spread stats recomputed independently
    spread = expected["ask"] - expected["bid"]
    mid = (expected["ask"] + expected["bid"]) / 2.0
    bps = spread / mid * 10000.0
    stats = content["spread_bps"]
    assert stats["count"] == len(expected)
    assert stats["min_bps"] == pytest.approx(float(bps.min()))
    assert stats["max_bps"] == pytest.approx(float(bps.max()))
    assert stats["mean_bps"] == pytest.approx(float(bps.mean()))
    assert content["ask_below_bid_count"] == 0
    assert content["invalid_bid_count"] == 0
    # schema integrity: exact returned inventory, no field assumed
    assert content["consecutive_identical_quote_state_excess_rows"] > 0
    assert report["schema_integrity"]["fields"] == list(TICK_DTYPE.names)
    assert report["dataset"]["timestamp_interpretation_confirmed"] is False


def test_bounded_payload_policy_no_raw_rows(tmp_path: Path) -> None:
    dataset_dir = _acquired_dataset(tmp_path, days=3, chunk_hours=6.0)
    report = analyze_dataset(dataset_dir, top_k=7)

    def walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            keys = set(node)
            row_like = {"time_msc", "bid", "ask"} <= keys and isinstance(node.get("bid"), (int, float))
            assert not row_like, f"raw row leaked into analysis report at {path}"
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            assert len(node) <= 64, f"unbounded list at {path}: {len(node)} items"
            for idx, value in enumerate(node):
                walk(value, f"{path}[{idx}]")

    walk(report)
    assert len(report["content"]["largest_gaps_top_k"]) <= 7
    assert len(report["content"]["price_jump_diagnostics"]["largest_abs_jumps_top_k"]) <= 7


def test_analysis_of_empty_dataset(tmp_path: Path) -> None:
    dataset_dir = _acquired_dataset(tmp_path, days=1, empty_response=True)
    report = analyze_dataset(dataset_dir)
    assert report["dataset"]["acquisition_status"] == "EMPTY_COMPLETE"
    assert report["content"]["row_count"] == 0
    assert report["provenance_validation"]["overall"] == "PASS"
    assert report["content"]["spread_bps"]["count"] == 0


def test_analysis_preserves_future_field_inventory(tmp_path: Path) -> None:
    dataset_dir = _acquired_dataset(tmp_path, days=1, future_fields=True)
    report = analyze_dataset(dataset_dir)
    assert "spread_points" in report["schema_integrity"]["fields"]
    assert report["schema_integrity"]["field_count"] == len(TICK_DTYPE.names) + 1
    checks = {c["check"]: c["status"] for c in report["schema_integrity"]["checks"]}
    assert checks.get("fields_match_manifest") == "PASS"


def test_analysis_partial_dataset_flagged_not_complete(tmp_path: Path) -> None:
    fake = FakeMT5(raise_keyboard_interrupt_calls={2})
    dataset_dir = tmp_path / "dataset"
    acquire_window(
        fake,
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment={"environment": "DEMO", "server": "WMMarkets-Demo", "is_demo": True},
        start_utc=END - timedelta(days=2),
        end_utc=END,
        dataset_dir=dataset_dir,
        flags=fake.COPY_TICKS_ALL,
        chunk=timedelta(hours=6.0),
        min_chunk=timedelta(minutes=60),
    )
    report = analyze_dataset(dataset_dir)
    assert report["dataset"]["acquisition_status"] == "PARTIAL_INTERRUPTED"
    assert report["provenance_validation"]["overall"] == "PASS"  # partial integrity still validates...
    # ...but nobody may read it as a complete dataset
    assert report["dataset"]["acquisition_status"] != "COMPLETE"


# ---------------------------------------------------------------------------
# Independence from MT5
# ---------------------------------------------------------------------------


def test_analysis_runs_with_metatrader5_import_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_dir = _acquired_dataset(tmp_path, days=1)
    # purge and hard-block the MetaTrader5 module, then analyze offline
    monkeypatch.delitem(sys.modules, "MetaTrader5", raising=False)

    class _Blocker:
        def find_module(self, name: str, path: object = None):  # noqa: ANN001
            if name == "MetaTrader5":
                return self
            return None

        def load_module(self, name: str):  # noqa: ANN001
            raise ImportError(f"{name} blocked for offline analysis test")

        def find_spec(self, name: str, path: object = None, target: object = None):  # noqa: ANN001
            if name == "MetaTrader5":
                raise ImportError("MetaTrader5 blocked for offline analysis test")
            return None

    blocker = _Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        report = analyze_dataset(dataset_dir)
    finally:
        sys.meta_path.remove(blocker)
    assert report["provenance_validation"]["overall"] == "PASS"
    assert report["analysis_independence"]["mt5_package_present_in_process"] is False
    assert report["analysis_independence"]["statement"]
    assert report["content"]["row_count"] > 0
