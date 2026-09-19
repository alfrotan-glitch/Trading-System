"""Run deferred quality analysis on a local MT5 Parquet dataset only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qts.data.mt5_history import analyze_mt5_dataset, write_analysis_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a completed local MT5 Parquet dataset; MT5 is never imported")
    parser.add_argument("dataset", type=Path, help="completed Parquet dataset directory")
    parser.add_argument("--metadata", type=Path, help="acquisition metadata sidecar")
    parser.add_argument("--output", type=Path, required=True, help="private or approved derived analysis report")
    args = parser.parse_args(argv)
    try:
        report = analyze_mt5_dataset(args.dataset, metadata_path=args.metadata)
        write_analysis_report(report, args.output)
    except Exception as exc:  # noqa: BLE001 - CLI emits an explicit failure
        failure = {"schema": "qts.mt5_raw_tick_analysis.v1", "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        args.output.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
