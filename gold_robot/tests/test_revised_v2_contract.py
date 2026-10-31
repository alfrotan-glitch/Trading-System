"""Preregistered V2 MT5 variants: read-only off-by-default A/B acceptance."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from compare_revised_variants import compare


def fake_run(root: Path, variant: str, *, profit: float = 1.0) -> None:
    root.mkdir()
    (root / "native").mkdir()
    (root / "OPEN_RESULTS.json").write_text(json.dumps({
        "state": "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
        "live": "LOCKED", "validated_edge": False,
        "research_variant": variant,
        "targeted": True, "selected_styles": [1, 3, 7, 8],
        "model": 4, "symbol": "XAUUSD@",
        "from_date": "2026.10.01", "to_date": "2026.10.30",
        "deposit_usd": 3000, "timeframe": "M15",
    }), encoding="utf-8")
    rows = []
    for style in (1, 3, 7, 8):
        (root / "native" / f"QTS_{style}_trades.csv").write_text(
            "position_id;deal_id;entry;type;time_msc;volume;price;sl;tp;reason;gross;commission;swap;fee\n"
            f"{style};{style*10+1};DEAL_ENTRY_IN;DEAL_TYPE_BUY;1791000000000;0.01;4180;4170;4190;DEAL_REASON_EXPERT;0;0;0;0\n"
            f"{style};{style*10+2};DEAL_ENTRY_OUT;DEAL_TYPE_SELL;1791000060000;0.01;4181;4170;4190;DEAL_REASON_TP;{profit};0;0;0\n",
            encoding="utf-8")
        native_html = (
            f"<!doctype html><html><body>EntryStyle={style}<table>"
            f"<tr><td>Total Net Profit</td><td>{profit}</td></tr>"
            "<tr><td>Profit Factor</td><td>1.1</td></tr>"
            "<tr><td>Total Trades</td><td>1</td></tr>"
            "<tr><td>Equity Drawdown Maximal</td><td>15.0</td></tr>"
            "</table></body></html>"
        ).encode("utf-8")
        (root / "native" / f"QTS_{style}.htm").write_bytes(native_html)
        rows.append({
            "style": style, "state": "PARSED", "style_identity": "STYLE_VERIFIED",
            "sha256": hashlib.sha256(native_html).hexdigest(),
            "trades": 1, "net_usd": profit,
            "profit_factor": 1.1, "maximal_equity_drawdown": 15.0,
        })
    (root / "QTS_Gold_Comparison_sample.json").write_text(json.dumps({
        "results": rows, "reports_parsed": 4, "validated_edge": False,
    }), encoding="utf-8")


def test_frozen_october_holdout_uses_same_native_evidence(tmp_path):
    baseline = tmp_path / "baseline"
    combined = tmp_path / "combined"
    fake_run(baseline, "BASELINE", profit=2.)
    fake_run(combined, "COMBINED", profit=-3.)
    result = compare(baseline, combined)
    assert result["state"] == "POST_HOC_EXPLORATORY_COMPARISON_ONLY"
    assert result["live"] == "LOCKED"
    assert result["edge_validated"] is False
    assert len(result["strategy_reports"]) == 4
    assert result["strategy_reports"][0]["net_difference_usd"] == -5.
    assert result["strategy_reports"][0]["native_pair_audit"]["matched_entries"] == 1
    assert not result["strategy_reports"][0]["native_pair_audit"]["evidence_sufficient_for_automatic_promotion"]
    assert result["individual_styles_are_not_an_executable_portfolio"]


def test_different_dates_or_missing_native_trades_cannot_validate(tmp_path):
    baseline = tmp_path / "baseline"
    combined = tmp_path / "combined"
    fake_run(baseline, "BASELINE")
    fake_run(combined, "COMBINED")
    p = combined / "OPEN_RESULTS.json"
    manifest = json.loads(p.read_text())
    manifest["to_date"] = "2026.10.29"
    p.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="not match"):
        compare(baseline, combined)
    manifest["to_date"] = "2026.10.30"
    p.write_text(json.dumps(manifest))
    (combined / "native/QTS_8_trades.csv").unlink()
    with pytest.raises(ValueError, match="style=8"):
        compare(baseline, combined)


def test_experiment_is_disabled_by_default_and_only_on_tester():
    ea = (ROOT / "mt5_robot/QTS_Gold_Robot.mq5").read_text("utf-8")
    tester = (ROOT / "research/RunAutomaticTester.ps1").read_text("utf-8")
    ps = (ROOT.parent / "QTS_REVISED_COMPARE.ps1").read_text("utf-8")
    launcher = (ROOT.parent / "QTS_REVISED_COMPARE.bat").read_text("utf-8")
    assert "input bool            TesterUseEntryQualityV2    = false;" in ea
    assert "input bool            TesterProtectNearTPV2      = false;" in ea
    assert "MQLInfoInteger(MQL_TESTER)==0" in ea
    assert "TesterEntryQualityV2(side,quote,atr,price,stop)" in ea
    assert "CopyRates(_Symbol,SignalTimeframe,1,1,closed)" in ea
    assert "TesterProtectNearTPPosition(ticket,sl,tp)" in ea
    assert "PositionModify(ticket,proposed,original_tp)" in ea
    assert "if((proposed-current_sl)*(double)side<=step*0.51) return;" in ea
    assert "if(advance<0.80*target_gap) return;" in ea
    assert "'TesterUseEntryQualityV2'=($ResearchVariant -in" in tester
    assert "'TesterProtectNearTPV2'=($ResearchVariant -in" in tester
    assert "research_variant=$ResearchVariant" in tester
    assert "foreach($arm in @('BASELINE','COMBINED'))" in ps
    assert "$from='2026.10.01'" in ps
    assert "$to='2026.10.30'" in ps
    assert "QTS_V2_HOLDOUT_EVIDENCE.zip" in ps
    assert "QTS_REVISED_COMPARE.ps1" in launcher
    assert "EnableDemoForwardOrders" not in ps
