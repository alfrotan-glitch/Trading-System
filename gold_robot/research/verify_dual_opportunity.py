"""Validate broker-native dual M15 closed-bar opportunity CSV; never infer fills.
Accept exactly two rows per observed bar, independent signal identities, and
closed-bar-only context descriptors. Always output a NO-GO on evidence gaps.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

FIELDS=("bar_time_server","observed_time_server","mode","style","side",
        "signal_reason","entry_decision_reason","exposure_blocked",
        "mode_direction_veto","atr14_closed","atr_rank_prior_192_pct",
        "adx_closed","h1_close_minus_ema50","bid","ask","spread",
        "candidate_class")
CATEGORIES={"NO_SIGNAL","SIGNAL_WHILE_EXPOSED","MODE_DIRECTION_VETO",
            "SIGNAL_NOT_FILL_PROOF"}

class LedgerError(ValueError): pass

def verify(path:Path,mode:int)->dict:
    if mode not in (1,2):raise LedgerError("Invalid tester dual mode")
    if path.stat().st_size>25_000_000:raise LedgerError("Oversized native ledger")
    with path.open(newline="",encoding="ascii",errors="strict") as source:
        reader=csv.DictReader(source,delimiter=";")
        if reader.fieldnames!=list(FIELDS):
            raise LedgerError("Missing, reordered, or duplicated native ledger columns")
        counts=Counter()
        classified=Counter()
        previous=None
        bars=set()
        observed=0
        atr_known=0
        rank_known=0
        signaled=0
        signal_exposed=0
        for row in reader:
            observed+=1
            if observed>350_000:raise LedgerError("Unbounded native row count")
            if None in row or any(value is None for value in row.values()):
                raise LedgerError("Malformed native ledger CSV row")
            try:
                bar=datetime.strptime(row["bar_time_server"],"%Y.%m.%d %H:%M:%S")
                when=datetime.strptime(row["observed_time_server"],"%Y.%m.%d %H:%M:%S")
                m=int(row["mode"]);style=int(row["style"]);side=int(row["side"])
                exposed=int(row["exposure_blocked"]);veto=int(row["mode_direction_veto"])
                atr=float(row["atr14_closed"]);rank=float(row["atr_rank_prior_192_pct"])
                adx=float(row["adx_closed"])
                h1=float(row["h1_close_minus_ema50"])
                bid=float(row["bid"]);ask=float(row["ask"]);spread=float(row["spread"])
            except (ValueError,TypeError) as e:
                raise LedgerError("Invalid native data value") from e
            if not all(math.isfinite(value) for value in (atr,rank,adx,h1,bid,ask,spread)):
                raise LedgerError("Non-finite native indicator or quote")
            if m!=mode or style not in (1,3) or side not in (-1,0,1) or exposed not in (0,1) or veto not in (0,1):
                raise LedgerError("Bad mode/style/side/exposure identity")
            if when<bar or not row["signal_reason"] or not row["entry_decision_reason"]:
                raise LedgerError("Missing native decision provenance")
            if atr!=-1 and atr<=0:raise LedgerError("Invalid ATR")
            if rank!=-1 and not 0<=rank<=100:raise LedgerError("Invalid ATR rank")
            if rank>=0 and atr<=0:raise LedgerError("Rank without ATR")
            if adx!=-1 and adx<0:raise LedgerError("Invalid ADX")
            if not (bid==ask==spread==-1) and not (bid>0 and ask>bid and abs((ask-bid)-spread)<0.00002):
                raise LedgerError("Inconsistent quoted spread")
            expected_veto=int(mode==2 and ((style==1 and side<0) or (style==3 and side>0)))
            if veto!=expected_veto:raise LedgerError("Direction veto mismatch")
            expected_cat=("NO_SIGNAL" if side==0 else
                         "SIGNAL_WHILE_EXPOSED" if exposed else
                         "MODE_DIRECTION_VETO" if veto else
                         "SIGNAL_NOT_FILL_PROOF")
            if row["candidate_class"]!=expected_cat or row["candidate_class"] not in CATEGORIES:
                raise LedgerError("Misclassified native opportunity")
            if previous is not None and bar<previous:
                raise LedgerError("Nonmonotonic closed-bar sequence")
            previous=bar
            counts[(bar,style)]+=1
            if counts[(bar,style)]>1:raise LedgerError("Duplicate style within closed bar")
            bars.add(bar)
            classified[(style,row["candidate_class"])]+=1
            atr_known+=int(atr>0)
            rank_known+=int(rank>=0)
            signaled+=int(side!=0)
            signal_exposed+=int(side!=0 and exposed==1)
        if observed<2 or len(bars)*2!=observed:
            raise LedgerError("Missing bars or incomplete two-style coverage")
        if any(counts[(bar,style)]!=1 for bar in bars for style in (1,3)):
            raise LedgerError("Missing one strategy on closed bar")
    return {
        "schema":"qts.dual_native_opportunity.v1",
        "status":"NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY",
        "live":"LOCKED","edge_validated":False,
        "fills_inferred":False,"skipped_trade_outcomes_inferred":False,
        "mode":mode,"bars":len(bars),"rows":observed,
        "atr_available_rows":atr_known,"atr_rank_available_rows":rank_known,
        "raw_signal_rows":signaled,"raw_signal_while_exposed_rows":signal_exposed,
        "by_strategy_class":[{"style":style,"category":c,"rows":n} for (style,c),n in sorted(classified.items())],
        "atr_rank_is_native_iatr_not_retro_simple_tr":True,
        "limitation":"Closed-bar signals are not executable missed fills or counterfactual profits."
    }

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--mode",type=int,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    try:
        result=verify(args.input,args.mode)
        code=0
    except (LedgerError,OSError,UnicodeError,OverflowError) as e:
        result={"schema":"qts.dual_native_opportunity.v1","status":"NATIVE_LEDGER_FAILED_NO_GO",
                "live":"LOCKED","edge_validated":False,"reason":str(e)}
        code=2
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(result["status"],str(args.output))
    return code

if __name__=="__main__":
    raise SystemExit(main())
