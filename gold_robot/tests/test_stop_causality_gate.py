"""Synthetic, read-only verification of the stop-causality research gate."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from verify_stop_causality_gate import evaluate, read_attribution


def sample():
    exit_ms = 1790847549171
    position = {
        "position_id": "3",
        "selected_style": 4,
        "regime": "TREND",
        "side": "BUY",
        "entry_time_msc": exit_ms - 70_000,
        "exit_time_msc": exit_ms,
        "entry_price": 100.0,
        "initial_sl": 98.0,
        "initial_tp": 103.0,
        "broker_net_usd": -8.0,
        "exit_reason": "DEAL_REASON_SL",
        "price_rr_ex_ante": 1.5,
        "duration_minutes": 1.16,
    }
    attribution = {
        "status": "ATTRIBUTED_FOR_RESEARCH_ONLY",
        "live": "LOCKED",
        "edge_validated": False,
        "can_autotune_or_promote": False,
        "native_positions_attributed": 1,
        "positions": [position],
    }
    windows = {}
    aggregates = {}
    for h in ("5", "15", "30", "60", "120"):
        minutes = int(h)
        touch = exit_ms + 6 * 60_000 if minutes >= 15 else None
        windows[h] = {
            "complete": True,
            "reclaimed_entry": minutes >= 15,
            "first_target_touch_ms": touch,
        }
        aggregates[h] = {
            "eligible_stops_with_contiguous_executable_quotes": 1,
            "reclaimed_entry_count": int(minutes >= 15),
            "post_stop_original_target_touch_count": int(minutes >= 15),
        }
    post = {
        "status": "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY",
        "same_source_as_native_tester_not_proven": True,
        "stop_trades": 1,
        "horizons_minutes": aggregates,
        "individual_trade_windows": [{
            "trade_id": "7:3",
            "side": "BUY",
            "stop_exit_time_ms": exit_ms,
            "original_entry_price": 100.0,
            "original_sl_price": 98.0,
            "original_tp_price": 103.0,
            "windows": windows,
        }],
    }
    return attribution, post


def test_one_stop_is_verified_but_not_profitable_or_trade_approved():
    original, post = sample()
    report = evaluate(original, post)
    assert report["native_positions"] == 1
    assert report["native_stops"] == 1
    assert report["post_stop_120m"] == {"LATER_TP_TOUCH": 1}
    assert report["selected_style_and_regime"]["4:TREND"]["stop_rate"] == 1.0
    assert report["pre_stop_quote_status"] == "NOT_SUPPLIED"
    assert report["independent_validation"]["approved"] is False
    assert report["can_modify_ea"] is False
    assert report["trade_diagnostics"][0]["post_stop_target_touch_is_profit"] is False
    assert report["trade_diagnostics"][0]["stop_too_tight_confirmed"] is False


def test_contradictory_original_target_is_rejected():
    original, post = sample()
    post["individual_trade_windows"][0]["original_tp_price"] = 105.0
    with pytest.raises(ValueError, match="mismatch"):
        evaluate(original, post)


def test_aggregate_fraud_and_invalid_touch_chronology_rejected():
    original, post = sample()
    post["horizons_minutes"]["15"]["post_stop_original_target_touch_count"] = 0
    with pytest.raises(ValueError, match="Aggregate"):
        evaluate(original, post)
    original, post = sample()
    post["individual_trade_windows"][0]["windows"]["15"]["first_target_touch_ms"] = (
        original["positions"][0]["exit_time_msc"] + 18 * 60_000
    )
    with pytest.raises(ValueError, match="chronology"):
        evaluate(original, post)


def test_safety_flags_and_no_causal_promotion_on_pre_summary():
    original, post = sample()
    pre = {
        "schema": "qts.stop.failed_paths.v1",
        "original_stop_cases": 1,
        "before_stop_quotes_collected": True,
        "live": "LOCKED",
    }
    report = evaluate(original, post, pre)
    assert report["pre_stop_quote_status"] == "CAPTURED_WITH_UNRESOLVED_ENTRY_CAUSALITY"
    assert report["edge_validated"] is False
    original["edge_validated"] = True
    with pytest.raises(ValueError, match="safety"):
        evaluate(original, post, pre)


def test_duplicate_broker_positions_fail_closed():
    original, post = sample()
    original["positions"].append(original["positions"][0].copy())
    original["native_positions_attributed"] = 2
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate(original, post)


def test_bundle_duplicate_original_attribution_rejected(tmp_path):
    path = tmp_path / "evidence.zip"
    original, _ = sample()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("QTS_V4_POSITION_ATTRIBUTION.json", json.dumps(original))
    assert read_attribution(path)[0]["positions"][0]["position_id"] == "3"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("QTS_V4_POSITION_ATTRIBUTION.json", json.dumps(original))
        archive.writestr("nested/QTS_V4_POSITION_ATTRIBUTION.json", json.dumps(original))
    # Nested files are not trusted as root-level original evidence.
    assert read_attribution(path)[0]["positions"][0]["position_id"] == "3"


def test_script_is_offline_and_one_month_is_not_independent():
    original, post = sample()
    result = evaluate(original, post)
    assert result["native_exit_months"] == ["2026-10"]
    assert result["observed_native_months_are_independent_future_holdout"] is False
    assert result["independent_validation"]["minimum_new_separate_test_months"] == 6
    assert result["independent_validation"]["minimum_independent_positions"] == 200
    script = (ROOT / "research" / "verify_stop_causality_gate.py").read_text("utf-8")
    assert "import MetaTrader5" not in script
    assert "order_send(" not in script
    assert "mt5.initialize(" not in script
