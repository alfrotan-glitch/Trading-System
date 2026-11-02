"""Synthetic-contract tests only: never interpreted as native profitability proof."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from dual_evidence_audit import EvidenceError, analyze


def write_run(path, variant, trades, source="a", compiled="b"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "OPEN_RESULTS.json").write_text(json.dumps({
        "research_variant": variant,
        "state": "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
        "live": "LOCKED",
        "validated_edge": False, "real_money_orders": False,
        "symbol": "XAUUSD@", "timeframe": "M15", "selected_styles": [7],
        "from_date": "2026.05.01", "to_date": "2026.11.01",
        "deposit_usd": 3000, "source_manifest_sha256": source,
        "compiled_ex5_sha256": compiled, "terminal_exe_sha256": "c",
    }), encoding="utf-8")
    (path / "QTS_TRADE_BY_TRADE.json").write_text(json.dumps({
        "status": "SELECTED_IMPORTED_FOR_REVIEW",
        "live": "LOCKED", "edge_validated": False,
        "selected_styles": [7], "trades": trades
    }), encoding="utf-8")


def trade(mode, style, side, when, net, entry=4600, stop=4595, adverse=0):
    return {
        "setup_reason": f"QTS-DUAL-M{mode}-S{style}",
        "status": "COMPLETE", "side": side,
        "entry_time_msc": str(when), "entry_price": entry,
        "initial_sl": stop, "risk_price_distance": abs(entry - stop),
        "entry_lots": 0.02, "net_usd": net, "exit_price": entry + 2,
        "charges_usd": 0, "exit_adverse_slippage_price": adverse,
        "position_id": str(when)
    }


def test_reconciled_decomposition_and_stop_warning(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    common = 1777625102418
    write_run(a, "DUAL_BOTH", [
        trade(1, 1, "BUY", common, 5),
        trade(1, 3, "BUY", 1777625103418, -2)])
    write_run(b, "DUAL_DIRECTIONAL", [
        trade(2, 1, "BUY", common, 6),
        trade(2, 3, "SELL", 1777625104418, 10, stop=4605, adverse=2)])
    result = analyze(a, b)
    s = result["sample"]
    assert s["common_entries"] == 1
    assert s["only_both"] == 1
    assert s["only_directional"] == 1
    assert s["both_net_usd"] == "3"
    assert s["directional_net_usd"] == "16"
    assert s["shared_entry_pnl_difference_usd"] == "1"
    assert s["removed_both_only_contribution_usd"] == "2"
    assert s["new_directional_only_contribution_usd"] == "10"
    assert s["net_difference_usd"] == "13"
    assert result["execution_anomalies"][0]["reason"] == "STOP_EXECUTION_DISLOCATION"
    assert result["atr_at_entry_available"] is False
    assert result["edge_validated"] is False


def test_rejects_source_mismatch(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_run(a, "DUAL_BOTH", [trade(1, 1, "BUY", 1777625102418, 1)])
    write_run(b, "DUAL_DIRECTIONAL", [trade(2, 1, "BUY", 1777625102418, 1)], compiled="different")
    with pytest.raises(EvidenceError, match="compiled_ex5_sha256"):
        analyze(a, b)


def test_rejects_forbidden_direction_and_incomplete_run(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_run(a, "DUAL_BOTH", [trade(1, 1, "BUY", 1777625102418, 1)])
    write_run(b, "DUAL_DIRECTIONAL", [trade(2, 3, "BUY", 1777625103418, 1)])
    with pytest.raises(EvidenceError, match="forbidden"):
        analyze(a, b)
    info = json.loads((b / "OPEN_RESULTS.json").read_text())
    info["state"] = "SELECTED_TESTS_WITH_EVIDENCE_GAPS"
    (b / "OPEN_RESULTS.json").write_text(json.dumps(info))
    with pytest.raises(EvidenceError, match="mismatch"):
        analyze(a, b)


def test_detects_stop_wrong_side_of_fill(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_run(a, "DUAL_BOTH", [trade(1, 1, "BUY", 1777625102418, -1, stop=4605)])
    write_run(b, "DUAL_DIRECTIONAL", [trade(2, 1, "BUY", 1777625102418, -1)])
    result = analyze(a, b)
    assert result["execution_anomalies"][0]["reason"] == "SL_WRONG_SIDE_OF_FILL"
