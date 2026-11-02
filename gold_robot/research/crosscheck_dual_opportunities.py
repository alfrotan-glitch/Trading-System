"""Cross-arm native dual opportunity comparison. Evidence only, never orders.

Requires both individually verified native observation files from the SAME
timestamps and market state. Does not simulate entries or claim counterfactual
PnL. Wrong evidence or stale/aliased decision reasons fail closed.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from verify_dual_opportunity import verify, LedgerError

MARKET_FIELDS=("observed_time_server","signal_reason","side","atr14_closed",
               "atr_rank_prior_192_pct","adx_closed","h1_close_minus_ema50",
               "bid","ask","spread")
def entries(path):
    with path.open(encoding="ascii",errors="strict",newline="") as fh:
        return {(r["bar_time_server"],int(r["style"])):r
                for r in csv.DictReader(fh,delimiter=";")}

def crosscheck(both:Path,directional:Path):
    a=verify(both,1)
    b=verify(directional,2)
    if a["bars"]!=b["bars"] or a["rows"]!=b["rows"]:
        raise LedgerError("Dual arms cover different numbers of M15 bars")
    left,right=entries(both),entries(directional)
    if set(left)!=set(right):
        raise LedgerError("Mismatched native bar/strategy identities across arms")
    for key in left:
        for field in MARKET_FIELDS:
            if left[key][field]!=right[key][field]:
                raise LedgerError("Native same-market signal/price mismatch: "+field)
    bars=sorted({k[0] for k in left})
    collisions=Counter()
    exposures={}
    for name,source in (("DUAL_BOTH",left),("DUAL_DIRECTIONAL",right)):
        raw=0
        while_exposed=0
        vetoed=0
        for row in source.values():
            sig=int(row["side"])
            raw+=sig!=0
            while_exposed+=sig!=0 and int(row["exposure_blocked"])==1
            vetoed+=sig!=0 and int(row["mode_direction_veto"])==1
        exposures[name]={
            "raw_signal_rows":raw,
            "signal_while_preexisting_exposure":while_exposed,
            "direction_vetoed_signal_rows":vetoed,
            "router_verdicts_by_bar":a["router_verdicts_by_closed_bar"] if name=="DUAL_BOTH"
                                    else b["router_verdicts_by_closed_bar"],
        }
    same_exposure_bars=0
    different_exposure_bars=0
    for bar in bars:
        s1=int(left[(bar,1)]["side"])
        s3=int(left[(bar,3)]["side"])
        if s1 and s3:
            collisions["same_direction" if s1==s3 else "opposite_direction"]+=1
            collisions["buy" if s1>0 else "sell"]+=1
        if left[(bar,1)]["exposure_blocked"]==right[(bar,1)]["exposure_blocked"]:
            same_exposure_bars+=1
        else: different_exposure_bars+=1
    return {
        "schema":"qts.dual_opportunity_crosscheck.v1",
        "status":"NATIVE_PAIRED_OPPORTUNITIES_REVIEW_ONLY",
        "live":"LOCKED","edge_validated":False,"real_money_orders_allowed":False,
        "independent_holdout":False,"causal_opportunity_displacement_proven":False,
        "raw_signals_identical":True,"native_market_fields_identical":True,
        "bars_per_arm":len(bars),"rows_per_arm":len(left),
        "raw_simultaneous_signal_bars":sum(1 for bar in bars
                                           if int(left[(bar,1)]["side"])!=0
                                           and int(left[(bar,3)]["side"])!=0),
        "collision_sides":dict(collisions),
        "exposure_different_bars":different_exposure_bars,
        "exposure_same_bars":same_exposure_bars,
        "variants":exposures,
        "limitations":[
            "Router eligibility is only observed where native EvaluateNewEntry reached the dual router.",
            "A signal is not a filled trade, and an eligible setup may never fill.",
            "Different exposures show different historical paths but do not prove causal profit.",
            "Trade costs, order lifecycle and post-stop price reconstruction are separate checks.",
        ],
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--both",required=True,type=Path)
    p.add_argument("--directional",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    x=p.parse_args()
    try:
        result=crosscheck(x.both,x.directional)
        rc=0
    except (LedgerError,OSError,UnicodeError,ValueError) as err:
        result={"schema":"qts.dual_opportunity_crosscheck.v1",
                "status":"NATIVE_CROSSCHECK_FAILED_NO_GO","live":"LOCKED",
                "edge_validated":False,"reason":str(err)}
        rc=2
    x.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(result["status"],str(x.output))
    return rc
if __name__=="__main__":
    raise SystemExit(main())
