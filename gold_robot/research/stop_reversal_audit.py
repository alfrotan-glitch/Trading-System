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
ticks.csv fields: time_ms,bid,ask, chronological, quotes must be executable.\nOptional stops.csv field initial_target_price enables later TP-touch event study.\nAll timestamp columns must share one broker/UTC epoch time convention.

Research only. No API imports or MT5 order functions.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from math import isfinite
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
    first_entry_reclaim_ms: int | None = None
    first_target_touch_ms: int | None = None
    favorable_extreme_price: float | None = None
    favorable_extreme_ms: int | None = None
    favorable_observed_r: float | None = None
    adverse_extreme_price: float | None = None
    adverse_extreme_ms: int | None = None
    adverse_observed_r: float | None = None
    max_favorable_r: float = 0.0
    max_adverse_r: float = 0.0

    def observe(self, *, ms: int, tradetime: int, directional_r: float,
                executable_exit: float, reclaimed: bool, reached_target: bool,
                max_gap_ms: int) -> None:
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
        if reclaimed and self.first_entry_reclaim_ms is None:
            self.first_entry_reclaim_ms = ms
        if reached_target and self.first_target_touch_ms is None:
            self.first_target_touch_ms = ms
        # Observed executable-price extrema must not use the zero-clamped
        # favorable/adverse excursion baselines: if *all* post-stop ticks
        # are unfavorable, the best observed tick can still be below zero R.
        if (self.favorable_observed_r is None or
                directional_r > self.favorable_observed_r):
            self.favorable_observed_r = directional_r
            self.favorable_extreme_price = executable_exit
            self.favorable_extreme_ms = ms
        if (self.adverse_observed_r is None or
                directional_r < self.adverse_observed_r):
            self.adverse_observed_r = directional_r
            self.adverse_extreme_price = executable_exit
            self.adverse_extreme_ms = ms
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
    initial_target_price: float | None = None
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
        target_text = row.get("initial_target_price", "").strip()
        target = float(target_text) if target_text else None
        direction = 1 if side == "BUY" else -1
        if (entry_ms < 0 or exit_ms <= entry_ms or
                not all(isfinite(v) for v in (entry, stop, exit_price)) or
                entry <= 0 or stop <= 0 or exit_price <= 0 or
                direction * (entry - stop) <= 0 or
                (target is not None and (not isfinite(target) or target <= 0 or
                                          direction * (target - entry) <= 0))):
            raise ValueError("invalid chronology, pricing or initial SL side")
        # No requirement that exit price equals planned SL: stop slip/gap exists.
        stops.append(Stop(identity, direction, entry_ms, exit_ms,
                          entry, stop, exit_price, target))
    return sorted(stops, key=lambda t: (t.exit_ms, t.trade_id)), ignored


