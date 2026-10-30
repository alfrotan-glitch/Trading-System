"""Independent native MT5 A/B read-only outcome comparison for QTS Gold V2.

Requires both variants on same untouched out-of-sample dates and real-tick
broker author reports. Never add style results into hypothetical portfolio PnL.
Positive backtests do NOT certify a deployable edge.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

STYLES = (1, 3, 7, 8)
REQUIRED_STATUS = "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED"


def load_run(root: Path, label: str) -> tuple[dict, dict[int, dict]]:
    outcome = json.loads((root / "OPEN_RESULTS.json").read_text(encoding="utf-8-sig"))
    if (outcome.get("state") != REQUIRED_STATUS or
        outcome.get("live") != "LOCKED" or outcome.get("validated_edge") is not False or
        outcome.get("research_variant") != label or
        outcome.get("selected_styles") != list(STYLES) or
        outcome.get("targeted") is not True or
        outcome.get("model") != 4 or outcome.get("symbol") != "XAUUSD@"):
        raise ValueError(f"Unverified native {label} result manifest")
    reports = list(root.glob("QTS_Gold_Comparison_*.json"))
    if len(reports) != 1:
        raise ValueError(f"Expected exactly one native comparison JSON: {label}")
    comparison = json.loads(reports[0].read_text(encoding="utf-8-sig"))
    parsed = {int(row["style"]): row for row in comparison["results"]
              if row.get("state") == "PARSED"}
    if (len(parsed) != len(STYLES) or set(parsed) != set(STYLES) or
        comparison.get("reports_parsed") != len(STYLES) or
        comparison.get("validated_edge") is not False):
        raise ValueError(f"Missing or wrongly identified native strategy reports: {label}")
    for style in STYLES:
        row = parsed[style]
        if (row.get("style_identity") != "STYLE_VERIFIED" or
            not row.get("sha256") or
            row.get("trades", 0) < 0 or
            row.get("profit_factor") is None or
            row.get("net_usd") is None or
            row.get("maximal_equity_drawdown") is None or
            not (root / "native" / f"QTS_{style}_trades.csv").is_file()):
            raise ValueError(f"Unverified broker facts style={style}, arm={label}")
    return outcome, parsed


def compare(baseline: Path, combined: Path) -> dict:
    a, old = load_run(baseline, "BASELINE")
    b, new = load_run(combined, "COMBINED")
    keys = ("from_date", "to_date", "deposit_usd", "timeframe", "model", "symbol")
    if any(a.get(key) != b.get(key) for key in keys):
        raise ValueError("A/B test inputs, dates or deposit do not match")
    if a.get("from_date") != "2026.10.01" or a.get("to_date") != "2026.10.30":
        raise ValueError("Out-of-sample October 2026 was not used")
    results = []
    for style in STYLES:
        left, right = old[style], new[style]
        results.append({
            "style": style,
            "baseline": {
                "trades": int(left["trades"]),
                "net_usd": float(left["net_usd"]),
                "profit_factor": float(left["profit_factor"]),
                "max_equity_drawdown_usd": float(left["maximal_equity_drawdown"]),
            },
            "combined": {
                "trades": int(right["trades"]),
                "net_usd": float(right["net_usd"]),
                "profit_factor": float(right["profit_factor"]),
                "max_equity_drawdown_usd": float(right["maximal_equity_drawdown"]),
            },
            "net_difference_usd": round(
                float(right["net_usd"]) - float(left["net_usd"]), 2
            ),
            "trade_count_difference": int(right["trades"]) - int(left["trades"]),
            "not_live_permission": True,
        })
    return {
        "schema": "qts.mt5.preregistered_v2_october_2026.v1",
        "state": "OOS_COMPARISON_RESEARCH_ONLY",
        "symbol": "XAUUSD@",
        "from_date": a["from_date"],
        "to_date": a["to_date"],
        "baseline_flags": ["TesterUseEntryQualityV2=false", "TesterProtectNearTPV2=false"],
        "combined_flags": ["TesterUseEntryQualityV2=true", "TesterProtectNearTPV2=true"],
        "strategy_reports": results,
        "individual_styles_are_not_an_executable_portfolio": True,
        "costs_independently_verified": False,
        "edge_validated": False,
        "live": "LOCKED",
        "limits": [
            "October 2026 is an untouched holdout for these rules only if no later tuning used it.",
            "The selected four styles were screened in sample; comparison is descriptive.",
            "Same-broker real-tick tester does not substitute for measured real execution costs.",
            "A single one-month holdout cannot validate persistent expectancy.",
            "Mirrored trades across styles must not be summed as an executable portfolio.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--combined", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    x = p.parse_args()
    result = compare(x.baseline, x.combined)
    x.output.parent.mkdir(parents=True, exist_ok=True)
    x.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("QTS V2 OUT-OF-SAMPLE RESULTS: RESEARCH ONLY / LIVE LOCKED")
    print("Style | Baseline trades/net/PF/DD | V2 trades/net/PF/DD | Delta net")
    for row in result["strategy_reports"]:
        left, right = row["baseline"], row["combined"]
        print(
            f"{row['style']:>5} | {left['trades']:>3} / {left['net_usd']:>8.2f} / "
            f"{left['profit_factor']:>4.2f} / {left['max_equity_drawdown_usd']:>7.2f} | "
            f"{right['trades']:>3} / {right['net_usd']:>8.2f} / "
            f"{right['profit_factor']:>4.2f} / {right['max_equity_drawdown_usd']:>7.2f} | "
            f"{row['net_difference_usd']:+.2f}"
        )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
