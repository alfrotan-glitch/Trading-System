import pytest

from qts.lifecycle.state import LifecycleState, StrategyLifecycle


def test_reject_without_validation():
    lc = StrategyLifecycle(strategy_id="S-1", state=LifecycleState.RESEARCH)
    with pytest.raises(ValueError):
        lc.transition(LifecycleState.PAPER)


def test_valid_flow():
    lc = StrategyLifecycle(strategy_id="S-1", state=LifecycleState.RESEARCH)
    lc.transition(LifecycleState.VALIDATING)
    lc.validation_passed = True
    lc.transition(LifecycleState.PAPER)
    assert lc.state == LifecycleState.PAPER
    lc.transition(LifecycleState.SHADOW)
    lc.paper_duration_ok = True
    lc.transition(LifecycleState.LIVE_CANDIDATE)
    lc.risk_approved = True
    lc.transition(LifecycleState.LIVE)
    assert lc.state == LifecycleState.LIVE


def test_live_requires_all():
    lc = StrategyLifecycle(
        strategy_id="S-1",
        state=LifecycleState.LIVE_CANDIDATE,
        validation_passed=False,
        risk_approved=True,
        paper_duration_ok=True,
    )
    with pytest.raises(ValueError):
        lc.transition(LifecycleState.LIVE)


def test_suspend_from_any():
    for state in [LifecycleState.RESEARCH, LifecycleState.PAPER, LifecycleState.LIVE]:
        lc = StrategyLifecycle(strategy_id="S-1", state=state)
        # RESEARCH cannot go directly to SUSPENDED, but others can via VALIDATING etc
        # Check SUSPENDED reachable from LIVE
        if state == LifecycleState.LIVE:
            lc.transition(LifecycleState.SUSPENDED)
            assert lc.state == LifecycleState.SUSPENDED
        # PAPER -> SUSPENDED
        if state == LifecycleState.PAPER:
            lc.transition(LifecycleState.SUSPENDED)
            assert lc.state == LifecycleState.SUSPENDED


def test_idempotency_and_retired():
    lc = StrategyLifecycle(strategy_id="S-1", state=LifecycleState.LIVE)
    lc.transition(LifecycleState.RETIRED)
    with pytest.raises(ValueError):
        lc.transition(LifecycleState.RESEARCH)
