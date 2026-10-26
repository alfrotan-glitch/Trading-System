"""QTS XAUUSD STOP-path audit: causal quote-only descriptive analysis.

Inputs: broker trade STOP exits (user-extracted) and timestamped executable
bid/ask tick rows. Does NOT execute orders or infer profit from a hindsight
reversal. A move AFTER a stop cannot prove a wider stop would be profitable.
No private broker login/account identifier should be present in either CSV.

Example:
 python gold_robot/research/stop_reversal_audit.py --stops stops.csv \
   --ticks ticks.csv --output stop_audit.json

stops.csv fields:
 trade_id,side,entry_time_ms,exit_time_ms,entry_price,initial_stop_price,exit_price,exit_reason
side BUY or SELL, exit_reason SL; times broker-history-aligned UTC epoch ms.
ticks.csv fields: time_ms,bid,ask, chronological, quotes must be executable.

Research only. No API imports or MT5 order functions.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Iterable

HORIZONS_MIN = (5, 15, 30, 60, 120)
FIELDS = ("trade_id", "side", "entry_time_ms", "exit_time_ms",
          "entry_price", "initial_stop_price", "exit_price", "exit_reason")


@dataclass
class Window:
    horizon_ms: int
    first_ms: int | None = None
    last_ms: int | None = None
    complete: bool = False
    finished: bool = False
    has_gap: bool = False
    reclaimed_entry: bool = False
    max_favorable_r: float = 0.0
    max_adverse_r: float = 0.0

    def observe(self, *, ms: int, tradetime: int, directional_r: float,
                reclaimed: bool, max_gap_ms: int) -> None:
        end = tradetime + self.horizon_ms
        if self.finished:
            return
        if ms > end:
            # A valid observation just before the end and complete prior
            # coverage are required; do not count missing days as no reversal.
            self.complete = (self.first_ms is not None
                             and self.first_ms - tradetime <= max_gap_ms
                             and self.last_ms is not None
                             and end - self.last_ms <= max_gap_ms
                             and not self.has_gap)
            self.finished = True
            return
        if self.first_ms is None:
            self.first_ms = ms
            if ms - tradetime > max_gap_ms:
                self.has_gap = True
        elif self.last_ms is not None and ms - self.last_ms > max_gap_ms:
            self.has_gap = True
        self.last_ms = ms
        self.reclaimed_entry |= reclaimed
        self.max_favorable_r = max(self.max_favorable_r, directional_r)
        self.max_adverse_r = min(self.max_adverse_r, directional_r)


@dataclass
class Stop:
    trade_id: str
    side: int
    entry_ms: int
    exit_ms: int
    entry: float
    initial_stop: float
    exit_price: float
    windows: dict[int, Window] = field(
        default_factory=lambda: {m: Window(m * 60000) for m in HORIZONS_MIN}
    )

    @property
    def r_price(self) -> float:
        return abs(self.entry - self.initial_stop)


def load_stops(rows: Iterable[dict[str, str]]) -> tuple[list[Stop], int]:
    stops: list[Stop] = []
    seen: set[str] = set()
    ignored = 0
    for row in rows:
        if row.get("exit_reason", "").strip().upper() not in ("SL", "STOP", "STOP_LOSS"):
            ignored += 1
            continue
        identity = row["trade_id"].strip()
        side = row["side"].strip().upper()
        if not identity or identity in seen or side not in ("BUY", "SELL"):
            raise ValueError("invalid/duplicate trade id or side")
        seen.add(identity)
        entry_ms = int(row["entry_time_ms"])
        exit_ms = int(row["exit_time_ms"])
        entry = float(row["entry_price"])
        stop = float(row["initial_stop_price"])
        exit_price = float(row["exit_price"])
        direction = 1 if side == "BUY" else -1
        if (entry_ms < 0 or exit_ms <= entry_ms or entry <= 0 or stop <= 0
                or exit_price <= 0 or direction * (entry - stop) <= 0):
            raise ValueError("invalid chronology, pricing or initial SL side")
        # No requirement that exit price equals planned SL: stop slip/gap exists.
        stops.append(Stop(identity, direction, entry_ms, exit_ms,
                          entry, stop, exit_price))
    return sorted(stops, key=lambda t: (t.exit_ms, t.trade_id)), ignored


def audit(stops: list[Stop], ticks: Iterable[dict[str, str]],
          *, max_gap_ms: int = 60000) -> dict:
    if max_gap_ms < 1:
        raise ValueError("gap threshold must be positive")
    next_stop = 0
    active: list[Stop] = []
    last_tick: int | None = None
    tick_count = 0
    for row in ticks:
        ms = int(row["time_ms"])
        bid = float(row["bid"])
        ask = float(row["ask"])
        if (ms < 0 or bid <= 0 or ask <= bid or
                last_tick is not None and ms < last_tick):
            raise ValueError("out-of-order or invalid executable tick")
        last_tick = ms
        tick_count += 1
        while next_stop < len(stops) and stops[next_stop].exit_ms < ms:
            candidate = stops[next_stop]
            # If tick history starts AFTER a stop, the first-sample gap
            # will invalidate any horizon whose start is not covered.
            active.append(candidate)
            next_stop += 1
        remaining: list[Stop] = []
        for stop in active:
            if ms <= stop.exit_ms:
                remaining.append(stop)
                continue
            executable_exit = bid if stop.side == 1 else ask
            directional_r = stop.side * (executable_exit - stop.exit_price) / stop.r_price
            reclaimed = (bid >= stop.entry if stop.side == 1 else ask <= stop.entry)
            for window in stop.windows.values():
                window.observe(ms=ms, tradetime=stop.exit_ms,
                               directional_r=directional_r, reclaimed=reclaimed,
                               max_gap_ms=max_gap_ms)
            if not all(w.finished for w in stop.windows.values()):
                remaining.append(stop)
        active = remaining
    # All windows that did not reach their end with quote coverage remain
    # indeterminate. The CSV must include ticks through every full horizon.
    results = {}
    for minutes in HORIZONS_MIN:
        valid = [s.windows[minutes] for s in stops if s.windows[minutes].complete]
        reclaimed = [w for w in valid if w.reclaimed_entry]
        results[str(minutes)] = {
            "eligible_stops_with_contiguous_executable_quotes": len(valid),
            "reclaimed_entry_count": len(reclaimed),
            "reclaimed_entry_fraction": round(len(reclaimed) / len(valid), 5) if valid else None,
            "median_max_favorable_R_after_stop": round(median(w.max_favorable_r for w in valid), 5)
                                                if valid else None,
            "median_max_adverse_R_after_stop": round(median(w.max_adverse_r for w in valid), 5)
                                              if valid else None,
            "not_eligible_or_incomplete": len(stops) - len(valid),
        }
    return {
        "status": "DESCRIPTIVE_ONLY_NO_TRADE_AUTHORITY",
        "stop_trades": len(stops),
        "ticks_scanned": tick_count,
        "max_contiguous_quote_gap_ms": max_gap_ms,
        "ignored_non_stop_rows": 0,
        "horizons_minutes": results,
        "individual_trade_windows": [
            {
                "trade_id": stop.trade_id,
                "side": "BUY" if stop.side == 1 else "SELL",
                "windows": {
                    str(m): {
                        "complete": w.complete,
                        "reclaimed_entry": w.reclaimed_entry if w.complete else None,
                        "max_favorable_R": round(w.max_favorable_r, 5) if w.complete else None,
                        "max_adverse_R": round(w.max_adverse_r, 5) if w.complete else None,
                    }
                    for m, w in stop.windows.items()
                },
            }
            for stop in stops
        ],
        "warning": (
            "Entry reclaim is NOT a hypothetical winning trade. Stop gaps, "
            "spread/commission, late fills, post-exit path, and original signal "
            "reselection preclude naive stop-widening or reverse-at-stop claims. "
            "Insufficient quote coverage remains UNKNOWN, never zero."
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="No-order XAUUSD post-stop quote audit")
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument("--ticks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-gap-seconds", type=int, default=60)
    args = parser.parse_args()
    with args.stops.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
            parser.error("stops CSV columns do not match documented field names")
        stops, ignored = load_stops(reader)
    with args.ticks.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"time_ms", "bid", "ask"}.issubset(reader.fieldnames):
            parser.error("ticks CSV must contain time_ms,bid,ask")
        result = audit(stops, reader, max_gap_ms=args.max_gap_seconds * 1000)
    result["ignored_non_stop_rows"] = ignored
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "individual_trade_windows"},
                     indent=2))


if __name__ == "__main__":
    main()
