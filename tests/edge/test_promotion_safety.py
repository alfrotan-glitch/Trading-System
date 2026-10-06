import pytest

from qts.edge.promotion import PromotionLedger, PromotionState


def test_promotion_transition_is_evidence_backed(tmp_path):
    ledger = PromotionLedger(tmp_path / "promotion.db")
    with pytest.raises(ValueError, match="evidence_hash"):
        ledger.transition("strategy-a", PromotionState.CANDIDATE)
    record = ledger.transition(
        "strategy-a",
        PromotionState.CANDIDATE,
        reason="candidate",
    )
    assert record.to_state == PromotionState.CANDIDATE

    with pytest.raises(ValueError, match="evidence_hash"):
        ledger.transition("strategy-a", PromotionState.VALIDATED)

    record = ledger.transition(
        "strategy-a",
        PromotionState.VALIDATED,
        reason="validated evidence",
        evidence_hash="sha256:test-evidence",
    )
    assert record.to_state == PromotionState.VALIDATED


def test_promotion_state_check_and_write_are_serialized(tmp_path):
    ledger = PromotionLedger(tmp_path / "promotion.db")
    ledger.transition("strategy-a", PromotionState.CANDIDATE)
    first = ledger.transition(
        "strategy-a",
        PromotionState.VALIDATING,
        evidence_hash="sha256:validation",
    )
    assert first.to_state == PromotionState.VALIDATING
