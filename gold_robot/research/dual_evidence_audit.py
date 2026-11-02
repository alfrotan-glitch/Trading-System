"""Evidence-first, read-only audit of TWO completed native dual-strategy MT5 runs.

No strategy optimization, orders, inferred ATR, post-stop prices or live approval.
Operates on exact native trade-forensics JSON and verified tester metadata.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

STATES = {"SELECTED_TESTS_FINISHED_REVIEW_REQUIRED"}
NATIVE_FORENSICS = "SELECTED_IMPORTED_FOR_REVIEW"
VALID_STYLES = {1, 3}


class EvidenceError(ValueError):
    pass


def amount(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EvidenceError("Non-numeric financial value") from exc
    if not result.is_finite():
        raise EvidenceError("Non-finite financial value")
    return result


def read_run(folder: Path, mode: str):
    outcome = json.loads((folder / "OPEN_RESULTS.json").read_text(encoding="utf-8-sig"))
    forensic = json.loads((folder / "QTS_TRADE_BY_TRADE.json").read_text(encoding="utf-8-sig"))
    expected = "DUAL_BOTH" if mode == "1" else "DUAL_DIRECTIONAL"
    if (outcome.get("research_variant") != expected
            or outcome.get("state") not in STATES
            or outcome.get("live") != "LOCKED"
            or outcome.get("validated_edge") is not False
            or outcome.get("real_money_orders") is not False
            or outcome.get("symbol") != "XAUUSD@"
            or outcome.get("timeframe") != "M15"
            or outcome.get("selected_styles") != [7]
            or not outcome.get("source_manifest_sha256")
            or not outcome.get("compiled_ex5_sha256")):
        raise EvidenceError("Tester identity/safety/evidence mismatch for " + expected)
    if (forensic.get("status") != NATIVE_FORENSICS
            or forensic.get("live") != "LOCKED"
            or forensic.get("edge_validated") is not False
            or forensic.get("selected_styles") != [7]):
        raise EvidenceError("Native trade evidence is incomplete for " + expected)
    trades = forensic.get("trades")
    if not isinstance(trades, list) or not trades:
        raise EvidenceError("No completed trades for " + expected)
    normalized = {}
    for trade in trades:
        match = re.fullmatch(r"QTS-DUAL-M([12])-S([13])", str(trade.get("setup_reason", "")))
        if not match or match.group(1) != mode or trade.get("status") != "COMPLETE":
            raise EvidenceError("Unknown or incomplete native deal attribution")
        style = int(match.group(2))
        side = trade.get("side")
        if style not in VALID_STYLES or side not in ("BUY", "SELL"):
            raise EvidenceError("Invalid style/side")
        if mode == "2" and not ((style == 1 and side == "BUY") or (style == 3 and side == "SELL")):
            raise EvidenceError("Directional variant contains forbidden strategy/side")
        entry = amount(trade["entry_price"])
        stop = amount(trade["initial_sl"])
        distance = amount(trade["risk_price_distance"])
        net = amount(trade["net_usd"])
        lots = amount(trade["entry_lots"])
        if lots <= 0 or distance <= 0:
            raise EvidenceError("Nonpositive lot or initial risk distance")
        # Position IDs are run-local; use an exact one-to-one entry signature.
        key = (style, side, str(trade["entry_time_msc"]), entry)
        if key in normalized:
            raise EvidenceError("Duplicate entry identity; no ambiguous pairing")
        raw = dict(trade)
        raw["_net"] = net
        raw["_lots"] = lots
        raw["_entry"] = entry
        raw["_stop"] = stop
        raw["_risk"] = distance
        normalized[key] = raw
    return outcome, normalized


def analyze(both: Path, directional: Path):
    a_meta, a = read_run(both, "1")
    b_meta, b = read_run(directional, "2")
    for k in ("symbol", "timeframe", "from_date", "to_date",
              "deposit_usd", "source_manifest_sha256", "compiled_ex5_sha256",
              "terminal_exe_sha256"):
        if a_meta.get(k) != b_meta.get(k):
            raise EvidenceError("Runs are not comparable: mismatched " + k)
    common = set(a) & set(b)
    only_a = set(a) - common
    only_b = set(b) - common
    profit = lambda xs: sum((t["_net"] for t in xs), Decimal("0"))
    total_a = profit(a.values())
    total_b = profit(b.values())
    paired = sum((b[k]["_net"] - a[k]["_net"] for k in common), Decimal("0"))
    removed = -profit(a[k] for k in only_a)
    released = profit(b[k] for k in only_b)
    if total_b - total_a != paired + removed + released:
        raise EvidenceError("Non-reconciling P/L decomposition")
    per_month = {"DUAL_BOTH": defaultdict(Decimal), "DUAL_DIRECTIONAL": defaultdict(Decimal)}
    anomalies = []
    for label, trades in (("DUAL_BOTH", a.values()), ("DUAL_DIRECTIONAL", b.values())):
        for t in trades:
            stamp = datetime.fromtimestamp(int(t["entry_time_msc"]) / 1000, tz=timezone.utc)
            per_month[label][stamp.strftime("%Y-%m")] += t["_net"]
            adverse = amount(t.get("exit_adverse_slippage_price", 0))
            invalid_stop = (t["side"] == "BUY" and t["_stop"] >= t["_entry"]) or (
                t["side"] == "SELL" and t["_stop"] <= t["_entry"])
            stop_ratio = adverse / t["_risk"]
            if invalid_stop or stop_ratio >= Decimal("0.25"):
                anomalies.append({
                    "variant": label, "position_id": str(t.get("position_id", "")),
                    "side": t["side"], "strategy": t["setup_reason"],
                    "reason": "SL_WRONG_SIDE_OF_FILL" if invalid_stop else "STOP_EXECUTION_DISLOCATION",
                    "initial_entry": str(t["_entry"]), "initial_sl": str(t["_stop"]),
                    "exit_price": str(t["exit_price"]), "loss_or_profit_usd": str(t["_net"]),
                    "adverse_slippage_price": str(adverse),
                    "slippage_as_fraction_of_initial_stop": str(stop_ratio)
                })
    costs_all_zero = all(amount(t.get("charges_usd", 0)) == 0 for t in list(a.values()) + list(b.values()))
    months = sorted(set(per_month["DUAL_BOTH"]) | set(per_month["DUAL_DIRECTIONAL"]))
    monthly = [{
        "month_utc_by_entry": month,
        "both_usd": str(per_month["DUAL_BOTH"][month]),
        "directional_usd": str(per_month["DUAL_DIRECTIONAL"][month]),
        "difference_usd": str(per_month["DUAL_DIRECTIONAL"][month] - per_month["DUAL_BOTH"][month])
    } for month in months]
    october = sum((amount(x["difference_usd"]) for x in monthly
                   if x["month_utc_by_entry"].endswith("-10")), Decimal("0"))
    difference = total_b - total_a
    return {
        "schema": "qts.dual_evidence_audit.v1",
        "status": "RESEARCH_REVIEW_ONLY_NOT_TRADE_PERMISSION",
        "live": "LOCKED", "edge_validated": False,
        "strategy_changed": False, "independent_holdout_tested": False,
        "atr_at_entry_available": False, "rejected_signal_ledger_available": False,
        "post_stop_tick_paths_available": False,
        "all_recorded_charges_zero": costs_all_zero,
        "common_entry_signature_does_not_prove_causal_opportunity_displacement": True,
        "months_are_utc_by_entry_not_broker_session": True,
        "native_source_manifest_sha256": a_meta["source_manifest_sha256"],
        "native_compiled_ex5_sha256": a_meta["compiled_ex5_sha256"],
        "sample": {
            "both_trades": len(a), "directional_trades": len(b),
            "common_entries": len(common), "only_both": len(only_a), "only_directional": len(only_b),
            "both_net_usd": str(total_a), "directional_net_usd": str(total_b),
            "net_difference_usd": str(difference),
            "removed_both_only_contribution_usd": str(removed),
            "new_directional_only_contribution_usd": str(released),
            "shared_entry_pnl_difference_usd": str(paired),
            "october_difference_usd": str(october),
            "october_share_of_difference_pct": str(october * 100 / difference) if difference else None
        },
        "monthly": monthly, "execution_anomalies": anomalies,
        "limitations": [
            "Same period used to choose the directional hypothesis; no independent holdout.",
            "No ATR-at-entry observations or skipped-opportunity ledger in these files.",
            "Entry pairing is observational; opportunity displacement is not proven causally.",
            "No broker tick path after stop: cannot infer subsequent target hits.",
            "Recorded commissions/swaps/fees are zero; independently verify real trading costs.",
            "Unusual fills/SL dislocations need MT5 tester ticks, order/deal journal and symbol specifications."
        ]
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--both", type=Path, required=True)
    p.add_argument("--directional", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / "QTS_DUAL_EVIDENCE_AUDIT.json"
    page = args.out / "QTS_DUAL_EVIDENCE_AUDIT.html"
    try:
        report = analyze(args.both, args.directional)
        code = 0
    except (EvidenceError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        report = {"schema": "qts.dual_evidence_audit.v1", "status": "FAILED_NO_GO",
                  "live": "LOCKED", "edge_validated": False, "reason": str(exc)}
        code = 2
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Render the trusted report object as escaped preformatted JSON to avoid injection.
    pretty = html.escape(json.dumps(report, indent=2, ensure_ascii=False))
    page.write_text("<!doctype html><html lang='en'><meta charset='utf-8'>"
                    "<title>QTS Dual Evidence Audit</title><style>"
                    "body{font:16px system-ui;max-width:1100px;margin:35px auto;line-height:1.5;"
                    "background:#101820;color:#f5f5f5;padding:15px}"
                    "pre{white-space:pre-wrap;word-break:break-word}h1{color:#eee}"
                    "</style><h1>QTS Dual Evidence Audit — RESEARCH ONLY, LIVE LOCKED</h1>"
                    "<p>Not a strategy recommendation, approval or native tick reconstruction.</p>"
                    "<pre>" + pretty + "</pre></html>", encoding="utf-8")
    print(output)
    print(page)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
