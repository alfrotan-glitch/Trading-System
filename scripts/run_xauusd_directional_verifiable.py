#!/usr/bin/env python
"""
Run H-DIR-02 on the verifiable Discovery-only view (70,783,710 rows).

This is the same mechanism as H-DIR-01 but on the maximal prefix whose
every row-group is provably < cutoff without opening the mixed straddling part.
H-DIR-01 remains NOT RUN / BLOCKED; this is a distinct experiment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qts.research.xauusd_directional import DiscoveryIdentity
from qts.research.xauusd_directional_view import scan_attested_view

# H-DIR-02 identity: verifiable prefix ending at previous_complete_part
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
VERIFIABLE_ROWS = 70783710
SOURCE_ROWS = 139930971
SOURCE_ZIP_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
SOURCE_DATASET_SHA256 = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"

IDENTITY = DiscoveryIdentity(
    time_min=TIME_MIN,
    cutoff=CUTOFF,
    rows=VERIFIABLE_ROWS,
    source_rows=SOURCE_ROWS,
    zip_sha256=SOURCE_ZIP_SHA256,
    dataset_sha256=SOURCE_DATASET_SHA256,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run H-DIR-02 on verifiable Discovery view")
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=False)
    args = parser.parse_args(argv)

    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    report = scan_attested_view(args.view_dir, authority, identity=IDENTITY)
    # Annotate as H-DIR-02, preserve original H-DIR-01 constants in report
    report["hypothesis_id"] = "H-DIR-02"
    report["preregistration"] = "docs/xauusd_directional_next_step_H-DIR-02_2026-09-23.md"
    report["verifiable_discovery_rows"] = VERIFIABLE_ROWS
    report["canonical_discovery_rows"] = 70834426
    report["omitted_rows_due_to_straddle"] = 70834426 - VERIFIABLE_ROWS
    report["note"] = "H-DIR-01 remains BLOCKED; this is H-DIR-02 on maximal verifiable prefix (99.928%)."

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.markdown:
        from qts.research.xauusd_directional import render_report

        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        # Reuse renderer but adjust header
        md = render_report(report).replace("H-DIR-01", "H-DIR-02")
        args.markdown.write_text(md, encoding="utf-8")

    print(
        json.dumps(
            {
                "hypothesis": "H-DIR-02",
                "status": report["hypotheses"]["H-DIR-01"]["status"] if "H-DIR-01" in report["hypotheses"] else report.get("decision"),
                "held_out_span_opened": report.get("held_out_span_opened"),
                "discovery_rows": VERIFIABLE_ROWS,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
