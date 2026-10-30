"""Synthetic safety tests: before/after stopped-trade failure classification."""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from analyze_stop_failure_paths import pre_stop_observations, classify


def stop(ident, entry_ms, exit_ms):
    return {
        "trade_id": ident, "style": "3", "side": "BUY",
        "entry_time_ms": str(entry_ms), "exit_time_ms": str(exit_ms),
        "entry_price": "100", "initial_stop_price": "95",
        "initial_target_price": "110", "exit_price": "94",
        "exit_reason": "SL",
    }


def quote_file(path, rows):
    path.mkdir(exist_ok=True)
    with (path / "ticks_00001.csv").open("w", newline="") as stream:
        w = csv.writer(stream)
        w.writerow(("time_msc", "bid", "ask"))
        for row in rows:
            w.writerow(row)


def test_pre_stop_near_target_then_sl_is_not_labeled_profitable(tmp_path):
    t = 1_780_000_000_000
    case = stop("3:1", t, t + 4 * 60_000)
    samples = [(t + i * 30_000, 109 if i == 2 else
                97 if i >= 5 else 99, 109.1 if i == 2 else
                97.1 if i >= 5 else 99.1) for i in range(9)]
    quote_file(tmp_path, samples)
    outcome = pre_stop_observations([case], tmp_path)["3:1"]
    assert outcome["pre_status"] == "COMPLETE"
    assert outcome["pre_category"] == "NEAR_TP_THEN_SL"
    assert outcome["max_fraction_of_original_TP_before_SL"] == pytest.approx(0.9)
    assert outcome["first_initial_TP_quote_ms"] is None


def test_short_wrong_direction_is_early_sl_without_progress(tmp_path):
    t = 1_780_000_000_000
    case = stop("3:2", t, t + 90_000)
    quote_file(tmp_path, [(t + i * 10000, 99-i*0.5, 99.1-i*0.5)
                          for i in range(10)])
    out = pre_stop_observations([case], tmp_path)["3:2"]
    assert out["pre_status"] == "COMPLETE"
    assert out["pre_category"] == "EARLY_SL_WITHOUT_PROGRESS"
    assert out["first_initial_SL_quote_ms"] is not None


def test_missing_entry_window_stays_unknown(tmp_path):
    t = 1_780_000_000_000
    case = stop("3:3", t, t + 900_000)
    quote_file(tmp_path, [(t + 700_000, 96, 96.1), (t + 899_000, 95, 95.1)])
    pre = pre_stop_observations([case], tmp_path)["3:3"]
    assert pre["pre_status"] == "UNKNOWN_GAP"
    assert pre["pre_category"] == "UNKNOWN"


def test_no_tp_and_no_reclaim_is_distinct_from_reclaim_and_unknown():
    t = 1_780_000_000_000
    cases = [stop(f"3:{i}",t,t+100_000+i) for i in range(3)]
    replay = {"individual_trade_windows": []}
    for i, c in enumerate(cases):
        complete = i != 2
        reached = i == 1
        windows = {
            "5": {"complete": True, "max_adverse_R": -1.5},
            "120": {
                "complete": complete, "first_target_touch_ms": None,
                "reclaimed_entry": reached, "max_adverse_R": -2.5,
                "max_favorable_R": 0.7,
                "favorable_extreme_executable_price": 99,
                "first_target_touch_after_stop_minutes": None,
            },
        }
        replay["individual_trade_windows"].append({
            "trade_id": c["trade_id"], "side": "BUY",
            "original_tp_price": 110.0,
            "stop_exit_time_ms": int(c["exit_time_ms"]), "windows": windows,
        })
    rows, summary = classify(cases, replay)
    assert [r["post_category_120m"] for r in rows] == [
        "CONTINUED_AGAINST_NO_RECLAIM", "RECLAIM_ONLY_NO_TP",
        "UNKNOWN_120M_COVERAGE"
    ]
    assert summary["post_2R_adverse_events"] == 2
    assert summary["pre_stop_outcomes"]["UNKNOWN"] == 3
    with pytest.raises(ValueError, match="does not match"):
        classify(cases[:-1], replay)


def test_read_only_code_contract_no_broker_order_api():
    text = (ROOT / "research/analyze_stop_failure_paths.py").read_text("utf-8")
    assert "order_send(" not in text
    assert "mt5.initialize(" not in text
    runner = (ROOT.parent / "QTS_ONE_CLICK_ROBOT.ps1").read_text("utf-8")
    assert "--phase','pre'" in runner
    assert "QTS_PRE_STOP_BROKER_TICKS" in runner
    assert "QTS_LOSING_STOP_PATHS.csv" in runner
    assert "QTS_POST_STOP_REVIEW.zip" in runner
