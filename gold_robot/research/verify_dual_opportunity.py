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
        "mode_direction_veto","router_eligible_count","router_verdict",
        "atr14_closed","atr_rank_prior_192_pct",
        "adx_closed","h1_close_minus_ema50","bid","ask","spread",
        "candidate_class")
CATEGORIES={"NO_SIGNAL","SIGNAL_WHILE_EXPOSED","MODE_DIRECTION_VETO",
            "SIGNAL_NOT_FILL_PROOF"}

class LedgerError(ValueError): pass

def verify(path:Path,mode:int)->dict:
    if mode not in (1,2,3):raise LedgerError("Invalid tester dual mode")
    if path.stat().st_size>25_000_000:raise LedgerError("Oversized native ledger")
    with path.open(newline="",encoding="ascii",errors="strict") as source:
        reader=csv.DictReader(source,delimiter=";")
        if reader.fieldnames!=list(FIELDS):
            raise LedgerError("Missing, reordered, or duplicated native ledger columns")
        counts=Counter()
        classified=Counter()
        previous=None
        bars=set()
        decision_by_bar={}
        signals_by_bar={}
        exposure_by_bar={}
        router_by_bar={}
        router_counts=Counter()
        quote_by_bar={}
        frozen_reason_evidence=0
        observed=0
        atr_known=0
        rank_known=0
        signaled=0
        signal_exposed=0
        for row in reader:
            observed+=1
            if observed>350_000:raise LedgerError("Unbounded native row count")
            if None in row or any(value is None for value in row.values()):
                # MQL5 FileWrite(FILE_CSV) does not provide an authenticated
                # row schema. A semicolon in a reason creates an extra column.
                # Report only structural metadata, never raw account/price text.
                extra=len(row.get(None) or [])
                absent=sum(value is None for key,value in row.items() if key is not None)
                actual=len(FIELDS)+extra-absent
                raise LedgerError(
                    "Malformed native ledger CSV row at record {} physical_line {}: "
                    "expected_fields={} actual_fields={}".format(
                        observed,reader.line_num,len(FIELDS),actual))
            try:
                bar=datetime.strptime(row["bar_time_server"],"%Y.%m.%d %H:%M:%S")
                when=datetime.strptime(row["observed_time_server"],"%Y.%m.%d %H:%M:%S")
                m=int(row["mode"]);style=int(row["style"]);side=int(row["side"])
                exposed=int(row["exposure_blocked"]);veto=int(row["mode_direction_veto"])
                router_eligible=int(row["router_eligible_count"])
                router_verdict=row["router_verdict"]
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
            valid_router=((router_eligible,router_verdict) in (
                (-1,"NOT_EVALUATED"),(0,"NO_EXECUTABLE"),
                (1,"CANDIDATE_SELECTED"),(2,"COLLISION_ABSTAIN")))
            if mode==3 and (router_eligible,router_verdict)==(2,"QUALITY_COLLISION_SELECTED"):
                valid_router=True
            if not valid_router:
                raise LedgerError("Invalid router eligibility/verdict")
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
            # Both rows share one pre-observation trading decision.
            # If each row instead inherits its own signal_reason, the
            # decision was overwritten by the diagnostic signal calls.
            if bar in decision_by_bar and row["entry_decision_reason"]!=decision_by_bar[bar]:
                raise LedgerError("Decision provenance changed between styles on one closed bar")
            decision_by_bar[bar]=row["entry_decision_reason"]
            signals_by_bar[(bar,style)]=side
            if bar in exposure_by_bar and exposed!=exposure_by_bar[bar]:
                raise LedgerError("Pre-decision exposure snapshot differs across styles")
            exposure_by_bar[bar]=exposed
            if bar in router_by_bar and router_by_bar[bar]!=(router_eligible,router_verdict):
                raise LedgerError("Router eligibility differs across styles on one closed bar")
            if bar not in router_by_bar:
                router_counts[router_verdict]+=1
            router_by_bar[bar]=(router_eligible,router_verdict)
            market=(row["observed_time_server"],row["atr14_closed"],
                    row["atr_rank_prior_192_pct"],row["adx_closed"],
                    row["h1_close_minus_ema50"],row["bid"],row["ask"],row["spread"])
            if bar in quote_by_bar and market!=quote_by_bar[bar]:
                raise LedgerError("One closed bar has conflicting native market observations")
            quote_by_bar[bar]=market
            if row["entry_decision_reason"]!=row["signal_reason"]:
                frozen_reason_evidence+=1
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
        if frozen_reason_evidence==0:
            raise LedgerError("Decision reason aliases strategy signal_reason in all rows")
        for bar in bars:
            _, verdict=router_by_bar[bar]
            if verdict=="QUALITY_COLLISION_SELECTED":
                if mode!=3 or signals_by_bar[(bar,1)]==0 or (
                    signals_by_bar[(bar,1)]!=signals_by_bar[(bar,3)]):
                    raise LedgerError("Quality collision lacks same-side dual signals")

    return {
        "schema":"qts.dual_native_opportunity.v1",
        "status":"NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY",
        "live":"LOCKED","edge_validated":False,
        "fills_inferred":False,"skipped_trade_outcomes_inferred":False,
        "mode":mode,"bars":len(bars),"rows":observed,
        "atr_available_rows":atr_known,"atr_rank_available_rows":rank_known,
        "raw_signal_rows":signaled,"raw_signal_while_exposed_rows":signal_exposed,
        "same_bar_decision_provenance_verified":True,
        "router_verdicts_by_closed_bar":dict(sorted(router_counts.items())),
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
