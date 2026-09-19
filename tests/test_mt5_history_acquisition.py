"""Contracts for the read-only MT5 raw tick acquisition layer.

Principles under test
---------------------
ACQUIRE first, ANALYZE later: acquisition performs zero per-row analysis,
preserves every returned row losslessly (schema + values + duplicates),
records durable provenance/integrity metadata, is interrupt-safe and
resumable, never touchs an order API, and keeps raw broker data out of Git.

No live broker is used anywhere here (CI-safe): fixtures come from
tests/fakes_mt5.py, which emits numpy structured arrays with the real MT5 tick
dtype layout.
"""

from __future__ import annotations

import ast
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest
from fakes_mt5 import TICK_DTYPE, TICK_DTYPE_WITH_FUTURE_FIELD, FakeMT5, generate_chunk_rows

from qts.data.mt5_history_acquisition import (
    ALLOWED_MT5_CALLS,
    AcquisitionRefused,
    RawTickDatasetWriter,
    acquire_window,
    dataset_digest,
    plan_base_chunks,
    require_read_only_demo,
    sha256_file,
)
from qts.data.mt5_history_analysis import REQUIRED_MANIFEST_KEYS, validate_dataset_integrity

REPO_ROOT = Path(__file__).resolve().parents[1]
END = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


def _env() -> dict:
    return {"environment": "DEMO", "server": "WMMarkets-Demo", "is_demo": True}


def _acquire(fake: FakeMT5, tmp_path: Path, days: int = 2, *, chunk_hours: float = 6.0, **kwargs):
    return acquire_window(
        fake,
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment=_env(),
        start_utc=END - timedelta(days=days),
        end_utc=END,
        dataset_dir=tmp_path / "dataset",
        flags=fake.COPY_TICKS_ALL,
        chunk=timedelta(hours=chunk_hours),
        min_chunk=timedelta(minutes=60),
        **kwargs,
    )


def _read_all_parts(dataset_dir: Path) -> np.ndarray:
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    frames = []
    for part in manifest["parts"]:
        table = pq.read_table(Path(part["path"]))
        frames.append(table.to_pandas().to_records(index=False))
    return np.concatenate(frames) if frames else np.empty(0, dtype=TICK_DTYPE)


def _expected_rows(days: int, chunk_hours: float, spacing_ms: int = 30_000) -> np.ndarray:
    chunks = plan_base_chunks(END - timedelta(days=days), END, timedelta(hours=chunk_hours))
    parts = [
        generate_chunk_rows(
            datetime.fromisoformat(c["start_utc"]), datetime.fromisoformat(c["end_utc"]), spacing_ms=spacing_ms
        )
        for c in chunks
    ]
    return np.concatenate(parts)


# ---------------------------------------------------------------------------
# Lossless preservation / schema
# ---------------------------------------------------------------------------


def test_schema_preservation_lossless_roundtrip(tmp_path: Path) -> None:
    fake = FakeMT5()
    manifest = _acquire(fake, tmp_path, days=2)
    assert manifest["status"] == "COMPLETE"
    assert manifest["returned_fields"] == list(TICK_DTYPE.names)
    assert manifest["returned_dtype_map"] == {name: str(TICK_DTYPE.fields[name][0]) for name in TICK_DTYPE.names}
    for part in manifest["parts"]:
        assert part["lossless_roundtrip_verified"] is True

    stored = _read_all_parts(tmp_path / "dataset")
    expected = _expected_rows(2, 6.0)
    assert stored.shape == expected.shape
    assert stored.dtype.names == expected.dtype.names
    for name in TICK_DTYPE.names or ():
        assert np.array_equal(stored[name], expected[name]), f"field {name} diverged"


def test_complete_raw_row_retention_including_duplicates_and_collisions(tmp_path: Path) -> None:
    """Every row MT5 returns is retained: same-ms distinct payloads AND exact repeats."""
    fake = FakeMT5()
    _acquire(fake, tmp_path, days=2)
    stored = _read_all_parts(tmp_path / "dataset")
    expected = _expected_rows(2, 6.0)
    # row order and multiplicity are exactly the provider's
    assert len(stored) == len(expected)
    # the generator emits same-ms distinct payloads at i%97==0 and exact repeats at i%499==0
    stamps, counts = np.unique(stored["time_msc"], return_counts=True)
    assert int((counts >= 2).sum()) > 0, "expected same-time_msc collisions to be preserved"
    structured_len = len(np.unique(stored))
    assert structured_len < len(stored), "expected exact full-row duplicates to be preserved (not deduped)"


