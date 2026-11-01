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
    COPY_TICKS_INFO = 1

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
        assert mode == self.COPY_TICKS_INFO
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


def test_partial_real_tick_coverage_is_packaged_with_no_go_exit():
    batch = (ROOT.parent / "QTS_POST_STOP_REVIEW.bat").read_text("utf-8")
    pack = (ROOT / "research" / "PackTradeEvidence.ps1").read_text("utf-8")
    assert 'set "QTS_POST_STOP_PARTIAL="' in batch
    assert 'if exist "%OUT%\\QTS_V4_POST_STOP_STRATEGY_COHORTS.json"' in batch
    assert 'set "QTS_POST_STOP_PARTIAL=1"' in batch
    assert "if defined QTS_POST_STOP_PARTIAL (" in batch
    assert "exit /b 2" in batch
    assert 'call "%REPO%QTS_SHARE_RESULTS.bat"' in batch
    assert "'post_stop_review/'+$name" in pack
    assert "raw broker ticks" in pack


class BrokenQuoteFakeMT5(FakeMT5):
    def copy_ticks_range(self, symbol, start, end, mode):
        rows = super().copy_ticks_range(symbol, start, end, mode)
        # Native MT5 may provide historical records with incomplete or
        # crossed executable quotes. The short pre-anomaly horizon is valid.
        rows.append({
            "time_msc": EXIT + 20 * 60_000,
            "bid": 0.0,
            "ask": 0.0,
        })
        rows.sort(key=lambda x: x["time_msc"])
        return rows


def test_zero_quote_does_not_abort_all_stops_or_falsify_long_horizon():
    replay, cohorts = replay_from_mt5(attribution(), BrokenQuoteFakeMT5())
    assert replay["quote_data_quality"]["mt5_tick_selection"] == "COPY_TICKS_INFO_BID_ASK_CHANGES_ONLY"
    assert replay["quote_data_quality"]["bad_bid_ask_rows"] == 1
    assert replay["quote_data_quality"]["per_stop"][0]["affected_unknown_horizons_minutes"] == [30, 60, 120]
    by_h = cohorts["stopped_positions"][0]["horizons"]
    assert by_h["5"]["quote_evidence"] == "COMPLETE"
    assert by_h["15"]["quote_evidence"] == "COMPLETE"
    for horizon in ("30", "60", "120"):
        assert by_h[horizon]["quote_evidence"] == "UNKNOWN"
        assert by_h[horizon]["original_tp_touched"] is None
    assert cohorts["status"] == "INCOMPLETE_TICK_COVERAGE_NO_GO"


def test_crossed_bid_ask_is_quarantined_without_trusting_tp_recovery():
    class Crossed(BrokenQuoteFakeMT5):
        def copy_ticks_range(self, *args):
            rows = super().copy_ticks_range(*args)
            rows[-100]["bid"] = 102.0
            rows[-100]["ask"] = 101.0
            return rows

    replay, cohorts = replay_from_mt5(attribution(), Crossed())
    assert replay["quote_data_quality"]["bad_bid_ask_rows"] >= 2
    assert cohorts["stopped_positions"][0]["horizons"]["120"]["quote_evidence"] == "UNKNOWN"


def test_out_of_order_native_broker_ticks_invalidate_all_windows():
    class Backward(FakeMT5):
        def copy_ticks_range(self, *args):
            rows = super().copy_ticks_range(*args)
            rows[12], rows[13] = rows[13], rows[12]
            return rows

    replay, cohorts = replay_from_mt5(attribution(), Backward())
    assert replay["quote_data_quality"]["out_of_order_rows"] == 1
    assert all(
        x["quote_evidence"] == "UNKNOWN"
        for x in cohorts["stopped_positions"][0]["horizons"].values()
    )


def test_failed_one_stop_history_read_is_unknown_not_total_exception():
    class Failed(FakeMT5):
        def copy_ticks_range(self, *args):
            return None

    replay, cohorts = replay_from_mt5(attribution(), Failed())
    assert replay["quote_data_quality"]["failed_history_reads"] == 1
    assert cohorts["status"] == "INCOMPLETE_TICK_COVERAGE_NO_GO"
    assert cohorts["stopped_positions"][0]["horizons"]["120"]["quote_evidence"] == "UNKNOWN"


