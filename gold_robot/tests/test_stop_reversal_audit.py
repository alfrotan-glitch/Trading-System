"""Synthetic no-lookahead tests of the offline STOP-path analyzer."""
from pathlib import Path
import importlib.util

import pytest

MODULE = Path(__file__).resolve().parents[1] / "research/stop_reversal_audit.py"
spec = importlib.util.spec_from_file_location("stop_reversal_audit", MODULE)
import sys
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def trade(ident, side, entry, sl, exit_price, exit_ms=60000):
    return {
        "trade_id": ident, "side": side, "entry_time_ms": "0",
        "exit_time_ms": str(exit_ms), "entry_price": str(entry),
        "initial_stop_price": str(sl), "exit_price": str(exit_price),
        "exit_reason": "SL",
    }


def ticks_to_130_minutes(price_fn):
    # Minute-aligned executable quotes; first observation is 1 minute after exit.
    for minute in range(1, 132):
        ms = 60000 + minute * 60000
        bid, ask = price_fn(minute)
        yield {"time_ms": str(ms), "bid": str(bid), "ask": str(ask)}


def test_buy_sl_then_7min_recovery_does_not_rewrite_5min_history():
    stops, ignored = mod.load_stops([
        trade("a", "BUY", 100, 95, 94),
        dict(trade("skip", "BUY", 100, 95, 94), exit_reason="TP"),
    ])
    assert ignored == 1
    ticks = ticks_to_130_minutes(
        lambda minute: (94.5, 94.7) if minute < 7 else (100.25, 100.45)
    )
    result = mod.audit(stops, ticks)
    assert result["stop_trades"] == 1
    assert result["horizons_minutes"]["5"]["reclaimed_entry_count"] == 0
    assert result["horizons_minutes"]["15"]["reclaimed_entry_count"] == 1
    assert result["horizons_minutes"]["30"]["reclaimed_entry_count"] == 1
    assert result["horizons_minutes"]["15"]["reclaimed_entry_fraction"] == 1.0
    assert result["status"] == "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY"


def test_sell_stop_recovery_requires_executable_ask_not_bid():
    stops, _ = mod.load_stops([trade("s", "SELL", 100, 105, 106)])
    # Bid dips below 100 by minute 8, but ASK remains >100 until minute 20.
    def quote(minute):
        if minute < 8:
            return 105.5, 105.7
        if minute < 20:
            return 99.9, 100.2
        return 99.3, 99.5
    result = mod.audit(stops, ticks_to_130_minutes(quote))
    assert result["horizons_minutes"]["15"]["reclaimed_entry_count"] == 0
    assert result["horizons_minutes"]["30"]["reclaimed_entry_count"] == 1


def test_incomplete_tick_coverage_is_not_counted_as_a_failed_recovery():
    stops, _ = mod.load_stops([trade("gap", "BUY", 100, 95, 94)])
    def sparse():
        for minute in (1, 2, 3, 4, 5, 6, 7, 95, 96, 130):
            yield {"time_ms": str(60000 + minute * 60000),
                   "bid": "101", "ask": "101.2"}
    result = mod.audit(stops, sparse())
    # Long 1+ hour gap; never present a fabricated 60/120-min recovery rate.
    assert result["horizons_minutes"]["5"]["eligible_stops_with_contiguous_executable_quotes"] == 1
    assert result["horizons_minutes"]["60"]["reclaimed_entry_fraction"] is None
    assert result["horizons_minutes"]["120"]["reclaimed_entry_fraction"] is None


def test_entry_must_be_before_stop_and_ticks_monotone():
    with pytest.raises(ValueError):
        mod.load_stops([trade("bad", "BUY", 100, 105, 104)])
    good, _ = mod.load_stops([trade("good", "BUY", 100, 95, 94)])
    with pytest.raises(ValueError):
        mod.audit(good, [
            {"time_ms": "200000", "bid": "100", "ask": "100.2"},
            {"time_ms": "100000", "bid": "100", "ask": "100.2"},
        ])


def test_empty_or_incomplete_data_never_pretend_profitable():
    stops, _ = mod.load_stops([trade("z", "BUY", 100, 95, 94)])
    result = mod.audit(stops, [])
    assert result["stop_trades"] == 1
    assert all(x["reclaimed_entry_fraction"] is None
               for x in result["horizons_minutes"].values())


def test_source_has_no_order_or_account_access():
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("OrderSend(", "order_send(", "mt5.initialize(", "WebRequest("):
        assert forbidden not in source
