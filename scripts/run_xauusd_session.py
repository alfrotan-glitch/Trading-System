"""Run the fixed UTC session assay on a local MT5 raw dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qts.research.xauusd_session import REVERSAL_SPECS, SPECS, render_session_report, scan_dataset, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed UTC session assay")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--timestamp-evidence", type=Path, required=True)
    parser.add_argument("--family", choices=("momentum", "reversal"), default="momentum")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = json.loads(args.timestamp_evidence.read_text(encoding="utf-8"))
    specs = SPECS if args.family == "momentum" else REVERSAL_SPECS
    report = scan_dataset(args.dataset_dir, timestamp_evidence=evidence, specs=specs)
    write_report(report, args.output)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_session_report(report) + "\n", encoding="utf-8")
    print(json.dumps({"decision": report["decision"], "hypotheses": {key: value["verdict"] for key, value in report["hypotheses"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
