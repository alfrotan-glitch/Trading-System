"""Automatically review SAVED native MT5 Retest/Sweep evidence; no new backtests.

Finds already archived baseline 1/3 runs, verifies their immutable source
identity, and studies closed H1/M15 bars and pre-entry broker Bid/Ask. Existing
archives and EA are NEVER changed. Duplicate or incomplete evidence is NO-GO.
This script never sends orders, switches accounts, optimizes or enables live.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import defaultdict
from pathlib import Path

from retrospective_context import SYMBOL, evaluate, load_evidence

SCHEMA = "qts.mt5.auto_context_review.v1"
MAX_ARCHIVES = 40
# Shallow, allowlisted report layouts. No recursive scan of user documents.
PATTERNS = (
    "auto_runs/*/QTS_SHARE_RESULTS.zip",
    "auto_runs/*/QTS_HOLDOUT_REVIEW.zip",
    "holdout_*/QTS_HOLDOUT_REVIEW.zip",
    "holdout_*/QTS_SHARE_RESULTS.zip",
)


def candidates(root: Path) -> list[Path]:
    """Never expand arbitrary paths from an archive."""
    if not root.is_dir():
        raise ValueError("No local MT5 reports directory")
    paths = sorted({p.resolve() for pattern in PATTERNS
                    for p in root.glob(pattern) if p.is_file()})
    if len(paths) > MAX_ARCHIVES:
        raise ValueError(f"More than {MAX_ARCHIVES} saved archives: "
                         "review archive retention before running")
    return paths


def review(root: Path, output_dir: Path, mt5=None) -> dict:
    found = candidates(root)
    if not found:
        return {
            "schema": SCHEMA, "status": "NO_SAVED_BASELINE_ARCHIVES_NO_GO",
            "archives_discovered": 0, "studied_runs": 0,
            "live": "LOCKED", "validated_edge": False,
            "connected_orders_authorized": False, "runs": [], "skipped": [],
            "period_conflicts": [], "recommendation": "No automatic trading decision",
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    periods: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in found:
        display = path.parent.name + "/" + path.name
        try:
            forensic, manifest, source_sha = load_evidence(path)
        except (ValueError, KeyError, TypeError, OSError, UnicodeError,
                json.JSONDecodeError, zipfile.BadZipFile) as exc:
            skipped.append({"archive": display, "status": "UNUSABLE_OR_NON_BASELINE",
                            "reason": str(exc)[:240]})
            continue
        period = manifest["from_date"] + ".." + manifest["to_date"]
        # Duplicated identical ledger is one sample, never additional trades.
        if source_sha in seen:
            skipped.append({"archive": display, "status": "DUPLICATE_IDENTICAL_LEDGER",
                            "source_sha256": source_sha})
            continue
        seen.add(source_sha)
        evaluation = evaluate(forensic, manifest, source_sha, mt5)
        digest = hashlib.sha256((period + "|" + source_sha).encode("utf-8")).hexdigest()[:16]
        name = "QTS_CONTEXT_" + digest + ".json"
        details = output_dir / name
        details.write_text(json.dumps(evaluation, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
        periods[period].append((source_sha, display))
        totals = evaluation["cohorts"].get("style", {})
        runs.append({
            "archive": display,
            "period": period,
            "source_forensics_sha256": source_sha,
            "run_status": evaluation["status"],
            "review_file": name,
            "native_position_count": evaluation["total_positions"],
            "validated_position_count": evaluation["validated_positions"],
            "excluded_position_count": evaluation["quarantined_position_count"],
            "complete_market_snapshots": evaluation["complete_market_snapshots"],
            "native_profit_by_style_usd": {
                style: totals[style]["native_net_usd"] for style in sorted(totals)},
            "extra_10usd_per_lot_by_style_usd": {
                style: totals[style]["after_10usd_per_lot_extra_cost"]
                for style in sorted(totals)},
        })
    conflicts = [{
        "period": period,
        "distinct_forensic_ledgers": len(sources),
        "archives": [label for _, label in sources],
    } for period, sources in sorted(periods.items()) if len(sources) > 1]
    any_gaps = any(r["run_status"] != "DESCRIPTIVE_ONLY_REVIEW_REQUIRED"
                   for r in runs)
    status = (
        "NO_ELIGIBLE_ARCHIVE_NO_GO" if not runs else
        "CONFLICTING_PERIOD_EVIDENCE_NO_GO" if conflicts else
        "INCOMPLETE_OR_QUARANTINED_EVIDENCE_NO_GO" if any_gaps else
        "DESCRIPTIVE_COMPARISON_ONLY_NOT_VALIDATED"
    )
    return {
        "schema": SCHEMA,
        "status": status,
        "symbol": SYMBOL,
        "archives_discovered": len(found),
        "studied_runs": len(runs),
        "periods": sorted(periods),
        "period_conflicts": conflicts,
        "runs": runs,
        "skipped": skipped,
        "research_filters_applied_to_trading": False,
        "data_snooping_warning": (
            "These historical periods have already been examined; "
            "favorable subgroups are NOT independent out-of-sample evidence."
        ),
        "quote_source_warning": (
            "Historical terminal quotes may differ from native Strategy Tester quotes. "
            "Real broker fees, slippage and future demo performance unverified."
        ),
        "recommendation": (
            "Do not fit entry restrictions from these cohorts. "
            "Review gaps and require independent forward DEMO evidence."
        ),
        "can_autotune_or_promote": False,
        "connected_orders_authorized": False,
        "live": "LOCKED",
        "validated_edge": False,
    }


def _readonly_demo_terminal():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise ValueError("MetaTrader5 Python package unavailable") from exc
    if not mt5.initialize():
        raise ValueError("WMMarkets DEMO terminal is unavailable")
    account = mt5.account_info()
    symbol = mt5.symbol_info(SYMBOL)
    server = str(getattr(account, "server", "")).lower().replace(" ", "")
    demo = (getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None) is not None
            and account is not None
            and account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO)
    if "wmmarkets" not in server or symbol is None or not demo:
        mt5.shutdown()
        raise ValueError("Wrong broker, demo mode or symbol; refusing history review")
    return mt5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--offline", action="store_true",
                        help="Unit-test/research mode only; absent H1/ATR/quotes stays UNKNOWN")
    args = parser.parse_args()
    root = args.reports_root.resolve()
    output_dir = (args.output_dir.resolve() if args.output_dir else
                  root / "context_auto")
    # Do not start MT5 if no local research archives exist.
    files = candidates(root)
    mt5 = None
    if files and not args.offline:
        mt5 = _readonly_demo_terminal()
    try:
        result = review(root, output_dir, mt5)
    finally:
        if mt5 is not None:
            mt5.shutdown()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "QTS_CONTEXT_AUTO_SUMMARY.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    print("QTS HISTORICAL CONTEXT: " + result["status"])
    for row in result["runs"]:
        print(f"  {row['period']}: {row['native_position_count']} positions; "
              f"{row['excluded_position_count']} quarantined; "
              f"{row['run_status']}")
        print(f"    Native P/L (research only): {row['native_profit_by_style_usd']}")
    for row in result["period_conflicts"]:
        print("  CONFLICT: repeated period " + row["period"])
    for row in result["skipped"]:
        print("  SKIPPED: " + row["archive"] + " (" + row["status"] + ")")
    print("Full summary: " + str(path))
    print("LIVE LOCKED | PROFITABLE EDGE NOT VALIDATED")
    return 0 if result["status"] == "DESCRIPTIVE_COMPARISON_ONLY_NOT_VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
