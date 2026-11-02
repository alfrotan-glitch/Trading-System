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
                "router_eligible_count":"-1","router_verdict":"NOT_EVALUATED",
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
    ("decision_mutated","Decision provenance changed"),
    ("exposure_mismatch","Pre-decision exposure snapshot differs"),
    ("router_mismatch","Router eligibility differs"),
    ("router_invalid","Invalid router eligibility"),
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
    elif mutation=="decision_mutated":data[1]["entry_decision_reason"]="SIGNAL: sell confirmed"
    elif mutation=="exposure_mismatch":data[1]["exposure_blocked"]="0";data[1]["candidate_class"]="SIGNAL_NOT_FILL_PROOF"
    elif mutation=="router_mismatch":data[1]["router_eligible_count"]="1";data[1]["router_verdict"]="CANDIDATE_SELECTED"
    elif mutation=="router_invalid":data[1]["router_eligible_count"]="2";data[1]["router_verdict"]="CANDIDATE_SELECTED"
    with pytest.raises(LedgerError,match=error):
        verify(write(tmp_path,data),2)

def test_unescaped_mql5_semicolon_reproduces_failed_native_csv(tmp_path):
    # DictWriter quotes delimiters, but native FileWrite writes text fields as
    # data separated by ;. Reproduce the actual native writer contract.
    entries=rows(1)
    sentence="LIMIT submission accepted; fills confirmed only from broker deals"
    for r in entries:
        r["entry_decision_reason"]=sentence
    path=tmp_path/"native.csv"
    def native_line(row):
        return ";".join(str(row[f]) for f in FIELDS)
    path.write_text(";".join(FIELDS)+"\\r\\n"+
                    "\\r\\n".join(native_line(row) for row in entries)+"\\r\\n",
                    encoding="ascii")
    with pytest.raises(LedgerError,match=r"record 1 physical_line 2: expected_fields=19 actual_fields=20"):
        verify(path,1)
    for r in entries:
        r["entry_decision_reason"]=sentence.replace(";"," |")
    path.write_text(";".join(FIELDS)+"\\r\\n"+
                    "\\r\\n".join(native_line(row) for row in entries)+"\\r\\n",
                    encoding="ascii")
    assert verify(path,1)["rows"]==4


def test_historical_alias_bug_detected(tmp_path):
    data=rows(1)
    for row in data:
        # Reproduces the real uploaded evidence: decision_reason is aliased
        # to the respective signal reason, instead of an immutable decision.
        row["entry_decision_reason"]="SIGNAL: fake" if row["style"]=="1" else "STRUCTURE: fake"
    with pytest.raises(LedgerError,match="Decision provenance changed"):
        verify(write(tmp_path,data),1)


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
    assert "      QtsObserveDualOpportunities(closed,dual_decision_snapshot,dual_exposure_before);" in ea
    assert "string dual_decision_snapshot=status_text;" in ea
    assert "string frozen_entry_decision=original_entry_reason;" in ledger
    assert "string QtsOpportunityCsvSafe(const string input)" in ledger
    assert 'StringReplace(cleaned,";"," |");' in ledger
    assert 'string safe_entry_reason=QtsOpportunityCsvSafe(frozen_entry_decision);' in ledger
    assert 'string safe_signal_reason=QtsOpportunityCsvSafe(signal_reason);' in ledger
    assert "          safe_entry_reason,(int)exposure" in ledger
    assert "safe_entry_reason,(int)exposure" in ledger
    assert "qts_dual_router_eligible,qts_dual_router_verdict" in ledger
    dual=(GOLD/"mt5_robot/DualResearch.mqh").read_text(encoding="utf-8")
    assert "qts_dual_router_verdict=eligible==0" in dual
    assert "qts_dual_router_eligible=eligible;" in dual
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
