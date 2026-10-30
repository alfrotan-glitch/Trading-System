"""QTS stop-failure forensics: losses that never reach TP, before and after SL.

All conclusions are descriptive, from same-broker executable Bid/Ask quotes.
A post-stop rebound is not a trade. No order API, optimization, or live permission.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

MAX_GAP_MS = 60_000
FIELDS = ("trade_id", "side", "entry_time_ms", "exit_time_ms", "entry_price",
          "initial_stop_price", "initial_target_price", "exit_price")
HORIZONS = ("5", "15", "30", "60", "120")


@dataclass
class Pre:
    entry_ms: int
    exit_ms: int
    side: int
    entry: float
    sl: float
    tp: float
    first_ms: int | None = None
    last_ms: int | None = None
    gap: bool = False
    max_favorable: float = float("-inf")
    max_adverse: float = float("inf")
    first_tp_ms: int | None = None
    first_sl_ms: int | None = None
    ticks: int = 0

    def observe(self, ms: int, bid: float, ask: float) -> None:
        if self.first_ms is None:
            self.first_ms = ms
        elif self.last_ms is not None and ms - self.last_ms > MAX_GAP_MS:
            self.gap = True
        self.last_ms = ms
        self.ticks += 1
        price = bid if self.side == 1 else ask
        directional = self.side * (price - self.entry)
        self.max_favorable = max(self.max_favorable, directional)
        self.max_adverse = min(self.max_adverse, directional)
        if self.first_tp_ms is None and self.side * (price - self.tp) >= 0:
            self.first_tp_ms = ms
        if self.first_sl_ms is None and self.side * (price - self.sl) <= 0:
            self.first_sl_ms = ms

    @property
    def complete(self) -> bool:
        return (self.first_ms is not None and self.last_ms is not None and
                self.first_ms - self.entry_ms <= MAX_GAP_MS and
                self.exit_ms - self.last_ms <= MAX_GAP_MS and not self.gap)


def pre_stop_observations(cases: list[dict], tick_dir: Path | None) -> dict[str, dict]:
    records = {r["trade_id"]: Pre(
        int(r["entry_time_ms"]), int(r["exit_time_ms"]),
        1 if r["side"] == "BUY" else -1,
        float(r["entry_price"]), float(r["initial_stop_price"]),
        float(r["initial_target_price"]),
    ) for r in cases}
    if tick_dir is None:
        return {}
    paths = sorted(tick_dir.glob("ticks_*.csv"),
                   key=lambda p: int(p.stem.split("_")[-1]))
    if not paths:
        raise ValueError("Pre-stop tick folder has no executable price files")
    pending = sorted(records.values(), key=lambda item: item.entry_ms)
    next_index = 0
    active: list[Pre] = []
    global_last: int | None = None
    for file in paths:
        with file.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {"time_msc", "bid", "ask"}.issubset(reader.fieldnames):
                raise ValueError("Invalid original pre-stop bid/ask evidence")
            for row in reader:
                ms = int(row["time_msc"])
                bid = float(row["bid"])
                ask = float(row["ask"])
                if ms < 0 or (global_last is not None and ms < global_last) or bid <= 0 or ask < bid:
                    raise ValueError("Invalid or out-of-order broker tick")
                global_last = ms
                while next_index < len(pending) and pending[next_index].entry_ms <= ms:
                    active.append(pending[next_index])
                    next_index += 1
                newer = []
                for p in active:
                    if ms > p.exit_ms:
                        continue
                    p.observe(ms, bid, ask)
                    newer.append(p)
                active = newer
    result = {}
    for ident, p in records.items():
        risk = abs(p.entry - p.sl)
        reward = abs(p.tp - p.entry)
        if risk <= 0 or reward <= 0:
            raise ValueError("Invalid original stop or target in research cases")
        if not p.complete:
            result[ident] = {"pre_status": "UNKNOWN_GAP", "pre_category": "UNKNOWN",
                             "pre_ticks": p.ticks}
            continue
        progress = max(0.0, p.max_favorable / reward)
        if p.first_tp_ms is not None:
            category = "TP_QUOTED_BEFORE_SL_RECONCILE"
        elif progress >= .8:
            category = "NEAR_TP_THEN_SL"
        elif progress >= .25:
            category = "PARTIAL_PROGRESS_THEN_SL"
        elif (p.exit_ms - p.entry_ms) <= 5 * 60_000:
            category = "EARLY_SL_WITHOUT_PROGRESS"
        else:
            category = "SL_WITHOUT_MEANINGFUL_PROGRESS"
        result[ident] = {
            "pre_status": "COMPLETE", "pre_category": category,
            "pre_ticks": p.ticks,
            "minutes_held": round((p.exit_ms - p.entry_ms) / 60000, 3),
            "max_favorable_R_before_SL": round(p.max_favorable / risk, 5),
            "max_adverse_R_before_SL": round(p.max_adverse / risk, 5),
            "max_fraction_of_original_TP_before_SL": round(progress, 5),
            "first_initial_SL_quote_ms": p.first_sl_ms,
            "first_initial_TP_quote_ms": p.first_tp_ms,
        }
    return result


def classify(cases: list[dict], replay: dict, pre: dict[str, dict] | None = None) -> tuple[list[dict], dict]:
    pre = pre or {}
    originals = {r["trade_id"]: r for r in cases}
    if len(originals) != len(cases):
        raise ValueError("Duplicate original stop case identifiers")
    observations = replay.get("individual_trade_windows", [])
    if len(observations) != len(cases):
        raise ValueError("Post-stop evidence count does not match original cases")
    enriched = []
    for item in observations:
        ident = item["trade_id"]
        if ident not in originals:
            raise ValueError("Unrecognized stop identifier in broker evidence")
        src = originals[ident]
        if (item["side"] != src["side"] or
                abs(float(item["original_tp_price"]) - float(src["initial_target_price"])) > 1e-6 or
                int(item["stop_exit_time_ms"]) != int(src["exit_time_ms"])):
            raise ValueError("Original broker trade identity or target mismatch")
        windows = item["windows"]
        recent = windows["5"]
        last = windows["120"]
        if not last["complete"]:
            category = "UNKNOWN_120M_COVERAGE"
        elif last["first_target_touch_ms"] is not None:
            category = "LATER_TP_TOUCH"
        elif last["reclaimed_entry"]:
            category = "RECLAIM_ONLY_NO_TP"
        else:
            category = "CONTINUED_AGAINST_NO_RECLAIM"
        adverse = last.get("max_adverse_R") if last["complete"] else None
        stress = ("UNKNOWN" if adverse is None else
                  "AT_LEAST_2R_AGAINST" if adverse <= -2 else
                  "AT_LEAST_1R_AGAINST" if adverse <= -1 else "UNDER_1R_AGAINST")
        entry = float(src["entry_price"])
        target = float(src["initial_target_price"])
        direction = 1 if src["side"] == "BUY" else -1
        if last["complete"] and last["first_target_touch_ms"] is None:
            favorable = last.get("favorable_extreme_executable_price")
            after_progress = (max(0.0, direction * (float(favorable) - entry) /
                                  abs(target - entry)) if favorable is not None else None)
        else:
            after_progress = None
        meta = pre.get(ident, {"pre_status": "NOT_COLLECTED", "pre_category": "UNKNOWN"})
        row = {
            "trade_id": ident, "style": int(src["style"]), "side": src["side"],
            "entry_time_ms": int(src["entry_time_ms"]),
            "stop_time_ms": int(src["exit_time_ms"]),
            "entry_price": entry, "initial_SL": float(src["initial_stop_price"]),
            "initial_TP": target,
            "minutes_held": round((int(src["exit_time_ms"])-int(src["entry_time_ms"])) / 60000, 3),
            "post_category_120m": category, "post_stress": stress,
            "first_5m_complete": bool(recent["complete"]),
            "adverse_R_first_5m": recent.get("max_adverse_R") if recent["complete"] else None,
            "adverse_R_120m": adverse,
            "favorable_R_120m": last.get("max_favorable_R") if last["complete"] else None,
            "near_original_TP_after_SL_80pct": (
                after_progress >= .8 if after_progress is not None else None),
            "TP_progress_fraction_after_SL": (
                round(after_progress, 5) if after_progress is not None else None),
            "first_TP_minutes_after_SL": last.get("first_target_touch_after_stop_minutes"),
            **{key: meta.get(key) for key in (
                "pre_status", "pre_category", "pre_ticks",
                "max_favorable_R_before_SL", "max_adverse_R_before_SL",
                "max_fraction_of_original_TP_before_SL",
                "first_initial_SL_quote_ms", "first_initial_TP_quote_ms"
            )},
        }
        enriched.append(row)
    if len({r["trade_id"] for r in enriched}) != len(originals):
        raise ValueError("Missing or duplicated broker stop ID")
    by_style = {}
    for style in sorted({r["style"] for r in enriched}):
        items = [r for r in enriched if r["style"] == style]
        by_style[str(style)] = {
            "stops": len(items),
            "post_120m_categories": dict(Counter(r["post_category_120m"] for r in items)),
            "pre_stop_categories": dict(Counter(r["pre_category"] for r in items)),
            "at_least_2R_adverse_after_stop": sum(r["post_stress"] == "AT_LEAST_2R_AGAINST" for r in items),
        }
    categories = Counter(r["post_category_120m"] for r in enriched)
    summary = {
        "schema": "qts.stop.failed_paths.v1",
        "status": "DESCRIPTIVE_RESEARCH_ONLY",
        "live": "LOCKED",
        "original_stop_cases": len(cases),
        "before_stop_quotes_collected": bool(pre),
        "post_120m_outcomes": dict(categories),
        "pre_stop_outcomes": dict(Counter(r["pre_category"] for r in enriched)),
        "post_2R_adverse_events": sum(r["post_stress"] == "AT_LEAST_2R_AGAINST" for r in enriched),
        "by_style": by_style,
        "warnings": [
            "Post-stop movement is not realized P&L or evidence to widen stops.",
            "Pre-stop price progress is descriptive. It cannot prove why a trade lost.",
            "Only complete executable Bid/Ask quote coverage supports classification.",
            "The four entry styles were selected after viewing in-sample outcomes.",
            "No parameters were optimized, and live execution remains locked.",
        ],
    }
    return enriched, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--post", type=Path, required=True)
    parser.add_argument("--pre-ticks", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.cases.open(encoding="utf-8-sig", newline="") as f:
        cases = list(csv.DictReader(f))
    replay = json.loads(args.post.read_text(encoding="utf-8-sig"))
    before = pre_stop_observations(cases, args.pre_ticks)
    rows, summary = classify(cases, replay, before)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "QTS_LOSING_STOP_PATHS.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "QTS_LOSING_STOP_SUMMARY.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
