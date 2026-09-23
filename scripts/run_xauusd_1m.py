#!/usr/bin/env python
"""Runner for H-1M-01 1m Donchian breakout on verifiable tick-derived bars."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from qts.research.xauusd_directional_view import preflight_view
from qts.research.xauusd_1m import DISCOVERY_ROWS, OneMScan, evaluate_1m

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="H-1M-01 runner")
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=False)
    args = parser.parse_args(argv)

    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    from qts.research.xauusd_directional_view import DiscoveryIdentity

    identity = DiscoveryIdentity(rows=DISCOVERY_ROWS)
    paths, manifest_sha = preflight_view(args.view_dir, authority, identity=identity)

    scan = OneMScan()
    for p in sorted(paths):
        pf = pq.ParquetFile(p)
        for rg in range(pf.metadata.num_row_groups):
            tbl = pf.read_row_group(rg, columns=["bid", "ask", "time_msc"])
            scan.add_batch(
                tbl.column("bid").to_numpy(),
                tbl.column("ask").to_numpy(),
                tbl.column("time_msc").to_numpy(),
            )

    result = evaluate_1m(scan)
    result["view"] = {"view_manifest_sha256": manifest_sha, "discovery_rows": scan.rows, "cutoff_time_msc": scan.cutoff}
    result["discovery_rows_read"] = scan.rows
    result["held_out_rows_read"] = 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        hyp = result["hypotheses"]["H-1M-01"]
        md = f"# XAUUSD H-1M-01 1m Donchian 20/12 (SYNTHETIC_DERIVED) — discovery only\n\n## H-1M-01: {hyp['status']}\n"
        for r in hyp["reasons"]:
            md += f"- {r}\n"
        md += f"\nHeld-out 40%: CLOSED. Orders: 0. Demo execution: DISABLED. Bars derived from tick mids.\n"
        md += f"\nBars: {result['window'].get('n_bars')} Events: {result['window'].get('n_events')} Long {result['window'].get('n_long')} Short {result['window'].get('n_short')}\n"
        args.markdown.write_text(md, encoding="utf-8")

    print(json.dumps({"discovery_rows": scan.rows, "n_bars": result["window"].get("n_bars"), "status": result["hypotheses"]["H-1M-01"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
