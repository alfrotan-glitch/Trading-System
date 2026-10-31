"""Autonomous research must remain bounded, reproducible and read-only."""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from autonomous_learning import (
    accepted_window, cycle, lessons, next_window, read_verified_archive
)
from test_revised_v2_contract import fake_run


def bundle(root: Path, destination: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for arm in ("BASELINE", "ENTRY_FILTER", "NEAR_TP", "COMBINED"):
        fake_run(root / arm.lower(), arm, profit=5.)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as z:
        for path in root.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(root).as_posix())
    return destination


def test_report_is_learned_once_and_never_enables_trading(tmp_path):
    zipped = bundle(tmp_path / "native", tmp_path / "evidence" / "a" /
                    "QTS_V2_ABLATION_EVIDENCE.zip")
    native = read_verified_archive(zipped)
    assert native["edge_validated"] is False
    assert native["live"] == "LOCKED"
    assert native["from_date"] == "2026.10.01"
    first = cycle(tmp_path / "evidence", tmp_path / "journal", date(2026, 12, 1))
    again = cycle(tmp_path / "evidence", tmp_path / "journal", date(2026, 12, 1))
    assert first["evidence_receipts"] == again["evidence_receipts"] == 1
    assert first["lessons"]["unique_periods"] == 1
    assert first["next_monthly_test"]["from_date"] == "2026.11.01"
    assert first["live"] == "LOCKED"
    assert not first["edge_validated"]
    assert not first["auto_modify_ea"]
    assert (tmp_path / "journal" / "QTS_AUTONOMOUS_STATUS.json").is_file()


def test_independent_month_only_and_bounded_failed_attempts():
    assert accepted_window("2026.10.01", "2026.10.30")
    assert accepted_window("2026.11.01", "2026.12.01")
    assert not accepted_window("2026.10.01", "2026.11.01")
    assert not accepted_window("2026.11.05", "2026.12.01")
    assert next_window(date(2026, 11, 30), [], {}) is None
    period = next_window(date(2026, 12, 1), [], {})
    assert (period["from_date"], period["to_date"]) == ("2026.11.01", "2026.12.01")
    assert next_window(date(2026, 12, 1), [], {"2026.11.01": 2}) is None
    assert next_window(date(2026, 12, 1),
                       [{"period_start": "2026.11.01",
                         "period_end": "2026.12.01"}], {}) is None


def test_duplicate_period_does_not_count_as_independent_support(tmp_path):
    zipped = bundle(tmp_path / "native", tmp_path / "evidence" / "a" /
                    "QTS_V2_ABLATION_EVIDENCE.zip")
    other = tmp_path / "evidence" / "b" / "QTS_V2_ABLATION_EVIDENCE.zip"
    other.parent.mkdir(parents=True, exist_ok=True)
    # Same broker evidence, a changed non-authoritative run note.
    with zipfile.ZipFile(zipped) as src, zipfile.ZipFile(other, "w") as dst:
        for item in src.namelist():
            dst.writestr(item, src.read(item))
        dst.writestr("RUN_STATUS.txt", "second alleged run")
    result = cycle(tmp_path / "evidence", tmp_path / "journal", date(2026, 12, 1))
    assert result["evidence_receipts"] == 2
    assert result["lessons"]["unique_periods"] == 0
    assert result["lessons"]["conflicting_periods"]
    assert all(s["approved_configuration"] is None
               for s in result["lessons"]["strategies"])


def test_invalid_zip_does_not_leak_into_lessons(tmp_path):
    zip_path = tmp_path / "evidence" / "x" / "QTS_V2_ABLATION_EVIDENCE.zip"
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("../bad.exe", b"unsafe")
    result = cycle(tmp_path / "evidence", tmp_path / "journal", date(2026, 12, 1))
    assert result["evidence_receipts"] == 0
    assert result["rejected_evidence"]
    assert result["lessons"]["unique_periods"] == 0


def test_scheduled_windows_runner_keeps_money_locked():
    runner = (ROOT.parent / "QTS_AUTONOMOUS_RESEARCH.ps1").read_text("utf-8")
    launcher = (ROOT.parent / "QTS_AUTONOMOUS_RESEARCH.bat").read_text("utf-8")
    native = (ROOT.parent / "QTS_V2_ABLATION.ps1").read_text("utf-8")
    assert "Register-ScheduledTask" in runner
    assert "New-ScheduledTaskTrigger -Daily" in runner
    assert "LogonType Interactive" in runner
    assert "Mutex" in runner
    assert "--reserve" in runner
    assert "NoOpen" in runner and "NoOpen" in native
    assert "QTS_AUTONOMOUS_RESEARCH.ps1" in launcher
    assert "order_send" not in runner.lower()
    assert "EnableDemoForwardOrders" not in runner
    assert "CONNECTED LIVE/DEMO ORDERS LOCKED" in native
