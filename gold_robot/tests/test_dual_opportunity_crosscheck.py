"""Native two-arm opportunity parity; synthetic fixtures are not MT5 proof."""
import csv
import sys
from pathlib import Path
import pytest

GOLD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(GOLD/"research"))
from verify_dual_opportunity import FIELDS, LedgerError
from crosscheck_dual_opportunities import crosscheck


def emit(path,mode,bad_market=False,bad_decision=False,collide=True):
    path.parent.mkdir(parents=True,exist_ok=True)
    records=[]
    for i in range(2):
        bar=f"2026.05.01 10:{i*15:02d}:00"
        observed=f"2026.05.01 10:{i*15+1:02d}:00"
        for style in (1,3):
            signal=(1 if i==0 else 0) if style==1 else (1 if collide and i==0 else 0)
            reason="SIGNAL: buy confirmed" if style==1 else "STRUCTURE: buy confirmed"
            mode_veto=int(mode==2 and style==3 and signal>0)
            record=dict.fromkeys(FIELDS,"")
            record.update({
                "bar_time_server":bar,"observed_time_server":observed,
                "mode":str(mode),"style":str(style),"side":str(signal),
                "signal_reason":reason,
                "entry_decision_reason":"DUAL: collision of eligible candidates" if i==0 else "DUAL: no executable setup",
                "exposure_blocked":"0","mode_direction_veto":str(mode_veto),
                "router_eligible_count":str(2 if mode==1 and i==0 else (1 if mode==2 and i==0 else 0)),
                "router_verdict":"COLLISION_ABSTAIN" if mode==1 and i==0 else (
                    "CANDIDATE_SELECTED" if mode==2 and i==0 else "NO_EXECUTABLE"),
                "atr14_closed":"5.000","atr_rank_prior_192_pct":"50.0",
                "adx_closed":"22","h1_close_minus_ema50":"-2.5",
                "bid":"4000.0","ask":"4000.3","spread":"0.3",
                "candidate_class":"NO_SIGNAL" if signal==0 else (
                    "MODE_DIRECTION_VETO" if mode_veto else "SIGNAL_NOT_FILL_PROOF")
            })
            if bad_market and mode==2 and i==0 and style==3:
                record["atr14_closed"]="5.999"
            if bad_decision and mode==2 and i==0 and style==3:
                record["entry_decision_reason"]="STRUCTURE: buy confirmed"
            records.append(record)
    with path.open("w",newline="",encoding="ascii") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter=";")
        w.writeheader()
        w.writerows(records)


def test_same_market_same_signals_different_router_decisions(tmp_path):
    a,b=tmp_path/"both.csv",tmp_path/"dir.csv"
    emit(a,1);emit(b,2)
    result=crosscheck(a,b)
    assert result["bars_per_arm"]==2
    assert result["raw_simultaneous_signal_bars"]==1
    assert result["collision_sides"]=={"same_direction":1,"buy":1}
    assert result["variants"]["DUAL_BOTH"]["router_verdicts_by_bar"]["COLLISION_ABSTAIN"]==1
    assert result["variants"]["DUAL_DIRECTIONAL"]["router_verdicts_by_bar"]["CANDIDATE_SELECTED"]==1
    assert result["edge_validated"] is False
    assert result["causal_opportunity_displacement_proven"] is False


def test_market_mismatch_fails_closed(tmp_path):
    a,b=tmp_path/"both.csv",tmp_path/"dir.csv"
    emit(a,1);emit(b,2,bad_market=True)
    with pytest.raises(LedgerError,match="conflicting native market observations"):
        crosscheck(a,b)


def test_per_style_decision_mutation_fails_before_pairing(tmp_path):
    a,b=tmp_path/"both.csv",tmp_path/"dir.csv"
    emit(a,1);emit(b,2,bad_decision=True)
    with pytest.raises(LedgerError,match="Decision provenance changed"):
        crosscheck(a,b)
