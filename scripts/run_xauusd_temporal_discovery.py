#!/usr/bin/env python
"""Run temporal descriptive discovery on verifiable Discovery view."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from qts.research.xauusd_temporal_discovery import discover_temporal
from qts.research.xauusd_directional_view import preflight_view
from qts.research.xauusd_directional import DiscoveryIdentity

IDENTITY = DiscoveryIdentity(rows=70783710)  # verifiable
VIEW_IDENTITY = DiscoveryIdentity(rows=70783710)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Temporal descriptive on verifiable view")
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=False)
    args = parser.parse_args(argv)

    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    paths, manifest_sha = preflight_view(args.view_dir, authority, identity=VIEW_IDENTITY)

    # Stream all time_msc, bid, ask for descriptive (still discovery-only, no held-out)
    times, bids, asks = [], [], []
    for p in paths:
        pf = pq.ParquetFile(p)
        for rg in range(pf.metadata.num_row_groups):
            tbl = pf.read_row_group(rg, columns=["time_msc", "bid", "ask"])
            times.append(tbl.column("time_msc").to_numpy())
            bids.append(tbl.column("bid").to_numpy())
            asks.append(tbl.column("ask").to_numpy())
    time_msc = np.concatenate(times) if times else np.array([], dtype=np.int64)
    bid = np.concatenate(bids) if bids else np.array([], dtype=np.float64)
    ask = np.concatenate(asks) if asks else np.array([], dtype=np.float64)

    result = discover_temporal(time_msc, bid, ask)
    result["view"] = {
        "view_manifest_sha256": manifest_sha,
        "discovery_rows": int(len(time_msc)),
        "view_identity_rows": IDENTITY.rows,
    }
    result["preregistration"] = "descriptive only, not a hypothesis test"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        # Simple markdown
        md = "# Temporal descriptive — verifiable Discovery (raw hour, no UTC claim)\n\n"
        md += f"Rows: {result['discovery_rows']}\n\n"
        md += "## Ticks by raw hour (time_msc % 86400000 // 3600000)\n\n"
        md += "| raw_hour | n | mean_spread |\n|---|---:|---:|\n"
        for row in result["spread_by_raw_hour"]:
            md += f"| {row['raw_hour']} | {row['n']} | {row['mean_spread']:.4f} |\n" if row["mean_spread"] is not None else f"| {row['raw_hour']} | 0 | - |\n"
        md += "\n*Descriptive only — no hypothesis tested, no UTC claim.*\n"
        args.markdown.write_text(md, encoding="utf-8")

    print(json.dumps({"discovery_rows": len(time_msc), "raw_hours_covered": sum(1 for c in result["ticks_by_raw_hour"] if c > 0)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
