"""Auditable opportunity routing: no connected orders and no invented edge."""
from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from gold_decision_audit import audit, classify_session, instant


def snapshot() -> dict:
    return {
        "as_of": "2026-10-29T13:05:00+00:00",
        "symbol": "XAUUSD@",
        "account": {
            "currency": "USD", "balance": 20000, "equity": 20000,
            "day_start_equity": 20000, "peak_equity": 20000,
            "risk_pct": 0.5, "existing_exposure": False,
        },
        "broker": {
            "contract_size": 100, "min_lot": 0.01, "max_lot": 10,
            "lot_step": 0.01, "margin_per_lot_usd": 1000,
            "free_margin_usd": 20000, "bid": 3999.9, "ask": 4000.1,
            "spread_price": 0.2, "adverse_slippage_price": 0.1,
            "round_turn_fee_per_lot_usd": 10,
            "min_stop_distance_price": 0.2,
            "quote_at": "2026-10-29T13:04:59+00:00",
        },
        "context": {
            "h1_closed_at": "2026-10-29T13:00:00+00:00",
            "h1_ema_fast": 4000, "h1_ema_slow": 3980,
            "m15_closed_at": "2026-10-29T13:00:00+00:00",
            "m15_ema_fast": 3998, "m15_ema_slow": 3990,
            "m15_adx": 29, "m15_atr": 10, "m15_atr_p90": 11,
            "m5_closed_at": "2026-10-29T13:00:00+00:00",
            "m5_close": 4001, "m5_ema_fast": 3999,
        },
        "news": {"status": "verified",
                 "fetched_at": "2026-10-29T12:00:00+00:00", "events": []},
        "candidates": [{
            "id": "signal-1", "style": "TREND_PULLBACK", "side": "BUY",
            "entry": 4000, "stop": 3990, "target": 4020,
            "closed_at": "2026-10-29T13:00:00+00:00",
            "setup_valid": True,
        }],
    }


def test_proposal_is_audit_not_order_authorization():
    value = audit(snapshot())
    assert value["session"] == "LONDON_NY_OVERLAP"
    assert value["regime"] == "TREND"
    assert value["decision"] == "RESEARCH_PROPOSAL_ONLY"
    assert value["selected_candidate_id"] == "signal-1"
    assert value["candidate_audit"][0]["lot_research_only"] >= 0.01
    assert value["connected_orders_authorized"] is False
    assert value["validated_edge"] is False
    assert value["live"] == "LOCKED"


def test_small_capital_cannot_force_broker_minimum_lot():
    s = snapshot()
    for field in ("balance", "equity", "day_start_equity", "peak_equity"):
        s["account"][field] = 200
    s["broker"]["free_margin_usd"] = 200
    result = audit(s)
    assert result["decision"] == "NO_TRADE"
    assert "MINIMUM_LOT_EXCEEDS_RISK_OR_MARGIN" in result["candidate_audit"][0]["reasons"]


def test_news_feed_missing_stale_and_event_veto():
    s = snapshot()
    del s["news"]
    assert "NEWS_CALENDAR_UNVERIFIED_OR_STALE" in audit(s)["candidate_audit"][0]["reasons"]
    s = snapshot()
    s["news"]["fetched_at"] = "2026-10-27T10:00:00+00:00"
    assert audit(s)["decision"] == "NO_TRADE"
    s = snapshot()
    s["news"]["events"] = [{
        "at": "2026-10-29T13:30:00+00:00", "currency": "USD", "impact": "high",
    }]
    assert "HIGH_IMPACT_NEWS_BLACKOUT" in audit(s)["candidate_audit"][0]["reasons"]


def test_no_lookahead_or_very_old_signal():
    s = snapshot()
    s["context"]["m5_closed_at"] = "2026-10-29T13:15:00+00:00"
    assert "STALE_CLOSED_BAR_M5_CLOSED_AT" in audit(s)["candidate_audit"][0]["reasons"]
    s = snapshot()
    s["candidates"][0]["closed_at"] = "2026-10-29T12:30:00+00:00"
    assert "CANDIDATE_BAR_STALE" in audit(s)["candidate_audit"][0]["reasons"]
    with pytest.raises(ValueError, match="Naive"):
        audit({**snapshot(), "as_of": "2026-10-29T13:05:00"})


