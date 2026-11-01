"""Read-only QTS stop-loss forensic integrity and independent-test gate.

Combines original MT5 broker-position attribution with later executable
Bid/Ask post-stop observations. Does not infer that a later target touch
was a possible winning trade. No broker API, order functions, or tuning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HORIZONS = ("5", "15", "30", "60", "120")
MIN_FUTURE_MONTHS = 6
MIN_FUTURE_POSITIONS = 200
ATTRIBUTION_FILE = "QTS_V4_POSITION_ATTRIBUTION.json"


def read_attribution(bundle: Path) -> tuple[dict, str]:
    with zipfile.ZipFile(bundle) as archive:
        matches = [entry for entry in archive.infolist()
                   if entry.filename == ATTRIBUTION_FILE]
        if len(matches) != 1 or matches[0].file_size > 5_000_000:
            raise ValueError("Missing, duplicated, or oversized original broker attribution")
        raw = archive.read(matches[0])
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def evaluate(attribution: dict, post: dict, pre: dict | None = None,
             *, attribution_sha256: str = "") -> dict:
    _require(attribution.get("status") == "ATTRIBUTED_FOR_RESEARCH_ONLY",
             "Unapproved or unverified broker attribution")
    _require(attribution.get("live") == "LOCKED" and
             attribution.get("edge_validated") is False and
             attribution.get("can_autotune_or_promote") is False,
             "Broker research safety contract missing")
    _require(post.get("status") == "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY" and
             post.get("same_source_as_native_tester_not_proven") is True,
             "Post-stop quote source contract missing")
    positions = attribution.get("positions")
    rows = post.get("individual_trade_windows")
    _require(isinstance(positions, list) and positions and
             isinstance(rows, list), "Missing original positions or post-stop windows")
    _require(len(positions) == attribution.get("native_positions_attributed"),
             "Incomplete broker position attribution")

    originals: dict[str, dict] = {}
    stops: dict[str, dict] = {}
    by_style: dict[str, dict] = {}
    months = set()
    for pos in positions:
        ident = str(pos["position_id"])
        _require(ident not in originals, "Duplicate original broker position")
        originals[ident] = pos
        _require(int(pos["entry_time_msc"]) < int(pos["exit_time_msc"]),
                 "Invalid original broker position time")
        months.add(datetime.fromtimestamp(int(pos["exit_time_msc"]) / 1000,
                                          timezone.utc).strftime("%Y-%m"))
        key = f"{pos['selected_style']}:{pos['regime']}"
        block = by_style.setdefault(key, {"positions": 0, "stops": 0,
                                          "broker_net_usd": 0.0,
                                          "post_tp_touch_120m": 0,
                                          "entry_reclaim_120m": 0})
        block["positions"] += 1
        block["broker_net_usd"] += float(pos["broker_net_usd"])
        if pos["exit_reason"] == "DEAL_REASON_SL":
            block["stops"] += 1
            stops[ident] = pos
    _require(len(stops) == post.get("stop_trades"), "Post-stop count differs from broker SL exits")
    _require(len(rows) == len(stops), "Post-stop row count differs from original SL exits")

    horizons = {h: {"complete": 0, "entry_reclaimed": 0, "original_tp_touched": 0}
                for h in HORIZONS}
    groups = Counter()
    observed = set()
    trades = []
    for row in rows:
        trade_id = str(row["trade_id"])
        _require(trade_id.startswith("7:"), "Unexpected broker stop identifier")
        ident = trade_id[2:]
        _require(ident in stops and ident not in observed,
                 "Unknown or duplicated original broker stop")
        observed.add(ident)
        orig = stops[ident]
        _require(row["side"] == orig["side"] and
                 int(row["stop_exit_time_ms"]) == int(orig["exit_time_msc"]) and
                 abs(float(row["original_entry_price"]) - float(orig["entry_price"])) < 1e-6 and
                 abs(float(row["original_sl_price"]) - float(orig["initial_sl"])) < 1e-6 and
                 abs(float(row["original_tp_price"]) - float(orig["initial_tp"])) < 1e-6,
                 "Stop exit, side, entry, SL or TP mismatch")
        previous_reclaim = False
        previous_target = False
        for h in HORIZONS:
            window = row["windows"][h]
            if window.get("complete") is True:
                horizons[h]["complete"] += 1
                reclaim = bool(window["reclaimed_entry"])
                target = window["first_target_touch_ms"] is not None
                if reclaim:
                    horizons[h]["entry_reclaimed"] += 1
                if target:
                    horizons[h]["original_tp_touched"] += 1
                    _require(reclaim, "TP touched without reclaiming original entry")
                    touch = int(window["first_target_touch_ms"])
                    exit_ms = int(orig["exit_time_msc"])
                    _require(exit_ms < touch <= exit_ms + int(h) * 60_000,
                             "TP touch chronology outside its reported horizon")
                _require(not previous_reclaim or reclaim,
                         "Entry reclaim disappears at a later complete horizon")
                _require(not previous_target or target,
                         "TP touch disappears at a later complete horizon")
                previous_reclaim, previous_target = reclaim, target
            else:
                _require(window.get("first_target_touch_ms") is None,
                         "Incomplete quote window claims a TP touch")
        final = row["windows"]["120"]
        category = ("UNKNOWN" if final.get("complete") is not True else
                    "LATER_TP_TOUCH" if final.get("first_target_touch_ms") is not None else
                    "ENTRY_RECLAIM_ONLY" if final.get("reclaimed_entry") else
                    "NO_ENTRY_RECLAIM")
        groups[category] += 1
        block = by_style[f"{orig['selected_style']}:{orig['regime']}"]
        if final.get("complete") is True:
            block["post_tp_touch_120m"] += category == "LATER_TP_TOUCH"
            block["entry_reclaim_120m"] += category in ("LATER_TP_TOUCH", "ENTRY_RECLAIM_ONLY")
        trades.append({
            "trade_id": trade_id,
            "selected_style": orig["selected_style"],
            "regime": orig["regime"],
            "exit_reason": "DEAL_REASON_SL",
            "broker_net_usd": orig["broker_net_usd"],
            "initial_RR_price": orig.get("price_rr_ex_ante"),
            "minutes_held": orig.get("duration_minutes"),
            "post_stop_category_120m": category,
            "post_stop_target_touch_is_profit": False,
            "pre_entry_signal_snapshot_available": False,
            "entry_cause_confirmed": False,
            "stop_too_tight_confirmed": False,
        })
    _require(len(observed) == len(stops), "Missing post-stop broker position")
    for h in HORIZONS:
        reported = post["horizons_minutes"][h]
        measured = horizons[h]
        _require(measured["complete"] ==
                 reported["eligible_stops_with_contiguous_executable_quotes"] and
                 measured["entry_reclaimed"] == reported["reclaimed_entry_count"] and
                 measured["original_tp_touched"] ==
                 reported["post_stop_original_target_touch_count"],
                 f"Aggregate post-stop evidence mismatch at {h} minutes")

    pre_quote_coverage = "NOT_SUPPLIED"
    if pre is not None:
        _require(pre.get("schema") == "qts.stop.failed_paths.v1" and
                 pre.get("original_stop_cases") == len(stops) and
                 pre.get("live") == "LOCKED",
                 "Entry-to-stop evidence is missing or belongs to another cohort")
        pre_quote_coverage = ("CAPTURED_WITH_UNRESOLVED_ENTRY_CAUSALITY"
                              if pre.get("before_stop_quotes_collected") else
                              "PRE_STOP_TICKS_NOT_COLLECTED")

    for block in by_style.values():
        block["broker_net_usd"] = round(block["broker_net_usd"], 2)
        block["stop_rate"] = round(block["stops"] / block["positions"], 5)
    # These months all come from the supplied historic native tester run.
    # A retrospective holdout from the same data is not an independent future test.
    review_ready = (len(months) >= MIN_FUTURE_MONTHS and
                    len(positions) >= MIN_FUTURE_POSITIONS)
    return {
        "schema": "qts.stop.entry_causality_gate.v1",
        "status": "SHADOW_RESEARCH_ONLY_NO_CAUSAL_PROOF",
        "live": "LOCKED",
        "edge_validated": False,
        "can_modify_ea": False,
        "can_autotune_or_promote": False,
        "original_broker_attribution_sha256": attribution_sha256,
        "native_positions": len(positions),
        "native_stops": len(stops),
        "native_exit_months": sorted(months),
        "observed_native_months_are_independent_future_holdout": False,
        "pre_stop_quote_status": pre_quote_coverage,
        "pre_entry_indicator_and_structure_snapshots": "NOT_IN_SUPPLIED_EVIDENCE",
        "post_stop_120m": dict(groups),
        "horizon_counts": horizons,
        "selected_style_and_regime": by_style,
        "trade_diagnostics": trades,
        "next_shadow_hypothesis": {
            "name": "TREND_IMPULSE_CAUSAL_ENTRY_AND_STOP_ROOM",
            "scope": "STYLE_4_TREND_ONLY",
            "status": "PREREGISTER_FOR_NEW_UNSEEN_NATIVE_TESTS",
            "questions": [
                "Was entry aligned with confirmed closed-bar trend, structure, and session?",
                "Was spread and broker slippage acceptable at entry and stop?",
                "Was initial SL behind a pre-entry invalidation level with ATR room?",
                "Would a frozen entry filter improve after-cost outcomes out of sample?",
            ],
            "execution_rule_change": "NONE",
            "stop_widening": "PROHIBITED_WITHOUT_NEW_TEST_EVIDENCE",
        },
        "independent_validation": {
            "minimum_new_separate_test_months": MIN_FUTURE_MONTHS,
            "minimum_independent_positions": MIN_FUTURE_POSITIONS,
            "current_run_meets_count_floors_only": review_ready,
            "approved": False,
            "missing": [
                "Pre-entry closed-bar indicators and broker spread at the actual decision time",
                "Actual pre-SL executable quote chronology and trade-level root-cause review",
                "A preregistered frozen challenger and separate unseen WMMarkets native tester runs",
                "Measured execution costs and independent shadow portfolio-path comparison",
                "Explicit owner approval and independent safety review",
            ],
        },
        "warnings": [
            "A quote touching the old TP after an executed SL is not a winning trade.",
            "The stop cohort is selected on losses; post-stop target frequency cannot establish an edge.",
            "Original native tester ticks and terminal history are not proven identical.",
            "No stop-level widening, router suppression, real orders, or live permissions are authorized.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--post", type=Path, required=True)
    parser.add_argument("--pre-summary", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    original, source_hash = read_attribution(args.bundle)
    post = json.loads(args.post.read_text(encoding="utf-8-sig"))
    pre = (json.loads(args.pre_summary.read_text(encoding="utf-8-sig"))
           if args.pre_summary else None)
    result = evaluate(original, post, pre, attribution_sha256=source_hash)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("STOP ENTRY CAUSALITY: SHADOW_RESEARCH_ONLY_NO_CAUSAL_PROOF")
    print("Original native positions:", result["native_positions"],
          "stops:", result["native_stops"],
          "quote-complete 120m:", result["horizon_counts"]["120"]["complete"])
    print("LIVE LOCKED; no strategy changes or orders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
