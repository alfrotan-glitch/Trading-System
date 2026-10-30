"""Read-only native MT5 broker-tick exporter for QTS post-SL windows.

Operates only on recorded, merged 120-minute post-stop windows. It never
logs in, sends orders, selects account credentials, or changes trade settings.
The MT5 Python API is used exclusively for connection metadata and quotes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

MAX_WINDOWS = 5000
MAX_WINDOW_MS = 48 * 3600_000  # overlapping clustered stops may merge
CHUNK_MS = 3 * 60_000
MIN_MS = 1_577_836_800_000
MAX_MS = 4_102_444_800_000


def read_windows(path: Path, expected_tag: str) -> list[tuple[int, int]]:
    if not path.is_file():
        raise ValueError("Missing generated post-stop windows")
    windows = []
    with path.open(encoding="ascii", newline="") as source:
        for row in csv.reader(source, delimiter=";"):
            if len(row) != 3 or row[2] != expected_tag:
                raise ValueError("Invalid or wrong-run MT5 stop-window manifest")
            start, end = int(row[0]), int(row[1])
            if (not MIN_MS <= start < end <= MAX_MS
                    or end - start > MAX_WINDOW_MS
                    or (windows and start <= windows[-1][1])):
                raise ValueError("Invalid, overlapping, or unbounded tick interval")
            windows.append((start, end))
    if not 0 < len(windows) <= MAX_WINDOWS:
        raise ValueError("No bounded post-stop windows, or too many windows")
    return windows


def export_windows(
    plan: Path, output: Path, tag: str, symbol: str = "XAUUSD@",
    mt5=None,
) -> dict:
    if mt5 is None:
        import MetaTrader5 as mt5  # official read-only quote API, Windows only
    windows = read_windows(plan, tag)
    if output.exists():
        raise FileExistsError("Quote directory already exists; refusing overwrite")
    output.mkdir(parents=True)
    status = {
        "schema": "qts.mt5.bounded_ticks.v1",
        "state": "INCOMPLETE",
        "run_tag": tag,
        "symbol": symbol,
        "windows_requested": len(windows),
        "windows_with_quotes": 0,
        "empty_or_missing_windows": 0,
        "ticks_written": 0,
        "live": "LOCKED",
        "price_after_stop_verified": False,
        "window_coverage": [],
        "source": "MT5 COPY_TICKS_INFO through local connected terminal",
    }
    session = False
    try:
        if not mt5.initialize():
            raise RuntimeError(f"Cannot attach to MT5 terminal (code={mt5.last_error()})")
        session = True
        terminal = mt5.terminal_info()
        if terminal is None or not getattr(terminal, "connected", False):
            raise RuntimeError("MT5 terminal is not connected to its existing broker")
        robot_path = Path(str(getattr(terminal, "data_path", ""))) / "MQL5" / "Experts" / "QTS_Gold_Robot.ex5"
        if not robot_path.is_file():
            raise RuntimeError(
                "MT5 attached to a different terminal: canonical QTS_Gold_Robot.ex5 is missing"
            )
        if mt5.symbol_info(symbol) is None:
            raise RuntimeError(f"Broker symbol {symbol} is not available in the terminal")
        # Selecting Market Watch is permitted; no orders or accounts changed.
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Cannot select {symbol} quotes: {mt5.last_error()}")
        for index, (start, end) in enumerate(windows, 1):
            target = output / f"ticks_{index:05d}.csv"
            if target.exists():
                raise RuntimeError("Unexpected pre-existing quote file")
            first_ms = None
            last_ms = None
            count_total = 0
            errors = 0
            with target.open("w", newline="", encoding="utf-8") as dest:
                writer = csv.writer(dest)
                writer.writerow(["time_msc", "bid", "ask"])
                cursor = start
                while cursor <= end:
                    chunk_end = min(cursor + CHUNK_MS - 1, end)
                    from_dt = datetime.fromtimestamp((cursor - 1000) / 1000, timezone.utc)
                    to_dt = datetime.fromtimestamp((chunk_end + 1000) / 1000, timezone.utc)
                    rows = mt5.copy_ticks_range(symbol, from_dt, to_dt, mt5.COPY_TICKS_INFO)
                    if rows is None:
                        errors += 1
                        print(f"Window {index}/{len(windows)}: broker ticks unavailable "
                              f"({mt5.last_error()})", flush=True)
                    else:
                        for tick in rows:
                            ms = int(tick["time_msc"])
                            bid = float(tick["bid"])
                            ask = float(tick["ask"])
                            if not cursor <= ms <= chunk_end:
                                continue
                            if bid <= 0 or ask <= bid:
                                continue
                            writer.writerow([ms, format(bid, ".8f"), format(ask, ".8f")])
                            count_total += 1
                            if first_ms is None:
                                first_ms = ms
                            last_ms = ms
                    cursor = chunk_end + 1
            if count_total:
                status["windows_with_quotes"] += 1
            else:
                status["empty_or_missing_windows"] += 1
            status["ticks_written"] += count_total
            status["window_coverage"].append({
                "window": index,
                "start_ms": start,
                "end_ms": end,
                "first_tick_ms": first_ms,
                "last_tick_ms": last_ms,
                "ticks": count_total,
                "api_failures": errors,
            })
            print(f"MT5 quotes {index}/{len(windows)}: {count_total} ticks, "
                  f"{errors} API failures", flush=True)
        failure_count = sum(w["api_failures"] for w in status["window_coverage"])
        # Market-closed windows may legitimately have zero quotes, so the
        # replay auditor will independently mark incomplete tick horizons.
        status["state"] = (
            "EXPORTED_FOR_GAP_AUDIT" if status["ticks_written"] > 0 and not failure_count
            else "EVIDENCE_GAPS"
        )
    except Exception as exc:
        status["error"] = str(exc)
        raise
    finally:
        if session:
            mt5.shutdown()
        (output / "export_status.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--symbol", default="XAUUSD@")
    args = parser.parse_args()
    result = export_windows(args.plan, args.output, args.tag, args.symbol)
    print(json.dumps({k: v for k, v in result.items() if k != "window_coverage"}, indent=2))
    return 0 if result["state"] == "EXPORTED_FOR_GAP_AUDIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
