"""Run the corrected fixed compressed-range assay on local MT5 ticks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.data.mt5_timestamp_basis import timestamp_basis_assessment
from qts.research.mt5_tick_bars import read_broker_bars
from qts.research.xauusd_broker_compression import aggregate_complete_fifteen_minute, evaluate_compression
from qts.research.xauusd_tick_discovery import discovery_cutoff


def run(dataset_dir: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    minute_bars = read_broker_bars(dataset_dir, manifest.get("parts") or [])
    bars = aggregate_complete_fifteen_minute(minute_bars)
    time_min, time_max = int(bars.time_msc.min()), int(bars.time_msc.max())
    result = evaluate_compression(bars, cutoff_time_msc=discovery_cutoff(time_min, time_max), time_min=time_min, time_max=time_max)
    result["dataset"] = {
        "manifest_dataset_sha256": manifest.get("dataset_sha256"),
        "raw_row_count": manifest.get("row_count"),
        "one_minute_bar_count": len(minute_bars.time_msc),
        "complete_fifteen_minute_bar_count": len(bars.time_msc),
    }
    result["timestamp_basis"] = timestamp_basis_assessment(manifest, evidence)
    if result["timestamp_basis"].get("status") not in {"CONFIRMED", "MEASURED_SAME_SESSION"}:
        result["decision"] = "INCONCLUSIVE"
        result["edge_claim"] = "NOT ESTABLISHED"
        result["strategy_promoted"] = False
        result.setdefault("integrity", {})["blocked_reason"] = "timestamp basis not confirmed"
    return result


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD corrected compressed-range breakout assay",
        "",
        f"Timestamp basis: {result.get('timestamp_basis', {}).get('status')}",
        f"Complete fifteen-minute bars: {result.get('dataset', {}).get('complete_fifteen_minute_bar_count')}",
        "",
        "| Horizon | Decision gate | Holdout trades | Holdout mean net bps at 2 bps stress | Bootstrap lower bound |",
        "|---|---|---:|---:|---:|",
    ]
    for name in ("primary", "stability"):
        hypothesis = result.get(name, {})
        cost = hypothesis.get("holdout", {}).get("costs", {}).get("2.0", {})
        lines.append(
            f"| {name} | {hypothesis.get('holdout_primary_pass')} | {hypothesis.get('holdout', {}).get('n')} | "
            f"{cost.get('mean_net_bps')} | {(cost.get('bootstrap') or {}).get('lo')} |"
        )
    lines += ["", "No candidate was promoted. LIVE is locked and order submission is disabled.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run corrected fixed compression research on local MT5 XAUUSD data")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--timestamp-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.dataset_dir, json.loads(args.timestamp_evidence.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(_render(result), encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "bar_count": result["dataset"]["complete_fifteen_minute_bar_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