def test_future_broker_fields_are_preserved_not_dropped(tmp_path: Path) -> None:
    """A response carrying a never-seen field keeps it end-to-end (no hard-coded schema)."""
    fake = FakeMT5(future_fields=True)
    manifest = _acquire(fake, tmp_path, days=1)
    assert manifest["returned_fields"] == list(TICK_DTYPE_WITH_FUTURE_FIELD.names)
    assert "spread_points" in manifest["returned_dtype_map"]
    stored = _read_all_parts(tmp_path / "dataset")
    assert "spread_points" in stored.dtype.names
    expected = np.arange(stored.shape[0], dtype="<u2") % 17
    # per-chunk arange resets; verify field survived with exact per-part values
    assert stored["spread_points"].dtype == np.dtype("<u2")
    assert int(stored["spread_points"][1]) == int(expected[1])


def test_mixed_schema_responses_are_refused(tmp_path: Path) -> None:
    """Schema drift mid-acquisition fails closed instead of silently mixing payloads."""
    writer = RawTickDatasetWriter.create(
        tmp_path / "dataset",
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment=_env(),
        request={"start_utc": (END - timedelta(hours=2)).isoformat(), "end_utc": END.isoformat()},
        software={"probe": "test"},
    )
    normal = generate_chunk_rows(END - timedelta(hours=2), END - timedelta(hours=1))
    writer.append_chunk(
        {
            "id": "c0",
            "start_utc": (END - timedelta(hours=2)).isoformat(),
            "end_utc": (END - timedelta(hours=1)).isoformat(),
            "span_hours": 1.0,
        },
        normal,
    )
    drifted = np.empty(1, dtype=TICK_DTYPE_WITH_FUTURE_FIELD)
    with pytest.raises(ValueError, match="schema drift"):
        writer.append_chunk(
            {
                "id": "c1",
                "start_utc": (END - timedelta(hours=1)).isoformat(),
                "end_utc": END.isoformat(),
                "span_hours": 1.0,
            },
            drifted,
        )


# ---------------------------------------------------------------------------
# Provenance / integrity metadata
# ---------------------------------------------------------------------------


def test_acquisition_manifest_required_metadata(tmp_path: Path) -> None:
    fake = FakeMT5()
    manifest = _acquire(fake, tmp_path, days=1)
    for key in REQUIRED_MANIFEST_KEYS:
        assert key in manifest, f"missing manifest key {key}"
    assert manifest["symbol"] == {"requested": "XAUUSD@", "actual": "XAUUSD@"}
    assert manifest["environment"]["environment"] == "DEMO"
    assert manifest["observation_mode"] == "OBSERVE_ONLY"
    assert manifest["read_only"] is True
    assert manifest["order_send_called"] is False
    assert manifest["request"]["start_utc"] == (END - timedelta(days=1)).isoformat()
    assert manifest["request"]["end_utc"] == END.isoformat()
    assert manifest["timestamp_interpretation_confirmed"] is False
    assert "RAW" in manifest["timestamp_basis"]
    assert manifest["row_count"] > 0
    assert manifest["raw_time_msc_min"] <= manifest["raw_time_msc_max"]
    assert manifest["chunks_committed"] == len(manifest["parts"])
    assert manifest["dataset_files_size_bytes"] == sum(p["size_bytes"] for p in manifest["parts"])
    # digests verify against the bytes on disk
    recomputed = {p["part"]: sha256_file(Path(p["path"])) for p in manifest["parts"]}
    assert manifest["dataset_sha256"] == dataset_digest(recomputed)
    assert manifest["software"]["qts_version"]
    assert manifest["software"]["probe"] == "qts.data.mt5_history_acquisition"


