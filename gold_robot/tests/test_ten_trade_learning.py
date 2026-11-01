"""Ten-trade checkpoints must create disciplined research, never auto-fit orders."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLD / "research"))
from ten_trade_learning import reflect, validate_positions


EXIT_START = 1_780_100_000_000


def position(i: int, *, style=8, regime="TREND", net=-2.0,
             reason="DEAL_REASON_SL", duration=3):
    exit_ms = EXIT_START + i*86_400_000
    return {
        "position_id": str(i), "selected_style": style, "strategy": "SMC_FVG_OB",
        "regime": regime, "side": "BUY", "entry_price": 4000.0,
        "initial_sl": 3992.0, "initial_tp": 4016.0,
        "exit_price": 3991.5 if reason == "DEAL_REASON_SL" else 4016.0,
        "entry_time_msc": exit_ms-duration*60000, "exit_time_msc": exit_ms,
        "exit_reason": reason, "lots": 0.02, "broker_net_usd": net,
        "gross_usd": net+0.2, "recorded_charges_usd": -0.2,
        "duration_minutes": duration, "price_rr_ex_ante": 2.0,
        "broker_exit_deal_ids": [f"deal-{i}"],
    }


def attribution(*rows):
    return {
        "schema": "qts.mt5.v4.position_strategy_attribution.v1",
        "status": "ATTRIBUTED_FOR_RESEARCH_ONLY",
        "live": "LOCKED", "edge_validated": False, "can_autotune_or_promote": False,
        "issues": [], "native_positions_seen": len(rows),
        "native_positions_attributed": len(rows), "positions": list(rows),
    }


def unknown_quotes(*rows):
    stops = [r for r in rows if r["exit_reason"] == "DEAL_REASON_SL"]
    return {
        "schema": "qts.mt5.v4.post_stop_strategy_cohorts.v1",
        "status": "TICKS_MISSING_NO_GO",
        "live": "LOCKED", "edge_validated": False,
        "automated_model_promotion": False, "issues": [],
        "native_attributed_positions": len(rows),
        "native_stop_exits": len(stops),
        "stopped_positions": [{
            "broker_position_id": r["position_id"],
            "trade_id": f"7:{r['position_id']}",
            "selected_style": r["selected_style"],
            "regime": r["regime"],
            "stop_exit_time_ms": r["exit_time_msc"],
            "horizons": {"120": {
                "quote_evidence": "UNKNOWN", "original_tp_touched": None,
            }},
        } for r in stops],
    }


def test_every_complete_ten_trade_batch_reviewed_once_and_tail_kept():
    rows = [position(i) for i in range(1, 26)]
    result = reflect(attribution(*reversed(rows)))
    assert result["complete_checkpoints"] == 2
    assert result["unreviewed_tail_positions"] == 5
    assert len(result["review_all_trades"]) == 25
    assert result["nonoverlapping_chronological_checkpoints"][0]["position_ids_in_exit_time_order"] == [
        str(i) for i in range(1, 11)]
    assert result["nonoverlapping_chronological_checkpoints"][1]["position_ids_in_exit_time_order"] == [
        str(i) for i in range(11, 21)]
    assert result["can_send_orders"] is False
    assert result["can_self_promote_strategy"] is False
    assert result["can_edit_ea"] is False
    assert result["auto_risk_increase"] is False


def test_first_ten_losses_propose_correction_not_a_deployed_change():
    rows = [position(i) for i in range(1, 11)]
    result = reflect(attribution(*rows))
    proposals = result["nonoverlapping_chronological_checkpoints"][0]["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["style"] == 8
    assert proposals[0]["regime"] == "TREND"
    assert proposals[0]["decision"] == "OBSERVE_REPEAT_BEFORE_SHADOW_CHALLENGER"
    assert proposals[0]["candidate_repair"] == "SHADOW_ONLY_SKIP_STYLE_IN_SPECIFIC_REGIME"
    assert proposals[0]["do_not_disable_production_strategy"]
    assert result["edge_validated"] is False
    assert result["live"] == "LOCKED"
    assert result["nonoverlapping_chronological_checkpoints"][0]["native_stop_exits"] == 10


def test_20_losses_of_same_group_propose_unseen_shadows_not_auto_execute():
    rows = [position(i) for i in range(1, 21)]
    result = reflect(attribution(*rows))
    assert len(result["proposed_shadow_only_revisions"]) == 2
    assert result["proposed_shadow_only_revisions"][1]["repeat_batches_with_similar_concern"] == 2
    assert result["proposed_shadow_only_revisions"][1]["decision"] == "PREREGISTER_UNSEEN_SHADOW_CHALLENGER"
    assert result["independent_shadow_acceptance"]["minimum_independently_observed_positions"] == 200
    assert result["independent_shadow_acceptance"]["minimum_full_separate_test_months"] == 6
    assert result["can_send_orders"] is False


def test_mixed_cohorts_need_minimum_three_trades_per_ten_checkpoint():
    rows = ([position(i, style=8) for i in range(1, 3)]
            + [position(i, style=3, regime="RANGE") for i in range(3, 5)]
            + [position(i, style=1, regime="TRANSITION") for i in range(5, 7)]
            + [position(i, style=0, regime="RANGE") for i in range(7, 9)]
            + [position(i, style=5, regime="RANGE") for i in range(9, 11)])
    result = reflect(attribution(*rows))
    assert result["complete_checkpoints"] == 1
    assert result["proposed_shadow_only_revisions"] == []
    assert result["nonoverlapping_chronological_checkpoints"][0]["next_step"].startswith("NO_EX_ANTE")


def test_less_than_ten_never_forces_strategy_changes():
    result = reflect(attribution(*[position(i) for i in range(1, 10)]))
    assert result["complete_checkpoints"] == 0
    assert result["status"] == "WAITING_FOR_TEN_COMPLETE_TRADES"
    assert result["unreviewed_tail_positions"] == 9
    assert result["proposed_shadow_only_revisions"] == []


def test_high_winning_batch_is_not_treated_as_proof_of_edge():
    rows = [position(i, net=100, reason="DEAL_REASON_TP") for i in range(1, 11)]
    result = reflect(attribution(*rows))
    assert result["nonoverlapping_chronological_checkpoints"][0]["stressed_winners"] == 10
    assert result["edge_validated"] is False
    assert result["can_self_promote_strategy"] is False
    assert result["proposed_shadow_only_revisions"] == []


def test_all_missing_post_stop_ticks_stay_unknown_not_false_losses():
    rows = [position(i) for i in range(1, 11)]
    report = reflect(attribution(*rows), unknown_quotes(*rows))
    assert all(row["full_quote_post_stop_tp_touch"] is None for row in report["review_all_trades"])
    assert "SOME_POST_STOP_REPLAYS_LACK_COMPLETE_BID_ASK_TICKS" in report["unresolved_evidence"]


def test_confirmed_post_stop_target_touch_remains_descriptive_only():
    rows = [position(i) for i in range(1, 11)]
    post = unknown_quotes(*rows)
    post["status"] = "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"
    for r in post["stopped_positions"]:
        r["horizons"]["120"] = {"quote_evidence": "COMPLETE", "original_tp_touched": True}
    result = reflect(attribution(*rows), post)
    assert all("OBSERVED_ORIGINAL_TP_AFTER_ACTUAL_STOP_NOT_REALIZED_PROFIT" in
               row["diagnostic_flags"] for row in result["review_all_trades"])
    assert result["can_self_promote_strategy"] is False


def test_bad_price_or_broker_deal_reconciliation_fails_entire_review():
    rows = [position(i) for i in range(1, 11)]
    rows[0]["broker_net_usd"] = 999999
    with pytest.raises(ValueError, match="charges/profit"):
        reflect(attribution(*rows))
    rows = [position(i) for i in range(1, 11)]
    rows[2]["broker_exit_deal_ids"] = ["deal-1"]
    with pytest.raises(ValueError, match="Duplicated"):
        reflect(attribution(*rows))


def test_foreign_quote_report_cannot_train_another_strategy():
    rows = [position(i) for i in range(1, 11)]
    post = unknown_quotes(*rows)
    post["stopped_positions"][0]["selected_style"] = 3
    with pytest.raises(ValueError, match="foreign/duplicate"):
        reflect(attribution(*rows), post)
    post = unknown_quotes(*rows)
    post["stopped_positions"][0]["horizons"]["120"]["original_tp_touched"] = True
    with pytest.raises(ValueError, match="fabricated"):
        reflect(attribution(*rows), post)


def test_stop_out_is_critical_and_does_not_trigger_risk_escalation():
    rows = [position(i) for i in range(1, 11)]
    rows[0]["exit_reason"] = "DEAL_REASON_SO"
    result = reflect(attribution(*rows))
    assert "BROKER_STOP_OUT_PRESENT; DO_NOT_AUTOMATICALLY_RESUME_EXECUTION" in result["unresolved_evidence"]
    assert result["can_send_orders"] is False


def test_nonoverlapping_trade_batch_determinism():
    rows = [position(i) for i in range(1, 26)]
    first = reflect(attribution(*rows))
    second = reflect(attribution(*reversed(rows)))
    assert first == second


def test_no_order_or_ea_mutation_inside_learner():
    learner = (GOLD / "research" / "ten_trade_learning.py").read_text("utf-8")
    for text in ("OrderSend(", "order_send(", "CTrade", "MetaTrader5", "git push"):
        assert text not in learner
    assert '"can_edit_ea": False' in learner
    assert '"can_self_promote_strategy": False' in learner


def test_native_mt5_v4_tester_automatically_runs_evidence_review():
    runner = (GOLD / "research" / "RunAutomaticTester.ps1").read_text("utf-8")
    assert "if($ResearchVariant -eq 'ADAPTIVE_V4')" in runner
    assert "research\\ten_trade_learning.py" in runner
    assert "QTS_TEN_TRADE_REFLECTION.json" in runner
    assert "--attribution $attr --post-stop $stopSummary --output $tenTradeReport" in runner
    assert "if($LASTEXITCODE -ne 0" in runner
    assert "'WAITING_FOR_TEN_COMPLETE_TRADES','TEN_TRADE_CHECKPOINTS_READY_RESEARCH_ONLY'" in runner
    assert "$reflection.can_send_orders -ne $false" in runner
    assert "$reflection.can_self_promote_strategy -ne $false" in runner


def test_missing_style_identity_or_nan_cannot_be_substituted_after_ten():
    rows = [position(i) for i in range(1, 11)]
    rows[0]["selected_style"] = 7
    with pytest.raises(ValueError, match="Unknown ex-ante"):
        reflect(attribution(*rows))
    rows = [position(i) for i in range(1, 11)]
    rows[0]["recorded_charges_usd"] = float("nan")
    with pytest.raises(ValueError, match="nonfinite"):
        reflect(attribution(*rows))


def test_policy_honours_original_native_broker_exit_reason():
    rows = [position(i) for i in range(1, 11)]
    rows[0]["exit_reason"] = "made_up"
    with pytest.raises(ValueError, match="Unknown broker exit cause"):
        reflect(attribution(*rows))
