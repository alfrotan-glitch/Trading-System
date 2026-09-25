"""End-to-end driver contracts: boundary ladder + deferred analysis + evidence.

The MetaTrader5 module is injected into sys.modules with a deterministic fake —
no live broker in CI.  These tests pin the full acquisition workflow:
fail-closed environment gate, per-window acquisition, independent deferred
analysis, bounded evidence JSON, resume/reuse semantics and order-API absence.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes_mt5 import FakeMT5, generate_chunk_rows

_RELPATH = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_RELPATH))

from scripts.acquire_mt5_history import main as driver_main  # noqa: E402

END = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


def _run_driver(tmp_path: Path, fake: FakeMT5, *extra: str) -> tuple[int, dict]:
    args = [
        "--symbol",
        "XAUUSD@",
        "--dataset-root",
        str(tmp_path / "raw"),
        "--evidence",
        str(tmp_path / "evidence.json"),
        "--end-utc",
        END.isoformat(),
        "--chunk-hours",
        "12",
        "--max-runtime-minutes",
        "10",
        *extra,
    ]
    code = driver_main(args)
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    return code, evidence


def test_driver_end_to_end_acquire_then_analyze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    code, evidence = _run_driver(tmp_path, fake, "--windows-days", "2,3")
    assert code == 0
    assert evidence["status"] == "ACQUISITION_LADDER_COMPLETE"
    assert evidence["read_only"] is True
    assert evidence["orders_submitted"] == 0
    assert fake.order_send_calls == 0
    assert fake.shutdown_calls == 1
    assert evidence["actual_symbol"] == "XAUUSD@"
    assert evidence["environment"]["is_demo"] is True
    assert evidence["result_summary"]["largest_complete_window_days"] == 3

    windows = {w["window_days"]: w for w in evidence["windows"]}
    assert set(windows) == {2, 3}
    for _days, window in windows.items():
        assert window["status"] == "COMPLETE", window
        summary = window["manifest_summary"]
        assert summary["row_count"] > 0
        assert summary["dataset_sha256"]
        assert summary["returned_fields"] == ["time", "bid", "ask", "last", "volume", "time_msc", "flags", "volume_real"]
        assert summary["timestamp_interpretation_confirmed"] is False
        # deferred analysis ran AFTER acquisition, from the local dataset
        assert window["analysis"] == "PASS"
        report_path = Path(window["analysis_report"])
        assert report_path.exists()
        analysis = json.loads(report_path.read_text(encoding="utf-8"))
        assert analysis["content"]["row_count"] == summary["row_count"]
        # driver process legitimately has the package loaded; the analysis itself never imports it
        assert analysis["analysis_independence"]["mt5_package_present_in_process"] is True

    # boundary assessment states facts without inventing a retention limit
    assessment = evidence["boundary_assessment"]
    assert assessment["largest_complete_window_days"] == 3
    assert "UNKNOWN_BOUNDARY" in assessment["retention_limit_classification"]

    # the analysis evidence contains no raw rows (bounded payload policy)
    analysis_2d = json.loads((tmp_path / windows[2]["analysis_report"]).read_text(encoding="utf-8"))

    def walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            keys = set(node)
            row_like = {"time_msc", "bid", "ask"} <= keys and isinstance(node.get("bid"), (int, float))
            assert not row_like, f"raw row leaked at {path}"
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            assert len(node) <= 512, f"unbounded list at {path}: {len(node)}"
            for idx, value in enumerate(node):
                walk(value, f"{path}[{idx}]")

    walk(evidence)
    walk(analysis_2d)


def test_driver_reuses_existing_complete_datasets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    code, _ = _run_driver(tmp_path, fake, "--windows-days", "2")
    assert code == 0
    calls_first = len(fake.copy_ticks_range_calls)
    assert calls_first > 0
    code, evidence = _run_driver(tmp_path, fake, "--windows-days", "2")
    assert code == 0
    window = evidence["windows"][0]
    assert window["status"] == "REUSED_EXISTING_COMPLETE"
    assert len(fake.copy_ticks_range_calls) == calls_first, "a COMPLETE window must not be re-queried"


def test_driver_refuses_non_demo_before_any_tick_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake = FakeMT5(demo=False)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    code, evidence = _run_driver(tmp_path, fake, "--windows-days", "2")
    assert code == 2
    assert evidence["status"] == "REFUSED_FAIL_CLOSED"
    assert fake.copy_ticks_range_calls == []
    assert fake.order_send_calls == 0


def test_driver_reports_mt5_package_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)  # import MetaTrader5 -> ImportError
    args = [
        "--windows-days",
        "2",
        "--dataset-root",
        str(tmp_path / "raw"),
        "--evidence",
        str(tmp_path / "evidence.json"),
    ]
    code = driver_main(args)
    assert code == 2
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "MT5_PACKAGE_UNAVAILABLE"
    assert evidence["read_only"] is True
    assert evidence["windows"] == []  # nothing queried, nothing fabricated


def test_driver_interrupted_window_is_partial_and_resumable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake = FakeMT5(raise_keyboard_interrupt_calls={2})
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    code, evidence = _run_driver(tmp_path, fake, "--windows-days", "2")
    assert code == 0  # the ladder itself completes; the window is honestly partial
    window = evidence["windows"][0]
    assert window["status"] == "PARTIAL_INTERRUPTED"
    assert window["manifest_summary"]["row_count"] > 0  # committed chunks survive
    assert window.get("analysis") == "PASS"  # analysis runs on the partial dataset without calling it complete
    # resume completes the same window without re-querying committed chunks
    fake2 = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake2)
    code2, evidence2 = _run_driver(tmp_path, fake2, "--windows-days", "2")
    assert code2 == 0
    window2 = evidence2["windows"][0]
    assert window2["status"] == "COMPLETE"
    assert window2["manifest_summary"]["resumed_from_previous_run"] is True
    expected_total = sum(
        len(
            generate_chunk_rows(
                END - timedelta(days=2) + timedelta(hours=12 * k),
                END - timedelta(days=2) + timedelta(hours=12 * (k + 1)),
            )
        )
        for k in range(4)
    )
    assert window2["manifest_summary"]["row_count"] == expected_total


def test_driver_analyze_only_needs_no_mt5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    code, _ = _run_driver(tmp_path, fake, "--windows-days", "1")
    assert code == 0
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    dataset_dir = evidence["windows"][0]["dataset_dir"]
    # now purge MetaTrader5 entirely and analyze offline
    monkeypatch.delitem(sys.modules, "MetaTrader5", raising=False)
    code = driver_main(["--analyze-only", dataset_dir])
    assert code == 0
    offline = json.loads((Path(dataset_dir) / "analysis.json").read_text(encoding="utf-8"))
    assert offline["provenance_validation"]["overall"] == "PASS"
    assert offline["analysis_independence"]["mt5_package_present_in_process"] is False
