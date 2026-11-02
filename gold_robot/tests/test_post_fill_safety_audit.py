"""Synthetic tests for native post-fill safety classification (not MT5 testing)."""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"research"))
from audit_post_fill_safety import audit, SafetyAuditError


def make_sample(tmp_path,unsafe=False,halt=False):
    trade={
        "position_id":"26","status":"COMPLETE","side":"BUY",
        "entry_price":4136.56 if unsafe else 4181.58,
        "initial_sl":4142.64 if unsafe else 4176.16,
        "initial_tp":4147.04 if unsafe else 4187.08,
        "entry_time_msc":"1792078202590",
        "exit_time_msc":"1792078202590" if unsafe else "1792078252590",
        "deal_count":2,"entry_lots":0.06,"exit_lots":0.06,
        "net_usd":-2.88 if unsafe else 11.18,
        "exit_reason":"DEAL_REASON_EXPERT" if unsafe else "DEAL_REASON_TP"
    }
    forensics={"live":"LOCKED","edge_validated":False,
               "status":"SELECTED_IMPORTED_FOR_REVIEW","selected_styles":[7],
               "trades":[trade]}
    f=tmp_path/"positions.json"
    f.write_text(json.dumps(forensics),encoding="utf-8")
    o=tmp_path/"opportunities.csv"
    with o.open("w",newline="",encoding="ascii") as fh:
        writer=csv.DictWriter(fh,fieldnames=["bar_time_server","entry_decision_reason"],delimiter=";")
        writer.writeheader()
        writer.writerow({"bar_time_server":"2026.10.15 15:30:00",
                         "entry_decision_reason":"Execution incident: manual broker reconciliation required"
                             if halt else "DUAL: no executable closed-bar setup"})
    return f,o


def test_october_native_bad_fill_is_safety_no_go(tmp_path):
    f,o=make_sample(tmp_path,unsafe=True,halt=True)
    result=audit(f,o)
    assert result["status"]=="POST_FILL_SAFETY_INCIDENT_NO_GO"
    assert result["unsafe_original_fill_count"]==1
    assert result["native_execution_halt_bar_count"]==1
    assert result["new_positions_after_first_unsafe_fill"]==0
    assert result["all_unsafe_fills_have_expert_close"] is True
    assert result["unsafe_fills"][0]["actual_entry"]==4136.56
    assert result["unsafe_fills"][0]["original_sl"]==4142.64
    assert result["trade_permission"] is False


def test_normal_trade_is_research_only_not_live_approval(tmp_path):
    f,o=make_sample(tmp_path)
    result=audit(f,o)
    assert result["status"]=="NO_POST_FILL_SAFETY_INCIDENT_OBSERVED_RESEARCH_ONLY"
    assert result["edge_validated"] is False
    assert result["live"]=="LOCKED"


def test_incident_halt_without_bad_geometry_is_still_no_go(tmp_path):
    f,o=make_sample(tmp_path,halt=True)
    result=audit(f,o)
    assert result["status"]=="POST_FILL_SAFETY_INCIDENT_NO_GO"
    assert result["unsafe_original_fill_count"]==0


def test_native_trades_after_unsafe_fill_are_not_hidden(tmp_path):
    f,o=make_sample(tmp_path,unsafe=True,halt=True)
    data=json.loads(f.read_text(encoding="utf-8"))
    later=dict(data["trades"][0],position_id="27",entry_time_msc="1792088202590",
               exit_time_msc="1792088302590",initial_sl=4100.0,
               entry_price=4135.0,initial_tp=4148.0)
    data["trades"].append(later)
    f.write_text(json.dumps(data),encoding="utf-8")
    result=audit(f,o)
    assert result["new_positions_after_first_unsafe_fill"]==1
    assert result["position_ids_entered_after_first_unsafe_fill"]==["27"]


def test_malformed_or_incomplete_native_evidence_fails_closed(tmp_path):
    f,o=make_sample(tmp_path)
    data=json.loads(f.read_text(encoding="utf-8"))
    data["trades"][0]["exit_lots"]=0.01
    f.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(SafetyAuditError,match="Unreconciled"):
        audit(f,o)


def test_runner_marks_native_safety_incident_no_go():
    runner=(ROOT/"research/RunAutomaticTester.ps1").read_text("utf-8-sig")
    assert "audit_post_fill_safety.py" in runner
    assert "QTS_POST_FILL_SAFETY_AUDIT.json" in runner
    assert "SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO" in runner
    assert "truncated run is NOT comparable" in runner
    assert "if($state -notin @(" in runner
    assert "SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO" not in (
        runner.split("if($state -notin @(")[-1].split("exit 2")[0])


