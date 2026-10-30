"""Synthetic contract tests for bounded post-SL MT5 quote export.

No MT5 network connection, no order placement, no claim of real tick history.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from prepare_stop_tick_windows import prepare

FIELDS = ["trade_id", "exit_reason", "exit_time_ms"]

def write_stops(path: Path, times: list[int]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, timestamp in enumerate(times):
            w.writerow({"trade_id": str(i), "exit_reason": "SL",
                        "exit_time_ms": timestamp})

def test_overlapping_stop_windows_merge_and_do_not_export_six_months(tmp_path):
    start = 1_780_000_000_000
    source = tmp_path / "stops.csv"
    target = tmp_path / "plan.csv"
    # Out-of-order, overlapping and separated SL events
    write_stops(source, [start + 30_000, start, start + 24 * 3600_000])
    summary = prepare(source, target, "20261031_011821")
    assert summary["stop_cases"] == 3
    assert summary["merged_windows"] == 2
    with target.open(newline="", encoding="ascii") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert len(rows) == 2
    a, b = rows
    assert int(a[0]) == start - 61_000
    assert int(a[1]) == start + 30_000 + 120*60_000 + 61_000
    assert int(a[1]) < int(b[0])
    assert all(row[2] == "20261031_011821" for row in rows)
    assert int(b[1]) - int(b[0]) <= 123 * 60_000

def test_reject_invalid_tag_and_non_stop_row(tmp_path):
    source = tmp_path / "stops.csv"
    target = tmp_path / "plan.csv"
    write_stops(source, [1_780_000_000_000])
    with pytest.raises(ValueError, match="tag"):
        prepare(source, target, "../../evil")
    source.write_text("trade_id,exit_reason,exit_time_ms\n1,TP,1780000000000\n")
    with pytest.raises(ValueError, match="Non-SL"):
        prepare(source, target, "20261031_011821")

def test_exporter_is_native_read_only_and_has_no_unbounded_history_copy():
    mql = (ROOT / "research/QTS_Export_Stop_Ticks.mq5").read_text()
    assert "CopyTicksRange(" in mql
    assert "QTS_STOP_WINDOWS.csv" in mql
    assert "cursor+899999" in mql
    assert "export_status.csv" in mql
    assert "CTrade" not in mql
    assert "OrderSend(" not in mql
    assert "CopyTicks(" not in mql
    batch = (ROOT.parent / "QTS_PREPARE_STOP_TICKS.bat").read_text()
    finish = (ROOT.parent / "QTS_FINISH_STOP_TICKS.bat").read_text()
    assert "QTS_PREPARE_STOP_TICKS.ps1" in batch
    assert "QTS_FINISH_STOP_TICKS.ps1" in finish


def test_pre_stop_window_is_from_actual_entry_through_actual_exit(tmp_path):
    t = 1_780_000_000_000
    source = tmp_path / "stops.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        w = csv.DictWriter(stream, fieldnames=FIELDS + ["entry_time_ms"])
        w.writeheader()
        w.writerow({"trade_id": "one", "exit_reason": "SL",
                    "entry_time_ms": t, "exit_time_ms": t + 15 * 60_000})
        w.writerow({"trade_id": "two", "exit_reason": "SL",
                    "entry_time_ms": t + 60_000,
                    "exit_time_ms": t + 20 * 60_000})
    output = tmp_path / "pre.csv"
    details = prepare(source, output, "20261031_011821", phase="pre")
    assert details["phase"] == "pre"
    assert details["merged_windows"] == 1
    with output.open(newline="") as stream:
        rows = list(csv.reader(stream, delimiter=";"))
    assert int(rows[0][0]) == t - 61_000
    assert int(rows[0][1]) == t + 20 * 60_000 + 61_000


def test_pre_stop_rejects_impossible_entry_exit_times(tmp_path):
    t = 1_780_000_000_000
    source = tmp_path / "stops.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        w = csv.DictWriter(stream, fieldnames=FIELDS + ["entry_time_ms"])
        w.writeheader()
        w.writerow({"trade_id": "bad", "exit_reason": "SL",
                    "entry_time_ms": t + 50_000, "exit_time_ms": t})
    with pytest.raises(ValueError, match="entry timestamp"):
        prepare(source, tmp_path / "bad.csv", "20261031_011821", phase="pre")
