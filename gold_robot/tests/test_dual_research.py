"""Test-only multi-strategy research contracts (not native MT5 evidence)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from dual_router_contract import Candidate, choose, candidate_quality_score


def test_both_strategies_and_sides_possible():
    for style in (1, 3):
        for side in (1, -1):
            assert choose(1, [Candidate(style, side)]) == (style, side)


def test_directional_split_is_a_distinct_post_hoc_challenger():
    assert choose(2, [Candidate(1, 1)]) == (1, 1)
    assert choose(2, [Candidate(3, -1)]) == (3, -1)
    assert choose(2, [Candidate(1, -1)]) is None
    assert choose(2, [Candidate(3, 1)]) is None


def test_simultaneous_candidates_abstain_even_if_both_agree():
    assert choose(1, [Candidate(1, 1), Candidate(3, 1)]) is None
    assert choose(1, [Candidate(1, 1), Candidate(3, -1)]) is None
    assert choose(2, [Candidate(1, 1), Candidate(3, -1)]) is None
    assert choose(1, []) is None


def test_invalid_or_ambiguous_and_nonexecutables_fail_closed():
    assert choose(1, [Candidate(1, 1, False)]) is None
    assert choose(1, [Candidate(3, 0)]) is None
    with pytest.raises(ValueError):
        choose(0, [Candidate(1, 1)])
    with pytest.raises(ValueError):
        choose(4, [Candidate(1, 1)])
    with pytest.raises(ValueError):
        choose(1, [Candidate(1, 1), Candidate(1, -1)])
    with pytest.raises(ValueError):
        choose(1, [Candidate(7, 1)])


def test_mode3_supports_both_styles_and_directions_without_direction_veto():
    for style in (1,3):
        for side in (-1,1):
            assert choose(3,[Candidate(style,side)])==(style,side)


def test_mode3_quality_tie_break_only_when_same_side_and_clear_advantage():
    retest=Candidate(1,1,quality_score=0.91)
    sweep=Candidate(3,1,quality_score=0.61)
    assert choose(1,[retest,sweep]) is None
    assert choose(3,[retest,sweep])==(1,1)
    assert choose(3,[Candidate(1,-1,quality_score=0.60),
                     Candidate(3,-1,quality_score=0.92)])==(3,-1)
    assert choose(3,[retest,Candidate(3,-1,quality_score=0.61)]) is None
    assert choose(3,[retest,Candidate(3,1,quality_score=0.82)]) is None
    assert choose(3,[retest,Candidate(3,1,quality_score=None)]) is None
    assert choose(3,[retest,Candidate(3,1,quality_score=-0.10)]) is None
    assert choose(3,[retest,Candidate(3,1,executable=False,quality_score=0.99)])==(1,1)


def test_quality_price_score_penalizes_spread_slippage_and_far_limits():
    params=dict(atr=4.0,price=4010.0,stop=4005.0,target=4015.0,
                bid=4010.0,ask=4010.2,adverse_slip=0.10)
    score=candidate_quality_score(**params)
    assert score is not None
    assert candidate_quality_score(**{**params,"ask":4011.0})<score
    assert candidate_quality_score(**{**params,"adverse_slip":0.50})<score
    assert candidate_quality_score(**{**params,"atr":2.0})<score
    assert candidate_quality_score(**{**params,"atr":0.0}) is None


def test_mode3_invalid_candidates_fail_closed():
    import math
    assert choose(3,[]) is None
    assert choose(3,[Candidate(1,1,quality_score=math.nan),
                     Candidate(3,1,quality_score=0.8)]) is None
    with pytest.raises(ValueError):
        choose(3,[Candidate(1,1),Candidate(1,-1)])


def test_mql5_challenger_is_default_off_and_cannot_touch_live():
    ea = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
    dual = (ROOT / "mt5_robot/DualResearch.mqh").read_text("utf-8")
    runner = (ROOT / "research/RunAutomaticTester.ps1").read_text("utf-8")
    installer = (ROOT / "mt5_robot/Install_QTS_Gold_Robot.ps1").read_text("utf-8")
    assert "TesterDualStrategyMode     = 0;" in ea
    assert 'EntryStyle!=QTS_ADAPTIVE_ROUTER || SignalTimeframe!=PERIOD_M15' in ea
    assert 'TesterDualStrategyMode>3' in ea
    assert 'TesterUseAdaptiveRouterV4 ||' in ea
    assert '#include "DualResearch.mqh"' in ea
    assert 'SelectDualResearchCandidate(' in ea
    assert 'request.comment=StringFormat("QTS-DUAL-M%d-S%d"' in ea
    assert 'MQLInfoInteger(MQL_TESTER)==0' in dual
    assert "eligible!=1 && !resolved_quality_collision" in dual
    assert "QUALITY_COLLISION_SELECTED" in dual
    assert "QtsDualCandidateQualityScore" in dual
    assert "signal==side" in dual
    assert "MathAbs(first_quality-quality)>=0.15" in dual
    assert "TesterDualStrategyMode==3" in dual
    assert "'DUAL_QUALITY'" in runner
    assert "SizedLots(signal,p,sl)<=0.0" in dual
    assert "AnyConflictingPositionOrOrder()" in ea
    assert "OrderCheck(request,check)" in ea
    assert "PlannedOrderFitsRisk(side,lots,price,stop)" in ea
    assert "DUAL_BOTH" in runner
    assert "DUAL_DIRECTIONAL" in runner
    assert "NATIVE_DUAL_INPUT_UNVERIFIED_NO_GO" in runner
    assert "DualResearch.mqh" in installer
    assert "$backupDual" in installer


def test_native_quality_abstention_logs_scores_without_changing_orders():
    dual=(ROOT/"mt5_robot/DualResearch.mqh").read_text(encoding="utf-8")
    assert "double second_quality=-1.0;" in dual
    assert "int candidate_side_before_reset=side;" in dual
    assert "if(second_side!=candidate_side_before_reset)" in dual
    assert "quality abstain: invalid stressed R score" in dual
    assert "quality abstain: scores %.5f %.5f margin %.5f below 0.15" in dual
    assert "eligible!=1 && !resolved_quality_collision" in dual


def test_existing_single_style_defaults_are_unchanged():
    ea = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
    assert "QTS_ADAPTIVE_ROUTER=7" in ea
    assert "input QTS_ENTRY_STYLE EntryStyle               = QTS_FORMER_STOP_LIMIT;" in ea
    assert "input bool            EnableDemoOrders          = false;" in ea
    assert "input bool            EnableDemoForwardOrders    = false;" in ea
