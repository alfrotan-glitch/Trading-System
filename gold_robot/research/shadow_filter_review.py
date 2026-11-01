"""Read-only, post-hoc shadow comparison for native Sweep/Reclaim positions.

This program sums ALREADY EXECUTED baseline MT5 trades in saved entry-context
reports. It does NOT replay skipped entries, regenerate equity, change the EA,
route connected orders, or validate a future edge. Two candidates are FIXED:
  SHADOW_ATR_LOW: Keep Style 3 only when entry M15 ATR <= trailing median.
  SHADOW_NO_BUY_HIGH_ATR: Keep Style 3 except BUY when entry ATR > median.
Both are selected AFTER looking at historical data; no promotion is allowed.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

SCHEMA = "qts.mt5.posthoc_shadow_filter_review.v1"
CONTEXT_SCHEMA = "qts.mt5.retrospective_context.v1"
COST_PER_LOT = (0.0, 10.0, 20.0)
STRATEGIES = ("BASELINE", "SHADOW_ATR_LOW", "SHADOW_NO_BUY_HIGH_ATR")


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _valid_context(report: dict) -> tuple[str, list[dict]]:
    """Only reconcile whole, zero-gap Style 1/3 baseline evidence."""
    _require(report.get("schema") == CONTEXT_SCHEMA
             and report.get("status") == "DESCRIPTIVE_ONLY_REVIEW_REQUIRED"
             and report.get("live") == "LOCKED"
             and report.get("validated_edge") is False
             and report.get("symbol") == "XAUUSD@",
             "Not a safe and completed native baseline context report")
    rows = report.get("positions")
    total = report.get("total_positions")
    _require(isinstance(rows, list) and rows and len(rows) == total
             and report.get("complete_market_snapshots") == total
             and report.get("quarantined_position_count", 0) == 0,
             "Incomplete, quarantined, or missing original MT5 positions")
    period = report.get("test_period")
    _require(isinstance(period, list) and len(period) == 2, "Missing period")
    start = datetime.strptime(period[0], "%Y.%m.%d")
    end = datetime.strptime(period[1], "%Y.%m.%d")
    _require(start < end, "Invalid historical period")
    _require(isinstance(report.get("source_compiled_ex5_sha256"), str)
             and isinstance(report.get("source_manifest_sha256"), str),
             "Missing native EA/source build provenance")
    selected = []
    seen = set()
    for p in rows:
        _require(isinstance(p, dict) and p.get("style") in (1, 3)
                 and p.get("side") in ("BUY", "SELL")
                 and p.get("atr_band") in ("ABOVE_TRAILING_MEDIAN",
                                          "AT_OR_BELOW_TRAILING_MEDIAN")
                 and p.get("market", {}).get("status")
                 == "COMPLETE_CLOSED_BAR_AND_BID_ASK",
                 "Missing or invalid entry-time market evidence")
        identity = (p["style"], str(p.get("position_id")))
        _require(identity not in seen and identity[1] not in ("None", ""),
                 "Duplicated or missing native position identity")
        seen.add(identity)
        pnl = float(p["net_usd"])
        lots = float(p["entry_lots"])
        _require(math.isfinite(pnl) and math.isfinite(lots) and lots > 0,
                 "Nonfinite P/L or invalid exposure in baseline")
        if p["style"] == 3:
            selected.append(p)
    totals = report.get("cohorts", {}).get("style", {}).get("3")
    _require(isinstance(totals, dict) and len(selected) == totals["positions"]
             and abs(sum(float(r["net_usd"]) for r in selected)
                     - float(totals["native_net_usd"])) < 0.025
             and abs(sum(float(r["entry_lots"]) for r in selected)
                     - float(totals["entry_lots"])) < 0.00001,
             "Native Sweep/Reclaim ledger cannot be reconciled")
    return period[0] + ".." + period[1], selected


def _kept(candidate: str, p: dict) -> bool:
    if candidate == "BASELINE":
        return True
    if candidate == "SHADOW_ATR_LOW":
        return p["atr_band"] == "AT_OR_BELOW_TRAILING_MEDIAN"
    if candidate == "SHADOW_NO_BUY_HIGH_ATR":
        return not (p["side"] == "BUY"
                    and p["atr_band"] == "ABOVE_TRAILING_MEDIAN")
    raise ValueError("Unknown research candidate")


def _stats(rows: list[dict]) -> dict:
    pnl = sum(float(p["net_usd"]) for p in rows)
    lots = sum(float(p["entry_lots"]) for p in rows)
    win = sum(float(p["net_usd"]) > 0 for p in rows)
    return {
        "positions": len(rows),
        "wins": win,
        "win_rate": round(win / len(rows), 4) if rows else None,
        "native_net_usd": round(pnl, 2),
        "entry_lots": round(lots, 5),
        "hypothetical_after_extra_costs_usd": {
            str(int(k)): round(pnl - k * lots, 2) for k in COST_PER_LOT
        },
    }


def review(contexts: list[dict]) -> dict:
    _require(contexts, "No market-context evidence supplied")
    periods = {}
    versions = set()
    date_ranges = []
    for report in contexts:
        key, trades = _valid_context(report)
        _require(key not in periods, "Duplicate/conflicting historical period")
        start, end = [datetime.strptime(x, "%Y.%m.%d")
                      for x in report["test_period"]]
        _require(all(start >= e or end <= s for s, e in date_ranges),
                 "Overlapping historical periods must not double-count trades")
        date_ranges.append((start, end))
        versions.add((report["source_compiled_ex5_sha256"],
                      report["source_manifest_sha256"]))
        periods[key] = trades
    _require(len(versions) == 1, "EA build/source mismatch between historical runs")
    output = {}
    for period, rows in sorted(periods.items()):
        baseline = _stats(rows)
        variants = {}
        for name in STRATEGIES:
            kept = [p for p in rows if _kept(name, p)]
            dropped = [p for p in rows if not _kept(name, p)]
            stats = _stats(kept)
            stats["excluded_positions"] = len(dropped)
            stats["excluded_native_profit_usd"] = round(
                sum(float(p["net_usd"]) for p in dropped), 2)
            stats["delta_native_usd_vs_baseline"] = round(
                stats["native_net_usd"] - baseline["native_net_usd"], 2)
            stats["monthly_native_net_usd"] = {
                month: round(sum(float(p["net_usd"]) for p in kept
                                 if p["month_utc"] == month), 2)
                for month in sorted({p["month_utc"] for p in rows})
            }
            variants[name] = stats
        output[period] = variants
    comparisons = {}
    for name in STRATEGIES[1:]:
        deltas = [v[name]["delta_native_usd_vs_baseline"]
                  for v in output.values()]
        after20 = [v[name]["hypothetical_after_extra_costs_usd"]["20"]
                   for v in output.values()]
        comparisons[name] = {
            "positive_delta_in_every_examined_period": all(v > 0 for v in deltas),
            "positive_absolute_net_after_20usd_per_lot_in_every_period":
                all(v > 0 for v in after20),
            "historical_deltas_usd": deltas,
            "historical_after_20usd_per_lot_usd": after20,
            "approval": "NOT_APPROVED_POST_HOC",
        }
    return {
        "schema": SCHEMA,
        "status": "POST_HOC_REVIEW_NO_LIVE_PROMOTION",
        "periods": list(output),
        "studied_period_count": len(output),
        "independent_out_of_sample_periods": 0,
        "native_baseline_symbol": "XAUUSD@",
        "style": 3,
        "ea_source_provenance_equal": True,
        "cohorts": output,
        "comparisons": comparisons,
        "counterfactual_warning": (
            "Shadow sums use only observed BASELINE entry/exit fills. "
            "Skipped trades were not re-simulated; overlapping positions, "
            "risk allocation, order sequencing and later fills may change. "
            "Profit deltas are hypothetical retained-position arithmetic."
        ),
        "data_snooping_warning": (
            "Both filters were proposed AFTER looking at these dates; "
            "neither historical period independently validates either filter."
        ),
        "cost_warning": (
            "Costs 10 and 20 are hypothetical EXTRA USD per standard lot. "
            "MT5 fill slippage is already included; do not double-count it."
        ),
        "shadow_signals_sending_orders": False,
        "shadow_filters_change_ea": False,
        "can_autotune_or_promote": False,
        "connected_orders_authorized": False,
        "validated_edge": False,
        "live": "LOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-dir", type=Path, required=True)
    args = parser.parse_args()
    dest = args.context_dir.resolve()
    try:
        paths = sorted(dest.glob("QTS_CONTEXT_*.json"))
        # Only exact context schema files are eligible, not prior shadow output.
        reports = [json.loads(p.read_text(encoding="utf-8"))
                   for p in paths if p.name != "QTS_CONTEXT_AUTO_SUMMARY.json"]
        answer = review(reports)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        answer = {"schema": SCHEMA, "status": "EVIDENCE_GAPS_NO_GO",
                  "error": str(exc)[:240], "live": "LOCKED",
                  "validated_edge": False, "can_autotune_or_promote": False,
                  "connected_orders_authorized": False}
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "QTS_SHADOW_FILTER_REVIEW.json").write_text(
            json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print("SHADOW NO-GO: cannot save review: " + str(exc)[:160])
        return 2
    print("QTS SHADOW REVIEW: " + answer["status"] + " | LIVE LOCKED")
    for period, variants in answer.get("cohorts", {}).items():
        print(period + ": " + str({k: v["native_net_usd"]
                                  for k, v in variants.items()}))
    return 0 if answer["status"] == "POST_HOC_REVIEW_NO_LIVE_PROMOTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
