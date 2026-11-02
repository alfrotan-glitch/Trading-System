"""Native dual opportunity observation contracts — synthetic data only."""
import csv
import sys
from datetime import datetime,timedelta
from pathlib import Path

import pytest

GOLD=Path(__file__).resolve().parents[1]
ROOT=GOLD.parent
sys.path.insert(0,str(GOLD/"research"))
from verify_dual_opportunity import FIELDS,LedgerError,verify

def rows(mode=1,bars=2):
    result=[]
    start=datetime(2026,5,1,10,0,0)
    for j in range(bars):
        for style in (1,3):
            side=1 if style==1 else -1
            veto=int(mode==2 and style==3 and side>0)
            r=dict.fromkeys(FIELDS,"")
            r.update({
                "bar_time_server":(start+timedelta(minutes=15*j)).strftime("%Y.%m.%d %H:%M:%S"),
                "observed_time_server":(start+timedelta(minutes=15*j,seconds=3)).strftime("%Y.%m.%d %H:%M:%S"),
                "mode":str(mode),"style":str(style),"side":str(side),
                "signal_reason":"SIGNAL confirmed","entry_decision_reason":"Another chart/strategy has a position or order",
                "exposure_blocked":"1","mode_direction_veto":str(veto),
                "atr14_closed":"4.52","atr_rank_prior_192_pct":"68.75",
                "adx_closed":"22.1","h1_close_minus_ema50":"-0.45",
                "bid":"4010.20","ask":"4010.43","spread":"0.23",
                "candidate_class":"SIGNAL_WHILE_EXPOSED"
            })
            result.append(r)
    return result

def write(tmp_path,content):
    p=tmp_path/"native.csv"
    with p.open("w",newline="",encoding="ascii") as f:
        writer=csv.DictWriter(f,FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows(content)
    return p

def test_two_styles_per_bar_even_when_exposed(tmp_path):
    result=verify(write(tmp_path,rows(1)),1)
    assert result["bars"]==2 and result["rows"]==4
    assert result["fills_inferred"] is False
    assert result["live"]=="LOCKED" and result["edge_validated"] is False

@pytest.mark.parametrize("mutation,error",[
    ("drop","Missing bars"),
    ("duplicate","Duplicate style"),
    ("wrong_mode","Bad mode"),
    ("wrong_veto","Direction veto"),
    ("future","Missing native decision provenance"),
    ("spread","Inconsistent quoted spread"),
    ("classifier","Misclassified native opportunity"),
])
def test_corruption_fails_closed(tmp_path,mutation,error):
    data=rows(2)
    if mutation=="drop":data.pop()
    elif mutation=="duplicate":data[1]=dict(data[0])
    elif mutation=="wrong_mode":data[0]["mode"]="1"
    elif mutation=="wrong_veto":data[0]["mode_direction_veto"]="1"
    elif mutation=="future":data[0]["observed_time_server"]="2026.04.01 00:00:00"
    elif mutation=="spread":data[0]["spread"]="0.05"
    elif mutation=="classifier":data[0]["candidate_class"]="UNKNOWN"
    with pytest.raises(LedgerError,match=error):
        verify(write(tmp_path,data),2)

def test_nonfinite_atr_or_quote_rejected(tmp_path):
    data=rows(1)
    data[0]["atr14_closed"]="nan"
    with pytest.raises(LedgerError,match="Non-finite"):
        verify(write(tmp_path,data),1)
    data=rows(1)
    data[0]["spread"]="inf"
    with pytest.raises(LedgerError,match="Non-finite"):
        verify(write(tmp_path,data),1)


def test_no_signal_and_veto_provenance(tmp_path):
    data=rows(2)
    data[0]["side"]="0"
    data[0]["candidate_class"]="NO_SIGNAL"
    data[0]["exposure_blocked"]="0"
    data[1]["side"]="1"
    data[1]["mode_direction_veto"]="1"
    data[1]["exposure_blocked"]="0"
    data[1]["candidate_class"]="MODE_DIRECTION_VETO"
    assert verify(write(tmp_path,data),2)["rows"]==4

def test_native_tester_only_and_unchanged_trade_decision():
    ea=(GOLD/"mt5_robot/QTS_Gold_Robot.mq5").read_text(encoding="utf-8")
    ledger=(GOLD/"mt5_robot/DualOpportunityLedger.mqh").read_text(encoding="utf-8")
    installer=(GOLD/"mt5_robot/Install_QTS_Gold_Robot.ps1").read_text(encoding="utf-8")
    runner=(GOLD/"research/RunAutomaticTester.ps1").read_text(encoding="utf-8")
    assert '#include "DualOpportunityLedger.mqh"' in ea
    assert "      bool dual_exposure_before=" in ea
    assert "      ConsiderNewEntry();\n      // Signals are inspected AFTER" in ea
    assert "      QtsObserveDualOpportunities(closed,status_text,dual_exposure_before);" in ea
    assert "   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER" in ledger
    assert "   if(TesterDualStrategyMode==0 || MQLInfoInteger(MQL_TESTER)==0)" in ledger
    assert "int original_style=evaluated_style;" in ledger
    assert "status_text=original_status;" in ledger
    assert "QtsCloseDualOpportunityLedger();" in ea
    assert not any(name in ledger for name in ("OrderSend(","OrderCheck(","trader.Buy(","trader.Sell(","OrderCalcProfit(","SizedLots("))
    assert "$backupLedger" in installer and "$destLedger" in installer
    assert "verify_dual_opportunity.py" in runner
    assert "DUAL_OPPORTUNITY_MISSING_NO_GO" in runner
    assert "DUAL_OPPORTUNITY_INVALID_NO_GO" in runner
