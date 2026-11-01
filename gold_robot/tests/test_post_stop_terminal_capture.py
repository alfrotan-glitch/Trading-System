"""Offline regressions for read-only MT5 post-stop executable quote capture.

All tick data below are synthetic; these tests never connect to MT5 or send orders.
"""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from capture_post_stop_quotes import read_attribution, replay_from_mt5


EXIT = 1790847549171


def attribution():
    row = {
        "position_id": "3", "selected_style": 4, "regime": "TREND",
        "side": "BUY", "entry_price": 100.0, "initial_sl": 99.0,
        "initial_tp": 101.5, "exit_price": 98.98,
        "entry_time_msc": EXIT - 90_000, "exit_time_msc": EXIT,
        "exit_reason": "DEAL_REASON_SL"
    }
    return {
        "schema": "qts.mt5.v4.position_strategy_attribution.v1",
        "status": "ATTRIBUTED_FOR_RESEARCH_ONLY",
        "live": "LOCKED", "edge_validated": False,
        "can_autotune_or_promote": False, "issues": [],
        "native_positions_seen": 1, "native_positions_attributed": 1,
        "positions": [row],
    }


class FakeMT5:
    COPY_TICKS_ALL = 0

    def __init__(self, *, gap_ms=30_000, server="WMMarkets-Demo", reach=True):
        self.gap_ms = gap_ms
        self.server = server
        self.reach = reach
        self.called = 0

    def account_info(self):
        return SimpleNamespace(server=self.server, currency="USD")

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbol_info(self, symbol):
        return SimpleNamespace(name=symbol) if symbol == "XAUUSD@" else None

    def copy_ticks_range(self, symbol, start, end, mode):
        assert symbol == "XAUUSD@"
        assert mode == self.COPY_TICKS_ALL
        assert start.tzinfo == timezone.utc
        self.called += 1
        limit = int(end.timestamp() * 1000)
        rows = []
        for ms in range(EXIT + 10_000, limit + 1, self.gap_ms):
            price = 102.0 if self.reach and ms > EXIT + 40 * 60_000 else 98.5
            rows.append({"time_msc": ms, "bid": price, "ask": price + .05})
        return rows

    def last_error(self):
        return (0, "fake")


def test_native_quote_paths_are_executable_broker_sides_and_reconciled():
    fake = FakeMT5()
    replay, cohorts = replay_from_mt5(attribution(), fake)
    assert fake.called == 1
    assert replay["status"] == "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY"
    assert replay["same_source_as_native_tester_not_proven"] is True
    assert len(replay["historical_quote_fingerprint_sha256"]) == 64
    assert replay["stop_trades"] == 1
    assert cohorts["status"] == "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"
    h120 = cohorts["by_strategy_and_regime"][0]["horizons"]["120"]
    assert h120["eligible_quote_complete"] == 1
    assert h120["original_tp_touched"] == 1
    assert h120["entry_reclaimed"] == 1
    h15 = cohorts["by_strategy_and_regime"][0]["horizons"]["15"]
    assert h15["eligible_quote_complete"] == 1
    assert h15["original_tp_touched"] == 0


def test_quote_gap_is_unknown_not_false_positive_tp_or_failure():
    replay, cohorts = replay_from_mt5(attribution(), FakeMT5(gap_ms=180_000))
    assert replay["stop_trades"] == 1
    assert cohorts["status"] == "INCOMPLETE_TICK_COVERAGE_NO_GO"
    entry = cohorts["stopped_positions"][0]["horizons"]["120"]
    assert entry["quote_evidence"] == "UNKNOWN"
    assert entry["original_tp_touched"] is None


def test_source_conflict_prevents_any_read_of_quote_history():
    mt5 = FakeMT5(server="UnrelatedBroker")
    with pytest.raises(ValueError, match="Wrong MT5 server"):
        replay_from_mt5(attribution(), mt5)
    assert mt5.called == 0


def test_native_missing_tick_history_does_not_fabricate_reversal():
    fake = FakeMT5()
    fake.copy_ticks_range = lambda *args: []
    replay, cohorts = replay_from_mt5(attribution(), fake)
    assert cohorts["status"] == "INCOMPLETE_TICK_COVERAGE_NO_GO"
    assert all(
        r["quote_evidence"] == "UNKNOWN"
        for r in cohorts["stopped_positions"][0]["horizons"].values()
    )


def test_original_broker_evidence_must_be_valid_zip(tmp_path):
    path = tmp_path / "original.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("QTS_V4_POSITION_ATTRIBUTION.json",
                         json.dumps(attribution()))
    assert len(read_attribution(path)["positions"]) == 1
    bad = attribution()
    bad["edge_validated"] = True
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("QTS_V4_POSITION_ATTRIBUTION.json", json.dumps(bad))
    with pytest.raises(ValueError, match="incomplete|inconsistent"):
        read_attribution(path)


def test_one_click_review_is_read_only_and_does_not_modify_live_permissions():
    script = (ROOT / "research" / "capture_post_stop_quotes.py").read_text("utf-8")
    root = ROOT.parent
    menu = (root / "START_HERE.bat").read_text("utf-8")
    launcher = (root / "QTS_POST_STOP_REVIEW.bat").read_text("utf-8")
    assert "copy_ticks_range(" in script
    assert "OrderSend(" not in script and "order_send(" not in script
    assert "same_source_as_native_tester_not_proven" in script
    assert "LIVE LOCKED" in script
    assert "choice /C 123456789A" in menu
    assert "goto STOP_QUOTES" in menu
    assert "capture_post_stop_quotes.py" in launcher
    assert "QTS_BROKER_TICKS_DIR" in launcher
