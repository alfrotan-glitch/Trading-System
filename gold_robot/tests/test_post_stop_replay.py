"""Synthetic proof that post-stop TP touch requires *later* executable quotes.

All inputs are fabricated. Tests must NEVER be read as a profitable edge.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qts_poststop", ROOT / "research/stop_reversal_audit.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

sys.path.insert(0, str(ROOT / "research"))
from build_post_stop_inputs import build, OUTPUT_STATUS


def test_buy_sl_followed_by_target_bid_touch_at_7min_not_5min():
    rows = [{
        "trade_id": "0:1", "side": "BUY", "entry_time_ms": "0",
        "exit_time_ms": "60000", "entry_price": "100",
        "initial_stop_price": "95", "exit_price": "94",
        "exit_reason": "SL", "initial_target_price": "107",
    }]
    stops, ignored = mod.load_stops(rows)
    assert ignored == 0
    ticks = [
        {"time_ms": str(60000 + minute * 60000),
         "bid": str(107.2 if minute >= 7 else 95.5),
         "ask": str(107.4 if minute >= 7 else 95.8)}
        for minute in range(1, 132)
    ]
    summary = mod.audit(stops, ticks)
    assert summary["horizons_minutes"]["5"]["post_stop_original_target_touch_count"] == 0
    assert summary["horizons_minutes"]["15"]["post_stop_original_target_touch_count"] == 1
    item = summary["individual_trade_windows"][0]["windows"]["15"]
    assert item["first_target_touch_ms"] == 60000 + 7 * 60000
    assert item["first_target_touch_after_stop_minutes"] == 7


def test_sell_target_touch_requires_ask_and_gaps_leave_unknown():
    stops, _ = mod.load_stops([{
        "trade_id": "2:3", "side": "SELL", "entry_time_ms": "1",
        "exit_time_ms": "60000", "entry_price": "100",
        "initial_stop_price": "105", "exit_price": "106",
        "exit_reason": "SL", "initial_target_price": "92",
    }])
    ticks = []
    for m in range(1, 132):
        bid, ask = (91.5, 92.5) if m < 20 else (91, 91.8)
        ticks.append({"time_ms": str(60000 + m * 60000),
                      "bid": str(bid), "ask": str(ask)})
    x = mod.audit(stops, ticks)
    assert x["horizons_minutes"]["15"]["post_stop_original_target_touch_count"] == 0
    assert x["horizons_minutes"]["30"]["post_stop_original_target_touch_count"] == 1
    sparse = [ticks[0], ticks[-1]]
    y = mod.audit(stops, sparse)
    assert y["horizons_minutes"]["120"]["post_stop_original_target_touch_fraction"] is None
    assert y["individual_trade_windows"][0]["windows"]["120"]["first_target_touch_ms"] is None


def make_deals(style: int) -> str:
    raw = io.StringIO()
    names = ["position_id", "deal_id", "order_id", "entry", "reason",
             "type", "time_msc", "volume", "price", "sl", "tp",
             "gross", "commission", "swap", "fee", "setup_reason"]
    w = csv.DictWriter(raw, fieldnames=names, delimiter=";", lineterminator="\n")
    w.writeheader()
    for row in (
        [str(style), str(style * 2), str(style * 2), "DEAL_ENTRY_IN",
         "DEAL_REASON_EXPERT", "DEAL_TYPE_BUY", "1000", "0.01",
         "100", "95", "105", "0", "0", "0", "0", "QTS RETEST LIMIT DEMO"],
        [str(style), str(style * 2 + 1), str(style * 2 + 1), "DEAL_ENTRY_OUT",
         "DEAL_REASON_SL", "DEAL_TYPE_SELL", "2000", "0.01",
         "94", "95", "105", "-6", "0", "0", "0", ""],
    ):
        w.writerow(dict(zip(names, row)))
    return raw.getvalue()


def test_adapter_all_eight_styles_reconciles_and_does_not_look_ahead(tmp_path):
    bundle = tmp_path / "evidence.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("comparison.json", json.dumps({
            "reports_parsed": 8,
            "results": [{"style": i, "trades": 1, "net_usd": -6}
                        for i in range(8)]
        }))
        z.writestr("QTS_TRADE_BY_TRADE.json", json.dumps({
            "status": "IMPORTED_FOR_REVIEW",
            "trades": [{"style": i, "position_id": str(i),
                        "status": "COMPLETE", "net_usd": -6,
                        "exit_reason": "DEAL_REASON_SL"}
                       for i in range(8)]
        }))
        for i in range(8):
            z.writestr(f"native/QTS_{i}_trades.csv", make_deals(i))
    cases, meta = build(bundle)
    assert meta["status"] == OUTPUT_STATUS
    assert meta["stop_cases_total"] == 8
    assert not meta["price_after_stop_verified"]
    assert cases[0]["trade_id"] == "0:0"
    assert cases[-1]["initial_target_price"] == 105
    assert set(str(i) for i in range(8)) == set(meta["per_style"])


def test_daily_native_mt5_time_msc_tick_folder_cli(tmp_path):
    import subprocess
    stops_file = tmp_path / "stops.csv"
    fields = ["trade_id", "side", "entry_time_ms", "exit_time_ms",
              "entry_price", "initial_stop_price", "exit_price",
              "exit_reason", "initial_target_price"]
    with stops_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow({"trade_id": "7:4", "side": "BUY", "entry_time_ms": "0",
                    "exit_time_ms": "60000", "entry_price": "100",
                    "initial_stop_price": "95", "exit_price": "94",
                    "exit_reason": "SL", "initial_target_price": "105"})
    directory = tmp_path / "ticks"
    directory.mkdir()
    with (directory / "ticks_0.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time_msc", "bid", "ask"])
        w.writeheader()
        for minute in range(1, 132):
            w.writerow({"time_msc": 60000 + minute * 60000,
                        "bid": 106 if minute >= 7 else 95.5,
                        "ask": 106.2 if minute >= 7 else 95.8})
    output = tmp_path / "review.json"
    p = subprocess.run(
        [sys.executable, str(ROOT / "research/stop_reversal_audit.py"),
         "--stops", str(stops_file), "--tick-dir", str(directory),
         "--output", str(output)],
        text=True, capture_output=True, check=False,
    )
    assert p.returncode == 0, p.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["horizons_minutes"]["15"]["post_stop_original_target_touch_count"] == 1
    assert data["individual_trade_windows"][0]["windows"]["15"]["first_target_touch_after_stop_minutes"] == 7


def test_extreme_quote_is_best_observed_even_when_every_future_tick_is_adverse():
    stops, _ = mod.load_stops([{
        "trade_id": "z", "side": "BUY", "entry_time_ms": "0",
        "exit_time_ms": "60000", "entry_price": "100",
        "initial_stop_price": "95", "exit_price": "94",
        "exit_reason": "SL", "initial_target_price": "107",
    }])
    ticks = []
    for m in range(1, 132):
        bid = 93 if m == 1 else (93.7 if m == 2 else 93.4)
        ticks.append({"time_ms": str(60000 + m * 60000),
                      "bid": str(bid), "ask": str(bid + .2)})
    out = mod.audit(stops, ticks)
    w = out["individual_trade_windows"][0]["windows"]["15"]
    assert w["complete"]
    assert w["favorable_extreme_executable_price"] == 93.7
    assert w["favorable_extreme_time_ms"] == 60000 + 2 * 60000
    assert w["adverse_extreme_executable_price"] == 93
    assert w["first_target_touch_ms"] is None


def test_selected_four_native_styles_produce_stop_cases_not_missing_style_errors(tmp_path):
    selected = [1, 3, 7, 8]
    path = tmp_path / "selected.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("OPEN_RESULTS.json", json.dumps({
            "targeted": True, "selected_styles": selected,
            "state": "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
            "results": [{"style_id": i, "status": "REPORT_AND_FORENSICS_SAVED"}
                        for i in selected]
        }))
        z.writestr("comparison.json", json.dumps({
            "reports_parsed": 4,
            "results": [{"style": i, "state": "PARSED", "trades": 1, "net_usd": -6}
                        for i in selected]
        }))
        z.writestr("QTS_TRADE_BY_TRADE.json", json.dumps({
            "status": "EVIDENCE_GAPS_NO_GO",
            "evidence": [{"style": i, "status": "IMPORTED", "deals": 2}
                         for i in selected],
            "trades": [{"style": i, "position_id": str(i),
                        "status": "COMPLETE", "net_usd": -6,
                        "exit_reason": "DEAL_REASON_SL"} for i in selected]
        }))
        for style in selected:
            z.writestr(f"native/QTS_{style}_trades.csv", make_deals(style))
    cases, report = build(path)
    assert {c["style"] for c in cases} == {1, 3, 7, 8}
    assert report["stop_cases_total"] == 4
    assert not report["price_after_stop_verified"]


def test_selected_stop_cases_fail_without_single_original_style_csv(tmp_path):
    selected = [1, 3, 7, 8]
    path = tmp_path / "missing_smc.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("OPEN_RESULTS.json", json.dumps({
            "targeted": True, "selected_styles": selected,
            "state": "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
            "results": [{"style_id": i, "status": "REPORT_AND_FORENSICS_SAVED"}
                        for i in selected]
        }))
        z.writestr("comparison.json", json.dumps({
            "reports_parsed": 4,
            "results": [{"style": i, "state": "PARSED", "trades": 1, "net_usd": -6}
                        for i in selected]
        }))
        z.writestr("QTS_TRADE_BY_TRADE.json", json.dumps({
            "evidence": [{"style": i, "status": "IMPORTED", "deals": 2}
                         for i in selected],
            "trades": []
        }))
        for style in selected[:-1]:
            z.writestr(f"native/QTS_{style}_trades.csv", make_deals(style))
    import pytest
    with pytest.raises(ValueError, match="Missing selected native deal files"):
        build(path)
