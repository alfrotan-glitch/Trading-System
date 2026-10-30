"""Regression contracts for seven fixed hypotheses plus an adaptive tester router.
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


def test_missing_trade_evidence_cannot_be_overwritten_by_native_html():
    assert "if(-not $hasForensics)" in AUTORUN
    assert "$item.status='FORENSIC_MISSING'" in AUTORUN
    assert "$item.status='REPORT_AND_FORENSICS_SAVED'" in AUTORUN
    assert "$badRuns=@($results | Where-Object" in AUTORUN
    assert "$nativeResult.reports_parsed -eq $names.Count" in AUTORUN
    assert "$nativeResult.all_styles_identified -eq $true" in AUTORUN


def test_entry_setup_comes_from_broker_order_comment_without_invention():
    assert "HistoryOrderGetString(order,ORDER_COMMENT)" in EA
    assert "HistoryOrderGetDouble(order,ORDER_SL)" in EA
    assert "HistoryOrderGetDouble(order,ORDER_TP)" in EA
    assert '"fee","setup_reason"' in EA
    forensic = (ROOT / "research" / "BuildTradeForensics.ps1").read_text(encoding="utf-8")
    assert "MIXED_EXIT_REASONS" in forensic
    assert "COMPLETE_MULTI_EXIT" in forensic
    assert "setup_reason=$entrySetup;exit_legs=$exitLegs" in forensic
    assert "REVERSAL_UNSUPPORTED" in forensic



def test_adaptive_router_is_closed_bar_test_only_and_never_changes_risk_execution():
    router = (ROOT / "mt5_robot" / "AdaptiveResearch.mqh").read_text(encoding="utf-8")
    assert "QTS_ADAPTIVE_ROUTER=7" in EA
    assert "if((int)EntryStyle<0 || (int)EntryStyle>9 ||" in EA
    assert "((int)EntryStyle>=4 && MQLInfoInteger(MQL_TESTER)==0)" in EA
    assert 'SelectAdaptiveCandidate(quote,side,atr,structure_level,structure_anchor,' in EA
    assert "evaluated_style=chosen_style;" in router
    assert "if(MQLInfoInteger(MQL_TESTER)==0)" in router
    assert "CopyBuffer(adx_handle,0,1,1,a)" in router
    assert "CopyBuffer(fast_handle,0,1,1,f)" in router
    assert "CopyBuffer(slow_handle,0,1,1,s)" in router
    assert "CopyBuffer(atr_handle,0,1,1,vol)" in router
    assert "if(priority==0) continue;" in router
    assert "if(SizedLots(candidate_side,p,sl)<=0.0) continue;" in router
    assert "chosen_style=-1;" in router
    assert "if(chosen_style<0)" in router
    assert "for(int style=0;style<7;style++)" in router
    assert "request.comment=evaluated_style==QTS_RETEST_LIMIT" in EA
    assert "OrderCheck(request,check)" in EA
    assert "PlannedOrderFitsRisk(side,lots,price,stop)" in EA
    assert "EntryStyle==QTS_ADAPTIVE_ROUTER" in EA
    assert "'ADAPTIVE_ROUTER'" in PRESETS
    assert "'ADAPTIVE_ROUTER'" in AUTORUN
    assert "QTS_SMC_FVG_OB=8" in EA
    assert "'SMC_FVG_OB'" in PRESETS
    assert "'SMC_FVG_OB'" in AUTORUN
    assert "QTS_M1_SCALP=9" in EA


def test_native_runner_refuses_success_exit_on_missing_evidence():
    # The normal Windows caller must not report success when any native
    # style lacks a forensic ledger, report, or independent model check.
    assert "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED" in AUTORUN
    assert "if($state -notin @('PREPARED_ONLY','TESTS_FINISHED_REVIEW_REQUIRED'," in AUTORUN
    assert "TESTS_FINISHED_WITH_EVIDENCE_GAPS" in AUTORUN


def test_selected_native_forensics_of_four_positive_screen_styles():
    assert "[string]$OnlyStyles=''" in AUTORUN
    assert "foreach($i in $selectedStyles)" in AUTORUN
    assert "SELECTED_TESTS_WITH_EVIDENCE_GAPS" in AUTORUN
    assert "_.style -eq $style -and $_.state -eq 'PARSED'" in AUTORUN
    assert "_.style -eq $style -and $_.status -eq 'IMPORTED' -and $_.deals -gt 0" in AUTORUN
    assert "selected_styles=@($selectedStyles);targeted=$targeted" in AUTORUN
    package = (ROOT / 'research' / 'PackTradeEvidence.ps1').read_text(encoding='utf-8')
    assert "foreach($i in $requiredStyles)" in package
    assert "SELECTED_CSV_FILES_PRESENT" in package
    assert "if($outcome.targeted -eq $true)" in package
    launcher = (ROOT.parent / 'QTS_FOUR_FINALISTS.bat').read_text(encoding='utf-8')
    assert '-OnlyStyles "1,3,7,8"' in launcher
    assert 'PackTradeEvidence.ps1' in launcher
    assert 'LIVE LOCKED' in launcher


def test_selected_trade_by_trade_report_never_claims_absent_styles_are_missing():
    report = (ROOT / "research" / "BuildTradeForensics.ps1").read_text(encoding="utf-8")
    assert "[int[]]$SelectedStyles=@()" in report
    assert "$targeted=$PSBoundParameters.ContainsKey('SelectedStyles')" in report
    assert "status='NOT_SELECTED'" in report
    assert "SELECTED_IMPORTED_FOR_REVIEW" in report
    assert "selected_styles=@($requiredStyles)" in report
    assert "-SelectedStyles $selectedStyles -NoOpen" in AUTORUN
    assert "$forensicSummary.status -eq 'SELECTED_IMPORTED_FOR_REVIEW'" in AUTORUN
