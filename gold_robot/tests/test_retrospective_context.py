"""Synthetic read-only evidence tests for the H1/ATR/spread retrospective audit."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLD / "research"))

from retrospective_context import evaluate, market_at_entry, validate_evidence

UTC = timezone.utc
ENTRY = int(datetime(2026, 1, 15, 12, 17, tzinfo=UTC).timestamp() * 1000)


def fixtures():
    trade = {
        "style": 1,
        "position_id": "p1",
        "side": "BUY",
        "status": "COMPLETE",
        "exit_reason": "DEAL_REASON_TP",
        "entry_time_msc": str(ENTRY),
        "exit_time_msc": str(ENTRY + 30000),
        "entry_lots": 0.03,
        "exit_lots": 0.03,
        "net_usd": 11.0,
        "gross_usd": 11.0,
        "charges_usd": 0.0,
    }
    forensic = {
        "schema": "qts.mt5.trade_forensics.v1",
        "status": "SELECTED_IMPORTED_FOR_REVIEW",
        "live": "LOCKED",
        "edge_validated": False,
        "targeted": True,
        "selected_styles": [1, 3],
        "trades": [trade],
    }
    manifest = {
        "live": "LOCKED",
        "validated_edge": False,
        "targeted": True,
        "selected_styles": [1, 3],
        "research_variant": "BASELINE",
        "symbol": "XAUUSD@",
        "model": 4,
        "from_date": "2026.01.01",
        "to_date": "2026.04.01",
    }
    return forensic, manifest


class FakeMT5:
    TIMEFRAME_H1 = 1
    TIMEFRAME_M15 = 15
    COPY_TICKS_ALL = 0

    def __init__(self, *, make_quote_stale=False, future_h1_close=9000):
        self.make_quote_stale = make_quote_stale
        self.future_h1_close = future_h1_close

    def copy_rates_from(self, symbol, timeframe, end, count):
        assert symbol == "XAUUSD@"
        assert end.tzinfo == UTC
        seconds = 3600 if timeframe == self.TIMEFRAME_H1 else 900
        epoch = ENTRY // 1000
        floor = epoch // seconds * seconds
        rows = []
        for i in range(170):
            price = 4000 + (i * 0.05)
            rows.append({
                "time": floor - (170 - i) * seconds,
                "open": price - 0.01,
                "high": price + 1.1,
                "low": price - 1.1,
                "close": price,
            })
        # This bar is OPEN at entry and must never influence H1 bias / ATR.
        rows.append({
            "time": floor,
            "open": 4000,
            "high": self.future_h1_close + 1,
            "low": 1,
            "close": self.future_h1_close,
        })
        return rows

    def copy_ticks_range(self, symbol, start, end, flags):
        assert symbol == "XAUUSD@"
        assert start.tzinfo == UTC and end.tzinfo == UTC
        age = 20_000 if self.make_quote_stale else 1000
        return [
            {"time_msc": ENTRY - age, "bid": 4200, "ask": 4200.35},
            {"time_msc": ENTRY + 500, "bid": 4200, "ask": 4300},
        ]


def test_all_context_features_use_only_completed_bars_and_old_quotes():
    x = market_at_entry(FakeMT5(future_h1_close=9000), ENTRY)
    y = market_at_entry(FakeMT5(future_h1_close=200), ENTRY)
    assert x == y
    assert x["status"] == "COMPLETE_CLOSED_BAR_AND_BID_ASK"
    assert x["h1_bias"] == "BUY"
    assert x["quote_age_ms"] == 1000
    assert x["spread_price"] == pytest.approx(0.35)
    assert x["m15_atr14"] > 0
    assert x["h1_last_closed_open_utc"] + 3600 <= ENTRY / 1000
    assert x["m15_last_closed_open_utc"] + 900 <= ENTRY / 1000


def test_stale_quotes_are_unknown_and_never_replaced_with_future_ticks():
    row = market_at_entry(FakeMT5(make_quote_stale=True), ENTRY)
    assert row["status"] == "UNKNOWN_MARKET_HISTORY"
    assert "Stale" in row["missing_reason"]


def test_offline_summary_is_fail_closed_but_preserves_native_baseline():
    f, m = fixtures()
    result = evaluate(f, m, "sha256-synthetic")
    assert result["status"] == "MARKET_HISTORY_INCOMPLETE_NO_GO"
    assert result["total_positions"] == 1
    assert result["complete_market_snapshots"] == 0
    assert result["cohorts"]["style"]["1"]["native_net_usd"] == 11
    assert result["cohorts"]["style"]["1"]["after_10usd_per_lot_extra_cost"] == 10.7
    assert result["can_autotune_or_promote"] is False
    assert result["connected_orders_authorized"] is False
    assert result["live"] == "LOCKED"


def test_market_context_only_observes_and_never_vetoes_trades():
    f, m = fixtures()
    result = evaluate(f, m, "sha256-synthetic", FakeMT5())
    assert result["status"] == "DESCRIPTIVE_ONLY_REVIEW_REQUIRED"
    assert result["complete_market_snapshots"] == 1
    assert result["positions"][0]["h1_alignment"] == "ALIGNED"
    assert result["research_filters_applied_to_trading"] is False
    assert result["cohorts"]["h1_alignment"]["1:ALIGNED"]["sample_too_small_for_selection"]


def test_duplicate_positions_bad_broker_or_unknown_exit_are_rejected():
    f, m = fixtures()
    f["trades"].append(f["trades"][0].copy())
    with pytest.raises(ValueError, match="Duplicate"):
        validate_evidence(f, m)
    f["trades"].pop()
    m["symbol"] = "XAUUSD"
    with pytest.raises(ValueError, match="identity"):
        validate_evidence(f, m)
    m["symbol"] = "XAUUSD@"
    f["trades"][0]["exit_reason"] = "MIXED_EXIT_REASONS"
    with pytest.raises(ValueError, match="partial"):
        validate_evidence(f, m)


def test_never_has_order_sender_or_authentication():
    source = (GOLD / "research" / "retrospective_context.py").read_text("utf-8")
    for forbidden in ("order_send(", "OrderSend(", "mt5.login(", "ENABLE_LIVE"):
        assert forbidden not in source
    assert "can_autotune_or_promote" in source
    assert "connected_orders_authorized" in source
    assert json.loads(json.dumps(fixtures()[1]))["symbol"] == "XAUUSD@"
