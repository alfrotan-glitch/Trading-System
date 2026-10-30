"""No-order synthetic coverage for the one-click broker quote path.

This test deliberately mocks the MT5 API; native broker verification still
requires the owner's installed and connected Windows terminal.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from auto_stop_ticks import export_windows, read_windows


class FakeMT5:
    COPY_TICKS_INFO = 2

    def __init__(self, data_path: Path, connected=True):
        self.data_path = data_path
        self.connected = connected
        self.calls = []
        self.closed = False

    def initialize(self, *args):
        self.calls.append("initialize")
        return True

    def terminal_info(self):
        return SimpleNamespace(data_path=str(self.data_path), connected=self.connected)

    def symbol_info(self, symbol):
        return SimpleNamespace(name=symbol) if symbol == "XAUUSD@" else None

    def symbol_select(self, symbol, selected):
        return symbol == "XAUUSD@" and selected

    def copy_ticks_range(self, symbol, first, last, flags):
        self.calls.append("copy_ticks_range")
        ms = int(first.timestamp() * 1000) + 2000
        return [{"time_msc": ms, "bid": 3000.0, "ask": 3000.1}]

    def shutdown(self):
        self.closed = True

    def last_error(self):
        return (1, "fake")


def plan(path: Path, tag: str):
    with path.open("w", newline="", encoding="ascii") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([1_780_000_000_000, 1_780_000_010_000, tag])
        w.writerow([1_780_000_020_000, 1_780_000_030_000, tag])


def test_native_broker_automation_without_manual_mt5_script_or_orders(tmp_path):
    tag = "20261031_011821"
    p = tmp_path / "plan.csv"
    plan(p, tag)
    terminal = tmp_path / "terminal"
    (terminal / "MQL5" / "Experts").mkdir(parents=True)
    (terminal / "MQL5" / "Experts" / "QTS_Gold_Robot.ex5").write_bytes(b"fixture")
    fake = FakeMT5(terminal)
    result = export_windows(p, tmp_path / "quotes", tag, mt5=fake, terminal_data=terminal)
    assert result["state"] == "EXPORTED_FOR_GAP_AUDIT"
    assert result["windows_requested"] == 2
    assert result["windows_with_quotes"] == 2
    assert result["ticks_written"] == 2
    assert fake.closed
    assert fake.calls.count("copy_ticks_range") == 2
    assert "order_send" not in fake.calls
    assert len(list((tmp_path / "quotes").glob("ticks_*.csv"))) == 2
    with pytest.raises(FileExistsError):
        export_windows(p, tmp_path / "quotes", tag, mt5=fake, terminal_data=terminal)


def test_wrong_terminal_rejected_without_quotes(tmp_path):
    tag = "20261031_011821"
    p = tmp_path / "plan.csv"
    plan(p, tag)
    terminal = tmp_path / "correct"
    (terminal / "MQL5" / "Experts").mkdir(parents=True)
    (terminal / "MQL5" / "Experts" / "QTS_Gold_Robot.ex5").write_bytes(b"fixture")
    fake = FakeMT5(tmp_path / "other")
    with pytest.raises(RuntimeError, match="Wrong MT5 terminal"):
        export_windows(p, tmp_path / "quotes", tag, mt5=fake, terminal_data=terminal)
    assert fake.closed
    assert (tmp_path / "quotes" / "export_status.json").exists()
    assert "copy_ticks_range" not in fake.calls


def test_wrong_run_tag_is_rejected(tmp_path):
    tag = "20261031_011821"
    p = tmp_path / "plan.csv"
    plan(p, tag)
    with pytest.raises(ValueError, match="wrong-run"):
        read_windows(p, "20261031_112233")


def test_code_never_invokes_trade_order_api():
    source = (ROOT / "research" / "auto_stop_ticks.py").read_text("utf-8")
    assert "mt5.order_send(" not in source
    assert "mt5.login(" not in source
    assert "mt5.order_check(" not in source
    launcher = (ROOT.parent / "QTS_ONE_CLICK_ROBOT.ps1").read_text("utf-8")
    assert "QTS_AUTO_BROKER_TICKS" in launcher
    assert "QTS_POST_STOP_REVIEW.zip" in launcher
    assert "-arguments" in launcher
    assert "order_send" not in launcher
