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
        "exit_legs": [{
            "deal_id": "exit-1",
            "reason": "DEAL_REASON_TP",
            "time_msc": str(ENTRY + 30000),
            "lots": 0.03,
            "gross": 11.0,
            "charges": 0.0,
        }],
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
    with pytest.raises(ValueError, match="mixed-exit"):
        validate_evidence(f, m)


def test_reconciled_two_leg_mixed_exits_are_included_without_false_sl_tp():
    f, m = fixtures()
    trade = f["trades"][0]
    trade["status"] = "COMPLETE_MULTI_EXIT"
    trade["exit_reason"] = "MIXED_EXIT_REASONS"
    trade["exit_legs"] = [
        {"deal_id": "a", "time_msc": str(ENTRY + 10000),
         "reason": "DEAL_REASON_TP", "lots": 0.01},
        {"deal_id": "b", "time_msc": str(ENTRY + 30000),
         "reason": "DEAL_REASON_EXPERT", "lots": 0.02},
    ]
    validate_evidence(f, m)
    result = evaluate(f, m, "mixed-evidence", FakeMT5())
    assert result["status"] == "DESCRIPTIVE_ONLY_REVIEW_REQUIRED"
    assert result["complete_market_snapshots"] == 1
    assert result["complete_multi_exit_positions"] == 1
    assert result["other_or_mixed_exit_positions"] == 1
    assert result["cohorts"]["exit_category"]["1:BROKER_OTHER_OR_MIXED"]["native_net_usd"] == 11
    assert result["positions"][0]["exit_leg_count"] == 2
    assert result["positions"][0]["exit_category"] == "BROKER_OTHER_OR_MIXED"
    assert result["can_autotune_or_promote"] is False


def test_non_sl_exit_reason_with_complete_broker_leg_is_descriptive():
    f, m = fixtures()
    f["trades"][0]["exit_reason"] = "DEAL_REASON_EXPERT"
    f["trades"][0]["exit_legs"][0]["reason"] = "DEAL_REASON_EXPERT"
    result = evaluate(f, m, "expert-evidence", FakeMT5())
    assert result["other_or_mixed_exit_positions"] == 1
    assert result["cohorts"]["exit_category"]["1:BROKER_OTHER_OR_MIXED"]["positions"] == 1


@pytest.mark.parametrize("bad_status", ["PARTIAL_OR_OPEN", "REVERSAL_UNSUPPORTED", "INCOMPLETE_POSITION"])
def test_partial_open_or_reversal_remains_hard_no_go(bad_status):
    f, m = fixtures()
    f["trades"][0]["status"] = bad_status
    with pytest.raises(ValueError, match="incomplete/reversed"):
        validate_evidence(f, m)


def test_fake_multi_exit_with_missing_fill_is_hard_no_go():
    f, m = fixtures()
    trade = f["trades"][0]
    trade["status"] = "COMPLETE_MULTI_EXIT"
    trade["exit_reason"] = "MIXED_EXIT_REASONS"
    trade["exit_legs"] = [
        {"deal_id": "a", "time_msc": str(ENTRY + 10000),
         "reason": "DEAL_REASON_TP", "lots": 0.01},
        {"deal_id": "b", "time_msc": str(ENTRY + 30000),
         "reason": "DEAL_REASON_SL", "lots": 0.01},
    ]
    with pytest.raises(ValueError, match="incomplete or out-of-order"):
        validate_evidence(f, m)


def test_mismatched_reported_exit_and_leg_reason_is_hard_no_go():
    f, m = fixtures()
    f["trades"][0]["exit_legs"][0]["reason"] = "DEAL_REASON_SL"
    with pytest.raises(ValueError, match="disagrees"):
        validate_evidence(f, m)


def test_never_has_order_sender_or_authentication():
    source = (GOLD / "research" / "retrospective_context.py").read_text("utf-8")
    for forbidden in ("order_send(", "OrderSend(", "mt5.login(", "ENABLE_LIVE"):
        assert forbidden not in source
    assert "can_autotune_or_promote" in source
    assert "connected_orders_authorized" in source
    assert json.loads(json.dumps(fixtures()[1]))["symbol"] == "XAUUSD@"
