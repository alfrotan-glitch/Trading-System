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
import re
from collections import defaultdict
from pathlib import Path


class SafetyAuditError(ValueError):
    pass


def inspect_native_entry_deals(path: Path, positions: dict, expected_mode: int | None) -> dict:
    """Reconcile every raw broker entry deal, not an averaged position fill.

    A weighted-average entry can conceal one unsafe partial fill. This check
    refuses missing/malformed, duplicate, foreign-mode and unreconciled deals.
    """
    if not path.is_file() or path.stat().st_size>25_000_000:
        raise SafetyAuditError("Missing or oversized native broker deals")
    required=("position_id","deal_id","order_id","entry","reason","type",
              "time_msc","volume","price","sl","tp","gross",
              "commission","swap","fee","setup_reason")
    ids=set()
    entries=defaultdict(list)
    exit_volumes=defaultdict(float)
    total=0
    with path.open(encoding="ascii",newline="") as fh:
        reader=csv.DictReader(fh,delimiter=";")
        if tuple(reader.fieldnames or ())!=required:
            raise SafetyAuditError("Native broker deal CSV schema mismatch")
        for record in reader:
            total+=1
            if total>100_000 or None in record or any(v is None for v in record.values()):
                raise SafetyAuditError("Malformed or unbounded raw broker deal rows")
            try:
                deal_id=int(record["deal_id"])
                order_id=int(record["order_id"])
                pid=str(int(record["position_id"]))
                stamp=int(record["time_msc"])
                lot=float(record["volume"])
                price=float(record["price"])
                sl=float(record["sl"])
                tp=float(record["tp"])
            except (TypeError,ValueError) as exc:
                raise SafetyAuditError("Invalid raw broker deal fields") from exc
            if (deal_id<=0 or order_id<=0 or stamp<=0 or
                pid not in positions or deal_id in ids or lot<=0 or
                not all(math.isfinite(v) for v in (lot,price,sl,tp))):
                raise SafetyAuditError("Invalid broker deal identity, volume or prices")
            ids.add(deal_id)
            entry=record["entry"]
            if entry=="DEAL_ENTRY_IN":
                setup=record["setup_reason"]
                match=re.fullmatch(r"QTS-DUAL-M([123])-S([13])",setup)
                if not match or (expected_mode is not None and
                                 int(match.group(1))!=expected_mode):
                    raise SafetyAuditError("Original entry order style/mode attribution missing")
                direction={"DEAL_TYPE_BUY":"BUY","DEAL_TYPE_SELL":"SELL"}.get(record["type"])
                if direction is None or positions[pid]["side"]!=direction:
                    raise SafetyAuditError("Entry deal direction conflicts with position")
                entries[pid].append((stamp,price,sl,tp,lot,deal_id,direction))
            elif entry=="DEAL_ENTRY_OUT":
                exit_volumes[pid]+=lot
            else:
                raise SafetyAuditError("Unsupported raw broker reversal or deal entry type")
    if not ids or set(entries)!=set(positions):
        raise SafetyAuditError("Native entry-deal coverage does not match completed positions")
    incidents=[]
    for pid,position in positions.items():
        legs=entries[pid]
        initial_time=min(v[0] for v in legs)
        entry_vol=sum(v[4] for v in legs)
        if (initial_time!=position["entry_time_msc"] or
            abs(entry_vol-position["entry_lots"])>1e-6 or
            abs(exit_volumes[pid]-position["exit_lots"])>1e-6):
            raise SafetyAuditError("Native broker entry/exit amounts or times mismatch")
        for stamp,price,sl,tp,lot,deal_id,side in legs:
            safe=sl<price<tp if side=="BUY" else tp<price<sl
            if not safe:
                incidents.append({
                    "position_id":pid,"entry_deal_id":str(deal_id),
                    "side":side,"entry_time_msc":stamp,
                    "exit_time_msc":position["exit_time_msc"],
                    "actual_entry":price,"original_sl":sl,"original_tp":tp,
                    "broker_exit_reason":position["exit_reason"],
                    "robot_protective_exit_observed":
                        position["exit_reason"]=="DEAL_REASON_EXPERT",
                    "net_usd":round(position["net_usd"],2),
                })
    return {"entry_deal_count":sum(map(len,entries.values())),
            "incidents":incidents}


def audit(forensics: Path, opportunities: Path,
          broker_deals: Path | None = None, mode: int | None = None) -> dict:
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
    positions_by_id={}
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
        positions_by_id[pid]={
            "side":side,"entry_time_msc":begin,"exit_time_msc":end,
            "entry_lots":entry_lots,"exit_lots":exit_lots,
            "exit_reason":row.get("exit_reason"),"net_usd":net
        }
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
    broker_entry_deals_verified=False
    entry_deal_count=None
    if broker_deals is not None:
        result=inspect_native_entry_deals(broker_deals,positions_by_id,mode)
        incidents=result["incidents"]
        entry_deal_count=result["entry_deal_count"]
        broker_entry_deals_verified=True
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
        "individual_entry_deals_verified":broker_entry_deals_verified,
        "native_entry_deal_count":entry_deal_count,
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
    parser.add_argument("--deals",required=True,type=Path)
    parser.add_argument("--mode",required=True,type=int,choices=(1,2,3))
    args=parser.parse_args()
    try:
        result=audit(args.forensics,args.opportunities,
                     broker_deals=args.deals,mode=args.mode)
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
