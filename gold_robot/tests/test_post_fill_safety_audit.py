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