def test_spread_rr_stop_and_market_bias_gates():
    s = snapshot()
    s["broker"].update({"bid": 3997, "ask": 4003, "spread_price": 6})
    row = audit(s)["candidate_audit"][0]
    assert "SPREAD_TOO_HIGH_FOR_ATR" in row["reasons"]
    s = snapshot()
    s["candidates"][0]["target"] = 4002
    assert "NET_REWARD_RISK_TOO_LOW" in audit(s)["candidate_audit"][0]["reasons"]
    s = snapshot()
    s["candidates"][0]["stop"] = 3999.9
    assert "STOP_TOO_CLOSE" in audit(s)["candidate_audit"][0]["reasons"]
    s = snapshot()
    s["candidates"][0]["side"] = "SELL"
    assert "H1_TREND_MISMATCH" in audit(s)["candidate_audit"][0]["reasons"]


def test_regime_mismatch_and_spike_abort():
    s = snapshot()
    s["context"]["m15_adx"] = 15
    assert "STRATEGY_WRONG_REGIME" in audit(s)["candidate_audit"][0]["reasons"]
    s = snapshot()
    s["context"]["m15_atr"] = 30
    assert "NO_STABLE_MARKET_REGIME" in audit(s)["candidate_audit"][0]["reasons"]


def test_dst_and_weekend_are_timezone_aware():
    assert classify_session(instant("2026-03-10T12:30:00+00:00")) == "LONDON_NY_OVERLAP"
    assert classify_session(instant("2026-10-29T13:05:00+00:00")) == "LONDON_NY_OVERLAP"
    s = snapshot()
    s["as_of"] = "2026-10-31T13:05:00+00:00"
    assert audit(s)["decision"] == "NO_TRADE"
    assert "SESSION_OUTSIDE_RESEARCH_HOURS" in audit(s)["candidate_audit"][0]["reasons"]


def test_research_risk_cap_and_stale_quote():
    s = snapshot()
    s["account"]["risk_pct"] = 2
    assert "RISK_EXCEEDS_RESEARCH_CAP" in audit(s)["candidate_audit"][0]["reasons"]
    s = snapshot()
    s["broker"]["quote_at"] = "2026-10-29T13:04:45+00:00"
    assert "QUOTE_STALE" in audit(s)["candidate_audit"][0]["reasons"]


def test_selection_is_deterministic_and_no_winner_is_invented():
    s = snapshot()
    extra = copy.deepcopy(s["candidates"][0])
    extra["id"] = "signal-2"
    extra["style"] = "BREAK_RETEST"
    s["candidates"].append(extra)
    first = audit(s)
    assert first["selected_candidate_id"] == "signal-1"
    assert audit(s) == first
    s["candidates"] = []
    assert audit(s)["decision"] == "NO_TRADE"
    assert audit(s)["selected_candidate_id"] is None


def test_invalid_missing_market_evidence_rejects_instead_of_crashing():
    s = snapshot()
    del s["broker"]["margin_per_lot_usd"]
    result = audit(s)
    assert result["decision"] == "NO_TRADE"
    assert "REQUIRED_MARKET_OR_BROKER_DATA_INVALID" in str(result["candidate_audit"][0]["reasons"])


def test_news_calendar_malformed_rows_fail_closed():
    s = snapshot()
    s["news"]["events"] = [None]
    assert "INVALID_NEWS_EVENT" in audit(s)["candidate_audit"][0]["reasons"]
    s["news"]["events"] = [{"impact": "mystery", "currency": "USD", "at": s["as_of"]}]
    assert "UNKNOWN_NEWS_IMPACT" in audit(s)["candidate_audit"][0]["reasons"]


def test_broker_volume_steps_start_at_min_lot_not_zero():
    s = snapshot()
    s["broker"]["min_lot"] = 0.03
    s["broker"]["lot_step"] = 0.02
    result = audit(s)
    assert result["candidate_audit"][0]["status"] == "RESEARCH_ELIGIBLE"
    assert result["candidate_audit"][0]["lot_research_only"] == 0.09


def test_no_order_sender_or_live_unlock_in_module():
    script = (ROOT / "research" / "gold_decision_audit.py").read_text("utf-8")
    assert "order_send(" not in script
    assert "trader.Buy(" not in script
    assert '"connected_orders_authorized": False' in script
