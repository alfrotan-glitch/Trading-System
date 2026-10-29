"""Read-only parser for QTS MT5 tester-agent logs; not an MT5 HTML report."""
from __future__ import annotations

import argparse
import hashlib
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

def read_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > 100_000_000:
        raise ValueError("Refusing log larger than 100 MB")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")

def audit_file(path: Path, fee_per_lot: float) -> list[dict]:
    lines = read_text(path).splitlines()
    starts = [(i, match) for i, line in enumerate(lines)
              if (match := START.search(line))]
    sessions = []
    for number, (start, match) in enumerate(starts, 1):
        stop = starts[number][0] if number < len(starts) else len(lines)
        segment = lines[start:stop]
        styles = [int(m.group(1)) for line in segment[:90]
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
        fingerprint = hashlib.sha256(
            json.dumps([style, match.group(1), match.group(2),
                        [(d["entry"], d["volume"], d["price"], d["net"])
                         for d in deals]], separators=(",", ":")).encode()
        ).hexdigest()
        sessions.append({
            "file": path.name, "session": number, "entry_style": style,
            "period_start": match.group(1), "period_end": match.group(2),
            "state": "COMPLETE_LOG_ONLY" if complete else "INCOMPLETE_LOG_ONLY",
            "stopped_by_user": stopped, "final_balance": balances[-1] if complete else None,
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
        "warnings": [
            "Agent logs are not native MT5 HTML reports.",
            "Recorded zero commission does not prove zero broker commission.",
            "Cost stress is illustrative; no commission or slippage model is verified.",
            "Incomplete, duplicated and mismatched-period runs must never be ranked.",
        ],
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "reports_local" / "native")
    parser.add_argument("--round-turn-fee-per-lot", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = args.paths or sorted(set(args.directory.glob("QTS_*.log")) | set(args.directory.glob("QTS_*.htm")))
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
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
