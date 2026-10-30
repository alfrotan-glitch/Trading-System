"""Prepare merged, bounded MT5 quote windows around actual SL exits.

Offline only. No broker orders, connections, or assumptions about future ticks.
The MQL5 exporter consumes ASCII semicolon separated start_ms;end_ms;run_tag
records and never exports multi-year tick history.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from pathlib import Path

HORIZON_MS = 120 * 60_000
MARGIN_MS = 61_000
MAX_STOPS = 5000

def prepare(stops_file: Path, output_file: Path, tag: str, *, phase: str = "post") -> dict:
    if phase not in ("post", "pre"):
        raise ValueError("Expected pre or post phase")
    if not re.fullmatch(r"\d{8}_\d{6}", tag):
        raise ValueError("Invalid native run tag")
    with stops_file.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or len(rows) > MAX_STOPS:
        raise ValueError("Expected 1..5000 real stop cases")
    raw = []
    for stop in rows:
        if stop.get("exit_reason") != "SL":
            raise ValueError("Non-SL case in stop evidence")
        ms = int(stop["exit_time_ms"])
        if not 1_577_836_800_000 <= ms <= 4_102_444_800_000:
            raise ValueError("Stop timestamp outside 2020-2100 UTC safety bounds")
        if phase == "pre":
            entry_ms = int(stop["entry_time_ms"])
            if entry_ms < 1_577_836_800_000 or entry_ms >= ms:
                raise ValueError("Invalid entry timestamp in a stopped trade")
            raw.append((entry_ms - MARGIN_MS, ms + MARGIN_MS))
        else:
            raw.append((ms - MARGIN_MS, ms + HORIZON_MS + MARGIN_MS))
    raw.sort()
    merged: list[list[int]] = []
    for start, end in raw:
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="ascii") as dest:
        writer = csv.writer(dest, delimiter=";", lineterminator="\r\n")
        for start, end in merged:
            writer.writerow([start, end, tag])
    return {
        "state": "PREPARED_ONLY_NO_TICKS",
        "stop_cases": len(rows),
        "merged_windows": len(merged),
        "phase": phase,
        "window_horizon_minutes": 120 if phase == "post" else None,
        "margin_seconds": 61,
        "run_tag": tag,
        "live": "LOCKED",
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--phase", choices=["post", "pre"], default="post")
    args = parser.parse_args()
    print(json.dumps(prepare(args.stops, args.output, args.tag, phase=args.phase), indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
