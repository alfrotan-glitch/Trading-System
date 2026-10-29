"""Regression contracts for the seven isolated MT5 research hypotheses.
This suite cannot compile MQL5 or validate a profitable edge."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EA = (ROOT / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text(encoding="utf-8")
OP = (ROOT / "mt5_robot" / "OpportunityResearch.mqh").read_text(encoding="utf-8")
PRESETS = (ROOT / "research" / "MakeTesterPresets.ps1").read_text(encoding="utf-8")
AUTORUN = (ROOT / "research" / "RunAutomaticTester.ps1").read_text(encoding="utf-8")


def test_seven_distinct_strategy_ids_and_tester_only_new_hypotheses():
    names = ("QTS_FORMER_STOP_LIMIT", "QTS_RETEST_LIMIT",
             "QTS_BREAK_ACCEPT_RETEST", "QTS_SWEEP_RECLAIM",
             "QTS_TREND_IMPULSE", "QTS_RANGE_REJECTION",
             "QTS_INSIDE_BREAKOUT")
    for number, name in enumerate(names):
        assert re.search(rf"\b{name}={number}\b", EA), (number, name)
    assert "((int)EntryStyle>=4 && MQLInfoInteger(MQL_TESTER)==0)" in EA
    assert 'QTS GOLD ROBOT: LIVE ACCOUNT BLOCKED' in EA
    assert 'QTS_TREND_IMPULSE' in OP
    assert 'QTS_RANGE_REJECTION' in OP
    assert 'QTS_INSIDE_BREAKOUT' in OP


def test_every_entry_uses_canonical_risk_and_order_guards():
    for key in ("OrderCheck(request,check)", "SizedLots(side,price,stop)",
                "PlannedOrderFitsRisk(side,lots,price,stop)",
                "AnyConflictingPositionOrOrder()",
                "PrepareOpportunityLimit(side,quote,atr,structure_level,structure_anchor",
                "PendingExpiration(deadline)", "ORDER_TYPE_BUY_LIMIT",
                "ORDER_TYPE_SELL_LIMIT"):
        assert key in EA, key
    assert "MqlRates mother=bars[n-3]" in OP
    assert "CopyRates(_Symbol,SignalTimeframe,1,n,bars)" in OP
    assert "CopyBuffer(atr_handle,0,1,1,atr)" in OP


def test_each_deal_has_broker_exit_reason_and_position_join_key():
    for key in ("HistoryDealGetInteger(trans.deal,DEAL_POSITION_ID)",
                "DEAL_REASON)", "HistoryDealGetDouble(trans.deal,DEAL_SL)",
                "HistoryDealGetDouble(trans.deal,DEAL_TP)",
                "double OnTester()", "HistoryDealGetInteger(deal,DEAL_POSITION_ID)",
                "FILE_COMMON", "QTS_FORENSIC_STYLE_"):
        assert key in EA, key
    assert "QTS_TRADE_BY_TRADE" in AUTORUN
    assert "QTS_FORENSIC_STYLE_" in AUTORUN


def test_seven_presets_are_active_risk_safeguards_in_auto_runner():
    assert "for($style=0;$style -lt $names.Count;$style++)" in PRESETS
    assert "TesterIgnoreDailyAndPeakStops']='false'" in PRESETS
    assert "for($i=0;$i -lt $names.Count;$i++)" in AUTORUN
    assert "EnableDemoForwardOrders=false" in AUTORUN
    assert "TesterIgnoreDailyAndPeakStops=false" in AUTORUN
    assert "risk stops active" in AUTORUN
