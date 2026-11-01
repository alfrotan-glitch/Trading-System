"""Synthetic native-deal-derived fixtures. No real broker or profitability claim."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLD / "research"))

from v4_position_attribution import audit, inspect_position, read_tag


def trade(*, pos="p1", tag="QTSV4-S8-R2", gross=12.0, charges=-1.0,
          exit_reason="DEAL_REASON_TP", status="COMPLETE", lots=0.02):
    return {
        "style": 7, "position_id": pos, "setup_reason": tag,
        "status": status, "side": "BUY", "entry_price": 4000,
        "initial_sl": 3992, "initial_tp": 4016, "exit_price": 4016,
        "entry_lots": lots, "exit_lots": lots,
        "gross_usd": gross, "charges_usd": charges,
        "net_usd": round(gross + charges, 2), "deal_count": 2,
        "exit_reason": exit_reason, "minutes_held": 31,
        "entry_time_msc": "1780000000000",
        "exit_time_msc": "1780001860000",
        "exit_legs": [{
            "deal_id": pos + "-exit", "reason": exit_reason,
            "time_msc": "1780001860000", "lots": lots,
            "price": 4016, "gross": gross, "charges": charges,
        }],
    }


def source(*positions):
    return {
        "schema": "qts.mt5.trade_forensics.v1",
        "status": "SELECTED_IMPORTED_FOR_REVIEW",
        "broker_fact_not_causal_proof": True, "live": "LOCKED",
        "edge_validated": False, "targeted": True, "selected_styles": [7],
        "trades": list(positions),
    }


def test_two_different_strategies_and_regimes_under_style7_are_separated():
    first = trade(pos="p1", tag="QTSV4-S8-R2", gross=12, charges=-1)
    second = trade(pos="p2", tag="QTSV4-S3-R0", gross=-8, charges=-1,
                   exit_reason="DEAL_REASON_SL")
    result = audit(source(first, second), extra_cost=10.0)
    assert result["status"] == "ATTRIBUTED_FOR_RESEARCH_ONLY"
    assert result["native_positions_attributed"] == 2
    assert result["by_strategy"]["8"]["positions"] == 1
    assert result["by_strategy"]["3"]["positions"] == 1
    assert result["by_strategy"]["1"]["positions"] == 0
    assert result["by_strategy"]["8"]["after_extra_stress_net_usd"] == 10.8
    assert result["by_strategy"]["3"]["after_extra_stress_net_usd"] == -9.2
    assert {r["regime"] for r in result["by_strategy_and_regime"]} == {"TREND", "RANGE"}
    assert result["positions"][0]["post_stop_tp_revisit"].startswith("UNKNOWN")
    assert result["can_autotune_or_promote"] is False
    assert result["connected_orders_authorized"] is False
    assert result["live"] == "LOCKED"


@pytest.mark.parametrize("tag", [
    "QTS TREND IMPULSE", "QTSV4-S7-R2", "QTSV4-S9-R0",
    "QTSV4-S8-R3", "garbage QTSV4-S8-R2", "QTSV4-S8-R2_extra",
    "", None, "QTSV4-S08-R2", "QTSV4-S2-R-1",
])
def test_no_guessing_from_broker_modified_or_unknown_order_tag(tag):
    with pytest.raises(ValueError, match="ORDER_COMMENT"):
        read_tag(tag)


def test_duplicate_positions_are_a_conspicuous_gate_failure():
    result = audit(source(trade(), trade()), extra_cost=10)
    assert result["native_positions_seen"] == 2
    assert result["native_positions_attributed"] == 1
    assert "DUPLICATE_NATIVE_POSITION" == result["issues"][0]["reason"]
    assert result["status"] == "INCOMPLETE_STRATEGY_ATTRIBUTION_NO_GO"


def test_partial_fill_exit_and_broker_reversal_fail_closed():
    missing_exit = trade(status="PARTIAL_OR_OPEN")
    result = audit(source(missing_exit))
    assert result["native_positions_attributed"] == 0
    assert "INCOMPLETE_OR_REVERSED_NATIVE_POSITION" == result["issues"][0]["reason"]
    reversed_trade = trade(status="REVERSAL_UNSUPPORTED")
    assert audit(source(reversed_trade))["status"].startswith("INCOMPLETE")


def test_reconciliation_and_broker_direction_guards():
    x = trade()
    x["net_usd"] = 999
    with pytest.raises(ValueError, match="NATIVE_NET"):
        inspect_position(x)
    x = trade()
    x["exit_lots"] = 0.04
    with pytest.raises(ValueError, match="ENTRY_EXIT_VOLUME"):
        inspect_position(x)
    x = trade()
    x["side"] = "SELL"
    with pytest.raises(ValueError, match="INVALID_ORIGINAL_SELL"):
        inspect_position(x)
    x = trade()
    x["exit_legs"][0]["lots"] = 0.3
    with pytest.raises(ValueError, match="EXIT_LEG_VOLUME"):
        inspect_position(x)


def test_invalid_input_never_bypasses_source_or_execution_permissions():
    src = source(trade())
    src["live"] = "ENABLED"
    with pytest.raises(ValueError, match="authority"):
        audit(src)
    src = source(trade())
    src["selected_styles"] = [1, 7]
    with pytest.raises(ValueError, match="dedicated Style 7"):
        audit(src)
    with pytest.raises(ValueError, match="nonnegative"):
        audit(source(trade()), extra_cost=float("nan"))
    with pytest.raises(ValueError, match="Missing completed"):
        audit(source())


def test_broker_costs_must_not_be_called_proven_edge():
    x = trade(gross=999999)
    result = audit(source(x))
    assert result["edge_validated"] is False
    assert result["can_autotune_or_promote"] is False
    assert "trading" not in str(result.get("status", "")).lower()
    assert result["by_strategy"]["8"]["positions"] == 1


def test_native_ea_order_comment_bound_to_selected_strategy_before_ordercheck():
    ea = (GOLD / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text("utf-8")
    marker = 'request.comment=StringFormat("QTSV4-S%d-R%d"'
    assert marker in ea
    assert ea.index(marker) < ea.index("OrderCheck(request,check)")
    assert "g_router_confirmed_regime" in ea[ea.index(marker)-400:ea.index(marker)+200]
    assert "if(TesterUseAdaptiveRouterV4)" in ea
    assert "if(RealAccountBlocked())" in ea
    assert "OrderSend(" not in (GOLD / "research" / "v4_position_attribution.py").read_text("utf-8")



def test_tampered_native_exit_timestamps_fail_closed():
    bad = trade()
    bad["exit_time_msc"] = "1779999999000"
    with pytest.raises(ValueError, match="BROKER_TIMESTAMP_ORDER_INVALID"):
        inspect_position(bad)
    bad = trade()
    bad["exit_legs"][0]["time_msc"] = "1780001960000"
    with pytest.raises(ValueError, match="EXIT_LEG_TIMESTAMP_OUTSIDE"):
        inspect_position(bad)


def test_cross_position_duplicate_deal_id_is_rejected():
    first = trade(pos="x")
    second = trade(pos="y", tag="QTSV4-S3-R0")
    second["exit_legs"][0]["deal_id"] = first["exit_legs"][0]["deal_id"]
    result = audit(source(first, second))
    assert result["status"] == "INCOMPLETE_STRATEGY_ATTRIBUTION_NO_GO"
    assert result["native_positions_attributed"] == 1
    assert result["issues"][0]["reason"] == "CROSS_POSITION_DUPLICATE_BROKER_DEAL_ID"


def test_realised_drawdown_is_not_floating_equity_drawdown():
    t1 = trade(pos="a", gross=10, charges=0)
    t2 = trade(pos="b", tag="QTSV4-S2-R2", gross=-25, charges=0)
    t2["exit_time_msc"] = "1780001900000"
    t2["exit_legs"][0]["time_msc"] = "1780001900000"
    report = audit(source(t1, t2), extra_cost=0)
    assert report["maximum_closed_trade_path_drawdown_after_stress_usd"] == 25.0
    assert report["closed_trade_drawdown_is_not_intratrade_equity_drawdown"] is True

def test_reference_immutable_broker_comment_extraction():
    ea = (GOLD / "mt5_robot" / "QTS_Gold_Robot.mq5").read_text("utf-8")
    assert "HistoryOrderGetString(order,ORDER_COMMENT)" in ea
    assert '"fee","setup_reason"' in ea
    forensics = (GOLD / "research" / "BuildTradeForensics.ps1").read_text("utf-8")
    assert "setup_reason=$entrySetup;exit_legs=$exitLegs" in forensics


def test_auto_tester_requires_attribution_for_v4_without_tuning_or_live():
    runner = (GOLD / "research" / "RunAutomaticTester.ps1").read_text("utf-8")
    assert "if($ResearchVariant -eq 'ADAPTIVE_V4')" in runner
    assert "research\\v4_position_attribution.py" in runner
    assert "QTS_V4_POSITION_ATTRIBUTION.json" in runner
    assert "if($LASTEXITCODE -ne 0" in runner
    assert "ATTRIBUTED_FOR_RESEARCH_ONLY" in runner
    assert "V4 native broker strategy attribution has gaps" in runner
    assert "OrderSend(" not in (GOLD / "research" / "v4_position_attribution.py").read_text("utf-8")


def test_forensic_export_retains_native_event_timestamps_without_price_predictions():
    native = (GOLD / "research" / "BuildTradeForensics.ps1").read_text("utf-8")
    assert "entry_time_msc=if($first){[string]$first.time_msc}" in native
    assert "exit_time_msc=if($last){[string]$last.time_msc}" in native
    assert "initial_sl=$initialSL;" in native
    assert "initial_tp=$initialTP;" in native