def audit(stops: list[Stop], ticks: Iterable[dict[str, str]],
          *, max_gap_ms: int = 60000) -> dict:
    if max_gap_ms < 1:
        raise ValueError("gap threshold must be positive")
    # A Stop object may be replayed with a second tick feed. Reusing stale
    # Window.complete/reached_target flags is a dangerous false TP proof.
    # Reinitialize all horizon state before EACH audit, including an empty feed.
    for stop in stops:
        stop.windows = {minutes: Window(minutes * 60000) for minutes in HORIZONS_MIN}
    next_stop = 0
    active: list[Stop] = []
    last_tick: int | None = None
    tick_count = 0
    for row in ticks:
        ms = int(row["time_ms"])
        bid = float(row["bid"])
        ask = float(row["ask"])
        if (ms < 0 or not isfinite(bid) or not isfinite(ask) or
                bid <= 0 or ask <= bid or
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
            reached_target = (stop.initial_target_price is not None and
                              ((bid >= stop.initial_target_price) if stop.side == 1
                               else (ask <= stop.initial_target_price)))
            for window in stop.windows.values():
                window.observe(ms=ms, tradetime=stop.exit_ms,
                               directional_r=directional_r,
                               executable_exit=executable_exit, reclaimed=reclaimed,
                               reached_target=reached_target, max_gap_ms=max_gap_ms)
            if not all(w.finished for w in stop.windows.values()):
                remaining.append(stop)
        active = remaining
    # All windows that did not reach their end with quote coverage remain
    # indeterminate. The CSV must include ticks through every full horizon.
    results = {}
    for minutes in HORIZONS_MIN:
        valid = [s.windows[minutes] for s in stops if s.windows[minutes].complete]
        reclaimed = [w for w in valid if w.reclaimed_entry]
        with_target = [s.windows[minutes] for s in stops
                       if s.initial_target_price is not None and
                       s.windows[minutes].complete]
        reached = [w for w in with_target if w.first_target_touch_ms is not None]
        results[str(minutes)] = {
            "eligible_stops_with_contiguous_executable_quotes": len(valid),
            "reclaimed_entry_count": len(reclaimed),
            "target_eligible_stops": len(with_target),
            "post_stop_original_target_touch_count": len(reached),
            "post_stop_original_target_touch_fraction": (
                round(len(reached) / len(with_target), 5) if with_target else None),
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
                "original_entry_price": stop.entry,
                "original_sl_price": stop.initial_stop,
                "original_tp_price": stop.initial_target_price,
                "stop_exit_price": stop.exit_price,
                "stop_exit_time_ms": stop.exit_ms,
                "windows": {
                    str(m): {
                        "complete": w.complete,
                        "first_entry_reclaim_ms": w.first_entry_reclaim_ms if w.complete else None,
                        "first_target_touch_ms": w.first_target_touch_ms if w.complete else None,
                        "first_target_touch_after_stop_minutes": (
                            round((w.first_target_touch_ms - stop.exit_ms) / 60000, 4)
                            if w.complete and w.first_target_touch_ms is not None else None),
                        "favorable_extreme_executable_price": (
                            w.favorable_extreme_price if w.complete else None),
                        "favorable_extreme_time_ms": (
                            w.favorable_extreme_ms if w.complete else None),
                        "adverse_extreme_executable_price": (
                            w.adverse_extreme_price if w.complete else None),
                        "adverse_extreme_time_ms": (
                            w.adverse_extreme_ms if w.complete else None),
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
            "Entry reclaim and later original TP touch are NOT hypothetical winning trades. Stop gaps, "
            "spread/commission, late fills, post-exit path, and original signal "
            "reselection preclude naive stop-widening or reverse-at-stop claims. "
            "Insufficient quote coverage remains UNKNOWN, never zero."
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="No-order XAUUSD post-stop quote audit")
    parser.add_argument("--stops", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticks", type=Path,
                        help="One combined CSV with time_ms,bid,ask")
    source.add_argument("--tick-dir", type=Path,
                        help="MT5 ExportBrokerData.mq5 daily ticks_<day>.csv files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-gap-seconds", type=int, default=60)
    args = parser.parse_args()
    with args.stops.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
            parser.error("stops CSV columns do not match documented field names")
        stops, ignored = load_stops(reader)
    def stream_executable_ticks():
        if args.ticks:
            paths = [args.ticks]
        else:
            paths = sorted(args.tick_dir.glob("ticks_*.csv"),
                           key=lambda p: int(p.stem.split("_")[-1]))
        if not paths:
            raise ValueError("No native exported tick CSV files found; price-after-SL is UNKNOWN")
        for path in paths:
            with path.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames or not {"bid", "ask"}.issubset(reader.fieldnames):
                    raise ValueError(f"Missing executable bid/ask fields in {path}")
                time_field = ("time_ms" if "time_ms" in reader.fieldnames
                              else "time_msc" if "time_msc" in reader.fieldnames else None)
                if time_field is None:
                    raise ValueError(f"Missing broker epoch millisecond time in {path}")
                for row in reader:
                    yield {"time_ms": row[time_field],
                           "bid": row["bid"], "ask": row["ask"]}
    result = audit(stops, stream_executable_ticks(),
                   max_gap_ms=args.max_gap_seconds * 1000)
    result["ignored_non_stop_rows"] = ignored
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "individual_trade_windows"},
                     indent=2))


if __name__ == "__main__":
    main()
