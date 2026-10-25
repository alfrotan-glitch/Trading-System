"""Compare LIMIT TP distances on identical entry signals using completed tick replays.

Screening ONLY: never auto-promote a high-win-rate target to a trading edge.
Out-of-sample days and actual broker fills are required for validation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite

from gold_robot.research.sim_limit import Result


@dataclass(frozen=True)
class Trial:
    signal_id: str
    day: str
    target_r: float
    result: Result


def compare_targets(trials: list[Trial], active_days: int) -> list[dict]:
    """Rank DEV candidates by *net per signal*, not just success percent.

    Each R must be evaluated on exactly the same pre-registered signal IDs.
    No target is marked validated or enabled by this statistical summary.
    """
    if active_days <= 0 or not trials:
        raise ValueError("provide trials and positive active_days")
    groups: dict[float, dict[str, Trial]] = defaultdict(dict)
    for item in trials:
        if not item.signal_id or not item.day or not isfinite(item.target_r) or item.target_r <= 0:
            raise ValueError("invalid signal identification or R")
        if item.result.outcome not in {
            "target", "stop", "timeout", "pending_unfilled", "open_at_end"
        } or not isfinite(item.result.net_usd):
            raise ValueError("unknown or nonfinite execution outcome")
        if item.signal_id in groups[item.target_r]:
            raise ValueError("duplicated signal for a target")
        groups[item.target_r][item.signal_id] = item
    cohort = {frozenset(g.keys()) for g in groups.values()}
    if len(cohort) != 1:
        raise ValueError("targets must use the identical original signals")
    dates = {item.day for item in trials}
    if len(dates) > active_days:
        raise ValueError("observed days exceed active_days")
    out = []
    for rr, group in groups.items():
        items = list(group.values())
        closes = [t for t in items if t.result.outcome in {"target", "stop", "timeout"}]
        fills = [t for t in items if t.result.outcome != "pending_unfilled"]
        unresolved = sum(t.result.outcome == "open_at_end" for t in items)
        successes = sum(t.result.outcome == "target" for t in items)
        net = sum(t.result.net_usd for t in closes)
        losses = -sum(t.result.net_usd for t in closes if t.result.net_usd < 0)
        gains = sum(t.result.net_usd for t in closes if t.result.net_usd > 0)
        out.append({
            "target_r": rr,
            "signals": len(items),
            "filled": len(fills),
            "closed": len(closes),
            "unresolved": unresolved,
            "tp_first_count": successes,
            "fill_rate": len(fills) / len(items),
            "tp_first_per_fill": successes / len(fills) if fills else None,
            "net_usd": net,
            "net_per_signal_usd": net / len(items),
            "profit_factor": gains / losses if losses > 0 else None,
            "closed_trades_per_active_day": len(closes) / active_days,
            "candidate_only": True,
            "valid_for_ranking": unresolved == 0 and len(closes) >= 100,
        })
    return sorted(out, key=lambda row: (-row["net_per_signal_usd"], row["target_r"]))
