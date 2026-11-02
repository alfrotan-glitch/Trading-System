"""Synthetic tests only; broker history and profitability are not simulated."""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
from dual_atr_market_audit import regime, enrich

def test_unknown_atr_never_becomes_market_regime():
    assert regime({"status":"UNKNOWN_MARKET_HISTORY","m15_atr_ratio_to_trailing_median":1.5})=="UNKNOWN"
    assert regime({"status":"COMPLETE_CLOSED_BAR_AND_BID_ASK","m15_atr_ratio_to_trailing_median":0.7})=="LOW"
    assert regime({"status":"COMPLETE_CLOSED_BAR_AND_BID_ASK","m15_atr_ratio_to_trailing_median":1.0})=="NORMAL"
    assert regime({"status":"COMPLETE_CLOSED_BAR_AND_BID_ASK","m15_atr_ratio_to_trailing_median":1.5})=="HIGH"

def _trade(mode,net):
    return {"position_id":"3","entry_time_msc":"1777625102418",
            "entry_price":4609.35,"initial_sl":4606.19,
            "exit_reason":"DEAL_REASON_TP","exit_adverse_slippage_price":0,
            "_entry":4609.35,"_stop":4606.19,"_lots":0.02,"_net":net}

def test_enrichment_counts_shared_history_once_and_never_authorizes_trades():
    same_key=(1,"BUY","1777625102418",4609.35)
    with patch("dual_atr_market_audit.analyze",return_value={"sample":{"net_difference_usd":"5.0"}}),\
         patch("dual_atr_market_audit.read_run",side_effect=[
             (None,{same_key:_trade(1,2.5)}),
             (None,{same_key:_trade(2,7.5)})
         ]):
        seen=[]
        def market(ms):
            seen.append(ms)
            return {"status":"COMPLETE_CLOSED_BAR_AND_BID_ASK","m15_atr14":4.0,
                    "m15_atr_ratio_to_trailing_median":1.4,"spread_to_atr":0.04,"h1_bias":"BUY"}
        result=enrich(Path("a"),Path("b"),market)
    assert len(seen)==1
    assert result["quote_requests"]==1
    assert result["coverage"]["DUAL_BOTH"]["observed"]==1
    assert result["coverage"]["DUAL_DIRECTIONAL"]["observed"]==1
    assert result["cohorts"][0]["regime"]=="HIGH"
    assert result["live"]=="LOCKED" and result["edge_validated"] is False
    assert result["orders_sent"]==0 and result["strategy_changed"] is False
    assert result["independent_holdout"] is False

def test_missing_history_fail_closed_without_filling_values():
    key=(1,"BUY","1777625102418",4609.35)
    with patch("dual_atr_market_audit.analyze",return_value={"sample":{}}),\
         patch("dual_atr_market_audit.read_run",side_effect=[
             (None,{key:_trade(1,-2)}),
             (None,{key:_trade(2,-2)})
         ]):
        result=enrich(Path("a"),Path("b"),lambda ms:{
            "status":"UNKNOWN_MARKET_HISTORY","missing_reason":"bid ask unavailable"})
    assert result["status"]=="INCOMPLETE_BROKER_HISTORY_NO_GO"
    assert result["coverage"]["DUAL_BOTH"]["missing"]==1
    assert result["trades"][0]["sl_distance_atr"] is None
    assert result["trades"][0]["regime"]=="UNKNOWN"

def test_one_click_script_is_read_only():
    root=Path(__file__).resolve().parents[2]
    ps=(root/"QTS_DUAL_ATR_REVIEW.ps1").read_text("utf-8")
    script=(root/"gold_robot/research/dual_atr_market_audit.py").read_text("utf-8")
    assert "market_at_entry(mt5,ms)" in script
    assert 'mt5.shutdown()' in script
    assert 'live":"LOCKED"' in script
    assert "QTS_DUAL_ATR_REVIEW.zip" in ps
    assert not any(x in script for x in ("order_send(","position_close(","order_modify("))
