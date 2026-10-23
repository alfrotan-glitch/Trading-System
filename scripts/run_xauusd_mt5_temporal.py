"""Run the preregistered H-TEMP-01 assay on a local MT5 tick ledger.

Only the chronological discovery prefix is passed to the existing locked
TemporalScan. The held-out suffix is never read by the hypothesis engine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.data.mt5_timestamp_basis import timestamp_basis_assessment
from qts.research.xauusd_temporal import TemporalScan, evaluate_temporal
from qts.research.xauusd_tick_discovery import discovery_cutoff


def _stamp_range(dataset_dir: Path, parts: list[dict[str, Any]]) -> tuple[int, int]:
    minimum: int | None = None
    maximum: int | None = None
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc"]):
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            if stamp.size == 0:
                continue
            lo, hi = int(stamp.min()), int(stamp.max())
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
    scan = TemporalScan(time_min=time_min, cutoff=cutoff)
    source_rows = 0
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc", "bid", "ask"]):
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            keep = stamp < cutoff
            source_rows += int(np.count_nonzero(keep))
            if not keep.any():
                continue
            scan.add_batch(
                batch.column("bid").to_numpy(zero_copy_only=False)[keep],
                batch.column("ask").to_numpy(zero_copy_only=False)[keep],
                stamp[keep],
            )
    result = evaluate_temporal(scan, complete_rows=source_rows)
    result["dataset"] = {
        "manifest_dataset_sha256": manifest.get("dataset_sha256"),
        "source_rows": manifest.get("row_count"),
        "discovery_rows": scan.rows,
        "held_out_rows_not_read_by_hypothesis": int(manifest.get("row_count") or 0) - source_rows,
        "time_msc_min": time_min,
        "time_msc_max": time_max,
        "cutoff_time_msc": cutoff,
    }
    result["timestamp_basis"] = timestamp_basis_assessment(manifest, evidence)
    result["safety"] = {
        "orders_submitted": 0,
        "order_send_called": False,
        "DEMO_EXECUTION": "DISABLED",
        "LIVE": "LOCKED",
    }
    return result


def _render(result: dict[str, Any]) -> str:
    hypothesis = result.get("hypotheses", {}).get("H-TEMP-01", {})
    lines = [
        "# XAUUSD H-TEMP-01 raw-hour magnitude on local MT5 data",
        "",
        f"Status: {hypothesis.get('status')}",
        f"Discovery rows: {result.get('dataset', {}).get('discovery_rows')}",
        f"Held-out rows not read by hypothesis: {result.get('dataset', {}).get('held_out_rows_not_read_by_hypothesis')}",
        f"Timestamp basis: {result.get('timestamp_basis', {}).get('status')}",
        "",
        "This is a fixed magnitude test, not a directional strategy or promotion.",
        "",
    ]
    for reason in hypothesis.get("reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`."])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fixed H-TEMP-01 on local MT5 data")
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
    print(json.dumps({"status": result["hypotheses"]["H-TEMP-01"]["status"], "discovery_rows": result["dataset"]["discovery_rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
