"""Independent, read-only QTS gold research evidence and capital readiness audit.

Important: this NEVER grants trade authority, even if research evidence clears
its numerical screens. It processes native, hash-matched MT5 HTML and broker
deal ledgers. All unverified or missing material remains an explicit blocker.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from ablate_revised_variants import verify_original_report
from paired_variant_diagnostics import load_positions, summary

SCHEMA = "qts.gold.capital_readiness.v1"
RESEARCH_START = date(2026, 11, 1)
STYLE = 7
STRESS_USD_PER_LOT = 10.0
MIN_COMPLETE_MONTHS = 6
MIN_CANDIDATE_TRADES = 200
REQUIRED_BASELINE = "BASELINE"
REQUIRED_CANDIDATE = "CONTEXT_V3"
EXPECTED_STATE = "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED"


class InvalidEvidence(ValueError):
    """Unsafe, conflicting or incomplete native test evidence."""


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)


def monthly_period(raw: dict, as_of: date) -> tuple[date, date]:
    try:
        a = datetime.strptime(raw["from_date"], "%Y.%m.%d").date()
        b = datetime.strptime(raw["to_date"], "%Y.%m.%d").date()
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidEvidence("Invalid report dates") from exc
    if a < RESEARCH_START or a.day != 1 or b != next_month(a):
        raise InvalidEvidence("Only prospectively preregistered complete calendar months qualify")
    # A month is not finished until the next month's first day.
    if b > as_of:
        raise InvalidEvidence("Incomplete or future test period")
    return a, b


def finite(raw: object, field: str) -> float:
    if isinstance(raw, bool):
        raise InvalidEvidence(f"Invalid numeric field {field}")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidEvidence(f"Invalid numeric field {field}") from exc
    if not math.isfinite(value):
        raise InvalidEvidence(f"Nonfinite numeric field {field}")
    return value


def load_native(root: Path, expected_variant: str, as_of: date) -> dict:
    """Require independently retained MT5 HTML, hash, deal rows and manifest."""
    try:
        manifest = json.loads((root / "OPEN_RESULTS.json").read_text("utf-8-sig"))
        report_paths = list(root.glob("QTS_Gold_Comparison_*.json"))
        if len(report_paths) != 1:
            raise InvalidEvidence("Exactly one native comparison JSON is required")
        comparison = json.loads(report_paths[0].read_text("utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise InvalidEvidence("Missing or invalid original research manifest") from exc
    if not isinstance(manifest, dict) or not isinstance(comparison, dict):
        raise InvalidEvidence("Native research summaries must be JSON objects")
    if (manifest.get("schema") != "qts.mt5.auto_tester.v1" or
        manifest.get("state") != EXPECTED_STATE or
        manifest.get("live") != "LOCKED" or
        manifest.get("validated_edge") is not False or
        manifest.get("real_money_orders") is not False or
        manifest.get("targeted") is not True or
        manifest.get("selected_styles") != [STYLE] or
        manifest.get("research_variant") != expected_variant or
        manifest.get("symbol") != "XAUUSD@" or
        manifest.get("model") != 4 or
        manifest.get("timeframe") != "M15"):
        raise InvalidEvidence(f"Native run identity or safety gate failed: {expected_variant}")
    if (comparison.get("validated_edge") is not False or
        comparison.get("live") != "LOCKED" or
        comparison.get("reports_parsed") != 1 or
        comparison.get("all_styles_identified") is not True):
        # Native parser labels selected 1/10 report runs; some versions
        # mark all_styles_identified False for valid selected runs.
        if (comparison.get("validated_edge") is not False or
            comparison.get("live") != "LOCKED" or
            comparison.get("reports_parsed") != 1):
            raise InvalidEvidence("Native comparison incomplete or unsafe")
    rows = comparison.get("results")
    if not isinstance(rows, list):
        raise InvalidEvidence("Native style result rows missing")
    identified = [r for r in rows if isinstance(r, dict) and r.get("style") == STYLE]
    if (len(identified) != 1 or identified[0].get("state") != "PARSED" or
        identified[0].get("style_identity") != "STYLE_VERIFIED"):
        raise InvalidEvidence("Exactly one style-7 native report must be verified")
    row = identified[0]
    for name in ("net_usd", "trades", "profit_factor", "maximal_equity_drawdown"):
        finite(row.get(name), name)
    if finite(row["trades"], "trades") != int(finite(row["trades"], "trades")):
        raise InvalidEvidence("Noninteger broker position count")
    a, b = monthly_period(manifest, as_of)
    source_digest = manifest.get("source_manifest_sha256")
    if not (isinstance(source_digest, str) and len(source_digest) == 64 and
            all(ch in "0123456789abcdef" for ch in source_digest.lower())):
        raise InvalidEvidence("Run source package SHA256 fingerprint missing or malformed")
    try:
        verify_original_report(root, STYLE, row)
        positions = load_positions(root / "native" / f"QTS_{STYLE}_trades.csv")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise InvalidEvidence("Native HTML or broker deal ledger verification failed: " + str(exc)) from exc
    totals = summary(positions)
    if (totals["positions"] != int(row["trades"]) or
        abs(totals["recorded_net_usd"] - finite(row["net_usd"], "net")) > 0.02):
        raise InvalidEvidence("Native broker deals conflict with MT5 HTML report")
    for position in positions:
        if (position["open"]["type"] not in ("DEAL_TYPE_BUY", "DEAL_TYPE_SELL") or
            position["close"]["type"] not in ("DEAL_TYPE_BUY", "DEAL_TYPE_SELL") or
            finite(position["open"]["sl"], "SL") <= 0 or
            finite(position["open"]["tp"], "TP") <= 0):
            raise InvalidEvidence("Trade side or protective SL/TP missing from native entry")
    return {
        "from_date": a.isoformat(),
        "to_date": b.isoformat(),
        "source_manifest_sha256": source_digest.lower(),
        "symbol": manifest["symbol"],
        "model": manifest["model"],
        "timeframe": manifest["timeframe"],
        "deposit_usd": finite(manifest.get("deposit_usd"), "deposit"),
        "positions": totals["positions"],
        "net_usd": totals["recorded_net_usd"],
        "stressed_net_usd": totals["extra_cost_10_usd_per_lot_net_usd"],
        "lots": totals["entry_lots_sum"],
        "max_equity_drawdown_usd": finite(row["maximal_equity_drawdown"], "drawdown"),
    }


def audit(pairs: list[tuple[Path, Path]], *, as_of: date) -> dict:
    """Defensive acceptance diagnostic; positive research never unlocks LIVE."""
    problems = []
    month_results = []
    used_periods = set()
    expected_next = RESEARCH_START
    baseline_sums = candidate_sums = 0.0
    candidate_trades = 0
    candidate_drawdown_peak = 0.0
    all_same_source = None

    for baseline, candidate in pairs:
        try:
            a = load_native(baseline, REQUIRED_BASELINE, as_of)
            b = load_native(candidate, REQUIRED_CANDIDATE, as_of)
            keys = ("from_date", "to_date", "deposit_usd", "symbol", "model",
                    "timeframe", "source_manifest_sha256")
            if any(a[key] != b[key] for key in keys):
                raise InvalidEvidence("Baseline and V3 source/settings/period mismatch")
            period = a["from_date"]
            if period in used_periods:
                raise InvalidEvidence("Duplicate research month")
            used_periods.add(period)
            if all_same_source is None:
                all_same_source = a["source_manifest_sha256"]
            elif all_same_source != a["source_manifest_sha256"]:
                raise InvalidEvidence("Code changed between monthly evaluation windows")
            month_results.append({
                "month": period, "baseline": a, "v3": b,
                "stressed_month_delta_usd": round(b["stressed_net_usd"] - a["stressed_net_usd"], 2),
            })
        except (InvalidEvidence, OSError, TypeError, ValueError) as exc:
            problems.append({"baseline": str(baseline), "v3": str(candidate),
                             "reason": str(exc)[:220]})
    month_results.sort(key=lambda r: r["month"])
    for record in month_results:
        month_start = date.fromisoformat(record["month"])
        if month_start != expected_next:
            problems.append({"reason": f"Missing/unsorted prospective research months before {month_start}"})
            expected_next = month_start
        expected_next = next_month(expected_next)
        a, b = record["baseline"], record["v3"]
        baseline_sums += a["stressed_net_usd"]
        candidate_sums += b["stressed_net_usd"]
        candidate_trades += b["positions"]
        candidate_drawdown_peak = max(candidate_drawdown_peak, b["max_equity_drawdown_usd"])
    blockers = [
        "REAL_MONEY_ORDER_AUTHORIZATION_NOT_AVAILABLE",
        "INDEPENDENT_NATIVE_WINDOWS_METAEDITOR_COMPILE_NOT_QUALIFIED",
        "BROKER_EXECUTION_COSTS_AND_SLIPPAGE_NOT_INDEPENDENTLY_MEASURED",
        "CONNECTED_DEMO_FORWARD_RELIABILITY_NOT_QUALIFIED",
        "INDEPENDENT_OUT_OF_SAMPLE_REVIEW_NOT_SIGNED",
    ]
    if problems:
        blockers.append("NATIVE_EVIDENCE_INVALID_OR_INCOMPLETE")
    if len(month_results) < MIN_COMPLETE_MONTHS:
        blockers.append("INSUFFICIENT_COMPLETED_PROSPECTIVE_MONTHS")
    if candidate_trades < MIN_CANDIDATE_TRADES:
        blockers.append("INSUFFICIENT_INDEPENDENT_NATIVE_POSITION_SAMPLE")
    if not month_results or candidate_sums <= 0:
        blockers.append("NO_POSITIVE_AFTER_COST_STRESS_CANDIDATE_EXPECTANCY")
    if month_results and candidate_sums <= baseline_sums:
        blockers.append("V3_NOT_BETTER_THAN_MATCHED_BASELINE_AFTER_STRESS")
    if month_results and (candidate_drawdown_peak > 0.10 * month_results[-1]["v3"]["deposit_usd"]):
        blockers.append("NATIVE_EQUITY_DRAWDOWN_EXCEEDS_RESEARCH_TOLERANCE")
    # The point of this gate is NEVER a machine-generated release token.
    return {
        "schema": SCHEMA,
        "as_of": as_of.isoformat(),
        "capital_decision": "DO_NOT_ENTRUST_REAL_CAPITAL",
        "live": "LOCKED",
        "edge_validated": False,
        "can_send_orders": False,
        "no_automated_live_promotion": True,
        "research_only": True,
        "months_verified": len(month_results),
        "native_v3_positions": candidate_trades,
        "v3_net_after_additional_10_usd_per_lot_stress": round(candidate_sums, 2),
        "baseline_net_after_same_stress": round(baseline_sums, 2),
        "v3_minus_baseline_stressed_net": round(candidate_sums - baseline_sums, 2),
        "maximum_reported_monthly_equity_drawdown_usd": round(candidate_drawdown_peak, 2),
        "native_evidence_issues": problems,
        "blockers": sorted(set(blockers)),
        "months": month_results,
        "notes": [
            "The baseline and V3 are alternative execution paths, not a merged portfolio.",
            "USD 10 per lot is an EXTRA stress assumption, not a measured WMMarkets broker fee.",
            "A successful hypothesis screen is NOT permission to deposit capital.",
            "The report cannot independently attest broker fills, compiler EX5 provenance or unmodified forward operation.",
            "No loss limit or backtest prevents gaps, abnormal slippage or full account loss.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", nargs=2, type=Path, action="append",
                        metavar=("BASELINE_FOLDER", "V3_FOLDER"), default=[])
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).date().isoformat(),
                        help="UTC YYYY-MM-DD for deterministic completed-month checks")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError as exc:
        parser.error("Invalid --as-of date: " + str(exc))
    result = audit(args.pair, as_of=as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"QTS CAPITAL DECISION: {result['capital_decision']}; "
          f"{len(result['blockers'])} blockers; {result['months_verified']} verified months")
    print(f"READ-ONLY REPORT: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
