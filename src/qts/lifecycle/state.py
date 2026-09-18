"""Lifecycle state machine — fail closed."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class LifecycleState(StrEnum):
    RESEARCH = "RESEARCH"
    VALIDATING = "VALIDATING"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE_CANDIDATE = "LIVE_CANDIDATE"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


# Allowed transitions
_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.RESEARCH: {
        LifecycleState.VALIDATING,
        LifecycleState.REJECTED,
        LifecycleState.RETIRED,
    },
    LifecycleState.VALIDATING: {
        LifecycleState.PAPER,
        LifecycleState.RESEARCH,
        LifecycleState.REJECTED,
        LifecycleState.SUSPENDED,
        LifecycleState.RETIRED,
    },
    LifecycleState.PAPER: {
        LifecycleState.SHADOW,
        LifecycleState.SUSPENDED,
        LifecycleState.REJECTED,
        LifecycleState.RETIRED,
    },
    LifecycleState.SHADOW: {
        LifecycleState.LIVE_CANDIDATE,
        LifecycleState.SUSPENDED,
        LifecycleState.REJECTED,
        LifecycleState.RETIRED,
    },
    LifecycleState.LIVE_CANDIDATE: {
        LifecycleState.LIVE,
        LifecycleState.SUSPENDED,
        LifecycleState.REJECTED,
        LifecycleState.RETIRED,
    },
    LifecycleState.LIVE: {LifecycleState.SUSPENDED, LifecycleState.RETIRED},
    LifecycleState.SUSPENDED: {
        LifecycleState.RESEARCH,
        LifecycleState.PAPER,
        LifecycleState.SHADOW,
        LifecycleState.LIVE_CANDIDATE,
        LifecycleState.RETIRED,
        LifecycleState.REJECTED,
    },
    LifecycleState.REJECTED: {LifecycleState.RETIRED},
    LifecycleState.RETIRED: set(),
}


class StrategyLifecycle(BaseModel):
    strategy_id: str
    state: LifecycleState = LifecycleState.RESEARCH
    validation_passed: bool = False
    risk_approved: bool = False
    paper_duration_ok: bool = False

    def can_transition(self, target: LifecycleState) -> tuple[bool, str]:
        if target not in _TRANSITIONS[self.state]:
            return False, f"transition {self.state.value} → {target.value} not allowed"
        # gates
        if target == LifecycleState.PAPER and not self.validation_passed:
            return False, "need validation_passed for PAPER"
        if target == LifecycleState.LIVE_CANDIDATE and not self.paper_duration_ok:
            return False, "need paper_duration_ok for LIVE_CANDIDATE"
        if target == LifecycleState.LIVE:
            if not self.validation_passed:
                return False, "need validation_passed for LIVE"
            if not self.risk_approved:
                return False, "need risk_approved for LIVE"
            if not self.paper_duration_ok:
                return False, "need paper_duration_ok for LIVE"
        return True, "ok"

    def transition(self, target: LifecycleState) -> None:
        ok, reason = self.can_transition(target)
        if not ok:
            raise ValueError(reason)
        self.state = target
