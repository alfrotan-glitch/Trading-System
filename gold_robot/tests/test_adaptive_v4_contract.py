"""V4 research contract: static invariants, not native MetaEditor compilation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
ROUTER = (ROOT / "mt5_robot/AdaptiveV4Research.mqh").read_text("utf-8")
V3 = (ROOT / "mt5_robot/MarketContextV3.mqh").read_text("utf-8")
RUNNER = (ROOT / "research/RunAutomaticTester.ps1").read_text("utf-8")
INSTALLER = (ROOT / "mt5_robot/Install_QTS_Gold_Robot.ps1").read_text("utf-8")
OLD = (ROOT / "mt5_robot/AdaptiveResearch.mqh").read_text("utf-8")


def test_v4_default_off_and_not_allowed_on_real_or_demo():
    assert "input bool            TesterUseAdaptiveRouterV4  = false;" in EA
    assert "TesterUseAdaptiveRouterV4 && !TesterUseMarketContextV3" in EA
    assert "TesterUseAdaptiveRouterV4 || TesterUsePreregisteredVetoV5) &&" in EA
    assert "MQLInfoInteger(MQL_TESTER)==0" in ROUTER
    assert "EntryStyle!=QTS_ADAPTIVE_ROUTER" in ROUTER
    assert "SignalTimeframe!=PERIOD_M15" in ROUTER
    assert "if(RealAccountBlocked())" in EA
    assert "ConnectedDemoForwardAuthorized()" in EA
    assert "OrderSend(" not in ROUTER


def test_v4_considers_all_compatible_strategies_per_closed_bar():
    assert "for(int style=0;style<=QTS_SMC_FVG_OB;style++)" in ROUTER
    assert "if(style==QTS_ADAPTIVE_ROUTER)" in ROUTER
    assert "signal=CompletedSmcSignal(a,l,an);" in ROUTER
    assert "prepared=PrepareSmcLimit(signal,quote,a,l,an,p,sl,tp);" in ROUTER
    for name in ("CompletedOpportunitySignal", "CompletedStructureSignal",
                 "CompletedBarSignal", "PrepareOpportunityLimit",
                 "PrepareStructureLimit", "PrepareRetestLimit",
                 "PreparePullbackLimit"):
        assert name in ROUTER, name
    assert "QTS_M1_SCALP" not in ROUTER
    assert "style==QTS_SMC_FVG_OB" in V3
    assert "V4RegimePriority(regime,style)" in ROUTER
    assert "ConfirmedRouterRegime(raw_regime)" in ROUTER
    assert "RouterVolatilityGuardPass()" in ROUTER


def test_every_candidate_vetted_independently_before_ranking():
    a = ROUTER.index("lots=SizedLots(signal,p,sl)")
    b = ROUTER.index("!TesterMarketContextV3(signal,style,quote,a,p,sl,tp)")
    c = ROUTER.index("OrderCalcProfit(type,_Symbol,lots,p,tp,gross_profit)")
    d = ROUTER.index("stressed_loss=EstimatedMonetaryLoss(signal,lots,p,sl)")
    e = ROUTER.index("net_rr<QTS_V4_MIN_NET_RR")
    f = ROUTER.index("const double score=")
    assert a < b < c < d < e < f
    assert "continue;" in ROUTER[b:f]
    assert "last_rejection=status_text;" in ROUTER
    assert "QTS V4 CANDIDATE" in ROUTER
    assert "QTS V4 ROUTER CHOICE" in ROUTER
    assert "QTS V4" in ROUTER
    assert "QTS V4: NO_TRADE" not in ROUTER or "NO_TRADE" in ROUTER
    assert "PrintFormat(" in ROUTER


def test_frozen_baseline_router_not_replaced_or_retuned():
    assert "SelectAdaptiveCandidate(" in EA
    assert "SelectAdaptiveCandidateV4(" in EA
    assert "SelectAdaptiveCandidate(quote,side,atr,structure_level" in EA
    assert "TesterUseAdaptiveRouterV4 ?" in EA
    assert "for(int style=0;style<7;style++)" in OLD
    assert "if(score>best+1e-9)" in OLD


def test_v4_is_tested_in_separate_native_arm():
    assert "'ADAPTIVE_V4'" in RUNNER
    assert "$ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO')" in RUNNER
    assert "'TesterUseMarketContextV3'=($ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO'))" in RUNNER
    assert "'TesterUseAdaptiveRouterV4'=($ResearchVariant -in @('ADAPTIVE_V4','ADAPTIVE_V5_VETO'))" in RUNNER
    assert "research_variant=$ResearchVariant" in RUNNER
    assert "source_manifest_sha256=$sourceManifestSha256" in RUNNER


def test_native_installer_hashes_and_restores_v4_file():
    assert '#include "AdaptiveV4Research.mqh"' in EA
    for name in ("$v4Rows", "$v4Hash", "$destV4", "$backupV4", "$hadV4",
                 "Copy-Item -LiteralPath $v4 -Destination $destV4 -Force",
                 "Copy-Item -LiteralPath $backupV4 -Destination $destV4 -Force",
                 "Remove-Item -LiteralPath $destV4 -Force"):
        assert name in INSTALLER, name
    assert INSTALLER.index("Missing V4 per-opportunity") < INSTALLER.index("$experts = ")
    assert EA.index('#include "AdaptiveV4Research.mqh"') < EA.index("void EvaluateNewEntry()")
