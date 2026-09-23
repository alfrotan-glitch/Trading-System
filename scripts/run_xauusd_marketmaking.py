#!/usr/bin/env python
"""Runner for H-MM-01 market-making spread capture on verifiable Discovery view."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from qts.research.xauusd_directional_view import preflight_view
from qts.research.xauusd_marketmaking import DISCOVERY_ROWS, MarketMakingScan, evaluate_marketmaking

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="H-MM-01 runner")
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=False)
    args = parser.parse_args(argv)

    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    from qts.research.xauusd_directional_view import DiscoveryIdentity

    identity = DiscoveryIdentity(rows=DISCOVERY_ROWS)
    paths, manifest_sha = preflight_view(args.view_dir, authority, identity=identity)

    scan = MarketMakingScan()
    for p in sorted(paths):
        pf = pq.ParquetFile(p)
        for rg in range(pf.metadata.num_row_groups):
            tbl = pf.read_row_group(rg, columns=["bid", "ask", "time_msc"])
            scan.add_batch(
                tbl.column("bid").to_numpy(),
                tbl.column("ask").to_numpy(),
                tbl.column("time_msc").to_numpy(),
            )

    result = evaluate_marketmaking(scan, complete_rows=DISCOVERY_ROWS)
    result["view"] = {"view_manifest_sha256": manifest_sha, "discovery_rows": scan.rows, "cutoff_time_msc": scan.cutoff}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        hyp = result["hypotheses"]["H-MM-01"]
        md = f"# XAUUSD H-MM-01 market-making (16 fill / 256 exc) — discovery only\n\n## H-MM-01: {hyp['status']}\n"
        for r in hyp["reasons"]:
            md += f"- {r}\n"
        md += f"\nHeld-out 40%: CLOSED. Orders: 0. Demo execution: DISABLED. SYNTHETIC fills.\n"
        md += f"\nFill/Exc: {result['measured'].get('16_fill_256_exc')}\n"
        args.markdown.write_text(md, encoding="utf-8")

    print(json.dumps({"discovery_rows": scan.rows, "status": result["hypotheses"]["H-MM-01"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
