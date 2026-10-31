"""Read-only October 2026 ablation: native trade reconciliation and no auto promotion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from ablate_revised_variants import compare_ablation, factorial_interaction
from test_revised_v2_contract import fake_run


def setup_arms(tmp_path):
    for arm in ("BASELINE", "ENTRY_FILTER", "NEAR_TP", "COMBINED"):
        fake_run(tmp_path / arm.lower(), arm, profit=5.)
        for style in (1, 3, 7, 8):
            raw = tmp_path / arm.lower() / "native" / f"QTS_{style}_trades.csv"
            raw.write_text(
                "position_id;deal_id;entry;type;time_msc;volume;price;sl;tp;reason;gross;commission;swap;fee\n"
                "4;1;DEAL_ENTRY_IN;DEAL_TYPE_BUY;1791000000000;0.02;4180;4170;4190;DEAL_REASON_EXPERT;0;0;0;0\n"
                "4;2;DEAL_ENTRY_OUT;DEAL_TYPE_SELL;1791000060000;0.02;4181;4170;4190;DEAL_REASON_TP;5;0;0;0\n",
                encoding="utf-8",
            )
        report = next((tmp_path / arm.lower()).glob("QTS_Gold_Comparison_*.json"))
        data = json.loads(report.read_text())
        for row in data["results"]:
            row["trades"] = 1
            row["net_usd"] = 5.
        report.write_text(json.dumps(data))
    return tmp_path


def test_four_arm_native_ledger_reconciliation_and_cost_scenarios(tmp_path):
    root = setup_arms(tmp_path)
    result = compare_ablation(root)
    assert result["status"] == "RESEARCH_ONLY_POST_HOC_OCTOBER"
    assert result["edge_validated"] is False
    assert result["live"] == "LOCKED"
    assert len(result["studies"]) == 4
    for study in result["studies"]:
        assert set(study["arms"]) == {"BASELINE", "ENTRY_FILTER", "NEAR_TP", "COMBINED"}
        assert study["arms"]["BASELINE"]["recorded_net_usd"] == 5.
        assert study["arms"]["BASELINE"]["entry_lots_sum"] == .02
        assert study["exact_entry_pair_audit"]["ENTRY_FILTER"]["matched_entries"] == 1
        assert study["exact_entry_pair_audit"]["NEAR_TP"]["matched_entries"] == 1
        assert study["exact_entry_pair_audit"]["COMBINED"]["matched_entries"] == 1
        assert study["entry_exit_interaction_usd"] == 0
        assert not study["non_additive_entry_exit_interaction"]
        assert not study["evidence_sufficient_for_automatic_promotion"]
        assert study["arms"]["BASELINE"]["additional_round_turn_cost_10_per_lot_usd"] == 4.8



def test_non_additive_adaptive_interaction_is_flagged_without_promotion():
    # Exact PnL values reproduced from the uploaded exploratory 16-arm MT5 study.
    assert factorial_interaction(-234.48, -234.48, -236.32, -217.85) == 18.47
    assert factorial_interaction(21.86, 33.90, 21.86, 33.90) == 0.0

def test_ledger_conflicting_report_is_rejected(tmp_path):
    root = setup_arms(tmp_path)
    report = next((root / "combined").glob("QTS_Gold_Comparison_*.json"))
    data = json.loads(report.read_text())
    next(row for row in data["results"] if row["style"] == 7)["net_usd"] = -55.
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Native HTML metric mismatch: Total Net Profit"):
        compare_ablation(root)


def test_partial_broker_fills_or_missing_arm_fail_closed(tmp_path):
    root = setup_arms(tmp_path)
    f = root / "entry_filter" / "native" / "QTS_3_trades.csv"
    f.write_text("position_id;deal_id;entry;volume;gross;commission;swap;fee\n"
                 "4;1;DEAL_ENTRY_IN;0.02;0;0;0;0\n")
    with pytest.raises(ValueError, match="Partial position"):
        compare_ablation(root)
    f.unlink()
    with pytest.raises(ValueError, match="broker|native|style"):
        compare_ablation(root)


def test_ablation_launcher_is_read_only_and_four_arm():
    script = (ROOT.parent / "QTS_V2_ABLATION.ps1").read_text("utf-8")
    batch = (ROOT.parent / "QTS_V2_ABLATION.bat").read_text("utf-8")
    assert "foreach($arm in @('BASELINE','ENTRY_FILTER','NEAR_TP','COMBINED'))" in script
    assert "2026.10.01" in script and "2026.10.30" in script
    assert "QTS_V2_ABLATION_EVIDENCE.zip" in script
    assert "ablate_revised_variants.py" in script
    assert "QTS_V2_ABLATION.ps1" in batch
    assert "order_send" not in script
    assert "EnableDemoForwardOrders" not in script
