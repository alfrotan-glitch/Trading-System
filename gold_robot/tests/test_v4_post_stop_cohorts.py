"""V4 post-stop cohorts require real chronological executable quote evidence."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from stop_reversal_audit import audit as replay_ticks, load_stops
from v4_post_stop_cohorts import summarize, validate_source

EXIT_MS = 1_780_000_000_000


def broker_position(pid="p1", strategy=8, regime="TREND", reason="DEAL_REASON_SL"):
    return {
        "position_id": pid, "selected_style": strategy, "regime": regime,
        "side": "BUY", "entry_price": 4000.0,
        "initial_sl": 3990.0, "initial_tp": 4020.0,
        "exit_price": 3989.0, "entry_time_msc": EXIT_MS-900000,
        "exit_time_msc": EXIT_MS, "exit_reason": reason,
    }


def attribution(*positions):
    return {
        "schema": "qts.mt5.v4.position_strategy_attribution.v1",
        "status": "ATTRIBUTED_FOR_RESEARCH_ONLY",
        "live": "LOCKED", "edge_validated": False,
        "can_autotune_or_promote": False, "issues": [],
        "native_positions_seen": len(positions),
        "native_positions_attributed": len(positions),
        "positions": list(positions),
    }


def tick_replay(*, target=True, missing=False):
    s = broker_position()
    stops, _ = load_stops([{
        "trade_id": "7:p1", "side": s["side"],
        "entry_time_ms": str(s["entry_time_msc"]),
        "exit_time_ms": str(s["exit_time_msc"]),
        "entry_price": str(s["entry_price"]),
        "initial_stop_price": str(s["initial_sl"]),
        "initial_target_price": str(s["initial_tp"]),
        "exit_price": str(s["exit_price"]), "exit_reason": "SL",
    }])
    # 30-second executable quotes: TP is touched 7 minutes AFTER actual SL
    # exit, not after mere M15 candle high.
    ticks = []
    duration = 4 if missing else 121 * 2 + 1
    for j in range(1, duration):
        minutes = j / 2
        bid = 4021.0 if target and minutes >= 7.0 else (
            4001.0 if minutes >= 4.0 else 3989.0)
        ticks.append({"time_ms": str(EXIT_MS + j*30000),
                      "bid": str(bid), "ask": str(bid + 0.20)})
    return replay_ticks(stops, ticks)


def test_complete_quote_replay_is_causally_attributed_to_actual_smc_trend():
    result = summarize(attribution(broker_position()), tick_replay())
    assert result["status"] == "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"
    assert result["native_stop_exits"] == 1
    group = result["by_strategy_and_regime"][0]
    assert group["strategy_id"] == 8
    assert group["regime"] == "TREND"
    assert group["horizons"]["5"]["eligible_quote_complete"] == 1
    assert group["horizons"]["5"]["original_tp_touched"] == 0
    assert group["horizons"]["15"]["original_tp_touched"] == 1
    assert group["horizons"]["120"]["original_tp_touched"] == 1
    assert result["stopped_positions"][0]["horizons"]["15"]["first_original_tp_touch_ms"] == EXIT_MS + 7*60000
    assert result["edge_validated"] is False
    assert result["real_orders_permitted"] is False


def test_no_ticks_is_unknown_not_failed_or_recovered():
    result = summarize(attribution(broker_position()), None)
    assert result["status"] == "TICKS_MISSING_NO_GO"
    for h in ("5", "15", "30", "60", "120"):
        row = result["by_strategy_and_regime"][0]["horizons"][h]
        assert row["eligible_quote_complete"] == 0
        assert row["incomplete_or_absent_quotes"] == 1
        assert row["original_tp_touch_fraction_among_complete_only"] is None
        assert result["stopped_positions"][0]["horizons"][h]["original_tp_touched"] is None


def test_incomplete_quote_history_is_never_counted_as_no_tp_touch():
    result = summarize(attribution(broker_position()), tick_replay(missing=True))
    assert result["status"] == "INCOMPLETE_TICK_COVERAGE_NO_GO"
    counts = result["by_strategy_and_regime"][0]["horizons"]["15"]
    assert counts["eligible_quote_complete"] == 0
    assert counts["original_tp_touch_fraction_among_complete_only"] is None


def test_bid_ask_replay_without_tp_touch_counts_valid_negative_observation():
    result = summarize(attribution(broker_position()), tick_replay(target=False))
    assert result["status"] == "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"
    c = result["by_strategy_and_regime"][0]["horizons"]["120"]
    assert c["eligible_quote_complete"] == 1
    assert c["original_tp_touched"] == 0
    assert c["original_tp_touch_fraction_among_complete_only"] == 0.0


def test_native_broker_fill_mismatch_rejected_not_force_merged():
    x = tick_replay()
    x["individual_trade_windows"][0]["original_sl_price"] = 3880.0
    result = summarize(attribution(broker_position()), x)
    assert result["status"] == "STOP_STRATEGY_EVIDENCE_MISMATCH_NO_GO"
    assert any(q["reason"] == "NATIVE_POSITION_PRICE_OR_TIME_MISMATCH" for q in result["issues"])
    assert result["stopped_positions"][0]["horizons"]["120"]["original_tp_touched"] is None


def test_duplicate_or_other_position_replays_are_explicit_errors():
    x = tick_replay()
    x["individual_trade_windows"].append(copy.deepcopy(x["individual_trade_windows"][0]))
    x["stop_trades"] = 2
    result = summarize(attribution(broker_position()), x)
    assert result["status"] == "STOP_STRATEGY_EVIDENCE_MISMATCH_NO_GO"
    assert any(q["reason"] == "UNKNOWN_OR_DUPLICATED_REPLAY_POSITION" for q in result["issues"])


def test_tampered_tp_first_touch_is_rejected_even_with_replay_complete():
    x = tick_replay()
    x["individual_trade_windows"][0]["windows"]["15"]["first_target_touch_ms"] = EXIT_MS - 100
    result = summarize(attribution(broker_position()), x)
    assert result["status"] == "STOP_STRATEGY_EVIDENCE_MISMATCH_NO_GO"
    assert result["stopped_positions"][0]["horizons"]["15"]["original_tp_touched"] is None


def test_missing_native_strategy_identity_is_fatal():
    x = attribution(broker_position())
    x["positions"][0]["selected_style"] = 7
    with pytest.raises(ValueError, match="Unknown ex-ante"):
        validate_source(x)
    x = attribution(broker_position())
    x["edge_validated"] = True
    with pytest.raises(ValueError, match="incomplete or order authority"):
        summarize(x)


def test_full_no_stops_does_not_create_fabricated_post_stop_losses():
    row = broker_position(reason="DEAL_REASON_TP")
    result = summarize(attribution(row))
    assert result["status"] == "NO_BROKER_STOPS_TO_REPLAY"
    assert result["native_stop_exits"] == 0
    assert result["by_strategy_and_regime"] == []


def test_mixed_partial_exit_cannot_be_spoken_of_as_single_confirmed_stop():
    r = summarize(attribution(broker_position(reason="MIXED_EXIT_REASONS")))
    assert r["status"] == "STOP_STRATEGY_EVIDENCE_MISMATCH_NO_GO"
    assert r["mixed_exit_cases_unresolved"] == 1


def test_no_order_or_unlocked_permissions_in_any_stop_cohort_code():
    content = (ROOT / "research" / "v4_post_stop_cohorts.py").read_text("utf-8")
    assert "OrderSend(" not in content
    assert "order_send(" not in content
    assert '"real_orders_permitted": False' in content
    assert '"automated_model_promotion": False' in content
