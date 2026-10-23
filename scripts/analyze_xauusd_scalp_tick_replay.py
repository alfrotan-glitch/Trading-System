"""Audit an existing QTS scalp tick report, without rerunning 53M raw ticks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qts.research.scalp_performance_diagnostics import analyze_scalp_tick_report

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "data" / "raw" / "scalp_replay_reports"


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD tick scalp — diagnostic review",
        "",
        "**Exploratory discovery-only evidence; no validated trading edge. LIVE LOCKED.**",
        "",
        "## Complete strategy results",
        "",
        "| Metric | Confirmed | Anticipatory |",
        "|---|---:|---:|",
    ]
    normal = result["modes"]["confirmed"]["overall"]
    early = result["modes"]["anticipatory"]["overall"]
    for label, key in (
        ("Trades", "trades"),
        ("Estimated mean net bps", "mean_net_bps"),
        ("Win rate", "win_rate"),
        ("Average winning trade bps", "average_win_bps"),
        ("Average losing trade bps", "average_loss_bps"),
        ("Break-even win rate for observed payoffs", "break_even_win_rate_for_observed_payoffs"),
    ):
        lines.append(f"| {label} | {normal[key]} | {early[key]} |")
    for mode, label in (("confirmed", "Confirmed"), ("anticipatory", "Anticipatory")):
        data = result["modes"][mode]
        lines += ["", f"## {label}: frozen calendar thirds", ""]
        for third, row in data["fixed_calendar_thirds"].items():
            lines.append(f"- {third}: trades={row['trades']}, estimated mean net bps={row['mean_net_bps']}")
        lines += ["", f"## {label}: contributions by exit reason", ""]
        for reason, row in data["by_exit_reason"].items():
            lines.append(
                f"- {reason}: trades={row['trades']}; "
                f"mean estimated net bps={row['mean_net_bps']}; "
                f"sum trade bps (not portfolio return)={row['sum_trade_bps_not_portfolio_return']}"
            )
    matched = result["matched_utc_weeks"]
    lines += [
        "", "## UTC week-level stability (exploratory)", "",
        f"- Weeks with both methods: {matched['weeks_with_both_modes']}",
        f"- Weeks where anticipatory mean was higher: {matched['weeks_early_mean_exceeds_confirmed']}",
        f"- Weeks where anticipatory mean was lower: {matched['weeks_early_mean_below_confirmed']}",
        f"- Equal-weight mean difference in overlapping weeks: {matched['equal_weight_mean_of_weekly_differences_bps']} bps",
        "", "## Interpretation restrictions", "",
        *[f"- {text}" for text in result["limitations"]],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=REPORTS / "report.json")
    parser.add_argument("--json", type=Path, default=REPORTS / "diagnostics.json")
    parser.add_argument("--markdown", type=Path, default=REPORTS / "diagnostics.md")
    args = parser.parse_args(argv)
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = analyze_scalp_tick_report(data)
    for path, content in (
        (args.json, json.dumps(result, indent=2, sort_keys=True) + "\n"),
        (args.markdown, _markdown(result)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    compact = {
        "status": result["status"],
        "confirmed": result["modes"]["confirmed"]["overall"],
        "anticipatory": result["modes"]["anticipatory"]["overall"],
        "confirmed_by_exit_reason": result["modes"]["confirmed"]["by_exit_reason"],
        "anticipatory_by_exit_reason": result["modes"]["anticipatory"]["by_exit_reason"],
        "matched_utc_weeks": {k: v for k, v in result["matched_utc_weeks"].items() if k != "weekly_comparison"},
    }
    print(json.dumps(compact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
