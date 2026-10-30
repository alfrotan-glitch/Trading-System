"""Build auditable post-SL replay inputs from QTS native MT5 deal ZIPs.

Read only. No MT5 connection or order API. This creates STOP case files; it
does NOT claim any post-stop reversal without future broker bid/ask ticks.
Use with stop_reversal_audit.py after matching tick data are exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

HEADER = ("trade_id", "side", "entry_time_ms", "exit_time_ms", "entry_price",
          "initial_stop_price", "exit_price", "exit_reason",
          "initial_target_price", "style", "setup_reason")
REQUIRED = ("position_id", "deal_id", "entry", "reason", "type", "time_msc",
            "volume", "price", "sl", "tp", "gross", "commission",
            "swap", "fee", "setup_reason")
OUTPUT_STATUS = "STOP_REPLAY_INPUTS_READY_TICKS_REQUIRED"


def build(bundle: Path) -> tuple[list[dict], dict]:
    cases = []
    summary = {
        "schema": "qts.stop.replay.input.v1",
        "status": OUTPUT_STATUS,
        "live": "LOCKED",
        "price_after_stop_verified": False,
        "source_file_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "per_style": {},
        "excluded_position_reasons": {},
        "limitations": [
            "Broker deal times must align with broker bid/ask tick timestamps.",
            "TP touch after an SL is unknown until synchronized future executable ticks are replayed.",
            "A later TP quote touch is not a possible profit or a reason to widen SL.",
            "No outcome-based model or strategy rule is fitted from these historical stops.",
        ],
    }
    excluded = defaultdict(int)
    with ZipFile(bundle) as z:
        names = set(z.namelist())
        if not {"comparison.json", "QTS_TRADE_BY_TRADE.json"}.issubset(names):
            raise ValueError("Missing native comparison or position evidence")
        comparison = json.loads(z.read("comparison.json"))
        forensic = json.loads(z.read("QTS_TRADE_BY_TRADE.json"))
        if "OPEN_RESULTS.json" in names:
            run = json.loads(z.read("OPEN_RESULTS.json"))
        else:
            run = {}
        if run.get("targeted") is True:
            selected = run.get("selected_styles")
            if (not isinstance(selected, list) or not selected
                    or any(type(i) is not int or not 0 <= i <= 9 for i in selected)
                    or len(selected) != len(set(selected))):
                raise ValueError("Invalid selected-style native run manifest")
            if run.get("state") != "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED":
                raise ValueError("Targeted run did not pass per-style forensic gates")
            if (len(run.get("results", [])) != len(selected) or
                    any(r.get("status") != "REPORT_AND_FORENSICS_SAVED"
                        or r.get("style_id") not in selected for r in run["results"])):
                raise ValueError("Selected native reports/forensics are incomplete")
            present = {int(e.get("style")) for e in forensic.get("evidence", [])
                       if e.get("status") == "IMPORTED" and int(e.get("deals", 0)) > 0}
            if not set(selected).issubset(present):
                raise ValueError("Missing original selected-style deal evidence")
        else:
            # Backward-compatible full-run evidence. Unselected styles must
            # never be silently dropped from a complete review.
            parsed = comparison.get("reports_parsed")
            if forensic.get("status") != "IMPORTED_FOR_REVIEW" or parsed not in (8, 10):
                raise ValueError("Incomplete or unverified full-run MT5 evidence")
            selected = list(range(parsed))
        required = {f"native/QTS_{i}_trades.csv" for i in selected}
        if not required.issubset(names):
            raise ValueError(f"Missing selected native deal files: {sorted(required - names)}")
        results = {int(r["style"]): r for r in comparison["results"]
                   if r.get("state", "PARSED") == "PARSED"}
        if (comparison.get("reports_parsed") != len(selected)
                or not set(selected).issubset(results)):
            raise ValueError("Selected reports do not have verified style identity")
        reference = defaultdict(dict)
        for trade in forensic.get("trades", []):
            style = int(trade["style"])
            ident = str(trade["position_id"])
            if ident in reference[style]:
                raise ValueError("Duplicate position in forensic summary")
            reference[style][ident] = trade
        for style in selected:
            blob = z.read(f"native/QTS_{style}_trades.csv")
            rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig")), delimiter=";"))
            if not rows or not set(REQUIRED).issubset(rows[0]):
                raise ValueError(f"Missing/invalid original deal rows for style {style}")
            grouped = defaultdict(list)
            for row in rows:
                grouped[row["position_id"]].append(row)
            if len(grouped) != int(results[style]["trades"]) or len(grouped) != len(reference[style]):
                raise ValueError(f"Position count mismatch for style {style}")
            expected = sum(float(p["net_usd"]) for p in reference[style].values())
            if abs(expected - float(results[style]["net_usd"])) > 0.05:
                raise ValueError(f"Net PnL doesn't reconcile for style {style}")
            style_stops = 0
            for ident, deals in grouped.items():
                position = reference[style].get(ident)
                if position is None or position["status"] not in ("COMPLETE", "COMPLETE_MULTI_EXIT"):
                    raise ValueError(f"Missing or incomplete joined position: {style}:{ident}")
                entries = [r for r in deals if r["entry"] == "DEAL_ENTRY_IN"]
                exits = [r for r in deals if r["entry"] == "DEAL_ENTRY_OUT"]
                if position.get("exit_reason") != "DEAL_REASON_SL":
                    continue
                # Multiple legs, reversals or uncertain volume accounting
                # cannot be flattened into one fabricated stop timestamp.
                if len(entries) != 1 or len(exits) != 1 or len(deals) != 2:
                    excluded["multi_deal_or_partial_stop"] += 1
                    continue
                entry, out = entries[0], exits[0]
                if out["reason"] != "DEAL_REASON_SL":
                    excluded["ambiguous_stop_reason"] += 1
                    continue
                side = "BUY" if entry["type"] == "DEAL_TYPE_BUY" else (
                    "SELL" if entry["type"] == "DEAL_TYPE_SELL" else None)
                if not side or not str(ident).strip():
                    raise ValueError("Unknown side or position id")
                price, stop, target = (float(entry[k]) for k in ("price", "sl", "tp"))
                entry_ms = int(entry["time_msc"])
                exit_ms = int(out["time_msc"])
                if (entry_ms < 0 or exit_ms <= entry_ms or min(price, stop, target) <= 0
                        or (side == "BUY" and not (stop < price < target))
                        or (side == "SELL" and not (target < price < stop))):
                    excluded["invalid_initial_stop_target_or_chronology"] += 1
                    continue
                cases.append({
                    "trade_id": f"{style}:{ident}", "side": side,
                    "entry_time_ms": entry_ms, "exit_time_ms": exit_ms,
                    "entry_price": price, "initial_stop_price": stop,
                    "exit_price": float(out["price"]), "exit_reason": "SL",
                    "initial_target_price": target, "style": style,
                    "setup_reason": entry["setup_reason"],
                })
                style_stops += 1
            summary["per_style"][str(style)] = {
                "native_positions": len(grouped), "stop_cases_exported": style_stops,
                "native_net_usd": float(results[style]["net_usd"]),
            }
    cases.sort(key=lambda c: (c["exit_time_ms"], c["trade_id"]))
    summary["stop_cases_total"] = len(cases)
    summary["excluded_position_reasons"] = dict(sorted(excluded.items()))
    return cases, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases, summary = build(args.bundle)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "QTS_STOP_CASES.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(cases)
    (args.out / "QTS_STOP_INPUT_AUDIT.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
