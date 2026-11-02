"""Broker-native post-fill incident audit. Research only; never approves live.

Read completed position forensics AND unmodified native opportunity ledger.
Differentiate a protective close from a broker SL and prove whether additional
broker positions opened after the incident. Do not interpret stopped trading
as evidence that the strategy is economically worse or better.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


class SafetyAuditError(ValueError):
    pass


def audit(forensics: Path, opportunities: Path) -> dict:
    with forensics.open(encoding="utf-8-sig") as fh:
        source=json.load(fh)
    if (source.get("live")!="LOCKED" or
        source.get("edge_validated") is not False or
        source.get("selected_styles")!=[7] or
        not isinstance(source.get("trades"),list) or
        not source["trades"]):
        raise SafetyAuditError("Missing or invalid native Style-7 broker forensics")
    incidents=[]
    positions=[]
    ids=set()
    for row in source["trades"]:
        if row.get("status")!="COMPLETE":
            raise SafetyAuditError("Native position is not complete")
        pid=str(row["position_id"])
        if pid in ids:
            raise SafetyAuditError("Duplicate broker position identifier")
        ids.add(pid)
        side=row["side"]
        if side not in ("BUY","SELL"):
            raise SafetyAuditError("Invalid broker position side")
        price=float(row["entry_price"])
        sl=float(row["initial_sl"])
        tp=float(row["initial_tp"])
        net=float(row["net_usd"])
        begin=int(row["entry_time_msc"])
        end=int(row["exit_time_msc"])
        if (not all(math.isfinite(x) for x in (price,sl,tp,net)) or
            price<=0 or sl<=0 or tp<=0 or begin<=0 or end<begin or
            int(row.get("deal_count",0))<2):
            raise SafetyAuditError("Invalid entry price/SL/TP or broker deal chronology")
        entry_lots=float(row["entry_lots"])
        exit_lots=float(row["exit_lots"])
        if (not all(math.isfinite(x) for x in (entry_lots,exit_lots)) or
            entry_lots<=0 or abs(entry_lots-exit_lots)>1e-6):
            raise SafetyAuditError("Unreconciled native entry/exit broker volume")
        safe=(sl<price<tp) if side=="BUY" else (tp<price<sl)
        positions.append((begin,pid))
        if not safe:
            incidents.append({
                "position_id":pid,
                "side":side,
                "entry_time_msc":begin,
                "exit_time_msc":end,
                "actual_entry":price,
                "original_sl":sl,
                "original_tp":tp,
                "broker_exit_reason":row.get("exit_reason"),
                "robot_protective_exit_observed":row.get("exit_reason")=="DEAL_REASON_EXPERT",
                "net_usd":round(net,2),
            })
    rows=0
    incident_bars=set()
    with opportunities.open(encoding="ascii",newline="") as fh:
        reader=csv.DictReader(fh,delimiter=";")
        for row in reader:
            rows+=1
            reason=row.get("entry_decision_reason","")
            if reason.startswith("Execution incident:"):
                incident_bars.add(row.get("bar_time_server",""))
    if rows==0:
        raise SafetyAuditError("Missing native opportunity history")
    if source.get("status") not in (
        "SELECTED_IMPORTED_FOR_REVIEW","IMPORTED_FOR_REVIEW"):
        raise SafetyAuditError("Native forensic import status is not reviewable")
    if not incidents and not incident_bars:
        status="NO_POST_FILL_SAFETY_INCIDENT_OBSERVED_RESEARCH_ONLY"
    else:
        status="POST_FILL_SAFETY_INCIDENT_NO_GO"
    first=min((r["entry_time_msc"] for r in incidents),default=None)
    late=[pid for start,pid in positions if first is not None and start>first]
    return {
        "schema":"qts.post_fill_native_safety_audit.v1",
        "status":status,
        "live":"LOCKED",
        "edge_validated":False,
        "trade_permission":False,
        "position_count":len(positions),
        "native_opportunity_rows":rows,
        "unsafe_original_fill_count":len(incidents),
        "native_execution_halt_bar_count":len(incident_bars),
        "new_positions_after_first_unsafe_fill":len(late),
        "position_ids_entered_after_first_unsafe_fill":late,
        "all_unsafe_fills_have_expert_close":bool(incidents) and all(
            r["robot_protective_exit_observed"] for r in incidents),
        "unsafe_fills":incidents,
        "limitation":"A tester protective close never guarantees a live gap exit price. "
                     "Lack of post-halt trades prevents an ordinary full-month "
                     "performance comparison.",
    }


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forensics",required=True,type=Path)
    parser.add_argument("--opportunities",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    try:
        result=audit(args.forensics,args.opportunities)
        code=0
    except (OSError,ValueError,TypeError,KeyError,UnicodeError) as exc:
        result={
            "schema":"qts.post_fill_native_safety_audit.v1",
            "status":"POST_FILL_SAFETY_AUDIT_FAILED_NO_GO",
            "live":"LOCKED","edge_validated":False,"trade_permission":False,
            "reason":str(exc),
        }
        code=2
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(result["status"],args.output)
    return code


if __name__=="__main__":
    raise SystemExit(main())
