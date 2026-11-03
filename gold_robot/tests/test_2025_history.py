"""Synthetic contract tests for 2025-to-present MT5 history (not a broker replay)."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"research"))
from summarize_2025_history import summarize


def fixture(tmp_path: Path, incident=False, bar="2025.01.02 11:00:00"):
    (tmp_path/"native").mkdir()
    meta={"research_variant":"DUAL_DIRECTIONAL",
          "state":"SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO" if incident else
                  "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
          "live":"LOCKED","validated_edge":False,"real_money_orders":False,
          "symbol":"XAUUSD@","model":4,"timeframe":"M15","deposit_usd":3000,
          "selected_styles":[7],"from_date":"2025.01.01","to_date":"2025.01.03",
          "compiled_ex5_sha256":"not_a_real_ex5","source_manifest_sha256":"synthetic"}
    (tmp_path/"OPEN_RESULTS.json").write_text(json.dumps(meta),encoding="utf-8")
    safety={"status":"POST_FILL_SAFETY_INCIDENT_NO_GO" if incident else
                   "NO_POST_FILL_SAFETY_INCIDENT_OBSERVED_RESEARCH_ONLY",
            "live":"LOCKED","edge_validated":False,"trade_permission":False,
            "individual_entry_deals_verified":True,"unsafe_original_fill_count":int(incident),
            "new_positions_after_first_unsafe_fill":0}
    (tmp_path/"QTS_POST_FILL_SAFETY_AUDIT.json").write_text(
        json.dumps(safety),encoding="utf-8")
    opportunity={"status":"NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY",
                 "mode":2,"rows":2,"bars":1,"live":"LOCKED","edge_validated":False}
    (tmp_path/"QTS_DUAL_OPPORTUNITY_SUMMARY.json").write_text(
        json.dumps(opportunity),encoding="utf-8")
    trades={"live":"LOCKED","edge_validated":False,"selected_styles":[7],
            "trades":[{"status":"COMPLETE","net_usd":-2.88 if incident else 11.18,
                       "entry_time_msc":"1735815600000",
                       "entry_lots":0.06,"setup_reason":"QTS-DUAL-M2-S1"}]}
    (tmp_path/"QTS_TRADE_BY_TRADE.json").write_text(
        json.dumps(trades),encoding="utf-8")
    with (tmp_path/"native"/"QTS_7_opportunities.csv").open(
        "w",newline="",encoding="ascii"
    ) as fh:
        writer=csv.DictWriter(fh,delimiter=";",
                              fieldnames=("bar_time_server","style","side","entry_decision_reason"))
        writer.writeheader()
        writer.writerow({"bar_time_server":bar,"style":1,"side":1,
                         "entry_decision_reason":"Execution incident: protective stop"
                         if incident else "CANDIDATE_SELECTED"})
        writer.writerow({"bar_time_server":bar,"style":3,"side":-1,
                         "entry_decision_reason":"Execution incident: protective stop"
                         if incident else "CANDIDATE_SELECTED"})
    return tmp_path


def test_full_coverage_reports_signals_but_never_live_or_missed_fills(tmp_path):
    folder=fixture(tmp_path)
    review=summarize(folder,"DUAL_DIRECTIONAL","2025.01.01","2025.01.03")
    assert review["status"]=="HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED"
    assert review["market_data_window_coverage_checked"] is True
    assert review["native_m15_closed_bars"]==1
    assert review["native_raw_signal_rows"]==2
    assert review["raw_signals_by_style_side"]=={"retest_buy":1,"sweep_sell":1}
    assert review["native_positions_net_usd"]==11.18
    assert review["native_total_entry_lots"]==0.06
    assert review["illustrative_fee_stress_10_usd_per_lot_net_usd"]==10.58
    assert review["monthly_native_broker_positions_by_utc_entry_month"]["2025-01"]["positions"]==1
    assert review["monthly_native_broker_positions_by_utc_entry_month"]["2025-01"]["retest_buy"]==1
    assert review["monthly_native_broker_positions_by_utc_entry_month"]["2025-01"]["net_usd"]==11.18
    assert review["live"]=="LOCKED"
    assert review["trade_permission"] is False
    assert review["edge_validated"] is False
    assert review["end_date_is_exclusive"] is True


def test_protective_halt_is_not_full_window_profitability(tmp_path):
    folder=fixture(tmp_path,incident=True)
    review=summarize(folder,"DUAL_DIRECTIONAL","2025.01.01","2025.01.03")
    assert review["status"]=="HISTORICAL_SAFETY_STOP_NO_GO"
    assert review["native_position_results_cover_full_window"] is False
    assert review["unsafe_original_entry_deals"]==1
    assert review["monthly_native_closed_bar_signals"]["2025-01"]["halt_bars"]==1


def test_missing_old_market_history_is_explicit_no_go(tmp_path):
    folder=fixture(tmp_path,bar="2025.01.29 09:00:00")
    meta=folder/"OPEN_RESULTS.json"
    data=json.loads(meta.read_text())
    data["to_date"]="2025.03.01"
    meta.write_text(json.dumps(data))
    review=summarize(folder,"DUAL_DIRECTIONAL","2025.01.01","2025.03.01")
    assert review["status"]=="HISTORICAL_MARKET_DATA_COVERAGE_NO_GO"
    assert review["market_data_window_coverage_checked"] is False


def test_safety_audit_and_result_cannot_disagree(tmp_path):
    folder=fixture(tmp_path)
    p=folder/"OPEN_RESULTS.json"
    data=json.loads(p.read_text())
    data["state"]="SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO"
    p.write_text(json.dumps(data))
    from summarize_2025_history import HistoricalEvidenceError
    import pytest
    with pytest.raises(HistoricalEvidenceError,match="contradicts"):
        summarize(folder,"DUAL_DIRECTIONAL","2025.01.01","2025.01.03")


def test_windows_launcher_is_research_only_and_date_scoped():
    ps=(ROOT.parent/"QTS_BACKTEST_2025_TO_DATE.ps1").read_text(encoding="utf-8")
    bat=(ROOT.parent/"QTS_BACKTEST_2025_TO_DATE.bat").read_text(encoding="utf-8")
    assert "DUAL_DIRECTIONAL" in ps and "DUAL_DIRECTIONAL" in bat
    assert "$start='2025.01.01'" in ps
    assert "ToString('yyyy.MM.dd')" in ps
    assert "'-OnlyStyles','7'" in ps
    assert "'-TimeoutMinutesPerRun'" in ps
    assert "QTS_2025_TO_DATE_EVIDENCE.zip" in ps
    assert "QTS_POST_FILL_SAFETY_AUDIT.json" in ps
    assert "exit 2" in ps and "exit /b 2" in bat
    assert "RESEARCH ONLY" in ps and "LIVE LOCKED" in bat
    assert "OrderSend(" not in ps and "OrderSend(" not in bat


def test_start_2025_may_include_one_prior_holiday_warmup_bar(tmp_path):
    folder=fixture(tmp_path)
    p=folder/"native"/"QTS_7_opportunities.csv"
    with p.open(newline="",encoding="ascii") as fh:
        original=list(csv.DictReader(fh,delimiter=";"))
    fields=("bar_time_server","style","side","entry_decision_reason",
            "candidate_class")
    extra=[{"bar_time_server":"2024.12.31 20:45:00",
            "style":style,"side":0,
            "entry_decision_reason":"ENTRY: outside broker session",
            "candidate_class":"NO_SIGNAL"} for style in (1,3)]
    for row in original:
        row["candidate_class"]="SIGNAL_NOT_FILL_PROOF"
    with p.open("w",newline="",encoding="ascii") as fh:
        writer=csv.DictWriter(fh,fieldnames=fields,delimiter=";")
        writer.writeheader()
        writer.writerows(extra+original)
    summary_file=folder/"QTS_DUAL_OPPORTUNITY_SUMMARY.json"
    obj=json.loads(summary_file.read_text("utf-8"))
    obj["rows"]=4
    obj["bars"]=2
    summary_file.write_text(json.dumps(obj),encoding="utf-8")
    review=summarize(folder,"DUAL_DIRECTIONAL","2025.01.01","2025.01.03")
    assert review["status"]=="HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED"
    assert review["excluded_prestart_warmup_rows"]==2
    assert review["native_original_export_rows"]==4
    assert review["native_raw_signal_rows"]==2
    assert review["native_m15_closed_bars"]==1
    assert review["excluded_prestart_warmup_bar_server"]=="2024.12.31 20:45:00"


def test_prestart_trade_signal_is_rejected_even_if_marked_warmup(tmp_path):
    folder=fixture(tmp_path)
    p=folder/"native"/"QTS_7_opportunities.csv"
    with p.open(newline="",encoding="ascii") as fh:
        original=list(csv.DictReader(fh,delimiter=";"))
    fields=("bar_time_server","style","side","entry_decision_reason",
            "candidate_class")
    extra=[{"bar_time_server":"2024.12.31 20:45:00",
            "style":style,"side":1 if style==1 else 0,
            "entry_decision_reason":"ENTRY: outside broker session",
            "candidate_class":"NO_SIGNAL"} for style in (1,3)]
    for row in original:row["candidate_class"]="SIGNAL_NOT_FILL_PROOF"
    with p.open("w",newline="",encoding="ascii") as fh:
        writer=csv.DictWriter(fh,fieldnames=fields,delimiter=";")
        writer.writeheader()
        writer.writerows(extra+original)
    summary_file=folder/"QTS_DUAL_OPPORTUNITY_SUMMARY.json"
    obj=json.loads(summary_file.read_text("utf-8"))
    obj["rows"]=4
    obj["bars"]=2
    summary_file.write_text(json.dumps(obj),encoding="utf-8")
    from summarize_2025_history import HistoricalEvidenceError
    import pytest
    with pytest.raises(HistoricalEvidenceError,match="prestart"):
        summarize(folder,"DUAL_DIRECTIONAL","2025.01.01","2025.01.03")
