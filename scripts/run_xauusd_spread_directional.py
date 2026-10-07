#!/usr/bin/env python
"""
Run H-DIR-03 spread-state directional on verifiable Discovery view.

Reuses the same verifiable 70,783,710-row view as H-DIR-02.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from qts.research.xauusd_spread_directional import (
    IDENTITY,
    SpreadDirectionalScan,
    evaluate_spread,
)

# Reuse view infrastructure's preflight but with H-DIR-03 identity
from qts.research.xauusd_directional_view import preflight_view
from qts.research.xauusd_directional import DiscoveryIdentity as ViewIdentity

# Map H-DIR-03 identity to view identity type expected by preflight
VIEW_IDENTITY = ViewIdentity(
    time_min=IDENTITY.time_min,
    cutoff=IDENTITY.cutoff,
    rows=IDENTITY.rows,
    source_rows=IDENTITY.source_rows,
    zip_sha256=IDENTITY.zip_sha256,
    dataset_sha256=IDENTITY.dataset_sha256,
)


def scan_view(view_dir: Path, authority: dict) -> dict:
    # Validate view via preflight (checks every row-group < cutoff, SHA, etc.)
    paths, manifest_sha = preflight_view(view_dir, authority, identity=VIEW_IDENTITY)
    scan = SpreadDirectionalScan(time_min=IDENTITY.time_min, cutoff=IDENTITY.cutoff)
    for path in paths:
        pf = pq.ParquetFile(path)
        for rg in range(pf.metadata.num_row_groups):
            # Defensive time check before reading bid/ask
            time_col = pf.read_row_group(rg, columns=["time_msc"]).column("time_msc").to_numpy()
            import numpy as np

            stamps = np.asarray(time_col, dtype=np.int64)
            if np.any(stamps >= IDENTITY.cutoff):
                raise ValueError("time_msc crossed cutoff")
            batch = pf.read_row_group(rg, columns=["bid", "ask"])
            scan.add_batch(batch.column("bid").to_numpy(), batch.column("ask").to_numpy(), stamps)
    if scan.rows != IDENTITY.rows:
        raise ValueError(f"row count {scan.rows} != {IDENTITY.rows}")
    report = evaluate_spread(scan, complete_rows=IDENTITY.rows)
    report["view"] = {
        "view_manifest_sha256": manifest_sha,
        "part_count": len(paths),
        "source_zip_sha256": IDENTITY.zip_sha256,
        "source_dataset_sha256": IDENTITY.dataset_sha256,
        "discovery_rows": IDENTITY.rows,
        "cutoff_time_msc": IDENTITY.cutoff,
    }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run H-DIR-03 spread-state directional")
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=False)
    args = parser.parse_args(argv)

    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    report = scan_view(args.view_dir, authority)
    report["hypothesis_family"] = "H-DIR-03"
    report["preregistration"] = "docs/xauusd_directional_next_step_H-DIR-03_2026-09-23.md"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.markdown:
        from qts.research.xauusd_spread_directional import render_report

        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_report(report), encoding="utf-8")

    # Print summary
    print(
        json.dumps(
            {
                "hypotheses": {k: v["status"] for k, v in report["hypotheses"].items()},
                "decision": report["decision"],
                "held_out_span_opened": report["held_out_span_opened"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