def write_raw_broker_deals(tmp_path, entries, exits, mode=3):
    path=tmp_path/"native_deals.csv"
    columns=["position_id","deal_id","order_id","entry","reason","type",
             "time_msc","volume","price","sl","tp","gross",
             "commission","swap","fee","setup_reason"]
    allrows=[]
    for i,row in enumerate(entries):
        allrows.append(dict(
            position_id="26",deal_id=str(100+i),order_id=str(200+i),
            entry="DEAL_ENTRY_IN",reason="DEAL_REASON_EXPERT",
            type="DEAL_TYPE_BUY",time_msc=row["time_msc"],
            volume=str(row["volume"]),price=str(row["price"]),
            sl=str(row["sl"]),tp=str(row["tp"]),gross="0",
            commission="0",swap="0",fee="0",
            setup_reason=f"QTS-DUAL-M{mode}-S1"))
    for i,row in enumerate(exits):
        allrows.append(dict(
            position_id="26",deal_id=str(900+i),order_id=str(800+i),
            entry="DEAL_ENTRY_OUT",reason="DEAL_REASON_EXPERT",
            type="DEAL_TYPE_SELL",time_msc=row["time_msc"],
            volume=str(row["volume"]),price=str(row.get("price",4187.20)),
            sl="4176.16",tp="4187.08",gross="0",
            commission="0",swap="0",fee="0",setup_reason=""))
    with path.open("w",newline="",encoding="ascii") as fh:
        writer=csv.DictWriter(fh,columns,delimiter=";")
        writer.writeheader()
        writer.writerows(allrows)
    return path


def test_native_individual_partial_fills_detect_hidden_bad_stop(tmp_path):
    f,o=make_sample(tmp_path)
    source=json.loads(f.read_text(encoding="utf-8"))
    trade=source["trades"][0]
    # The aggregated entry is perfectly valid, but a smaller second fill
    # crossed above its own attached original stop.
    trade.update(entry_price=4177.078,initial_sl=4176.16,
                 initial_tp=4187.08,entry_lots=0.10,exit_lots=0.10,
                 entry_time_msc="1792078202590",exit_time_msc="1792078302590")
    f.write_text(json.dumps(source),encoding="utf-8")
    entry=[
        {"time_msc":"1792078202590","volume":0.09,"price":4181.58,
         "sl":4176.16,"tp":4187.08},
        {"time_msc":"1792078202600","volume":0.01,"price":4136.56,
         "sl":4142.64,"tp":4147.04}
    ]
    dealfile=write_raw_broker_deals(tmp_path,entry,[
        {"time_msc":"1792078302590","volume":0.10}])
    result=audit(f,o,broker_deals=dealfile,mode=3)
    assert result["status"]=="POST_FILL_SAFETY_INCIDENT_NO_GO"
    assert result["individual_entry_deals_verified"] is True
    assert result["native_entry_deal_count"]==2
    assert result["unsafe_original_fill_count"]==1
    assert result["unsafe_fills"][0]["entry_deal_id"]=="101"
    assert result["unsafe_fills"][0]["actual_entry"]==4136.56


def test_broker_partial_fill_without_complete_exit_fails_closed(tmp_path):
    f,o=make_sample(tmp_path)
    raw=write_raw_broker_deals(tmp_path,[{
        "time_msc":"1792078202590","volume":0.06,"price":4181.58,
        "sl":4176.16,"tp":4187.08}],
        [{"time_msc":"1792078252590","volume":0.03}])
    with pytest.raises(SafetyAuditError,match="amounts or times mismatch"):
        audit(f,o,broker_deals=raw,mode=3)


def test_broker_wrong_strategy_mode_fails_closed(tmp_path):
    f,o=make_sample(tmp_path)
    raw=write_raw_broker_deals(tmp_path,[{
        "time_msc":"1792078202590","volume":0.06,"price":4181.58,
        "sl":4176.16,"tp":4187.08}],
        [{"time_msc":"1792078252590","volume":0.06}],mode=2)
    with pytest.raises(SafetyAuditError,match="style/mode attribution"):
        audit(f,o,broker_deals=raw,mode=3)


def test_safety_evidence_zip_survives_native_no_go():
    quality=(ROOT.parent/"QTS_DUAL_QUALITY.ps1").read_text("utf-8")
    threeway=(ROOT.parent/"QTS_DUAL_THREEWAY.ps1").read_text("utf-8")
    for source in (quality,threeway):
        assert "SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO" in source
        assert "POST_FILL_SAFETY_INCIDENT_NO_GO" in source
        assert "QTS_POST_FILL_SAFETY_AUDIT.json" in source
        assert "Compress-Archive" in source
        assert "exit 2" in source
    assert "QTS_SAFETY_INCIDENT_NO_GO.zip" in threeway
    assert "QTS_DUAL_QUALITY_EVIDENCE.zip" in quality


def test_native_auditor_requires_each_broker_entry_deal():
    audit_source=(ROOT/"research/audit_post_fill_safety.py").read_text("utf-8")
    runner=(ROOT/"research/RunAutomaticTester.ps1").read_text("utf-8-sig")
    assert "inspect_native_entry_deals(" in audit_source
    assert "set(entries)!=set(positions)" in audit_source
    assert "--deals $nativeDeals --mode $dualMode" in runner
    assert "individual_entry_deals_verified -ne $true" in runner


def test_windows_launcher_distinguishes_expected_safety_no_go_from_execution_error():
    for launcher in ("QTS_DUAL_QUALITY.bat","QTS_DUAL_THREEWAY.bat"):
        source=(ROOT.parent/launcher).read_text("utf-8")
        assert 'if "%QTS_EXIT%"=="2"' in source
        assert 'if not "%QTS_EXIT%"=="0"' in source
        assert "exit /b 2" in source
        assert "exit /b 1" in source
        assert "SAFETY NO-GO" in source
        assert "LIVE LOCKED" in source or "real-money orders" in source
