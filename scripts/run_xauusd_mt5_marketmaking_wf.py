"""Run the preregistered H-MM-02 synthetic liquidity assay on MT5 ticks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.data.mt5_timestamp_basis import timestamp_basis_assessment
from qts.research.xauusd_marketmaking import MarketMakingScan
from qts.research.xauusd_marketmaking_wf import HYPOTHESIS, evaluate_marketmaking_wf
from qts.research.xauusd_tick_discovery import discovery_cutoff


def _stamp_range(dataset_dir: Path, parts: list[dict[str, Any]]) -> tuple[int, int]:
    minimum: int | None = None
    maximum: int | None = None
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc"]):
            stamps = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            if stamps.size == 0:
                continue
            lo, hi = int(stamps.min()), int(stamps.max())
            minimum = lo if minimum is None else min(minimum, lo)
            maximum = hi if maximum is None else max(maximum, hi)
    if minimum is None or maximum is None:
        raise ValueError("dataset has no time_msc values")
    return minimum, maximum


def run(dataset_dir: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    parts = manifest.get("parts") or []
    time_min, time_max = _stamp_range(dataset_dir, parts)
    cutoff = discovery_cutoff(time_min, time_max)
    scan = MarketMakingScan(time_min=time_min, cutoff=cutoff)
    discovery_rows = 0
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc", "bid", "ask"]):
            stamps = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            keep = stamps < cutoff
            discovery_rows += int(np.count_nonzero(keep))
            if not keep.any():
                continue
            scan.add_batch(
                batch.column("bid").to_numpy(zero_copy_only=False)[keep],
                batch.column("ask").to_numpy(zero_copy_only=False)[keep],
                stamps[keep],
            )
    result = evaluate_marketmaking_wf(scan, complete_rows=discovery_rows)
    hypothesis = result.get("hypotheses", {}).get(HYPOTHESIS, {})
    engine_status = hypothesis.get("status")
    result["dataset"] = {
        "manifest_dataset_sha256": manifest.get("dataset_sha256"),
        "source_rows": manifest.get("row_count"),
        "discovery_rows": discovery_rows,
        "held_out_rows_not_read_by_hypothesis": int(manifest.get("row_count") or 0) - discovery_rows,
        "time_msc_min": time_min,
        "time_msc_max": time_max,
        "cutoff_time_msc": cutoff,
    }
    result["timestamp_basis"] = timestamp_basis_assessment(manifest, evidence)
    result["inference"] = {
        "bootstrap": "NOT RUN by inherited engine; a synthetic pass is forced to INCONCLUSIVE",
        "fill_source": "SYNTHETIC front-of-queue touch model",
        "commission_slippage_swaps_fills": "UNMEASURED",
        "engine_status_before_bootstrap_gate": engine_status,
    }
    if engine_status == "TESTED":
        hypothesis["status"] = "INCONCLUSIVE"
        hypothesis.setdefault("reasons", []).append("bootstrap inference is not implemented; no synthetic pass may be promoted")
        result["decision"] = "INCONCLUSIVE"
    result["safety"] = {
        "orders_submitted": 0,
        "order_send_called": False,
        "DEMO_EXECUTION": "DISABLED",
        "LIVE": "LOCKED",
    }
    return result


def _render(result: dict[str, Any]) -> str:
    hypothesis = result.get("hypotheses", {}).get(HYPOTHESIS, {})
    lines = [
        "# XAUUSD H-MM-02 synthetic market-making walk-forward",
        "",
        f"Status: {hypothesis.get('status')}",
        f"Discovery rows: {result.get('dataset', {}).get('discovery_rows')}",
        f"Held-out rows not read by hypothesis: {result.get('dataset', {}).get('held_out_rows_not_read_by_hypothesis')}",
        f"Timestamp basis: {result.get('timestamp_basis', {}).get('status')}",
        "",
        "Synthetic front-of-queue fills are not broker execution evidence.",
        f"Bootstrap: {result.get('inference', {}).get('bootstrap')}",
        "",
    ]
    for reason in hypothesis.get("reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`."])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fixed H-MM-02 on local MT5 data")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--timestamp-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = json.loads(args.timestamp_evidence.read_text(encoding="utf-8"))
    result = run(args.dataset_dir, evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(_render(result), encoding="utf-8")
    print(json.dumps({"status": result["hypotheses"][HYPOTHESIS]["status"], "discovery_rows": result["dataset"]["discovery_rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
