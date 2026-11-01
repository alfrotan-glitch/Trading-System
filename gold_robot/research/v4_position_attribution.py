"""Independent MT5 V4 per-position strategy/regime attribution. NO order authority.

Input: BuildTradeForensics.ps1 JSON, originally reconstructed from native MT5
broker deals and the executed entry order's historical ORDER_COMMENT.
A style-7 router result is NOT a single strategy: attribute each broker
position to the chosen Style 0..6 or 8 and contemporaneous closed-bar
market regime 0..2. Missing/mutated tags => EVIDENCE_GAPS, NEVER guess.
This audit is exploratory and does NOT train, optimize or promote the EA.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

SCHEMA = "qts.mt5.v4.position_strategy_attribution.v1"
TAG = re.compile(r"QTSV4-S([0-6]|8)-R([0-2])", re.ASCII)
STRATEGIES = {
    0: "FORMER_STOP", 1: "RETEST", 2: "BREAK_ACCEPT_RETEST",
    3: "SWEEP_RECLAIM", 4: "TREND_IMPULSE", 5: "RANGE_REJECTION",
    6: "INSIDE_BREAKOUT", 8: "SMC_FVG_OB",
}
REGIMES = {0: "RANGE", 1: "TRANSITION", 2: "TREND"}
NATIVE_STATUS = {"SELECTED_IMPORTED_FOR_REVIEW", "IMPORTED_FOR_REVIEW"}
TRADING_STATUS = {"COMPLETE", "COMPLETE_MULTI_EXIT"}


def number(item: dict, field: str, *, positive: bool = False) -> float:
    value = item.get(field)
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field}: missing or non-numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field}: invalid numeric value") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{field}: nonfinite or nonpositive value")
    return result


def integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: boolean is not an integer")
    try:
        raw = int(str(value))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field}: invalid integer") from exc
    if str(raw) != str(value):
        raise ValueError(f"{field}: fractional or malformed integer")
    return raw


def read_tag(raw: object) -> tuple[int, int]:
    # Exact identity, not a substring: broker or another EA altering a
    # comment is evidence loss, not permission to infer a sub-strategy.
    if not isinstance(raw, str):
        raise ValueError("BROKER_ORDER_COMMENT_MISSING")
    match = TAG.fullmatch(raw)
    if match is None:
        raise ValueError("BROKER_ORDER_COMMENT_NOT_EXACT_V4_TAG")
    return int(match.group(1)), int(match.group(2))


def inspect_position(row: dict) -> dict:
    if not isinstance(row, dict):
        raise ValueError("Invalid broker position object")
    if integer(row.get("style"), "native style") != 7:
        raise ValueError("Only native Style 7 adaptive positions are admissible")
    position_id = str(row.get("position_id", ""))
    if not position_id or position_id in ("None", "0"):
        raise ValueError("Missing native broker position ID")
    if row.get("status") not in TRADING_STATUS:
        raise ValueError("INCOMPLETE_OR_REVERSED_NATIVE_POSITION")
    style, regime = read_tag(row.get("setup_reason"))
    if row.get("side") not in ("BUY", "SELL"):
        raise ValueError("Unknown executed broker side")
    entry = number(row, "entry_price", positive=True)
    stop = number(row, "initial_sl", positive=True)
    target = number(row, "initial_tp", positive=True)
    exit_price = number(row, "exit_price", positive=True)
    if row["side"] == "BUY" and not stop < entry < target:
        raise ValueError("INVALID_ORIGINAL_BUY_STOP_TARGET")
    if row["side"] == "SELL" and not target < entry < stop:
        raise ValueError("INVALID_ORIGINAL_SELL_STOP_TARGET")
    entry_lots = number(row, "entry_lots", positive=True)
    exit_lots = number(row, "exit_lots", positive=True)
    if abs(entry_lots - exit_lots) > max(1e-7, entry_lots * 1e-7):
        raise ValueError("ENTRY_EXIT_VOLUME_MISMATCH")
    if integer(row.get("deal_count"), "deal_count") < 2:
        raise ValueError("NATIVE_DEAL_LEGS_MISSING")
    legs = row.get("exit_legs")
    if not isinstance(legs, list) or not legs:
        raise ValueError("EXIT_LEGS_MISSING")
    if len(legs) > 1 and row["status"] != "COMPLETE_MULTI_EXIT":
        raise ValueError("MULTI_EXIT_EVIDENCE_MISLABELED")
    leg_volume = 0.0
    unique_deals: set[str] = set()
    for leg in legs:
        if not isinstance(leg, dict):
            raise ValueError("MALFORMED_EXIT_LEG")
        identifier = str(leg.get("deal_id", ""))
        if not identifier or identifier in unique_deals:
            raise ValueError("DUPLICATE_OR_MISSING_EXIT_DEAL_ID")
        unique_deals.add(identifier)
        leg_volume += number(leg, "lots", positive=True)
        number(leg, "price", positive=True)
        number(leg, "gross")
        number(leg, "charges")
    if abs(leg_volume - exit_lots) > max(1e-7, exit_lots * 1e-7):
        raise ValueError("EXIT_LEG_VOLUME_RECONCILIATION_FAILED")
    gross = number(row, "gross_usd")
    charges = number(row, "charges_usd")
    net = number(row, "net_usd")
    if abs(gross + charges - net) > 0.031:
        raise ValueError("NATIVE_NET_DOES_NOT_RECONCILE")
    held = number(row, "minutes_held")
    if held < 0:
        raise ValueError("NEGATIVE_BROKER_HOLD_TIME")
    initial_rr = (target - entry) / (entry - stop) if row["side"] == "BUY" else (
        entry - target) / (stop - entry)
    if initial_rr <= 0 or not math.isfinite(initial_rr):
        raise ValueError("INVALID_EX_ANTE_RR")
    return {
        "position_id": position_id,
        "selected_style": style, "strategy": STRATEGIES[style],
        "regime": REGIMES[regime], "regime_id": regime,
        "side": row["side"], "entry_price": entry,
        "initial_sl": stop, "initial_tp": target,
        "exit_price": exit_price, "lots": entry_lots,
        "broker_net_usd": net,
        "gross_usd": gross, "recorded_charges_usd": charges,
        "exit_reason": str(row.get("exit_reason", "UNKNOWN")),
        "duration_minutes": held,
        "price_rr_ex_ante": round(initial_rr, 4),
        "post_stop_tp_revisit": "UNKNOWN_REQUIRES_POST_EXIT_BID_ASK_TICKS",
        "mae_mfe": "UNKNOWN_REQUIRES_FULL_POSITION_BID_ASK_TICKS",
    }


def cohort(rows: list[dict], additional_usd_per_lot: float) -> dict:
    lots = sum(r["lots"] for r in rows)
    native = sum(r["broker_net_usd"] for r in rows)
    stressed = native - additional_usd_per_lot * lots
    wins = sum(r["broker_net_usd"] - additional_usd_per_lot*r["lots"] > 0 for r in rows)
    losses = sum(r["broker_net_usd"] - additional_usd_per_lot*r["lots"] < 0 for r in rows)
    return {
        "positions": len(rows),
        "entry_lots_sum": round(lots, 8),
        "broker_net_usd": round(native, 2),
        "native_recorded_charges_usd": round(sum(r["recorded_charges_usd"] for r in rows), 2),
        "additional_execution_stress_usd_per_lot": additional_usd_per_lot,
        "after_extra_stress_net_usd": round(stressed, 2),
        "mean_stressed_net_usd_per_position": round(stressed / len(rows), 4) if rows else None,
        "stressed_winning_positions": wins,
        "stressed_losing_positions": losses,
        "stressed_flat_positions": len(rows) - wins - losses,
        "native_stop_exits": sum(r["exit_reason"] == "DEAL_REASON_SL" for r in rows),
        "native_tp_exits": sum(r["exit_reason"] == "DEAL_REASON_TP" for r in rows),
    }


def audit(document: dict, *, extra_cost: float = 10.0) -> dict:
    """An exact, read-only result for ALL native adaptive positions; no cherry-picking."""
    if not isinstance(document, dict) or document.get("schema") != "qts.mt5.trade_forensics.v1":
        raise ValueError("Not a native QTS position-forensics JSON")
    if (document.get("live") != "LOCKED" or document.get("edge_validated") is not False or
        document.get("broker_fact_not_causal_proof") is not True):
        raise ValueError("Native forensics authority/safety fields invalid")
    if document.get("status") not in NATIVE_STATUS:
        raise ValueError("Native trade-forensics status is incomplete")
    selected = document.get("selected_styles")
    if selected != [7] or document.get("targeted") is not True:
        raise ValueError("Require a dedicated Style 7 native V4 tester run, not a multi-style sum")
    if not math.isfinite(extra_cost) or extra_cost < 0:
        raise ValueError("Extra execution-cost stress must be nonnegative and finite")
    positions = document.get("trades")
    if not isinstance(positions, list) or not positions:
        raise ValueError("Missing completed native broker positions")
    valid = []
    issues = []
    seen = set()
    for idx, row in enumerate(positions):
        position_id = row.get("position_id") if isinstance(row, dict) else None
        try:
            fact = inspect_position(row)
            if fact["position_id"] in seen:
                raise ValueError("DUPLICATE_NATIVE_POSITION")
            seen.add(fact["position_id"])
            valid.append(fact)
        except (TypeError, ValueError, KeyError) as exc:
            issues.append({"row_index": idx, "position_id": position_id,
                           "reason": str(exc)[:160]})
    # A missing original setup identity or partial exit invalidates *all*
    # per-strategy totals for promotion. Preserve audit facts but no release.
    groups = defaultdict(list)
    for fact in valid:
        groups[(fact["selected_style"], fact["regime"])].append(fact)
    by_strategy = {
        str(style): {"strategy": STRATEGIES[style],
                     **cohort([x for x in valid if x["selected_style"] == style], extra_cost)}
        for style in STRATEGIES
    }
    by_regime_strategy = [
        {"selected_style": style, "strategy": STRATEGIES[style], "regime": regime,
         **cohort(rows, extra_cost)}
        for (style, regime), rows in sorted(groups.items())
    ]
    return {
        "schema": SCHEMA,
        "status": "INCOMPLETE_STRATEGY_ATTRIBUTION_NO_GO" if issues else "ATTRIBUTED_FOR_RESEARCH_ONLY",
        "live": "LOCKED", "edge_validated": False,
        "connected_orders_authorized": False,
        "can_autotune_or_promote": False,
        "native_positions_seen": len(positions),
        "native_positions_attributed": len(valid),
        "issues": issues,
        "overall_attributed": cohort(valid, extra_cost),
        "by_strategy": by_strategy,
        "by_strategy_and_regime": by_regime_strategy,
        "positions": valid,
        "warnings": [
            "Selection tags are original broker ORDER_COMMENT, not a signed independent execution attestation.",
            "A mutated or missing broker order comment causes an identity gap. Never infer the style from outcome.",
            "All rows must be retained. A selected winner after seeing PnL is in-sample overfitting.",
            "The extra per-lot cost is hypothetical and native charges may exclude true WMMarkets friction.",
            "Stop-to-original-TP recovery and MAE/MFE require synchronized bid/ask ticks; never infer from bars.",
            "Native position-forensics JSON needs original matching MT5 HTML, deal CSV and source hashes for independent acceptance.",
            "Even fully attributed profitable historical research is NOT an independently validated positive edge.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--extra-cost-usd-per-lot", type=float, default=10.0)
    a = p.parse_args()
    data = json.loads(a.input.read_text(encoding="utf-8-sig"))
    result = audit(data, extra_cost=a.extra_cost_usd_per_lot)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"V4 STRATEGY ATTRIBUTION {result['status']}: "
          f"{result['native_positions_attributed']}/{result['native_positions_seen']} native positions")
    print(f"READ-ONLY REPORT {a.output}; LIVE LOCKED")
    return 0 if not result["issues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
