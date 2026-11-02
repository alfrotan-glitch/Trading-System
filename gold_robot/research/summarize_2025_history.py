"""Read-only full-period QTS Gold history summary from verified native MT5 data.

No broker orders, portfolio optimization, missed-fill predictions or trading
permission. A strategy can be HALTED early yet continue producing raw signals.
Never represent its truncated broker deals as full-window performance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

MODES = {"DUAL_BOTH": 1, "DUAL_DIRECTIONAL": 2, "DUAL_QUALITY": 3}
STATES = {"SELECTED_TESTS_FINISHED_REVIEW_REQUIRED",
          "SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO"}
SAFETY_STATES = {"POST_FILL_SAFETY_INCIDENT_NO_GO",
                 "NO_POST_FILL_SAFETY_INCIDENT_OBSERVED_RESEARCH_ONLY"}


class HistoricalEvidenceError(ValueError):
    pass


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as source:
        return json.load(source)


def summarize(folder: Path, variant: str, from_date: str, to_date: str) -> dict:
    mode = MODES[variant]
    requested_start = datetime.strptime(from_date, "%Y.%m.%d")
    requested_end = datetime.strptime(to_date, "%Y.%m.%d")
    if requested_start >= requested_end:
        raise HistoricalEvidenceError("Invalid requested test window")
    meta = read_json(folder/"OPEN_RESULTS.json")
    if (meta.get("research_variant") != variant or
        meta.get("state") not in STATES or
        meta.get("live") != "LOCKED" or
        meta.get("validated_edge") is not False or
        meta.get("real_money_orders") is not False or
        meta.get("symbol") != "XAUUSD@" or
        meta.get("model") != 4 or
        meta.get("timeframe") != "M15" or
        meta.get("deposit_usd") != 3000 or
        meta.get("selected_styles") != [7] or
        meta.get("from_date") != from_date or
        meta.get("to_date") != to_date or
        not meta.get("compiled_ex5_sha256") or
        not meta.get("source_manifest_sha256")):
        raise HistoricalEvidenceError("Native research identity, dates or lock invalid")
    safety = read_json(folder/"QTS_POST_FILL_SAFETY_AUDIT.json")
    if (safety.get("status") not in SAFETY_STATES or
        safety.get("live") != "LOCKED" or
        safety.get("edge_validated") is not False or
        safety.get("trade_permission") is not False or
        safety.get("individual_entry_deals_verified") is not True):
        raise HistoricalEvidenceError("Unverified original broker-deal safety audit")
    incident = safety["status"] == "POST_FILL_SAFETY_INCIDENT_NO_GO"
    if incident != (meta["state"] == "SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO"):
        raise HistoricalEvidenceError("Safety audit contradicts MT5 run result")
    verified = read_json(folder/"QTS_DUAL_OPPORTUNITY_SUMMARY.json")
    if (verified.get("status") != "NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY"
        or verified.get("mode") != mode or verified.get("live") != "LOCKED"
        or verified.get("edge_validated") is not False):
        raise HistoricalEvidenceError("Unverified native two-style signal ledger")

    opportunities = folder/"native"/"QTS_7_opportunities.csv"
    if not opportunities.is_file():
        raise HistoricalEvidenceError("Native closed-bar ledger is missing")
    monthly = defaultdict(lambda: {"closed_bars": 0, "retest_buy": 0,
                                   "retest_sell": 0, "sweep_buy": 0,
                                   "sweep_sell": 0, "halt_bars": 0})
    earliest = latest = prior = None
    total_rows = 0
    total_bars = 0
    signal_counts = Counter()
    gap_days = 0.0
    with opportunities.open(encoding="ascii", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        needed = {"bar_time_server", "style", "side", "entry_decision_reason"}
        if not reader.fieldnames or not needed.issubset(reader.fieldnames):
            raise HistoricalEvidenceError("Missing required native opportunity columns")
        for row in reader:
            total_rows += 1
            if total_rows > 350_000 or None in row or any(v is None for v in row.values()):
                raise HistoricalEvidenceError("Malformed/oversized native signal ledger")
            try:
                bar = datetime.strptime(row["bar_time_server"], "%Y.%m.%d %H:%M:%S")
                style = int(row["style"])
                side = int(row["side"])
            except (ValueError, TypeError) as exc:
                raise HistoricalEvidenceError("Invalid native bar timestamp or signal") from exc
            if not (requested_start <= bar < requested_end) or style not in (1,3) or side not in (-1,0,1):
                raise HistoricalEvidenceError("Native signal outside requested period or invalid style")
            if prior is not None and bar < prior:
                raise HistoricalEvidenceError("Nonmonotonic native closed-bar timeline")
            if bar != prior:
                if prior is not None:
                    gap_days = max(gap_days, (bar-prior).total_seconds()/86400)
                total_bars += 1
                key = bar.strftime("%Y-%m")
                monthly[key]["closed_bars"] += 1
                if row["entry_decision_reason"].startswith("Execution incident:"):
                    monthly[key]["halt_bars"] += 1
                earliest = earliest or bar
                latest = bar
            if side:
                key = ("retest" if style == 1 else "sweep") + ("_buy" if side>0 else "_sell")
                monthly[bar.strftime("%Y-%m")][key] += 1
                signal_counts[key] += 1
            prior = bar
    if total_rows != 2*total_bars or total_rows != int(verified["rows"]) or total_bars != int(verified["bars"]):
        raise HistoricalEvidenceError("Native signal coverage disagrees with verified two-row ledger")

    trades = read_json(folder/"QTS_TRADE_BY_TRADE.json")
    if (trades.get("live") != "LOCKED" or trades.get("edge_validated") is not False
        or trades.get("selected_styles") != [7] or
        not isinstance(trades.get("trades"), list)):
        raise HistoricalEvidenceError("Native broker position forensics unavailable")
    net = 0.0
    wins = losses = 0
    for trade in trades["trades"]:
        value = float(trade["net_usd"])
        if trade.get("status") != "COMPLETE" or not math.isfinite(value):
            raise HistoricalEvidenceError("Incomplete or invalid broker position")
        net += value
        wins += int(value>0)
        losses += int(value<0)

    coverage_start = earliest is not None and earliest <= requested_start+timedelta(days=14)
    coverage_end = latest is not None and latest >= requested_end-timedelta(days=14)
    coverage_gaps = gap_days > 14
    # On extended periods, isolated daily records must not masquerade as
    # complete M15 broker history. Gold ordinarily has hundreds of CLOSED
    # M15 bars even in shortened/holiday trading months.
    thin_full_months=[]
    if (requested_end-requested_start).days>=45:
        first_of_month=datetime(requested_start.year,requested_start.month,1)
        month=first_of_month
        while month<requested_end:
            nxt=(datetime(month.year+1,1,1) if month.month==12 else
                 datetime(month.year,month.month+1,1))
            if month>=requested_start and nxt<=requested_end:
                label=month.strftime("%Y-%m")
                if monthly[label]["closed_bars"]<300:
                    thin_full_months.append(label)
            month=nxt
    full_coverage = coverage_start and coverage_end and not coverage_gaps and not thin_full_months
    if safety.get("new_positions_after_first_unsafe_fill", 0)>0:
        status = "HISTORICAL_UNSAFE_POST_HALT_TRADING_NO_GO"
    elif incident:
        status = "HISTORICAL_SAFETY_STOP_NO_GO"
    elif not full_coverage:
        status = "HISTORICAL_MARKET_DATA_COVERAGE_NO_GO"
    else:
        status = "HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED"

    return {
        "schema": "qts.gold.2025_to_date_native_review.v1",
        "status": status,
        "live": "LOCKED",
        "edge_validated": False,
        "trade_permission": False,
        "tested_variant": variant,
        "tested_mode": mode,
        "period_requested": [from_date, to_date],
        "end_date_is_exclusive": True,
        "first_observed_bar_server": earliest.strftime("%Y.%m.%d %H:%M:%S") if earliest else None,
        "last_observed_bar_server": latest.strftime("%Y.%m.%d %H:%M:%S") if latest else None,
        "market_data_window_coverage_checked": bool(full_coverage),
        "maximum_gap_calendar_days": round(gap_days,2),
        "months_with_insufficient_m15_bars": thin_full_months,
        "native_m15_closed_bars": total_bars,
        "native_raw_signal_rows": total_rows,
        "raw_signals_not_broker_fills": True,
        "raw_signals_by_style_side": dict(sorted(signal_counts.items())),
        "native_completed_positions": len(trades["trades"]),
        "native_winners": wins,
        "native_losers": losses,
        "native_positions_net_usd": round(net,2),
        "native_position_results_cover_full_window": bool(full_coverage and not incident),
        "native_safety_audit_status": safety["status"],
        "unsafe_original_entry_deals": int(safety["unsafe_original_fill_count"]),
        "positions_entered_after_first_unsafe_fill": int(safety["new_positions_after_first_unsafe_fill"]),
        "monthly_native_closed_bar_signals": dict(sorted(monthly.items())),
        "limitations": [
            "The broker may lack older real ticks; ledger coverage is separately checked.",
            "MT5 server bar timestamps, not the user's Kabul time, define months.",
            "Observed closed-bar signals cannot be assigned imagined fill PnL.",
            "A stopped EA's later observed signals are NOT trades.",
            "Net PnL reflects broker-exported costs; zero charges require independent verification.",
            "No live permission or positive edge is inferred from historical data."
        ]
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--variant", choices=tuple(MODES), required=True)
    p.add_argument("--from-date", required=True)
    p.add_argument("--to-date", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        result = summarize(a.folder,a.variant,a.from_date,a.to_date)
        code = 0 if result["status"] == "HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED" else 2
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,OverflowError) as e:
        result = {
            "schema":"qts.gold.2025_to_date_native_review.v1",
            "status":"HISTORICAL_EVIDENCE_INVALID_NO_GO",
            "reason":str(e),"live":"LOCKED","edge_validated":False,
            "trade_permission":False
        }
        code=2
    a.output.write_text(json.dumps(result,indent=2)+"\n", encoding="utf-8")
    print("HISTORICAL RESEARCH:",result["status"],str(a.output))
    return code


if __name__=="__main__":
    raise SystemExit(main())
