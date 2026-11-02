"""Test-only multi-strategy research contracts (not native MT5 evidence)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from dual_router_contract import Candidate, choose


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
        choose(3, [Candidate(1, 1)])
    with pytest.raises(ValueError):
        choose(1, [Candidate(1, 1), Candidate(1, -1)])
    with pytest.raises(ValueError):
        choose(1, [Candidate(7, 1)])


def test_mql5_challenger_is_default_off_and_cannot_touch_live():
    ea = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
    dual = (ROOT / "mt5_robot/DualResearch.mqh").read_text("utf-8")
    runner = (ROOT / "research/RunAutomaticTester.ps1").read_text("utf-8")
    installer = (ROOT / "mt5_robot/Install_QTS_Gold_Robot.ps1").read_text("utf-8")
    assert "TesterDualStrategyMode     = 0;" in ea
    assert 'EntryStyle!=QTS_ADAPTIVE_ROUTER || SignalTimeframe!=PERIOD_M15' in ea
    assert 'TesterDualStrategyMode>2' in ea
    assert 'TesterUseAdaptiveRouterV4 ||' in ea
    assert '#include "DualResearch.mqh"' in ea
    assert 'SelectDualResearchCandidate(' in ea
    assert 'request.comment=StringFormat("QTS-DUAL-M%d-S%d"' in ea
    assert 'MQLInfoInteger(MQL_TESTER)==0' in dual
    assert "eligible!=1" in dual
    assert "SizedLots(signal,p,sl)<=0.0" in dual
    assert "AnyConflictingPositionOrOrder()" in ea
    assert "OrderCheck(request,check)" in ea
    assert "PlannedOrderFitsRisk(side,lots,price,stop)" in ea
    assert "DUAL_BOTH" in runner
    assert "DUAL_DIRECTIONAL" in runner
    assert "NATIVE_DUAL_INPUT_UNVERIFIED_NO_GO" in runner
    assert "DualResearch.mqh" in installer
    assert "$backupDual" in installer


def test_existing_single_style_defaults_are_unchanged():
    ea = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
    assert "QTS_ADAPTIVE_ROUTER=7" in ea
    assert "input QTS_ENTRY_STYLE EntryStyle               = QTS_FORMER_STOP_LIMIT;" in ea
    assert "input bool            EnableDemoOrders          = false;" in ea
    assert "input bool            EnableDemoForwardOrders    = false;" in ea
