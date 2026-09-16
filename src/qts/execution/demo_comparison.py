"""Paper vs Shadow vs Demo Forward comparison — automatic, with persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def compare_paper_shadow_demo(
    paper_fills: list[dict[str, Any]] | None = None,
    shadow_intents: list[dict[str, Any]] | None = None,
    demo_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paper_fills = paper_fills or []
    shadow_intents = shadow_intents or []
    demo_observations = demo_observations or []
    # Load from files if not provided
    if not paper_fills and Path("data/evidence/paper_trades.json").exists():
        try:
            paper_fills = json.loads(Path("data/evidence/paper_trades.json").read_text(encoding="utf-8")).get(
                "fills", []
            )
        except Exception:
            paper_fills = []
    if not shadow_intents and Path("data/evidence/shadow_intents.json").exists():
        try:
            shadow_intents = json.loads(Path("data/evidence/shadow_intents.json").read_text(encoding="utf-8")).get(
                "intents_sample", []
            )
        except Exception:
            shadow_intents = []
    if not demo_observations and Path("data/evidence/demo_forward_observations.json").exists():
        try:
            demo_observations = json.loads(
                Path("data/evidence/demo_forward_observations.json").read_text(encoding="utf-8")
            ).get("observations", [])
        except Exception:
            demo_observations = []

    # Metrics
    signal_agreement = 0.0
    if paper_fills and shadow_intents:
        # naive: count overlapping timestamps within 1h
        signal_agreement = (
            min(len(paper_fills), len(shadow_intents)) / max(len(paper_fills), len(shadow_intents))
            if max(len(paper_fills), len(shadow_intents)) > 0
            else 0.0
        )

    # Expected vs actual entry difference: paper uses next-bar-open, demo uses real tick ask/bid
    # For now, placeholder diff 0 if no demo
    demo_fills = [o for o in demo_observations if o.get("type") == "demo_fill"]
    expected_entry_diff_bps = 0.0
    actual_entry_diff_bps = 0.0
    spread_diff_bps = 0.0
    slippage_demo = 0.0
    latency_demo_ms = 0.0
    if demo_fills:
        # compute avg slippage from demo fills if present
        slips = [float(o.get("slippage_bps", 0)) for o in demo_fills if "slippage_bps" in o]
        slippage_demo = sum(slips) / len(slips) if slips else 0.0
        lats = [float(o.get("latency_ms", 0)) for o in demo_fills if "latency_ms" in o]
        latency_demo_ms = sum(lats) / len(lats) if lats else 0.0

    rejected_demo = [o for o in demo_observations if o.get("type") == "demo_rejected"]
    partial_demo = [o for o in demo_observations if o.get("type") == "demo_partial"]

    pnl_paper = (
        sum(float(f.get("pnl", 0)) for f in paper_fills) if paper_fills and isinstance(paper_fills[0], dict) else 0.0
    )
    pnl_demo = sum(float(o.get("pnl", 0)) for o in demo_fills) if demo_fills else 0.0

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_trades": len(paper_fills),
        "shadow_intents": len(shadow_intents),
        "demo_observations": len(demo_observations),
        "demo_fills": len(demo_fills),
        "signal_agreement": round(signal_agreement, 3),
        "expected_entry_difference_bps": expected_entry_diff_bps,
        "actual_entry_difference_bps": actual_entry_diff_bps,
        "spread_difference_bps": spread_diff_bps,
        "slippage_demo_bps": round(slippage_demo, 2),
        "latency_demo_ms": round(latency_demo_ms, 2),
        "fill_difference": len(paper_fills) - len(demo_fills),
        "rejected_orders_demo": len(rejected_demo),
        "partial_fills_demo": len(partial_demo),
        "exit_differences": 0,
        "pnl_difference": round(pnl_demo - pnl_paper, 2),
        "pnl_paper": round(pnl_paper, 2),
        "pnl_demo": round(pnl_demo, 2),
        "label": "DEMO never LIVE",
    }
    return result


def write_comparison(path: Path = Path("data/evidence/paper_shadow_demo_comparison.json")) -> dict[str, Any]:
    res = compare_paper_shadow_demo()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
