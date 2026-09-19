"""Offline contracts for lossless MT5 acquisition and deferred analysis."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow.dataset as ds
import pytest

from qts.data.mt5_history import (
    AcquisitionError,
    SchemaDriftError,
    acquire_mt5_ticks,
    analyze_mt5_dataset,
)

FIELDS = ["time", "time_msc", "bid", "ask", "last", "volume", "flags", "volume_real"]
DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("time_msc", "<i8"),
        ("bid", "<f8"),
        ("ask", "<f8"),
        ("last", "<f8"),
        ("volume", "<u8"),
        ("flags", "<u4"),
        ("volume_real", "<f8"),
    ]
)


def rows(*values: tuple[int, int, float, float, float, int, int, float]) -> np.ndarray:
    result = np.zeros(len(values), dtype=DTYPE)
    for index, value in enumerate(values):
        result[index] = value
    return result


class FakeMT5:
    COPY_TICKS_ALL = 7

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[datetime, datetime]] = []
        self.order_send_calls = 0

    def copy_ticks_range(self, symbol, start, end, flags):
        self.calls.append((start, end))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def order_send(self, *args, **kwargs):  # pragma: no cover - sentinel
        self.order_send_calls += 1
        raise AssertionError("historical acquisition must never call order_send")


def bounds() -> tuple[datetime, datetime]:
    end = datetime(2026, 9, 19, tzinfo=UTC)
    return end - timedelta(hours=2), end


def test_acquisition_preserves_schema_duplicates_and_same_timestamp_rows(tmp_path: Path) -> None:
    start, end = bounds()
    first = rows(
        (100, 100000, 2000.0, 2000.5, 0.0, 1, 1, 1.0),
        (100, 100000, 2000.1, 2000.6, 0.0, 1, 1, 1.0),
        (100, 100000, 2000.1, 2000.6, 0.0, 1, 1, 1.0),
    )
    second = rows((101, 100001, 2000.2, 2000.7, 0.0, 1, 1, 1.0))
    mt5 = FakeMT5([first, second])
    output = tmp_path / "xauusd-history.parquet"
    metadata = acquire_mt5_ticks(
        mt5,
        symbol="XAUUSD@",
        start_utc=start,
        end_utc=end,
        output_path=output,
        chunk_hours=1,
        context={"broker_server": "WMMarkets-Demo", "actual_symbol": "XAUUSD@"},
    )
    assert metadata["status"] == "COMPLETE"
    assert metadata["row_count"] == 4
    assert metadata["returned_schema"] == [
        {"name": name, "arrow_type": arrow, "nullable": True}
        for name, arrow in zip(FIELDS, ["int64", "int64", "double", "double", "double", "uint64", "uint32", "double"], strict=True)
    ]
    dataset = ds.dataset(output, format="parquet")
    table = dataset.to_table()
    assert table.num_rows == 4
    assert table.column("time_msc").to_pylist() == [100000, 100000, 100000, 100001]
    assert table.column("bid").to_pylist() == [2000.0, 2000.1, 2000.1, 2000.2]
    assert metadata["coverage"]["first_returned_row_timestamps"] == {"time": 100, "time_msc": 100000}
    assert mt5.order_send_calls == 0
    assert len(mt5.calls) == 2


def test_analysis_is_local_only_and_retains_duplicate_semantics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start, end = bounds()
    output = tmp_path / "history.parquet"
    acquire_mt5_ticks(
        FakeMT5([rows(
            (100, 100000, 2000.0, 2000.5, 0.0, 1, 1, 1.0),
            (100, 100000, 2000.1, 2000.6, 0.0, 1, 1, 1.0),
            (100, 100000, 2000.1, 2000.6, 0.0, 1, 1, 1.0),
        )]),
        symbol="XAUUSD@",
        start_utc=start,
        end_utc=start + timedelta(hours=1),
        output_path=output,
        chunk_hours=1,
    )
    metadata_path = Path(str(output) + ".metadata.json")
    bomb = type("NoMT5", (), {"copy_ticks_range": lambda *_: (_ for _ in ()).throw(AssertionError("MT5 contacted"))})
    monkeypatch.setitem(sys.modules, "MetaTrader5", bomb)
    report = analyze_mt5_dataset(output, metadata_path=metadata_path)
    assert report["row_count"] == 3
    assert report["duplicates"]["same_time_msc_excess_rows"] == 2
    assert report["duplicates"]["same_time_msc_distinct_quote_rows"] == 2
    assert report["duplicates"]["identical_full_row_excess_count"] == 1
    assert report["provenance_validation"]["status"] == "VALID"
    assert report["research_prerequisites"]["r5_solved"] is False


def test_interrupted_acquisition_is_marked_and_never_finalized(tmp_path: Path) -> None:
    start, end = bounds()
    output = tmp_path / "interrupted.parquet"
    mt5 = FakeMT5([rows((100, 100000, 2000.0, 2000.5, 0.0, 1, 1, 1.0)), KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        acquire_mt5_ticks(mt5, symbol="XAUUSD@", start_utc=start, end_utc=end, output_path=output, chunk_hours=1)
    assert not output.exists()
    partial_metadata = list(tmp_path.glob(".*partial-*.metadata.json"))
    assert partial_metadata
    report = json.loads(partial_metadata[0].read_text())
    assert report["status"] == "INTERRUPTED"
    assert report["row_count"] == 1
    assert not Path(str(output) + ".metadata.json").exists()


def test_query_failure_is_partial_and_restart_isolation_is_explicit(tmp_path: Path) -> None:
    start, end = bounds()
    output = tmp_path / "failed.parquet"
    with pytest.raises(AcquisitionError):
        acquire_mt5_ticks(
            FakeMT5([rows((100, 100000, 2000.0, 2000.5, 0.0, 1, 1, 1.0)), None]),
            symbol="XAUUSD@", start_utc=start, end_utc=end, output_path=output, chunk_hours=1,
        )
    partial_metadata = list(tmp_path.glob(".*partial-*.metadata.json"))
    assert json.loads(partial_metadata[0].read_text())["status"] == "PARTIAL"
    with pytest.raises(FileExistsError):
        acquire_mt5_ticks(FakeMT5([]), symbol="XAUUSD@", start_utc=start, end_utc=end, output_path=output, chunk_hours=1)


def test_schema_drift_is_persisted_separately_not_dropped(tmp_path: Path) -> None:
    start, end = bounds()
    first = rows((100, 100000, 2000.0, 2000.5, 0.0, 1, 1, 1.0))
    second = [{"time": 101, "time_msc": 100001, "bid": 2000.0, "ask": 2000.5, "future_field": "kept"}]
    output = tmp_path / "drift.parquet"
    with pytest.raises(SchemaDriftError):
        acquire_mt5_ticks(FakeMT5([first, second]), symbol="XAUUSD@", start_utc=start, end_utc=end, output_path=output, chunk_hours=1)
    drift_files = list(tmp_path.glob(".*partial-*/schema-drift-*.parquet"))
    assert drift_files
    assert "future_field" in ds.dataset(drift_files[0], format="parquet").schema.names


def test_gitignore_excludes_private_parquet_sidecars() -> None:
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "*.parquet" in ignore
    assert "*.parquet.metadata.json" in ignore