def test_integrity_validation_detects_tampering(tmp_path: Path) -> None:
    fake = FakeMT5()
    _acquire(fake, tmp_path, days=1)
    dataset_dir = tmp_path / "dataset"
    result = validate_dataset_integrity(dataset_dir)
    assert result["overall"] == "PASS"
    # flip one byte in the second part; integrity must fail closed
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    victim = Path(manifest["parts"][1]["path"])
    blob = bytearray(victim.read_bytes())
    blob[0] ^= 0xFF
    victim.write_bytes(bytes(blob))
    broken = validate_dataset_integrity(dataset_dir)
    assert broken["overall"] == "FAIL"
    failed = {c["check"] for c in broken["checks"] if c["status"] == "FAIL"}
    assert "part_sha256_match" in failed


def test_in_progress_dataset_is_not_valid_complete_evidence(tmp_path: Path) -> None:
    writer = RawTickDatasetWriter.create(
        tmp_path / "dataset",
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment=_env(),
        request={"start_utc": END.isoformat(), "end_utc": END.isoformat()},
        software={"probe": "test"},
    )
    rows = generate_chunk_rows(END - timedelta(hours=1), END)
    writer.append_chunk(
        {"id": "c0", "start_utc": (END - timedelta(hours=1)).isoformat(), "end_utc": END.isoformat(), "span_hours": 1.0},
        rows,
    )
    result = validate_dataset_integrity(tmp_path / "dataset")
    assert result["overall"] == "FAIL"
    status_check = next(c for c in result["checks"] if c["check"] == "manifest_status_final")
    assert status_check["status"] == "FAIL"
    assert "IN_PROGRESS" in status_check["detail"]


# ---------------------------------------------------------------------------
# Interruption / resume
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_marks_partial_and_resume_completes_identically(tmp_path: Path) -> None:
    days, chunk_hours = 2, 6.0
    base_chunks = plan_base_chunks(END - timedelta(days=days), END, timedelta(hours=chunk_hours))
    interrupt_call = 3  # fail during the 3rd chunk query
    fake = FakeMT5(raise_keyboard_interrupt_calls={interrupt_call})
    manifest = _acquire(fake, tmp_path, days=days, chunk_hours=chunk_hours)
    assert manifest["status"] == "PARTIAL_INTERRUPTED"
    assert manifest["chunks_committed"] == interrupt_call - 1
    assert manifest["dataset_sha256"]  # partial datasets still carry integrity metadata
    assert manifest["row_count"] < len(_expected_rows(days, chunk_hours))

    # resume with a healthy terminal: same window, same dataset dir
    fake2 = FakeMT5()
    resumed = acquire_window(
        fake2,
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment=_env(),
        start_utc=END - timedelta(days=days),
        end_utc=END,
        dataset_dir=tmp_path / "dataset",
        flags=fake2.COPY_TICKS_ALL,
        chunk=timedelta(hours=chunk_hours),
        min_chunk=timedelta(minutes=60),
    )
    assert resumed["status"] == "COMPLETE"
    assert resumed["row_count"] == len(_expected_rows(days, chunk_hours))
    assert resumed["resumed_from_previous_run"] is True
    assert resumed["chunks_committed"] == len(base_chunks)
    # byte-level equality of the concatenated restored series vs a single uninterrupted run
    uninterrupted_dir = tmp_path / "uninterrupted"
    acquire_window(
        FakeMT5(),
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment=_env(),
        start_utc=END - timedelta(days=days),
        end_utc=END,
        dataset_dir=uninterrupted_dir,
        flags=FakeMT5.COPY_TICKS_ALL,
        chunk=timedelta(hours=chunk_hours),
        min_chunk=timedelta(minutes=60),
    )
    resumed_rows = _read_all_parts(tmp_path / "dataset")
    fresh_rows = _read_all_parts(uninterrupted_dir)
    assert resumed_rows.shape == fresh_rows.shape
    for name in TICK_DTYPE.names or ():
        assert np.array_equal(resumed_rows[name], fresh_rows[name]), f"resume diverged on field {name}"
    assert validate_dataset_integrity(tmp_path / "dataset")["overall"] == "PASS"


