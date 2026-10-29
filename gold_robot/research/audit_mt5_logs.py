"""Read-only parser for QTS MT5 tester-agent logs; not an MT5 HTML report."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path

START = re.compile(r"testing of Experts\\QTS_Gold_Robot\.ex5 from ([\d.]+ \d\d:\d\d) to ([\d.]+ \d\d:\d\d) started with inputs:")
STYLE = re.compile(r"\bEntryStyle=(\d+)\b")
DEAL = re.compile(
    r"\bQTS broker deal: deal=(\d+) entry=(\d+) volume=([\d.]+) "
    r"price=([\d.]+) gross=([-\d.]+) commission=([-\d.]+) "
    r"swap=([-\d.]+) fee=([-\d.]+) net=([-\d.]+)"
)
BALANCE = re.compile(r"final balance\s+([-\d.]+) USD")
REASON = re.compile(r"QTS ENTRY AUDIT.*reason=(.*)")
INPUT = re.compile(r"\bTester\s+([A-Za-z_]\w*)=([^\s]+)\s*$")
FILENAME_STYLE = re.compile(r"^QTS_([0-3])\.htm(?:\.log)?$", re.IGNORECASE)

def read_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > 100_000_000:
        raise ValueError("Refusing log larger than 100 MB")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")

def audit_file(path: Path, fee_per_lot: float) -> list[dict]:
    contents = read_text(path)
    if re.search(r"(?i)<!doctype\s+html|<html\b", contents[:1000]):
        return []
    lines = contents.splitlines()
    starts = [(i, match) for i, line in enumerate(lines)
              if (match := START.search(line))]
    sessions = []
    for number, (start, match) in enumerate(starts, 1):
        stop = starts[number][0] if number < len(starts) else len(lines)
        segment = lines[start:stop]
        params = {m.group(1): m.group(2) for line in segment[:100]
                  if (m := INPUT.search(line))}
        styles = [int(m.group(1)) for line in segment[:100]
                  if (m := STYLE.search(line))]
        style = styles[0] if len(set(styles)) == 1 and styles else None
        balances = [float(m.group(1)) for line in segment
                    if (m := BALANCE.search(line))]
        stopped = any("stopped by user" in line for line in segment)
        finished = any("Test passed in " in line for line in segment)
        complete = finished and bool(balances) and not stopped and style is not None
        deals = []
        for line in segment:
            m = DEAL.search(line)
            if m:
                values = (int(m.group(1)), int(m.group(2)),
                          *[float(v) for v in m.groups()[2:]])
                deals.append(dict(zip(("id", "entry", "volume", "price", "gross",
                                       "commission", "swap", "fee", "net"), values)))
        exits = [d for d in deals if d["entry"] == 1]
        pnl = [d["net"] for d in exits]
        wins = sum(n > 0 for n in pnl)
        gains = sum(n for n in pnl if n > 0)
        losses = -sum(n for n in pnl if n < 0)
        volume = sum(d["volume"] for d in exits)
        actual_sum = sum(d["net"] for d in deals)
        reasons = Counter(m.group(1) for line in segment
                          if (m := REASON.search(line)))
        named = FILENAME_STYLE.match(path.name)
        name_matches = named is None or (style is not None and int(named.group(1)) == style)
        fingerprint = hashlib.sha256(
            json.dumps([style, params, match.group(1), match.group(2),
                        [(d["entry"], d["volume"], d["price"], d["net"])
                         for d in deals]], separators=(",", ":")).encode()
        ).hexdigest()
        sessions.append({
            "file": path.name, "session": number, "entry_style": style,
            "filename_style_matches": name_matches,
            "input_parameters": params,
            "period_start": match.group(1), "period_end": match.group(2),
            "state": "COMPLETE_LOG_ONLY" if complete else "INCOMPLETE_LOG_ONLY",
            "stopped_by_user": stopped, "final_balance": balances[-1] if complete else None,
            "eligible_for_comparison": complete and name_matches,
            "pending_accepted": sum("QTS DEMO LIMIT accepted order=" in line for line in segment),
            "entry_deals": sum(d["entry"] == 0 for d in deals),
            "closed_deals": len(exits), "wins": wins, "losses": sum(n < 0 for n in pnl),
            "deal_net_usd": round(actual_sum, 2),
            "reported_commission_usd": round(sum(d["commission"] for d in deals), 2),
            "reported_swap_usd": round(sum(d["swap"] for d in deals), 2),
            "reported_other_fee_usd": round(sum(d["fee"] for d in deals), 2),
            "closed_lots": round(volume, 4),
            "stressed_net_usd": round(actual_sum - fee_per_lot * volume, 2),
            "profit_factor_on_exit_deals": round(gains / losses, 4) if losses else None,
            "top_entry_rejections": reasons.most_common(6),
            "fingerprint": fingerprint,
            "duplicate_of": None,
        })
    return sessions

def audit(paths: list[Path], fee_per_lot: float = 10.0) -> dict:
    if fee_per_lot < 0 or fee_per_lot > 1000:
        raise ValueError("Cost scenario must be between 0 and 1000 USD per lot")
    sessions = []
    for path in paths:
        sessions.extend(audit_file(path, fee_per_lot))
    seen = {}
    for item in sessions:
        if item["state"] == "COMPLETE_LOG_ONLY":
            if item["fingerprint"] in seen:
                item["duplicate_of"] = seen[item["fingerprint"]]
            else:
                seen[item["fingerprint"]] = f'{item["file"]} session {item["session"]}'
    return {
        "release_status": "RESEARCH_ONLY_LIVE_LOCKED",
        "input_files": [p.name for p in paths],
        "cost_scenario_usd_per_round_turn_lot": fee_per_lot,
        "sessions": sessions,
        "complete_unique": sum(
            s["state"] == "COMPLETE_LOG_ONLY" and s["duplicate_of"] is None
            for s in sessions
        ),
        "edge_validated": False,
        "all_evidence_ready": False,
        "filename_mismatches": sum(not s["filename_style_matches"] for s in sessions),
        "warnings": [
            "Agent logs are not native MT5 HTML reports.",
            "Recorded zero commission does not prove zero broker commission.",
            "Cost stress is illustrative; no commission or slippage model is verified.",
            "Incomplete, duplicated, mislabeled and mismatched-period runs must never be ranked.",
        ],
    }

def render_html(report: dict) -> str:
    """Generate a local, escaped HTML report without network or browser scripts."""
    def cell(value: object) -> str:
        return "<td>" + html.escape(str(value), quote=True) + "</td>"

    labels = {0: "Former-stop LIMIT", 1: "Retest LIMIT",
              2: "Break and retest", 3: "Sweep and reclaim"}
    rows = []
    for item in report["sessions"]:
        state = item["state"]
        if not item["filename_style_matches"]:
            state += " / WRONG_FILENAME"
        if item["duplicate_of"]:
            state += " / DUPLICATE"
        reasons = "; ".join(f"{reason} ({count})"
                            for reason, count in item["top_entry_rejections"][:3])
        fields = [item["file"], item["session"], labels.get(item["entry_style"], "Unidentified"),
                  item["period_start"], item["period_end"], state, item["closed_deals"],
                  f'{item["wins"]}/{item["losses"]}', item["deal_net_usd"],
                  item["stressed_net_usd"], item["duplicate_of"] or "-", reasons]
        rows.append("<tr>" + "".join(cell(v) for v in fields) + "</tr>")
    body = "\n".join(rows) or '<tr><td colspan="12">No agent sessions detected. Native HTML reports belong in option 6.</td></tr>'
    total = len(report["sessions"])
    complete = report["complete_unique"]
    mismatches = report["filename_mismatches"]
    cost = html.escape(str(report["cost_scenario_usd_per_round_turn_lot"]), quote=True)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QTS Gold | Agent Log Review</title><style>
body{{font:14px/1.65 "Segoe UI",Arial,sans-serif;background:#f3f6fa;color:#172438;margin:0}}
main{{max-width:1200px;margin:auto;padding:20px}}header{{background:#163450;color:white;border-radius:12px;padding:25px}}
h1{{font-size:24px;margin:0}}header p{{color:#d9e7f6}}
section{{background:white;border-radius:12px;border:1px solid #dfe5ef;margin-top:16px;padding:18px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;min-width:1000px;font-size:12px}}
th,td{{padding:8px;text-align:left;border-bottom:1px solid #e3eaf1}}
th{{background:#eaf1f9}}.alert{{border-left:4px solid #bb7900;padding-left:12px}}
</style></head><body><main><header><h1>QTS Gold | Agent Log Review</h1>
<p>RESEARCH ONLY · LIVE LOCKED · EDGE UNVALIDATED</p></header>
<section><strong>{total} runs detected · {complete} completed unique · {mismatches} mislabeled files</strong>
<p>Assumed cost stress: {cost} USD per round-turn lot (not a measured broker charge).</p></section>
<section><h2>Individual test sessions</h2>
<table><thead><tr><th>File</th><th>Run</th><th>Style</th><th>Start</th><th>End</th>
<th>State</th><th>Deals</th><th>W/L</th><th>Logged USD</th>
<th>Stressed USD</th><th>Duplicate</th><th>Primary entry rejections</th>
</tr></thead><tbody>{body}</tbody></table></section>
<section class="alert"><h2>Interpretation</h2>
<p>Logs are not native MT5 HTML performance reports. Zero reported commission does not prove a zero-cost account.
Stressed P&amp;L is hypothetical. Do not rank incomplete, mislabeled or duplicate runs.
For native Strategy Tester results use START_HERE option 6 after saving the original HTML reports.</p>
<p>No strategy profitability or real-money trading permission has been verified.</p></section></main></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "reports_local" / "native")
    parser.add_argument("--round-turn-fee-per-lot", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--html-output", type=Path)
    parser.add_argument("--include-downloads", action="store_true")
    args = parser.parse_args()
    paths = args.paths or sorted(set(args.directory.glob("QTS_*.log")) | set(args.directory.glob("QTS_*.htm")))
    if args.include_downloads and not args.paths:
        downloads = Path.home() / "Downloads"
        paths = sorted(set(paths) | set(downloads.glob("QTS_*.log")) | set(downloads.glob("QTS_*.htm")))
    if not paths:
        parser.error("No QTS_*.log or QTS_*.htm files found; save MT5 agent logs in reports_local/native")
    output = audit(paths, args.round_turn_fee_per_lot)
    contents = json.dumps(output, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(contents, encoding="utf-8")
        print(f"Audit saved: {args.output}")
    else:
        print(contents, end="")
    if args.html_output:
        args.html_output.parent.mkdir(parents=True, exist_ok=True)
        args.html_output.write_text(render_html(output), encoding="utf-8")
        print(f"HTML report: {args.html_output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
