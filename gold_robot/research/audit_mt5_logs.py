"""Read-only parser for QTS MT5 tester-agent logs; not an MT5 HTML report."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
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
    if path.stat().st_size > 100_000_000:
        raise ValueError("Refusing log larger than 100 MB")
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if b"\x00" in data[:100]:
        return data.decode("utf-16-le")
    return data.decode("utf-8-sig", errors="replace")

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
<p>Assumed cost stress: {cost} USD per round-turn lot (not a measured broker charge).</p>
<p>Discovery: {html.escape(str(report.get("file_search", {}).get("status", "NOT_SCANNED")))}.
Native MT5 HTML reports found: {len(report.get("file_search", {}).get("native_html_reports_found", []))}.
If none were found, use MT5 to save a report or select an existing file.</p></section>
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



SEARCH_EXTENSIONS = {".log", ".htm", ".html", ".txt"}
MAX_SCAN_FILES = 3000
MAX_PREVIEW_BYTES = 512 * 1024


def user_search_directories(report_directory: Path, include_saved_folders: bool) -> list[Path]:
    """Only the report folder and a few user-facing export locations; never a disk-wide crawl."""
    folders = [report_directory]
    if include_saved_folders:
        roots = [Path.home()]
        for key in ("USERPROFILE", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            value = os.environ.get(key)
            if value:
                roots.append(Path(value))
        for root in roots:
            folders.extend(root / part for part in ("Downloads", "Desktop", "Documents"))
    unique: list[Path] = []
    seen: set[str] = set()
    for folder in folders:
        identity = str(folder.expanduser().resolve(strict=False)).casefold()
        if identity not in seen:
            seen.add(identity)
            unique.append(folder.expanduser())
    return unique


def file_preview(path: Path) -> str:
    """Bounded read; classify content before ingesting any non-QTS-named file."""
    with path.open("rb") as handle:
        data = handle.read(MAX_PREVIEW_BYTES)
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:100]:
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def discover_files(folders: list[Path]) -> dict:
    logs: list[Path] = []
    native_reports: list[Path] = []
    scanned = 0
    skipped_large = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            continue
        for path in entries:
            if scanned >= MAX_SCAN_FILES:
                break
            if path.suffix.lower() not in SEARCH_EXTENSIONS or not path.is_file():
                continue
            try:
                size = path.stat().st_size
                if size > 100_000_000:
                    skipped_large += 1
                    continue
                scanned += 1
                preview = file_preview(path)
                if START.search(preview):
                    logs.append(path)
                elif re.search(r"(?is)<!doctype\s+html|<html\b", preview[:2000]):
                    if re.search(r"(?i)QTS_Gold_Robot|MetaTrader\s*5|Total Net Profit", preview):
                        native_reports.append(path)
            except (OSError, UnicodeError):
                continue
    return {
        "log_paths": logs,
        "native_report_paths": native_reports,
        "folders": [str(folder) for folder in folders],
        "scanned": scanned,
        "skipped_large": skipped_large,
        "search_limited": scanned >= MAX_SCAN_FILES,
    }


def pick_saved_files() -> list[Path]:
    """Optional native file dialog. Cancellation never changes or creates any input."""
    if sys.platform != "win32":
        return []
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilenames(
                parent=root,
                title="Select saved MetaTrader 5 test logs or reports",
                filetypes=[("MT5 logs and reports", "*.log *.htm *.html *.txt"),
                           ("All files", "*.*")],
            )
        finally:
            root.destroy()
        return [Path(path) for path in selected]
    except Exception as exc:
        print(f"File selection dialog unavailable: {type(exc).__name__}", file=sys.stderr)
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "reports_local" / "native")
    parser.add_argument("--round-turn-fee-per-lot", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--html-output", type=Path)
    parser.add_argument("--include-downloads", action="store_true",
                        help="Search Downloads, Desktop and Documents (including OneDrive), by file contents")
    parser.add_argument("--pick-on-empty", action="store_true",
                        help="On Windows, offer a file picker when nothing is found")
    args = parser.parse_args()
    search = discover_files(user_search_directories(args.directory, args.include_downloads)) if not args.paths else {
        "log_paths": [], "native_report_paths": [], "folders": [], "scanned": 0,
        "skipped_large": 0, "search_limited": False,
    }
    paths = args.paths or search["log_paths"]
    if not paths and args.pick_on_empty:
        selected = pick_saved_files()
        for candidate in selected:
            try:
                preview = file_preview(candidate)
                if START.search(preview):
                    paths.append(candidate)
                elif re.search(r"(?is)<!doctype\s+html|<html\b", preview[:2000]):
                    if re.search(r"(?i)QTS_Gold_Robot|MetaTrader\s*5|Total Net Profit", preview):
                        search["native_report_paths"].append(candidate)
            except (OSError, UnicodeError):
                print(f"Cannot read selected file: {candidate.name}", file=sys.stderr)
    output = audit(paths, args.round_turn_fee_per_lot)
    output["file_search"] = {
        "folders_checked": search["folders"],
        "candidate_files_inspected": search["scanned"],
        "files_over_100mb_skipped": search["skipped_large"],
        "scan_limit_reached": search["search_limited"],
        "native_html_reports_found": [p.name for p in search["native_report_paths"]],
        "log_files_found": len(paths),
        "status": "LOGS_FOUND" if output["sessions"] else (
            "NATIVE_HTML_ONLY" if search["native_report_paths"] else "NO_AGENT_LOGS_FOUND"
        ),
    }
    if not output["sessions"]:
        print("No QTS agent log sessions were detected. This is not a failed trading test.")
        for folder in search["folders"]:
            print(f"  Looked in: {folder}")
        if search["native_report_paths"]:
            print("Native MT5 HTML report(s) were found; use START_HERE option 6 to compare those reports.")
        print("Save a tester log from MT5 or select the correct file using the Windows picker.")
    else:
        print(f"Detected {len(output['sessions'])} QTS tester session(s) in {len(paths)} file(s).")
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