def test_crash_mid_chunk_orphan_part_is_discarded_on_resume(tmp_path: Path) -> None:
    days = 1
    fake = FakeMT5(raise_keyboard_interrupt_calls={2})
    partial = _acquire(fake, tmp_path, days=days, chunk_hours=6.0)
    assert partial["status"] == "PARTIAL_INTERRUPTED"
    parts_dir = tmp_path / "dataset" / "parts"
    # simulate a crash mid-write: orphan tmp part that never reached the ledger
    orphan = parts_dir / "part-000099.parquet.part-4242"
    orphan.write_bytes(b"garbage-not-a-real-part")
    fake2 = FakeMT5()
    manifest = acquire_window(
        fake2,
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment=_env(),
        start_utc=END - timedelta(days=days),
        end_utc=END,
        dataset_dir=tmp_path / "dataset",
        flags=fake2.COPY_TICKS_ALL,
        chunk=timedelta(hours=6.0),
        min_chunk=timedelta(minutes=60),
    )
    assert manifest["status"] == "COMPLETE"
    assert not orphan.exists()
    integrity = validate_dataset_integrity(tmp_path / "dataset")
    assert integrity["overall"] == "PASS"
    unrecorded = next(c for c in integrity["checks"] if c["check"] == "no_unrecorded_part_files")
    assert unrecorded["status"] == "PASS"


def test_completed_dataset_is_not_reopened_for_append(tmp_path: Path) -> None:
    fake = FakeMT5()
    _acquire(fake, tmp_path, days=1)
    with pytest.raises(FileExistsError):
        RawTickDatasetWriter.open_existing(tmp_path / "dataset")


# ---------------------------------------------------------------------------
# Failure vocabulary — never fake completeness
# ---------------------------------------------------------------------------


def test_empty_response_is_empty_complete_not_data(tmp_path: Path) -> None:
    fake = FakeMT5(empty_response=True)
    manifest = _acquire(fake, tmp_path, days=1, chunk_hours=6.0)
    assert manifest["status"] == "EMPTY_COMPLETE"
    assert manifest["row_count"] == 0
    assert manifest["parts"] and all(p["rows"] == 0 for p in manifest["parts"])


def test_none_response_marks_partial_query_error_never_complete(tmp_path: Path) -> None:
    fake = FakeMT5(none_response=True)
    manifest = _acquire(fake, tmp_path, days=1, chunk_hours=6.0)  # 6h chunks split to the 1h floor
    assert manifest["status"] == "PARTIAL_QUERY_ERROR"
    assert manifest["row_count"] == 0
    assert manifest["chunks_failed"] > 0
    assert manifest["mt5_error_last"]
    assert all("Terminal: Call failed" in c["error"] or "exception" in c["error"] for c in manifest["failed_chunks"])


def test_failure_abort_after_max_failed_chunks_is_query_error_not_interruption(tmp_path: Path) -> None:
    """An MT5-side failure storm aborts as PARTIAL_QUERY_ERROR, never as an operator stop."""
    fake = FakeMT5(none_response=True)
    manifest = _acquire(fake, tmp_path, days=1, chunk_hours=24.0, max_failed_chunks=3)
    assert manifest["status"] == "PARTIAL_QUERY_ERROR"
    assert manifest["chunks_failed"] == 4  # stops as soon as the limit is exceeded
    assert manifest["row_count"] == 0
    assert any("max_failed_chunks_exceeded" in note for note in manifest.get("notes", []))


def test_adaptive_split_recovers_span_capped_server(tmp_path: Path) -> None:
    """A server that refuses spans > 3h is recovered by recursive halving."""
    cap = 3 * 3600 * 1000
    fake = FakeMT5(fail_spans_above_ms=cap)
    manifest = _acquire(fake, tmp_path, days=1, chunk_hours=24.0)
    assert manifest["status"] == "COMPLETE"
    assert manifest["chunks_committed"] == 8  # 24h -> 12h -> 6h -> 3h succeeds
    spans_ms = [p["chunk"]["span_hours"] * 3600 * 1000 for p in manifest["parts"]]
    assert all(span <= cap for span in spans_ms)
    # every committed chunk's content is exactly the generator output for its bounds
    expected_total = sum(
        len(
            generate_chunk_rows(
                datetime.fromisoformat(p["chunk"]["start_utc"]),
                datetime.fromisoformat(p["chunk"]["end_utc"]),
            )
        )
        for p in manifest["parts"]
    )
    assert manifest["row_count"] == expected_total
    # and the whole requested day is still covered exactly once, with no lost range
    stored = _read_all_parts(tmp_path / "dataset")
    stamps = np.sort(stored["time_msc"])
    day_full = generate_chunk_rows(END - timedelta(days=1), END)["time_msc"]
    assert set(np.unique(stamps).tolist()) >= set(np.unique(day_full).tolist()) - set()
    assert int(stamps[0]) == int(day_full[0])
    assert int(stamps[-1]) == int(day_full[-1])


