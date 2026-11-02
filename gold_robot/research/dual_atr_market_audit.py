"""Read-only broker-history ATR enrichment of two native dual MT5 runs.
No orders, strategy changes, trained decisions or live approval.
"""
from __future__ import annotations
import argparse, html, json, math, os, sys, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from dual_evidence_audit import analyze, read_run
from retrospective_context import market_at_entry

def regime(m):
    if m.get("status") != "COMPLETE_CLOSED_BAR_AND_BID_ASK":
        return "UNKNOWN"
    x = float(m["m15_atr_ratio_to_trailing_median"])
    if not math.isfinite(x) or x <= 0: return "UNKNOWN"
    return "LOW" if x < 0.8 else "HIGH" if x > 1.25 else "NORMAL"

def enrich(both:Path, directional:Path, market):
    prior=analyze(both,directional) # mandatory broker provenance and reconciliation
    left=read_run(both,"1")[1]
    right=read_run(directional,"2")[1]
    cache={}
    trades=[]
    groups=defaultdict(list)
    for variant, source in (("DUAL_BOTH",left),("DUAL_DIRECTIONAL",right)):
        for (style,side,when,entry),t in source.items():
            key=(when,str(entry))
            if key not in cache: cache[key]=market(int(when))
            m=cache[key]
            band=regime(m)
            atr=float(m["m15_atr14"]) if band!="UNKNOWN" else None
            stop=float(t["_stop"])
            price=float(t["_entry"])
            valid_stop=(stop<price if side=="BUY" else stop>price)
            row={
                "variant":variant, "style":style, "side":side,
                "position_id":str(t.get("position_id","")),
                "entry_utc":datetime.fromtimestamp(int(when)/1000,timezone.utc).isoformat(),
                "entry_time_msc":str(when), "net_usd":float(t["_net"]),
                "lots":float(t["_lots"]), "exit_reason":t.get("exit_reason"),
                "regime":band, "history_status":m.get("status","UNKNOWN"),
                "atr14_closed_simple_tr_mean":atr,
                "atr_to_prior_median":m.get("m15_atr_ratio_to_trailing_median") if atr else None,
                "spread_to_atr":m.get("spread_to_atr") if atr else None,
                "h1_bias":m.get("h1_bias") if atr else None,
                "initial_stop_on_correct_side_of_fill":valid_stop,
                "sl_distance_atr":round(abs(price-stop)/atr,5) if atr and valid_stop else None,
                "adverse_slippage_atr":round(float(t.get("exit_adverse_slippage_price",0))/atr,5) if atr else None,
                "missing_reason":str(m.get("missing_reason",""))[:160] if not atr else None
            }
            trades.append(row)
            if atr: groups[(variant,style,side,band)].append(row)
    coverage={}
    for variant,total in (("DUAL_BOTH",len(left)),("DUAL_DIRECTIONAL",len(right))):
        got=sum(x["variant"]==variant and x["regime"]!="UNKNOWN" for x in trades)
        coverage[variant]={"total":total,"observed":got,"missing":total-got}
    cohorts=[]
    for (variant,style,side,band),rows in sorted(groups.items()):
        net=sum(x["net_usd"] for x in rows)
        lots=sum(x["lots"] for x in rows)
        cohorts.append({
            "variant":variant,"style":style,"side":side,"regime":band,"n":len(rows),
            "net_usd":round(net,2),"wins":sum(x["net_usd"]>0 for x in rows),
            "after_additional_10usd_per_lot":round(net-10*lots,2),
            "too_small_to_select":len(rows)<30
        })
    full=all(x["missing"]==0 for x in coverage.values())
    return {
        "schema":"qts.dual_atr_market_audit.v1",
        "status":"COMPLETE_RESEARCH_ONLY" if full else "INCOMPLETE_BROKER_HISTORY_NO_GO",
        "live":"LOCKED","edge_validated":False,"independent_holdout":False,
        "orders_sent":0,"strategy_changed":False,
        "coverage":coverage,"quote_requests":len(cache),
        "existing_broker_evidence":prior["sample"],
        "atr_definition":"Closed M15 simple average of 14 true ranges; retrospective proxy, not native MT5 iATR",
        "exploratory_bands":"LOW <0.80 trailing ATR median; HIGH >1.25; otherwise NORMAL",
        "cohorts":cohorts,"trades":trades,
        "limitations":[
            "Executed deals only: skipped or overlapping signals remain unobserved.",
            "Two tests share trades and do not constitute independent samples.",
            "Unknown historical bars or quotes are not guessed.",
            "ATR regime thresholds are not optimized, validated or trade permissions.",
            "No proof of post-stop reversals or future profitability."
        ]
    }

def save(report, out:Path):
    out.mkdir(parents=True,exist_ok=True)
    path=out/"QTS_DUAL_ATR_REVIEW.json"
    page=out/"QTS_DUAL_ATR_REVIEW.html"
    bundle=out/"QTS_DUAL_ATR_REVIEW.zip"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    summary={k:v for k,v in report.items() if k!="trades"}
    page.write_text(
        "<!doctype html><html><meta charset='utf-8'><title>QTS ATR Audit</title>"
        "<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:30px auto;"
        "padding:16px;background:#111827;color:#f9fafb}pre{white-space:pre-wrap}</style>"
        "<h2>QTS Dual ATR — RESEARCH ONLY, LIVE LOCKED</h2><pre>"
        +html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+"</pre></html>",
        encoding="utf-8")
    with zipfile.ZipFile(bundle,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.write(path,arcname=path.name);z.write(page,arcname=page.name)
    return bundle

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--both",required=True,type=Path)
    p.add_argument("--directional",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--terminal-data",required=True,type=Path)
    p.add_argument("--terminal-path",required=True,type=Path)
    a=p.parse_args()
    try: import MetaTrader5 as mt5
    except ImportError: p.error("Official MetaTrader5 Python package missing.")
    if not a.terminal_path.is_file(): p.error("MT5 executable unavailable")
    if not mt5.initialize(path=str(a.terminal_path)): p.error("MT5 read-only connection failed")
    try:
        info=mt5.terminal_info()
        if not info or os.path.normcase(os.path.abspath(str(info.data_path))) != os.path.normcase(os.path.abspath(str(a.terminal_data))):
            raise ValueError("Wrong MT5 terminal data folder")
        if mt5.symbol_info("XAUUSD@") is None or not mt5.symbol_select("XAUUSD@",True):
            raise ValueError("WMMarkets XAUUSD@ quote history unavailable")
        result=enrich(a.both,a.directional,lambda ms:market_at_entry(mt5,ms))
        bundle=save(result,a.out)
        print("QTS ATR STATUS:",result["status"])
        print("QTS ATR COVERAGE:",result["coverage"])
        print("QTS ATR ZIP:",bundle)
        return 0 if all(x["missing"]==0 for x in result["coverage"].values()) else 2
    except (OSError,ValueError,TypeError,KeyError) as exc:
        bundle=save({"schema":"qts.dual_atr_market_audit.v1","status":"FAILED_NO_GO",
                     "live":"LOCKED","edge_validated":False,"reason":str(exc)},a.out)
        print("RESEARCH NO_GO:",exc,"REPORT:",bundle,file=sys.stderr)
        return 2
    finally:mt5.shutdown()

if __name__=="__main__":raise SystemExit(main())
