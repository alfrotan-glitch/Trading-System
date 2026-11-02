"""Strict native THREE-arm dual strategy comparison. Research only, LIVE LOCKED.

Do not combine PnL across parallel simulations. Keep a clear separation
between exploratory historical rankings and independent future validation.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path

from verify_dual_opportunity import LedgerError, verify

ARMS={"DUAL_BOTH":1,"DUAL_DIRECTIONAL":2,"DUAL_QUALITY":3}
SIGNAL_FIELDS=("bar_time_server","observed_time_server","style","side",
               "signal_reason","atr14_closed","atr_rank_prior_192_pct",
               "adx_closed","h1_close_minus_ema50","bid","ask","spread")


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def arm_result(folder: Path, variant: str) -> tuple[dict, dict]:
    mode=ARMS[variant]
    meta=read_json(folder/"OPEN_RESULTS.json")
    if (meta.get("research_variant")!=variant or
        meta.get("state")!="SELECTED_TESTS_FINISHED_REVIEW_REQUIRED" or
        meta.get("live")!="LOCKED" or
        meta.get("validated_edge") is not False or
        meta.get("real_money_orders") is not False or
        meta.get("selected_styles")!=[7] or
        meta.get("symbol")!="XAUUSD@" or meta.get("model")!=4 or
        meta.get("timeframe")!="M15" or
        meta.get("deposit_usd")!=3000 or
        not meta.get("compiled_ex5_sha256") or
        not meta.get("source_manifest_sha256")):
        raise LedgerError("Unverified native identity, safety or Style 7: "+variant)
    stored=read_json(folder/"QTS_DUAL_OPPORTUNITY_SUMMARY.json")
    csvfile=folder/"native"/"QTS_7_opportunities.csv"
    verified=verify(csvfile,mode)
    if (stored.get("status")!="NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY" or
        stored.get("mode")!=mode or
        stored.get("bars")!=verified["bars"] or
        stored.get("rows")!=verified["rows"] or
        stored.get("router_verdicts_by_closed_bar")!=verified["router_verdicts_by_closed_bar"]):
        raise LedgerError("Native paired opportunity summary mismatch: "+variant)
    forensic=read_json(folder/"QTS_TRADE_BY_TRADE.json")
    positions=forensic.get("trades")
    if (not isinstance(positions,list) or
        forensic.get("edge_validated") is not False or
        forensic.get("live")!="LOCKED"):
        raise LedgerError("Missing or unauthorized native broker trade provenance: "+variant)
    pnl=[]
    fee_lots=0.0
    stop_wrong_side=0
    zero_charges=True
    for item in positions:
        if (item.get("status")!="COMPLETE" or
            not str(item.get("setup_reason","")).startswith("QTS-DUAL-M"+str(mode)+"-S") or
            item.get("side") not in ("BUY","SELL")):
            raise LedgerError("Incomplete or mismatched broker position attribution: "+variant)
        net=float(item["net_usd"]);volume=float(item["entry_lots"])
        closed_volume=float(item["exit_lots"])
        charges=float(item["charges_usd"])
        entry=float(item["entry_price"]);sl=float(item["initial_sl"])
        if not all(math.isfinite(x) for x in
                   (net,volume,closed_volume,charges,entry,sl)):
            raise LedgerError("Nonfinite trade economics: "+variant)
        if (volume<=0 or closed_volume<=0 or
            abs(volume-closed_volume)>0.000001 or
            int(item.get("deal_count",0))<2):
            raise LedgerError("Unreconciled open/exit lots or missing broker deals: "+variant)
        zero_charges=zero_charges and abs(charges)<1e-8
        stop_wrong_side+=int((item["side"]=="BUY" and sl>=entry) or
                             (item["side"]=="SELL" and sl<=entry))
        pnl.append(net);fee_lots+=volume
    gross_win=sum(x for x in pnl if x>0)
    gross_loss=-sum(x for x in pnl if x<0)
    peak=0.0;running=0.0;trade_dd=0.0
    for value in pnl:
        running+=value;peak=max(peak,running)
        trade_dd=max(trade_dd,peak-running)
    native_signals={}
    with csvfile.open(encoding="ascii",errors="strict",newline="") as fh:
        for row in csv.DictReader(fh,delimiter=";"):
            key=(row["bar_time_server"],int(row["style"]))
            native_signals[key]=tuple(row[x] for x in SIGNAL_FIELDS)
    details={
        "variant":variant,"mode":mode,"bars":verified["bars"],"rows":verified["rows"],
        "raw_signal_rows":verified["raw_signal_rows"],
        "router_verdicts_by_closed_bar":verified["router_verdicts_by_closed_bar"],
        "trades":len(pnl),"winners":sum(x>0 for x in pnl),
        "losers":sum(x<0 for x in pnl),
        "net_usd":round(sum(pnl),2),
        "profit_factor":round(gross_win/gross_loss,3) if gross_loss>0 else None,
        "closed_trade_drawdown_usd":round(trade_dd,2),
        "all_recorded_charges_zero":zero_charges,
        "unverified_fee_stress_usd_per_lot":10.0,
        "stressed_net_usd":round(sum(pnl)-10*fee_lots,2),
        "wrong_side_initial_sl_count":stop_wrong_side,
    }
    return details,{"meta":meta,"native_signals":native_signals}


def compare(folders: dict[str,Path]) -> dict:
    if set(folders)!=set(ARMS):
        raise LedgerError("Exactly three separate native variant directories required")
    result={};provenance={}
    for variant in ARMS:
        result[variant],provenance[variant]=arm_result(folders[variant],variant)
    base=provenance["DUAL_BOTH"]
    keys=("from_date","to_date","symbol","model","timeframe","deposit_usd",
          "source_manifest_sha256","compiled_ex5_sha256",
          "terminal_exe_sha256")
    for variant in ("DUAL_DIRECTIONAL","DUAL_QUALITY"):
        other=provenance[variant]
        if any(base["meta"].get(k)!=other["meta"].get(k) for k in keys):
            raise LedgerError("Incomparable date/symbol/EX5/source/terminal across arms")
        if base["native_signals"]!=other["native_signals"]:
            raise LedgerError("Mismatched broker-native bars, prices or raw strategy signals")
    historical=base["meta"]["from_date"]<="2026.11.03"
    # Largest stressed net is a descriptive SAMPLE leader, never live approval.
    leader=max(result,key=lambda x:result[x]["stressed_net_usd"])
    return {
        "schema":"qts.dual_threeway_selection_review.v1",
        "status":"THREE_MODE_RESEARCH_REVIEW_ONLY",
        "live":"LOCKED","edge_validated":False,"trade_permission":False,
        "independent_holdout":not historical,
        "same_native_source_and_signals_verified":True,
        "test_period":[base["meta"]["from_date"],base["meta"]["to_date"]],
        "historical_sample_leader_after_assumed_fee_stress":leader,
        "leader_is_trade_approval":False,
        "variants":[result[x] for x in ARMS],
        "limitations":[
          "Identical historical period is a comparison, not three combined independent portfolios.",
          "October 2026 informed the choice of the directional hypothesis.",
          "Assumed USD 10 per lot fee stress is not an authenticated broker commission.",
          "Closed-trade drawdown omits open-equity drawdown: prefer native MT5 equity figures.",
          "Abnormal stop fills and post-stop tick paths require direct independent review.",
          "A completed backtest is not evidence of profitable forward performance."
        ]
    }


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("both","directional","quality"):
        p.add_argument("--"+k,required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    try:
        results=compare({"DUAL_BOTH":args.both,
                         "DUAL_DIRECTIONAL":args.directional,
                         "DUAL_QUALITY":args.quality})
        code=0
    except (OSError,ValueError,TypeError,UnicodeError,KeyError,LedgerError) as exc:
        results={"schema":"qts.dual_threeway_selection_review.v1",
                 "status":"THREE_MODE_COMPARISON_FAILED_NO_GO","live":"LOCKED",
                 "edge_validated":False,"trade_permission":False,
                 "reason":str(exc)}
        code=2
    args.output.write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    print(results["status"],str(args.output))
    return code


if __name__=="__main__":
    raise SystemExit(main())
