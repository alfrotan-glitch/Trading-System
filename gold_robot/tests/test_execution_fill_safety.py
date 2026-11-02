"""Safety regression for abnormal broker LIMIT fills.

Only symbolic/synthetic assertions are executable in Python. Final authority
requires MetaEditor zero-error compilation and real-tick MT5 Strategy Tester.
No profitable edge or live-account authorization is implied.
"""
from __future__ import annotations
import math
from pathlib import Path
import pytest

GOLD=Path(__file__).resolve().parents[1]
SOURCE=(GOLD/"mt5_robot/QTS_Gold_Robot.mq5").read_text(encoding="utf-8")
POLICY=(GOLD/"mt5_robot/ExecutionPolicy.mqh").read_text(encoding="utf-8")


def consistent(side:int,price:float,sl:float,tp:float)->bool:
    """Independent price geometry model of the MQL5 pure safety predicate."""
    if side not in (-1,1) or not all(
        math.isfinite(x) and x>0 for x in (price,sl,tp)
    ):
        return False
    return sl<price<tp if side==1 else tp<price<sl


@pytest.mark.parametrize("side,price,sl,tp,expected",[
    (1,4181.58,4176.16,4187.08,True),
    (-1,4168.99,4172.01,4165.64,True),
    (1,4136.56,4142.64,4147.04,False),
    (-1,4148.00,4142.00,4136.00,False),
    (1,4000.00,4000.00,4010.00,False),
    (-1,4000.00,4010.00,4000.00,False),
    (1,4000.00,0.0,4010.00,False),
    (1,math.nan,3900.00,4010.00,False),
])
def test_original_stop_geometry(side,price,sl,tp,expected):
    assert consistent(side,price,sl,tp) is expected


def test_post_fill_loss_only_accepts_original_risk_or_lower():
    # Price-space model only. MQL uses broker-specific OrderCalcProfit.
    def money_loss(side,entry,sl,volume=0.02,contract=100.0):
        return abs(entry-sl)*contract*volume
    original_buy=money_loss(1,4000.0,3995.0)
    favorable_buy=money_loss(1,3999.0,3995.0)
    adverse_buy=money_loss(1,4001.0,3995.0)
    assert favorable_buy<original_buy<adverse_buy
    original_sell=money_loss(-1,4000.0,4005.0)
    favorable_sell=money_loss(-1,4001.0,4005.0)
    adverse_sell=money_loss(-1,3999.0,4005.0)
    assert favorable_sell<original_sell<adverse_sell


def test_native_source_reads_broker_entry_deal_and_original_order_not_current_sl():
    assert "trans.type!=TRADE_TRANSACTION_DEAL_ADD" in SOURCE
    assert "DEAL_ENTRY_IN || entry_kind==DEAL_ENTRY_INOUT" in SOURCE
    assert "HistoryDealGetDouble(trans.deal,DEAL_PRICE)" not in SOURCE or (
        "double fill_price=HistoryDealGetDouble(trans.deal,DEAL_PRICE);" in SOURCE)
    assert "original_sl=HistoryDealGetDouble(trans.deal,DEAL_SL)" in SOURCE
    assert "original_tp=HistoryDealGetDouble(trans.deal,DEAL_TP)" in SOURCE
    assert "QtsFillStopsConsistent(entry_side,fill_price" in SOURCE
    assert "QtsFillRiskNotWorseThanOriginalOrder(" in SOURCE
    assert "HistoryDealGetInteger(entry_deal,DEAL_ORDER)" in SOURCE
    assert "HistoryOrderGetDouble(entry_order,ORDER_PRICE_OPEN)" in SOURCE
    assert "HistoryOrderGetDouble(entry_order,ORDER_SL)" in SOURCE
    assert "bool in_history=HistoryOrderSelect(entry_order);" in SOURCE
    assert "if(!in_history && !OrderSelect(entry_order))" in SOURCE
    assert "OrderGetDouble(ORDER_PRICE_OPEN)" in SOURCE
    assert "OrderGetDouble(ORDER_SL)" in SOURCE
    assert "actual_loss<=planned_loss+0.000001" in SOURCE
    assert "PlannedOrderFitsRisk(entry_side,volume,fill_price,original_sl)" not in SOURCE
    assert "bool QtsFillStopsConsistent(" in POLICY
    assert "initial_sl<fill_price && fill_price<initial_tp" in POLICY
    assert "initial_tp<fill_price && fill_price<initial_sl" in POLICY


def test_native_incident_halts_retries_and_never_replaces_order():
    assert "QtsMarkUnsafeFill(identifier," in SOURCE
    assert "GlobalVariableSet(key,1.0)" in SOURCE
    assert 'LatchExecutionHalt(reason);' in SOURCE
    assert "ManageOwnedPendingOrders(true);" in SOURCE
    assert "ManageOwnedPositions();" in SOURCE
    assert "bool unsafe_fill=QtsOwnedPositionFlagged();" in SOURCE
    assert "EmergencyFlattenOwned || unsafe_fill" in SOURCE
    assert "trader.PositionClose(ticket)" in SOURCE
    assert "TRADE_RETCODE_DONE_PARTIAL" in SOURCE
    assert "ProtectiveRequestDue(ticket,\"CLOSE\")" in SOURCE
    assert "request.action=TRADE_ACTION_PENDING;" in SOURCE
    assert "LIVE LOCKED" in SOURCE


def test_native_ownership_and_restart_guards():
    assert "QtsPositionEntriesExclusivelyOwned(" in SOURCE
    assert "HistoryDealGetInteger(deal,DEAL_POSITION_ID)!=identifier" in SOURCE
    assert "HistoryDealGetInteger(deal,DEAL_MAGIC)!=RobotMagic" in SOURCE
    assert "QtsAuditActiveOriginalFills();" in SOURCE
    assert "qts_unsafe_fill_runtime_identifier" in SOURCE
    assert "identifier==qts_unsafe_fill_runtime_identifier" in SOURCE
    assert "QtsUnsafeFillKey(position_identifier)" in SOURCE
    assert "StringLen(key)<=63" in SOURCE
    assert "mixed or unavailable original entry-deal provenance" in SOURCE


def test_frozen_strategy_inputs_unchanged():
    assert "TesterDualStrategyMode     = 0;" in SOURCE
    assert "EnableDemoOrders          = false;" in SOURCE
    assert "EnableDemoForwardOrders    = false;" in SOURCE
    assert "RetestDepthAtr            = 0.35;" in SOURCE
    assert "AdverseStopSlipPrice      = 0.10;" in SOURCE
    assert "RiskPerTradePct           = 1.0;" in SOURCE


def test_timer_reconciles_owned_positions_independently_of_trade_callback():
    timer=SOURCE.split("void OnTimer()",1)[1].split("void RecordNativeForwardShadow",1)[0]
    assert "if(connected && PositionsTotal()>0)" in timer
    assert "QtsAuditActiveOriginalFills();" in timer
    assert timer.index("QtsAuditActiveOriginalFills();") < timer.index("ManageOwnedPositions();")
    assert "RealAccountBlocked()" in timer
    assert "ManageOwnedPendingOrders();" in timer


def test_unverified_position_never_triggered_forced_liquidation():
    assert "if(unsafe_fill &&" in SOURCE
    assert "QtsPositionEntriesExclusivelyOwned(PositionGetInteger(POSITION_IDENTIFIER))" in SOURCE
    assert "refusing automatic close of mixed/unverified position" in SOURCE
