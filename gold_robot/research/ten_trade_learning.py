"""QTS V4: causal 10-completed-trade reflection with SHADOW-ONLY repair proposals.

Consumes native broker-position attribution. Each closed trade is reviewed exactly
once within immutable, non-overlapping 10-position checkpoints ordered by broker
exit timestamps. Creates deterministic, unprivileged challenger hypotheses; it
does NOT edit an EA, adjust live risk, trade, fit weights to hindsight, or claim
an edge. Stop-rebound claims require complete, matched executable bid/ask quotes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from v4_post_stop_cohorts import validate_source

SCHEMA = "qts.mt5.ten_trade_reflection.v1"
BATCH = 10
EXTRA_USD_PER_LOT = 10.0
SHADOW_CRITERIA = {
    "minimum_full_separate_test_months": 6,
    "minimum_independently_observed_positions": 200,
    "requires_original_native_mt5_real_tick_reports": True,
    "requires_measured_broker_costs_and_capital_fit": True,
    "frozen_proposals_must_be_tested_only_on_future_unseen_windows": True,
}


def finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(name + ": boolean instead of amount")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + ": not numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(name + ": nonfinite value")
    return numeric


def validate_positions(attributed: dict) -> list[dict]:
    rows = validate_source(attributed)
    seen_deals: set[str] = set()
    for row in rows:
        for field in ("broker_net_usd", "recorded_charges_usd", "gross_usd",
                      "lots", "duration_minutes", "price_rr_ex_ante"):
            value = finite(row.get(field), field)
            if field in ("lots", "price_rr_ex_ante") and value <= 0:
                raise ValueError("invalid positive trade quantity: " + field)
            if field == "duration_minutes" and value < 0:
                raise ValueError("negative trade holding time")
        if abs((row["gross_usd"] + row["recorded_charges_usd"]) -
               row["broker_net_usd"]) > 0.031:
            raise ValueError("Native broker charges/profit do not reconcile")
        deals = row.get("broker_exit_deal_ids")
        if not isinstance(deals, list) or not deals:
            raise ValueError("Broker exit deal identity missing")
        if any(not isinstance(d, str) or not d or d in seen_deals for d in deals):
            raise ValueError("Duplicated/invalid broker exit deal identity")
        seen_deals.update(deals)
        if row.get("exit_reason") not in (
                "DEAL_REASON_SL", "DEAL_REASON_TP", "DEAL_REASON_EXPERT",
                "DEAL_REASON_CLIENT", "DEAL_REASON_SO", "DEAL_REASON_MOBILE",
                "DEAL_REASON_WEB", "DEAL_REASON_ROLLOVER", "DEAL_REASON_VMARGIN",
                "DEAL_REASON_SPLIT", "DEAL_REASON_CORPORATE_ACTION",
                "MIXED_EXIT_REASONS"):
            raise ValueError("Unknown broker exit cause, do not infer from PnL")
    return sorted(rows, key=lambda r: (r["exit_time_msc"], r["position_id"]))


def read_quote_evidence(post: dict | None, positions: list[dict]) -> dict:
    if post is None:
        return {}
    if not isinstance(post, dict) or post.get("schema") != "qts.mt5.v4.post_stop_strategy_cohorts.v1":
        raise ValueError("Stop-path evidence uses an unsupported schema")
    if (post.get("live") != "LOCKED" or post.get("edge_validated") is not False or
        post.get("automated_model_promotion") is not False or post.get("issues") != []):
        raise ValueError("Stop-path identity/permission/evidence mismatch")
    if post.get("status") not in (
        "TICKS_MISSING_NO_GO", "QUOTE_PATHS_ATTRIBUTED_RESEARCH_ONLY",
        "INCOMPLETE_TICK_COVERAGE_NO_GO", "NO_BROKER_STOPS_TO_REPLAY"):
        raise ValueError("Stop quote classification not accepted")
    stops = {str(row["position_id"]): row for row in positions
             if row["exit_reason"] == "DEAL_REASON_SL"}
    if post.get("native_attributed_positions") != len(positions) or post.get("native_stop_exits") != len(stops):
        raise ValueError("Post-stop native counts do not match broker position evidence")
    rows = post.get("stopped_positions")
    if not isinstance(rows, list):
        raise ValueError("Missing per-position quote audit")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed post-stop item")
        pid = str(row.get("broker_position_id", ""))
        src = stops.get(pid)
        if (src is None or pid in result or
            row.get("trade_id") != f"7:{pid}" or
            row.get("selected_style") != src["selected_style"] or
            row.get("regime") != src["regime"] or
            row.get("stop_exit_time_ms") != src["exit_time_msc"]):
            raise ValueError("Post-stop item refers to foreign/duplicate broker position")
        horizons = row.get("horizons")
        if not isinstance(horizons, dict) or "120" not in horizons:
            raise ValueError("Missing native 120-minute stop quote observation")
        result[pid] = horizons["120"]
    if result.keys() != stops.keys():
        raise ValueError("Some native stopped positions are missing from quote audit")
    # A pre-existing report marked UNKNOWN must never smuggle a TP-touch result.
    if post["status"] == "TICKS_MISSING_NO_GO":
        if any(w.get("quote_evidence") != "UNKNOWN" or
               w.get("original_tp_touched") is not None for w in result.values()):
            raise ValueError("Missing-quote report fabricated a stop rebound")
    return result


def lesson(row: dict, quote: dict | None, extra_cost: float) -> dict:
    native = row["broker_net_usd"]
    stress = native - extra_cost * row["lots"]
    cause = row["exit_reason"]
    flags = []
    if cause == "DEAL_REASON_SL":
        flags.append("BROKER_SL_EXIT_REVIEW_STOP_ROOM")
        if row["duration_minutes"] <= 5:
            flags.append("EARLY_STOP_REVIEW_ENTRY_TIMING_NOT_CAUSAL_PROOF")
    elif cause == "DEAL_REASON_TP":
        flags.append("BROKER_TP_EXIT_VERIFY_NET_AFTER_COST")
    elif cause == "DEAL_REASON_SO":
        flags.append("MARGIN_STOP_OUT_CRITICAL")
    else:
        flags.append("NON_STANDARD_EXIT_REQUIRES_BROKER_CONTEXT")
    if native > 0 and stress <= 0:
        flags.append("PROFIT_SWALLOWED_BY_ADDITIONAL_EXECUTION_STRESS")
    if row["recorded_charges_usd"] < 0 and row["gross_usd"] > 0 and (
            -row["recorded_charges_usd"] / row["gross_usd"] >= 0.25):
        flags.append("NATIVE_COST_DRAG_AT_LEAST_25_PERCENT_OF_GROSS")
    if stress < 0:
        flags.append("STRESSED_NET_LOSS")
    tp_after_stop = None
    if cause == "DEAL_REASON_SL" and quote is not None:
        if quote.get("quote_evidence") == "COMPLETE":
            if type(quote.get("original_tp_touched")) is not bool:
                raise ValueError("Completed quote audit has invalid TP touch boolean")
            tp_after_stop = quote["original_tp_touched"]
            if tp_after_stop:
                flags.append("OBSERVED_ORIGINAL_TP_AFTER_ACTUAL_STOP_NOT_REALIZED_PROFIT")
            else:
                flags.append("OBSERVED_NO_ORIGINAL_TP_TOUCH_WITHIN_120_MIN")
        elif quote.get("quote_evidence") != "UNKNOWN" or quote.get("original_tp_touched") is not None:
            raise ValueError("Incomplete quote path cannot report target touch")
    if cause == "DEAL_REASON_SL" and tp_after_stop is None:
        flags.append("POST_STOP_TARGET_PATH_UNKNOWN")
    return {
        "broker_position_id": row["position_id"],
        "closed_at_ms": row["exit_time_msc"],
        "selected_strategy": row["selected_style"],
        "strategy": row["strategy"],
        "regime": row["regime"], "broker_exit_reason": cause,
        "recorded_broker_net_usd": round(native, 2),
        "after_additional_cost_stress_net_usd": round(stress, 4),
        "full_quote_post_stop_tp_touch": tp_after_stop,
        "diagnostic_flags": flags,
        "causal_conclusion": "UNKNOWN; DESCRIPTIVE EVIDENCE, NOT A PROVEN REASON FOR LOSS",
    }


def batch_summary(trades: list[dict], start: int, extra_cost: float) -> dict:
    stressed = [r["broker_net_usd"]-extra_cost*r["lots"] for r in trades]
    wins = sum(x > 0 for x in stressed)
    negatives = sum(x < 0 for x in stressed)
    peak = 0.0
    total = 0.0
    max_closed_drawdown = 0.0
    for x in stressed:
        total += x
        peak = max(peak, total)
        max_closed_drawdown = max(max_closed_drawdown, peak-total)
    return {
        "checkpoint": start // BATCH + 1,
        "start_trade": start + 1, "end_trade": start+BATCH,
        "first_exit_ms": trades[0]["exit_time_msc"],
        "last_exit_ms": trades[-1]["exit_time_msc"],
        "position_ids_in_exit_time_order": [r["position_id"] for r in trades],
        "native_net_usd": round(sum(r["broker_net_usd"] for r in trades), 2),
        "additional_cost_stress_usd_per_lot": extra_cost,
        "net_after_additional_stress_usd": round(sum(stressed), 2),
        "stressed_winners": wins, "stressed_losers": negatives,
        "stressed_flat": BATCH - wins - negatives,
        "native_stop_exits": sum(r["exit_reason"] == "DEAL_REASON_SL" for r in trades),
        "native_take_profit_exits": sum(r["exit_reason"] == "DEAL_REASON_TP" for r in trades),
        "maximum_closed_trade_realized_drawdown_usd": round(max_closed_drawdown, 2),
        "not_floating_equity_drawdown": True,
    }


def reflect(attributed: dict, post: dict | None = None, *,
            extra_cost: float = EXTRA_USD_PER_LOT) -> dict:
    if not math.isfinite(extra_cost) or extra_cost < 0:
        raise ValueError("Unbounded or negative extra execution cost")
    rows = validate_positions(attributed)
    quotes = read_quote_evidence(post, rows)
    reflections = [lesson(row, quotes.get(str(row["position_id"])), extra_cost) for row in rows]
    batches = []
    revisions = []
    repeated: dict[tuple[int, str], int] = defaultdict(int)
    previous_shadow: list[dict] = []
    shadow_forward_reviews: list[dict] = []
    for start in range(0, len(rows) - BATCH + 1, BATCH):
        ten = rows[start:start+BATCH]
        brief = batch_summary(ten, start, extra_cost)
        # A candidate frozen AFTER the PREVIOUS 10 trades is examined on the
        # NEXT complete batch only. No outcome from that next batch may have
        # influenced its original hypothesis or routing rule. This remains
        # OBSERVATIONAL: actual alternative routing was never executed.
        next_shadow_reviews = []
        for proposal in previous_shadow:
            if ten[0]["exit_time_msc"] <= proposal["frozen_after_ms"]:
                # Same-time exits cannot supply clean prospective evidence.
                next_shadow_reviews.append({
                    "candidate": proposal["candidate_repair"],
                    "origin_checkpoint": proposal["checkpoint"],
                    "style": proposal["style"], "regime": proposal["regime"],
                    "status": "UNSAFE_OVERLAPPING_BROKER_EXIT_TIMESTAMPS",
                    "never_promote": True,
                })
                continue
            future = [r for r in ten if
                      r["selected_style"] == proposal["style"] and
                      r["regime"] == proposal["regime"]]
            future_net = sum(r["broker_net_usd"]-extra_cost*r["lots"] for r in future)
            next_shadow_reviews.append({
                "candidate": proposal["candidate_repair"],
                "origin_checkpoint": proposal["checkpoint"],
                "evaluated_on_checkpoint": brief["checkpoint"],
                "style": proposal["style"], "regime": proposal["regime"],
                "origin_frozen_after_ms": proposal["frozen_after_ms"],
                "future_trade_count": len(future),
                "future_observed_stressed_net_usd": round(future_net, 2),
                "observed_exclusion_sensitivity_usd": round(-future_net, 2),
                "status": ("NO_FUTURE_OBSERVATIONS" if not future else
                           "OBSERVED_EXCLUSION_HURTS_NET" if future_net > 0 else
                           "OBSERVED_EXCLUSION_HELPS_NET" if future_net < 0 else
                           "OBSERVED_EXCLUSION_NEUTRAL"),
                "not_a_replayed_alternative_portfolio": True,
                "replacement_trade_path_unknown": True,
                "never_promote": True,
            })
        brief["prior_shadow_hypotheses_on_this_next_batch"] = next_shadow_reviews
        shadow_forward_reviews.extend(next_shadow_reviews)
        group = defaultdict(list)
        for row in ten:
            group[(row["selected_style"], row["regime"])].append(row)
        # A checkpoint finds research opportunities, NOT permission to update
        # the deployed router. Group sizes 1-2 cannot support even a proposal.
        proposals = []
        for (style, regime), sample in sorted(group.items()):
            n = len(sample)
            stressed = [r["broker_net_usd"]-extra_cost*r["lots"] for r in sample]
            count_loss = sum(x < 0 for x in stressed)
            stops = sum(r["exit_reason"] == "DEAL_REASON_SL" for r in sample)
            if n >= 3 and count_loss >= 2 and sum(stressed) < 0:
                repeated[(style, regime)] += 1
                proposals.append({
                    "style": style, "regime": regime,
                    "trade_count_in_batch": n,
                    "losses_after_stress": count_loss, "native_stops": stops,
                    "cohort_stressed_net_usd": round(sum(stressed), 2),
                    "repeat_batches_with_similar_concern": repeated[(style, regime)],
                    "candidate_repair": "SHADOW_ONLY_SKIP_STYLE_IN_SPECIFIC_REGIME",
                    "decision": ("PREREGISTER_UNSEEN_SHADOW_CHALLENGER" if
                                 repeated[(style, regime)] >= 2 else
                                 "OBSERVE_REPEAT_BEFORE_SHADOW_CHALLENGER"),
                    "not_evidence_of_counterfactual_profit": True,
                    "requires_new_independent_native_forward_data": True,
                    "do_not_disable_production_strategy": True,
                })
        brief["proposals"] = proposals
        if not proposals:
            brief["next_step"] = "NO_EX_ANTE_ROUTING_CHANGE; CONTINUE_COLLECTING_COMPLETE_EVIDENCE"
        else:
            brief["next_step"] = "KEEP_CURRENT_ROUTER_FROZEN; EVALUATE_PROPOSED_CHANGE_IN_SHADOW"
        batches.append(brief)
        revisions.extend({**p, "checkpoint": brief["checkpoint"]} for p in proposals)
        previous_shadow = [
            {**p, "checkpoint": brief["checkpoint"],
             "frozen_after_ms": brief["last_exit_ms"]}
            for p in proposals
        ]
    issues = []
    if any(row["exit_reason"] == "DEAL_REASON_SO" for row in rows):
        issues.append("BROKER_STOP_OUT_PRESENT; DO_NOT_AUTOMATICALLY_RESUME_EXECUTION")
    if any(f["full_quote_post_stop_tp_touch"] is None for f in reflections
           if f["broker_exit_reason"] == "DEAL_REASON_SL"):
        issues.append("SOME_POST_STOP_REPLAYS_LACK_COMPLETE_BID_ASK_TICKS")
    report = {
        "schema": SCHEMA,
        "status": "TEN_TRADE_CHECKPOINTS_READY_RESEARCH_ONLY" if batches else "WAITING_FOR_TEN_COMPLETE_TRADES",
        "live": "LOCKED", "edge_validated": False, "can_send_orders": False,
        "can_edit_ea": False, "can_self_promote_strategy": False,
        "auto_risk_increase": False,
        "native_completed_positions": len(rows),
        "complete_checkpoints": len(batches),
        "unreviewed_tail_positions": len(rows) % BATCH,
        "nonoverlapping_chronological_checkpoints": batches,
        "review_all_trades": reflections,
        "proposed_shadow_only_revisions": revisions,
        "next_checkpoint_observational_shadow_reviews": shadow_forward_reviews,
        "unresolved_evidence": issues,
        "independent_shadow_acceptance": SHADOW_CRITERIA,
        "research_limits": [
            "A 10-trade checkpoint cannot establish a statistically reliable trading edge.",
            "A cohort seen repeatedly in losing samples is a SHADOW hypothesis, not a deployed fix.",
            "No code, lot, stop, take profit, broker order or risk setting is automatically modified.",
            "The next-batch shadow exclusion sensitivity is NOT a real alternative portfolio.",
            "No implied profitability from retrospectively deleting losing historical trades.",
            "Post-SL TP touches are not realized profit; UNKNOWN quotes must not be filled in.",
            "The complete native source, tick quality, independent test period and broker fees are required.",
            "The groupwise net may be noisy and should not be optimized on the same 10-trade sample.",
        ],
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--attribution", required=True, type=Path)
    p.add_argument("--post-stop", type=Path, help="Optional matched native post-stop cohort report")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--extra-cost-usd-per-lot", type=float, default=EXTRA_USD_PER_LOT)
    a = p.parse_args()
    source = a.attribution.read_bytes()
    attributed = json.loads(source.decode("utf-8-sig"))
    quote = json.loads(a.post_stop.read_text(encoding="utf-8-sig")) if a.post_stop else None
    result = reflect(attributed, quote, extra_cost=a.extra_cost_usd_per_lot)
    result["read_only_native_attribution_sha256"] = hashlib.sha256(source).hexdigest()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"QTS TEN TRADE REFLECTION: {result['complete_checkpoints']} complete 10-trade reviews;"
          f" {result['unreviewed_tail_positions']} pending; LIVE LOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