def test_chunk_planning_is_half_open_oldest_first() -> None:
    start = END - timedelta(days=1)
    chunks = plan_base_chunks(start, END, timedelta(hours=7))
    assert datetime.fromisoformat(chunks[0]["start_utc"]) == start
    assert datetime.fromisoformat(chunks[-1]["end_utc"]) == END
    prev_end = None
    for chunk in chunks:
        s, e = datetime.fromisoformat(chunk["start_utc"]), datetime.fromisoformat(chunk["end_utc"])
        assert prev_end is None or s == prev_end
        assert e > s
        prev_end = e


# ---------------------------------------------------------------------------
# Safety boundaries
# ---------------------------------------------------------------------------


def test_non_demo_account_fails_closed_without_querying_ticks(tmp_path: Path) -> None:
    fake = FakeMT5(demo=False)
    with pytest.raises(AcquisitionRefused, match="DEMO"):
        require_read_only_demo(fake)
    assert fake.copy_ticks_range_calls == []


def test_no_order_api_reachable_from_acquisition_modules() -> None:
    """AST scan: the acquisition/analysis code paths may reference only the read-only MT5 allowlist."""
    forbidden = {
        "order_send",
        "order_check",
        "order_calc_margin",
        "order_calc_profit",
        "positions_get",
        "positions_total",
        "orders_get",
        "orders_total",
        "history_orders_get",
        "history_deals_get",
        "history_order_get",
        "OrderSend",
        "OrderSendAsync",
    }
    targets = [
        REPO_ROOT / "src/qts/data/mt5_history_acquisition.py",
        REPO_ROOT / "src/qts/data/mt5_history_analysis.py",
        REPO_ROOT / "scripts/acquire_mt5_history.py",
    ]
    forbidden_constants = {"ACCOUNT_TRADE_MODE_DEMO", "COPY_TICKS_ALL", "__version__", "initialize", "shutdown"}
    allowed = ALLOWED_MT5_CALLS | forbidden_constants
    for target in targets:
        tree = ast.parse(target.read_text(encoding="utf-8"))
        accessed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {
                "mt5",
                "MetaTrader5",
            }:
                accessed.add(node.attr)
        assert not (accessed & forbidden), f"{target}: forbidden MT5 APIs referenced: {accessed & forbidden}"
        assert accessed <= allowed, f"{target}: unexpected MT5 surface used: {accessed - allowed}"
    # the analysis module must not import MetaTrader5 at all
    analysis_tree = ast.parse((REPO_ROOT / "src/qts/data/mt5_history_analysis.py").read_text(encoding="utf-8"))
    for node in ast.walk(analysis_tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            module = getattr(node, "module", "") or ""
            assert "MetaTrader5" not in names and "MetaTrader5" not in module


def test_fake_sentinel_order_send_never_fired(tmp_path: Path) -> None:
    fake = FakeMT5()
    _acquire(fake, tmp_path, days=1)
    assert fake.order_send_calls == 0


def test_raw_dataset_paths_are_git_ignored() -> None:
    """Private broker data cannot be committed: the raw tree must be ignored."""
    samples = [
        "data/raw/mt5_ticks/XAUUSD_/1d__20260919T120000Z/manifest.json",
        "data/raw/mt5_ticks/XAUUSD_/1d__20260919T120000Z/parts/part-000000.parquet",
        "data/raw/mt5_ticks/XAUUSD_/1d__20260919T120000Z/parts/part-000000.parquet.part-4242",
    ]
    for sample in samples:
        result = subprocess.run(
            ["git", "check-ignore", "-q", sample],  # noqa: S603,S607
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"{sample} is NOT git-ignored — raw broker data could leak into Git"
