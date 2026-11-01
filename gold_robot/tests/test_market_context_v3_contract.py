"""Frozen M15 adaptive V3: source review checks, NOT native MetaEditor compilation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
V3 = (ROOT / "mt5_robot/MarketContextV3.mqh").read_text("utf-8")
RUNNER = (ROOT / "research/RunAutomaticTester.ps1").read_text("utf-8")
ADAPTIVE = (ROOT / "mt5_robot/AdaptiveResearch.mqh").read_text("utf-8")
INSTALLER = (ROOT / "mt5_robot/Install_QTS_Gold_Robot.ps1").read_text("utf-8")


def test_v3_is_unarmed_and_tester_only():
    assert "input bool            TesterUseMarketContextV3   = false;" in EA
    assert "#include \"MarketContextV3.mqh\"" in EA
    assert "(TesterUseEntryQualityV2 || TesterProtectNearTPV2 || TesterUseMarketContextV3 ||" in EA
    assert "EntryStyle!=QTS_ADAPTIVE_ROUTER || SignalTimeframe!=PERIOD_M15" in EA
    assert "MQLInfoInteger(MQL_TESTER)==0" in V3
    assert "if(!TesterUseMarketContextV3)" in V3
    assert "return true;" in V3
    assert "LIVE" not in V3 or "Strategy Tester ONLY" in V3


def test_v3_context_veto_precedes_any_broker_order():
    at = EA.index("if(!TesterMarketContextV3(side,evaluated_style,quote,atr,price,stop,target))")
    check = EA.index("OrderCheck(request,check)")
    send = EA.index("OrderSend(request,result)")
    assert at < check < send
    assert "double risk=EstimatedMonetaryLoss(side,min_lot,entry,stop);" in V3
    assert "net_tp/risk<1.25" in V3
    assert "gap<3.0*spread" in V3
    assert "QTS V3 ACCEPT research-only" in V3
    assert "QTS V3 veto closed-bar market context" in V3


def test_v3_only_uses_completed_multitimeframe_data():
    for fragment in (
        "CopyRates(_Symbol,PERIOD_M15,1,QTS_V3_M15_HISTORY,m15)",
        "CopyRates(_Symbol,PERIOD_M5,1,2,m5)",
        "CopyRates(_Symbol,PERIOD_H1,1,1,h1)",
        "CopyBuffer(h1_handle,0,1,1,h1_ema)",
        "CopyBuffer(fast_handle,0,1,1,m15_ema)",
        "m15[QTS_V3_M15_HISTORY-1].time+900!=asof",
        "m5[1].time+300>asof",
        "m15[k].time-m15[k-1].time!=900",
        "m5[1].close<m5[0].close",
        "h1[0].close<=h1_ema[0]",
        "m15[last].low>=support",
        "m15[last].high<=resistance",
    ):
        assert fragment in V3, fragment
    assert "CopyRates(_Symbol,PERIOD_M5,0," not in V3
    assert "CopyRates(_Symbol,PERIOD_M15,0," not in V3
    assert "CopyBuffer(h1_handle,0,0," not in V3


def test_candidate_ranking_does_not_hide_valid_alternatives():
    assert "if(TesterUseMarketContextV3 &&" in ADAPTIVE
    assert "!TesterMarketContextV3(candidate_side,style,quote,candidate_atr,p,sl,tp)" in ADAPTIVE
    assert ADAPTIVE.index("!TesterMarketContextV3(candidate_side") < ADAPTIVE.index("double score=")
    assert "A failed top candidate cannot hide another valid alternative." in ADAPTIVE
    assert "bool TesterMarketContextV3(const int side,const int style," in EA


def test_windows_installer_installs_all_required_context_includes_atomically():
    assert "MarketContextV3.mqh" in INSTALLER
    for phrase in (
        "$contextV3Rows", "$contextV3Hash", "$destContextV3",
        "$backupContextV3", "$hadContextV3",
        "Copy-Item -LiteralPath $contextV3 -Destination $destContextV3 -Force",
        "Copy-Item -LiteralPath $backupContextV3 -Destination $destContextV3 -Force",
        "Remove-Item -LiteralPath $destContextV3 -Force",
        "V3 market-context include changed during compilation.",
    ):
        assert phrase in INSTALLER, phrase
    assert INSTALLER.index("Missing V3 market-context include") < INSTALLER.index("$experts = ")
    assert INSTALLER.index("$contextV3Hash = ") < INSTALLER.index("Copy-Item -LiteralPath $contextV3 -Destination $destContextV3 -Force")


def test_broker_minimum_lot_step_and_budget_are_never_rounded_up():
    start = EA.index("double SizedLots(")
    end = EA.index("// Owner-defined relocation:", start)
    body = EA[start:end]
    assert "risk_limit=MathMin(budget/one_lot_cost,maximum)" in body
    assert "MathFloor((risk_limit-minimum)/step+1e-9)" in body
    assert "NormalizeDouble(minimum+units*step,8)" in body
    assert "if(volume<minimum" in body
    assert "loss>budget+1e-8" in body


def test_automated_tester_v3_is_isolated_from_baseline():
    assert "'BASELINE','ENTRY_FILTER','NEAR_TP','COMBINED','CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO'" in RUNNER
    assert "$ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO') -and ($OnlyStyles -ne '7')" in RUNNER
    assert "'TesterUseMarketContextV3'=($ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO'))" in RUNNER
    assert "'TesterUseEntryQualityV2'=($ResearchVariant -in @('ENTRY_FILTER','COMBINED'))" in RUNNER
    assert "'TesterProtectNearTPV2'=($ResearchVariant -in @('NEAR_TP','COMBINED'))" in RUNNER
    assert "EnableDemoForwardOrders" not in V3
    assert "OrderSend(" not in V3
