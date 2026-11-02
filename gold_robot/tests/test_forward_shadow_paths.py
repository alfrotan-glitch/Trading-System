"""Fail-closed prospective 60-minute bid/ask paths, never fill/PnL tests."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLD / "research"))

from forward_shadow_observer import FIELDS, freeze
from forward_shadow_paths import quote_path, review, _native_events

START = 1_780_000_000


class QuoteTerminal:
    COPY_TICKS_ALL = 0

    def __init__(self, *, gap=False, empty=False, invalid=False):
        self.gap = gap
        self.empty = empty
        self.invalid = invalid
        self.calls = []

    def copy_ticks_range(self, symbol, start, end, mode):
        assert symbol == "XAUUSD@" and mode == self.COPY_TICKS_ALL
        assert start.tzinfo is not None and end.tzinfo is not None
        self.calls.append((start, end))
        if self.empty:
            return []
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        times = range(0, 3601, 30)
        if self.gap:
            times = [0, 30, 60, 90, 3500, 3530, 3560, 3590, 3600]
        rows = []
        for i in times:
            stamp = start_ms + i * 1000
            if stamp > end_ms:
                continue
            bid = 2450.5 + (i % 240) / 80.0
            ask = bid + 0.25
            rows.append({"time_msc": stamp, "bid": bid, "ask": ask})
        if self.invalid and rows:
            rows[0]["ask"] = rows[0]["bid"] - 1.0
        return rows


def make(tmp_path, *, style=3, side="BUY", when=START + 60):
    src = tmp_path / "EA.mq5"
    src.write_text("frozen native source", encoding="utf-8")
    reports = tmp_path / "reports"
    signal_files = tmp_path / "files"
    signal_files.mkdir()
    freeze(reports, src, now_utc_s=START)
    bar = when - 965
    path = signal_files / ("QTS_ForwardShadowV2_Style%d_%s.csv" % (
        style, datetime.fromtimestamp(when, timezone.utc).strftime("%Y%m")))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDS), delimiter=";")
        writer.writeheader()
        writer.writerow({
            "schema": "qts.mt5.forward_shadow_signal.v2",
            "observed_utc_s": when, "closed_bar_open_server_s": bar,
            "tick_server_time_msc": (when - 1) * 1000,
            "symbol": "XAUUSD@", "timeframe": "M15", "style": style,
            "side": side, "bid": 2450.21, "ask": 2450.42,
            "atr14": 6.0, "prior_48_atr_median": 10.0,
            "atr_band": "AT_OR_BELOW_TRAILING_MEDIAN",
            "source": "NATIVE_CLOSED_BAR_UNARMED_DEMO",
        })
    return reports, signal_files, src


def test_future_quote_path_only_after_maturity_and_in_quote_units(tmp_path):
    reports, signals, src = make(tmp_path)
    broker = QuoteTerminal()
    first = review(reports, signals, src, broker, now_utc_s=START + 900)
    assert first["status"] == "WAITING_FOR_COMPLETED_POST_SIGNAL_WINDOWS"
    assert first["quote_paths_complete_by_gap_heuristic"] == 0
    assert broker.calls == []
    second = review(reports, signals, src, broker, now_utc_s=START + 3900)
    assert second["status"] == "POST_SIGNAL_QUOTE_EXCURSIONS_ONLY_UNVALIDATED"
    assert second["quote_paths_complete_by_gap_heuristic"] == 1
    row = second["post_signal_price_paths"][0]
    assert row["favorable_quote_excursion_price"] > 0
    assert row["adverse_quote_excursion_price"] >= 0
    assert row["quote_units"].startswith("XAUUSD dollars per troy ounce")
    assert not row["executed_entry_fill_known"]
    assert not row["sl_hit_known"]
    assert not row["tp_hit_known"]
    assert second["validated_edge"] is False
    assert second["live"] == "LOCKED"


@pytest.mark.parametrize("issue", ["gap", "empty", "invalid"])
def test_missing_or_gapped_quotes_never_turn_into_a_win(tmp_path, issue):
    reports, signals, src = make(tmp_path)
    terminal = QuoteTerminal(**{issue: True})
    out = review(reports, signals, src, terminal, now_utc_s=START + 3900)
    assert out["status"] == "QUOTE_PATHS_UNKNOWN_NO_GO"
    assert len(out["unknown_quote_paths"]) == 1
    assert out["quote_paths_complete_by_gap_heuristic"] == 0
    assert out["validated_edge"] is False


def test_nonprospective_signal_or_tampered_native_ea_rejected(tmp_path):
    reports, signals, src = make(tmp_path, when=START - 90)
    broker = QuoteTerminal()
    result = review(reports, signals, src, broker, now_utc_s=START + 3900)
    assert result["pre_registration_signals_excluded"] == 1
    assert result["prospective_signals_seen"] == 0
    assert broker.calls == []
    src.write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        review(reports, signals, src, broker, now_utc_s=START + 3900)


def test_clock_mismatch_makes_paths_unknown(tmp_path):
    reports, signals, src = make(tmp_path)
    # The input has structurally plausible bar age, but inconsistent PC UTC;
    # after structural acceptance, quote_path must fail the clock-binding test.
    events, unknown, old = _native_events(signals, START, START + 3900)
    assert not unknown and not old
    event = dict(events[0], tick_server_msc=events[0]["tick_server_msc"] - 240_000)
    with pytest.raises(ValueError, match="reconcile"):
        quote_path(event, QuoteTerminal(), now_utc_s=START + 3900)


def test_sell_excursions_use_ask_not_bid(tmp_path):
    reports, signals, src = make(tmp_path, side="SELL")
    out = review(reports, signals, src, QuoteTerminal(), now_utc_s=START + 3900)
    assert out["status"] == "POST_SIGNAL_QUOTE_EXCURSIONS_ONLY_UNVALIDATED"
    row = out["post_signal_price_paths"][0]
    assert row["favorable_quote_excursion_price"] == 0
    assert row["adverse_quote_excursion_price"] > 0


def test_bounded_review_processes_newest_not_stuck_on_first_64(tmp_path):
    reports, signals, src = make(tmp_path)
    csv_path = next(signals.glob("QTS_ForwardShadowV2_Style3_*.csv"))
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDS), delimiter=";")
        for i in range(1, 66):
            when = START + 60 + i * 900
            writer.writerow({
                "schema": "qts.mt5.forward_shadow_signal.v2",
                "observed_utc_s": when,
                "closed_bar_open_server_s": when - 965,
                "tick_server_time_msc": (when - 1) * 1000,
                "symbol": "XAUUSD@", "timeframe": "M15",
                "style": 3, "side": "SELL",
                "bid": 2450.21, "ask": 2450.42,
                "atr14": 6.0, "prior_48_atr_median": 10.0,
                "atr_band": "AT_OR_BELOW_TRAILING_MEDIAN",
                "source": "NATIVE_CLOSED_BAR_UNARMED_DEMO",
            })
    out = review(reports, signals, src, QuoteTerminal(), now_utc_s=START + 100000)
    assert out["prospective_signals_seen"] == 66
    assert out["not_reviewed_due_to_bounded_batch"] == 2
    assert out["quote_paths_complete_by_gap_heuristic"] == 64
    assert out["status"] == "QUOTE_PATHS_UNKNOWN_NO_GO"
    assert out["post_signal_price_paths"][-1]["signal_event_utc_s"] == START + 60 + 65 * 900


def test_no_signals_produces_waiting_report_without_terminal(tmp_path, monkeypatch):
    import forward_shadow_paths as module

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(module, "_demo_terminal",
                        lambda: (_ for _ in ()).throw(RuntimeError("Unexpected broker call")))
    monkeypatch.setattr(sys, "argv", ["forward_shadow_paths.py",
                                      "--report-dir", str(tmp_path / "reports")])
    assert module.main() == 0
    result = json.loads((tmp_path / "reports" /
                         "QTS_FORWARD_SHADOW_V2_QUOTE_PATHS.json").read_text("utf-8"))
    assert result["status"] == "WAITING_FOR_NEW_NATIVE_SIGNALS"
    assert result["validated_edge"] is False


def test_broker_quote_reader_requires_exact_native_terminal_binding(tmp_path, monkeypatch):
    import types
    from forward_shadow_paths import _demo_terminal

    exe = tmp_path / "mt5" / "terminal64.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"fixture: not an executable")
    data = tmp_path / "terminal_data"
    data.mkdir()
    calls = []

    class FakeMt5:
        ACCOUNT_TRADE_MODE_DEMO = 0

        def initialize(self, **kwargs):
            calls.append(("initialize", kwargs))
            return True

        def account_info(self):
            return types.SimpleNamespace(trade_mode=0, server="WMMarkets-Demo")

        def terminal_info(self):
            return types.SimpleNamespace(
                connected=True, path=str(exe.parent), data_path=str(data)
            )

        def symbol_info(self, name):
            assert name == "XAUUSD@"
            return object()

        def shutdown(self):
            calls.append(("shutdown", {}))

    fake = FakeMt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    with pytest.raises(ValueError, match="PINNED_MT5_TARGET_REQUIRED_NO_GO"):
        _demo_terminal()
    assert _demo_terminal(executable=exe, data_dir=data) is fake
    assert calls == [("initialize", {"path": str(exe)})]


def test_broker_reader_rejects_another_terminal_with_same_broker(tmp_path, monkeypatch):
    import types
    from forward_shadow_paths import _demo_terminal

    exe = tmp_path / "first" / "terminal64.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"fake")
    data = tmp_path / "requested_data"
    data.mkdir()
    calls = []

    class WrongInstance:
        ACCOUNT_TRADE_MODE_DEMO = 0

        def initialize(self, **kwargs):
            return True

        def account_info(self):
            return types.SimpleNamespace(trade_mode=0, server="WMMarkets-Demo")

        def terminal_info(self):
            return types.SimpleNamespace(connected=True, path=str(exe.parent),
                                         data_path=str(tmp_path / "WRONG_DATA"))

        def symbol_info(self, name):
            return object()

        def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setitem(sys.modules, "MetaTrader5", WrongInstance())
    with pytest.raises(ValueError, match="PINNED_MT5_IDENTITY_OR_DEMO_MISMATCH_NO_GO"):
        _demo_terminal(executable=exe, data_dir=data)
    assert calls == ["shutdown"]


def test_quote_path_source_is_read_only():
    source = (GOLD / "research" / "forward_shadow_paths.py").read_text(encoding="utf-8")
    for illegal in ("order_send(", "OrderSend(", "mt5.login(", "strategy_promotion("):
        assert illegal not in source
    assert "No limit-entry fill" in source
    assert "REAL account" not in source or "Wrong" in source
