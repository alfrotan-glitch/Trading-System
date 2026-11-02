"""Synthetic contract tests. Not evidence that a real MT5 native run passed."""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path
import pytest

GOLD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(GOLD/"research"))
sys.path.insert(0,str(GOLD/"tests"))
from compare_dual_modes import compare
from verify_dual_opportunity import FIELDS,verify,LedgerError
from test_dual_opportunity_contract import rows

VARIANTS={"DUAL_BOTH":1,"DUAL_DIRECTIONAL":2,"DUAL_QUALITY":3}

def setup_arm(root:Path,variant:str):
    mode=VARIANTS[variant]
    folder=root/variant
    (folder/"native").mkdir(parents=True)
    meta={
        "research_variant":variant,
        "state":"SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
        "live":"LOCKED","validated_edge":False,"real_money_orders":False,
        "selected_styles":[7],"symbol":"XAUUSD@","model":4,
        "timeframe":"M15","deposit_usd":3000,
        "compiled_ex5_sha256":"same_mock_binary",
        "source_manifest_sha256":"same_mock_source",
        "terminal_exe_sha256":"same_mock_terminal",
        "from_date":"2026.10.01","to_date":"2026.11.01",
    }
    (folder/"OPEN_RESULTS.json").write_text(json.dumps(meta),encoding="utf-8")
    payload=rows(mode)
    path=folder/"native"/"QTS_7_opportunities.csv"
    with path.open("w",newline="",encoding="ascii") as f:
        writer=csv.DictWriter(f,FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows(payload)
    native=verify(path,mode)
    (folder/"QTS_DUAL_OPPORTUNITY_SUMMARY.json").write_text(
        json.dumps(native),encoding="utf-8")
    trade={
        "status":"COMPLETE","setup_reason":f"QTS-DUAL-M{mode}-S1",
        "side":"BUY","net_usd":9.0,"entry_lots":0.02,
        "charges_usd":0.0,"entry_price":4000.0,"initial_sl":3995.0
    }
    forensic={"edge_validated":False,"live":"LOCKED","trades":[trade]}
    (folder/"QTS_TRADE_BY_TRADE.json").write_text(
        json.dumps(forensic),encoding="utf-8")
    return folder

def setup_three(tmp_path):
    return {v:setup_arm(tmp_path,v) for v in VARIANTS}

def test_native_threeway_comparison_is_research_only(tmp_path):
    folders=setup_three(tmp_path)
    review=compare(folders)
    assert review["same_native_source_and_signals_verified"] is True
    assert review["independent_holdout"] is False
    assert review["live"]=="LOCKED"
    assert review["edge_validated"] is False
    assert review["trade_permission"] is False
    assert len(review["variants"])==3
    assert review["variants"][0]["stressed_net_usd"]==8.8

def test_cross_arm_binary_identity_mismatch_fails_closed(tmp_path):
    folders=setup_three(tmp_path)
    p=folders["DUAL_QUALITY"]/"OPEN_RESULTS.json"
    d=json.loads(p.read_text(encoding="utf-8"))
    d["compiled_ex5_sha256"]="WRONG_BINARY"
    p.write_text(json.dumps(d),encoding="utf-8")
    with pytest.raises(LedgerError,match="Incomparable"):
        compare(folders)

def test_raw_market_signals_mismatch_fails_closed(tmp_path):
    folders=setup_three(tmp_path)
    p=folders["DUAL_QUALITY"]/"native"/"QTS_7_opportunities.csv"
    with p.open(newline="",encoding="ascii") as f:
        data=list(csv.DictReader(f,delimiter=";"))
    data[0]["bid"]="4009.20"
    data[0]["ask"]="4009.43"
    with p.open("w",newline="",encoding="ascii") as f:
        writer=csv.DictWriter(f,FIELDS,delimiter=";")
        writer.writeheader();writer.writerows(data)
    with pytest.raises(LedgerError,match="Mismatched broker-native"):
        compare(folders)

def test_wrong_side_stop_is_reported_not_silently_normalized(tmp_path):
    folders=setup_three(tmp_path)
    p=folders["DUAL_BOTH"]/"QTS_TRADE_BY_TRADE.json"
    d=json.loads(p.read_text(encoding="utf-8"))
    d["trades"][0]["initial_sl"]=4001.0
    p.write_text(json.dumps(d),encoding="utf-8")
    review=compare(folders)
    assert review["variants"][0]["wrong_side_initial_sl_count"]==1

def test_research_wrapper_has_no_real_money_approval():
    ps=(GOLD.parent/"QTS_DUAL_THREEWAY.ps1").read_text(encoding="utf-8")
    assert "('DUAL_BOTH','DUAL_DIRECTIONAL','DUAL_QUALITY')" in ps
    assert "same_native_source_and_signals_verified" in ps
    assert "trade_permission -ne $false" in ps
    assert "QTS_DUAL_THREEWAY_EVIDENCE.zip" in ps
    assert "OrderSend(" not in ps
