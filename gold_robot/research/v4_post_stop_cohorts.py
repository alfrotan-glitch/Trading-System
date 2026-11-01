"""Join native V4 strategy IDs to genuine post-stop executable quote paths.

Read-only, no broker connection, no tuning, no orders or live permission.
Unlike replay of pooled Style-7 trades, this attributes a stopped fill to
the EXACT entry-time strategy and closed-bar regime recorded by the broker.
Incomplete quote windows remain UNKNOWN, not failed or recovered targets.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

SCHEMA = "qts.mt5.v4.post_stop_strategy_cohorts.v1"
HORIZONS = ("5", "15", "30", "60", "120")
STRATEGY_IDS = (0, 1, 2, 3, 4, 5, 6, 8)
REGIMES = {"RANGE", "TRANSITION", "TREND"}
EPSILON_PRICE = 0.000011  # for original broker levels rounded to 5 decimal places


def validate_source(data: dict) -> list[dict]:
    if not isinstance(data, dict) or data.get("schema") != "qts.mt5.v4.position_strategy_attribution.v1":
        raise ValueError("Not the original V4 broker-strategy attribution report")
    if (data.get("status") != "ATTRIBUTED_FOR_RESEARCH_ONLY" or
        data.get("live") != "LOCKED" or
        data.get("edge_validated") is not False or
        data.get("can_autotune_or_promote") is not False or
        data.get("issues") != []):
        raise ValueError("V4 position identity is incomplete or order authority is inconsistent")
    rows = data.get("positions")
    if not isinstance(rows, list) or not rows:
        raise ValueError("No original broker positions to review")
    if data.get("native_positions_seen") != len(rows) or data.get("native_positions_attributed") != len(rows):
        raise ValueError("Broker position totals do not reconcile with V4 attribution")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed V4 broker position")
        pid = str(row.get("position_id", ""))
        if not pid or pid in seen:
            raise ValueError("Duplicated/missing V4 broker position")
        seen.add(pid)
        if row.get("selected_style") not in STRATEGY_IDS or row.get("regime") not in REGIMES:
            raise ValueError("Unknown ex-ante style or market regime")
        if row.get("side") not in ("BUY", "SELL"):
            raise ValueError("Unknown broker side")
        for name in ("entry_price", "initial_sl", "initial_tp", "exit_price"):
            val = row.get(name)
            if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val) or val <= 0:
                raise ValueError("Missing or invalid native broker price " + name)
        for name in ("entry_time_msc", "exit_time_msc"):
            if isinstance(row.get(name), bool) or not isinstance(row.get(name), int):
                raise ValueError("Invalid native broker event epoch")
        if row["entry_time_msc"] >= row["exit_time_msc"]:
            raise ValueError("Inverted native entry/exit times")
        if (row["side"] == "BUY" and not row["initial_sl"] < row["entry_price"] < row["initial_tp"]) or (
            row["side"] == "SELL" and not row["initial_tp"] < row["entry_price"] < row["initial_sl"]):
            raise ValueError("Invalid original stop/target geometry")
    return rows


def _close(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    try:
        af, bf = float(a), float(b)
    except (ValueError, TypeError, OverflowError):
        return False
    return math.isfinite(af) and math.isfinite(bf) and abs(af - bf) <= EPSILON_PRICE


def validate_replay(replay: dict, stopped: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    issues = []
    if not isinstance(replay, dict) or replay.get("status") != "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY":
        raise ValueError("Not an authentic QTS read-only stop-reversal report")
    rows = replay.get("individual_trade_windows")
    if not isinstance(rows, list) or replay.get("stop_trades") != len(rows):
        raise ValueError("Invalid native stop-replay trade count")
    expected = {f"7:{r['position_id']}": r for r in stopped}
    found: dict[str, dict] = {}
    for item in rows:
        if not isinstance(item, dict):
            issues.append({"reason": "MALFORMED_REPLAY_ROW"})
            continue
        ident = item.get("trade_id")
        if not isinstance(ident, str) or ident not in expected or ident in found:
            issues.append({"trade_id": str(ident), "reason": "UNKNOWN_OR_DUPLICATED_REPLAY_POSITION"})
            continue
        source = expected[ident]
        if (item.get("side") != source["side"] or
            item.get("stop_exit_time_ms") != source["exit_time_msc"] or
            not _close(item.get("original_entry_price"), source["entry_price"]) or
            not _close(item.get("original_sl_price"), source["initial_sl"]) or
            not _close(item.get("original_tp_price"), source["initial_tp"]) or
            not _close(item.get("stop_exit_price"), source["exit_price"])):
            issues.append({"trade_id": ident, "reason": "NATIVE_POSITION_PRICE_OR_TIME_MISMATCH"})
            continue
        found[ident] = item
    for ident in expected.keys() - found.keys():
        issues.append({"trade_id": ident, "reason": "MISSING_MATCHED_POST_STOP_QUOTE_REPLAY"})
    return found, issues


def summarize(attributed: dict, replay: dict | None = None) -> dict:
    source = validate_source(attributed)
    stopped = [r for r in source if r.get("exit_reason") == "DEAL_REASON_SL"]
    mixed = [r for r in source if r.get("exit_reason") == "MIXED_EXIT_REASONS"]
    issues = [
        {"position_id": r["position_id"], "reason": "MIXED_PARTIAL_STOP_EXITS_REQUIRE_LEG_LEVEL_REPLAY"}
        for r in mixed
    ]
    by_id, rows = {}, []
    if replay is not None:
        by_id, mismatches = validate_replay(replay, stopped)
        issues.extend(mismatches)
    cohorts: dict[tuple[int, str], dict] = {}
    for stop in stopped:
        key = (stop["selected_style"], stop["regime"])
        if key not in cohorts:
            cohorts[key] = {
                "strategy_id": key[0], "regime": key[1], "native_stops": 0,
                "horizons": {h: {"eligible_quote_complete": 0,
                                "incomplete_or_absent_quotes": 0,
                                "original_tp_touched": 0, "entry_reclaimed": 0}
                             for h in HORIZONS},
            }
        cohort = cohorts[key]
        cohort["native_stops"] += 1
        ident = f"7:{stop['position_id']}"
        native = by_id.get(ident)
        results = {"broker_position_id": stop["position_id"],
                   "trade_id": ident,
                   "selected_style": stop["selected_style"],
                   "regime": stop["regime"],
                   "stop_exit_time_ms": stop["exit_time_msc"],
                   "horizons": {}}
        for h in HORIZONS:
            q = None
            if native is not None and isinstance(native.get("windows"), dict):
                q = native["windows"].get(h)
            known = isinstance(q, dict) and q.get("complete") is True
            if known:
                tp_ms = q.get("first_target_touch_ms")
                ent_ms = q.get("first_entry_reclaim_ms")
                # Touch times must be AFTER the actual stopped exit and
                # inside the fixed 5/15/30/60/120 min observation horizon.
                end = stop["exit_time_msc"] + int(h) * 60_000
                if (tp_ms is not None and
                    (type(tp_ms) is not int or not stop["exit_time_msc"] < tp_ms <= end)):
                    issues.append({"trade_id": ident, "horizon": h,
                                   "reason": "IMPOSSIBLE_OR_NONCAUSAL_TP_TOUCH_TIME"})
                    known = False
                if (ent_ms is not None and
                    (type(ent_ms) is not int or not stop["exit_time_msc"] < ent_ms <= end)):
                    issues.append({"trade_id": ident, "horizon": h,
                                   "reason": "IMPOSSIBLE_OR_NONCAUSAL_ENTRY_RECLAIM_TIME"})
                    known = False
                if (tp_ms is not None and ent_ms is None) or (
                        tp_ms is not None and ent_ms is not None and tp_ms < ent_ms):
                    issues.append({"trade_id": ident, "horizon": h,
                                   "reason": "TARGET_TOUCH_WITHOUT_PRIOR_ENTRY_RECLAIM"})
                    known = False
                if known and q.get("reclaimed_entry") is not (ent_ms is not None):
                    issues.append({"trade_id": ident, "horizon": h,
                                   "reason": "QUOTE_RECLAIM_FLAG_CONTRADICTS_EVENT"})
                    known = False
            bucket = cohort["horizons"][h]
            if known:
                bucket["eligible_quote_complete"] += 1
                if tp_ms is not None:
                    bucket["original_tp_touched"] += 1
                if ent_ms is not None:
                    bucket["entry_reclaimed"] += 1
                results["horizons"][h] = {
                    "quote_evidence": "COMPLETE",
                    "original_tp_touched": tp_ms is not None,
                    "first_original_tp_touch_ms": tp_ms,
                    "entry_reclaimed": ent_ms is not None,
                    "first_entry_reclaim_ms": ent_ms,
                }
            else:
                bucket["incomplete_or_absent_quotes"] += 1
                results["horizons"][h] = {
                    "quote_evidence": "UNKNOWN", "original_tp_touched": None,
                    "first_original_tp_touch_ms": None, "entry_reclaimed": None,
                    "first_entry_reclaim_ms": None,
                }
        rows.append(results)
    by_strategy_regime = []
    for key in sorted(cohorts):
        c = cohorts[key]
        for h in HORIZONS:
            counts = c["horizons"][h]
            denominator = counts["eligible_quote_complete"]
            counts["original_tp_touch_fraction_among_complete_only"] = (
                round(counts["original_tp_touched"] / denominator, 5) if denominator else None
            )
            counts["quote_coverage_fraction_of_all_native_stops"] = (
                round(denominator / c["native_stops"], 5)
            )
        by_strategy_regime.append(c)
    if issues:
        status = "STOP_STRATEGY_EVIDENCE_MISMATCH_NO_GO"
    elif replay is None:
        status = "TICKS_MISSING_NO_GO" if stopped else "NO_BROKER_STOPS_TO_REPLAY"
    elif any(w["quote_evidence"] == "UNKNOWN" for row in rows for w in row["horizons"].values()):
        status = "INCOMPLETE_TICK_COVERAGE_NO_GO"
    else:
        status = "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY"
    return {
        "schema": SCHEMA, "status": status,
        "live": "LOCKED", "edge_validated": False, "real_orders_permitted": False,
        "automated_model_promotion": False,
        "native_attributed_positions": len(source),
        "native_stop_exits": len(stopped),
        "mixed_exit_cases_unresolved": len(mixed),
        "post_stop_quotes_were_supplied": replay is not None,
        "issues": issues,
        "by_strategy_and_regime": by_strategy_regime,
        "stopped_positions": rows,
        "limits": [
            "All counts and denominators refer ONLY to actual V4 broker SL exits.",
            "Unknown quote coverage is NOT a negative TP touch.",
            "A price reaching the original TP AFTER a stopped trade is NOT an executable winning trade.",
            "An M15 candle's high/low cannot replace chronological executable bid/ask quotes.",
            "Matched broker timestamps and prices do not independently prove tick origin or authenticity.",
            "These retrospective observations do not identify the causal reason for a losing signal.",
            "All training and live trading remain disabled; new hypotheses require untouched forward validation.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--attribution", type=Path, required=True)
    p.add_argument("--post-stop-replay", type=Path,
                   help="Actual stop_reversal_audit.py native executable-bid/ask quote output")
    p.add_argument("--allow-missing-ticks", action="store_true",
                   help="For automatic native runs: save explicit UNKNOWN report without inventing price history")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    attribution = json.loads(args.attribution.read_text(encoding="utf-8-sig"))
    replay = (json.loads(args.post_stop_replay.read_text(encoding="utf-8-sig"))
              if args.post_stop_replay else None)
    report = summarize(attribution, replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"V4 STOP COHORTS: {report['status']}; stops={report['native_stop_exits']}")
    print(f"READ ONLY: {args.output}; LIVE LOCKED")
    if (args.allow_missing_ticks and args.post_stop_replay is None and
            report["status"] == "TICKS_MISSING_NO_GO"):
        return 0  # diagnostic artifact only, NOT trade qualification
    return 0 if report["status"] in (
        "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY", "NO_BROKER_STOPS_TO_REPLAY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
