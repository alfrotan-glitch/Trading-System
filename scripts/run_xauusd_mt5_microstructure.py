"""Run the fixed microstructure scan on a local MT5 raw dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qts.research.xauusd_microstructure import render_microstructure, scan_dataset, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed local MT5 microstructure scan")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--timestamp-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = json.loads(args.timestamp_evidence.read_text(encoding="utf-8"))
    report = scan_dataset(args.dataset_dir, timestamp_evidence=evidence)
    write_report(report, args.output)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_microstructure(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "timestamp_basis": report["timestamp_basis"]["status"],
                "hypotheses": {key: value.get("status") for key, value in report["hypotheses"].items()},
                "strategy_promoted": report["strategy_promoted"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