def test_quarantine_prevents_packing_a_stale_prior_quote_result():
    batch = (ROOT.parent / "QTS_POST_STOP_REVIEW.bat").read_text("utf-8")
    assert "A failed new query must NEVER re-share stale" in batch
    assert "del /f /q" in batch
    assert "stale post-stop analysis file could not be cleared" in batch


class MT5SecondBoundaryFake(FakeMT5):
    """MT5 may include quote ticks in the UTC second containing the stop."""
    def copy_ticks_range(self, symbol, start, end, mode):
        assert int(start.timestamp() * 1000) == (EXIT // 1000) * 1000
        assert int(end.timestamp() * 1000) == ((EXIT + 121 * 60_000 + 999) // 1000) * 1000
        rows = super().copy_ticks_range(symbol, start, end, mode)
        rows[:0] = [
            {"time_msc": EXIT - 160, "bid": 99.1, "ask": 99.3},
            {"time_msc": EXIT - 10, "bid": 99.1, "ask": 99.3},
        ]
        return rows


def test_second_boundary_quotes_are_ignored_without_falsifying_tp_paths():
    replay, cohorts = replay_from_mt5(attribution(), MT5SecondBoundaryFake())
    assert cohorts["status"] == "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"
    quality = replay["quote_data_quality"]
    assert quality["ignored_pre_stop_boundary_rows"] == 2
    assert quality["out_of_range_rows"] == 0
    assert quality["out_of_order_rows"] == 0
    assert quality["per_stop"][0]["ignored_pre_stop_boundary_rows"] == 2
    assert cohorts["stopped_positions"][0]["horizons"]["120"]["original_tp_touched"] is True


def test_only_post_buffer_boundary_overfetch_is_ignored():
    class AfterBuffer(FakeMT5):
        def copy_ticks_range(self, symbol, start, end, mode):
            rows = super().copy_ticks_range(symbol, start, end, mode)
            end_ms = EXIT + 121 * 60_000
            rows.append({"time_msc": end_ms + 200, "bid": 102.0, "ask": 102.1})
            return rows

    replay, cohorts = replay_from_mt5(attribution(), AfterBuffer())
    assert replay["quote_data_quality"]["ignored_post_buffer_boundary_rows"] == 1
    assert replay["quote_data_quality"]["out_of_range_rows"] == 0
    assert cohorts["status"] == "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"


@pytest.mark.parametrize("bad_ms_delta", [-1500, 121 * 60_000 + 1500])
def test_materially_outside_requested_seconds_cannot_validate_recovery(bad_ms_delta):
    class WrongDate(FakeMT5):
        def copy_ticks_range(self, symbol, start, end, mode):
            rows = super().copy_ticks_range(symbol, start, end, mode)
            rows.append({"time_msc": EXIT + bad_ms_delta, "bid": 102.0, "ask": 102.1})
            rows.sort(key=lambda item: item["time_msc"])
            return rows

    replay, cohorts = replay_from_mt5(attribution(), WrongDate())
    assert replay["quote_data_quality"]["out_of_range_rows"] == 1
    assert all(
        w["quote_evidence"] == "UNKNOWN"
        for w in cohorts["stopped_positions"][0]["horizons"].values()
    )


def test_out_of_order_boundary_quote_remains_unknown():
    class WrongBoundaryOrder(MT5SecondBoundaryFake):
        def copy_ticks_range(self, *args):
            rows = super().copy_ticks_range(*args)
            rows[0], rows[1] = rows[1], rows[0]
            return rows

    replay, cohorts = replay_from_mt5(attribution(), WrongBoundaryOrder())
    assert replay["quote_data_quality"]["out_of_order_rows"] == 1
    assert cohorts["status"] == "INCOMPLETE_TICK_COVERAGE_NO_GO"
