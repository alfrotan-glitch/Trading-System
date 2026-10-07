"""Run the preregistered state-conditional scan on the canonical zip.

The zip is hashed before extraction. Rows are not repaired. The locked span
is not used to choose a feature, a threshold, or a state. No strategy is promoted.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from qts.data.canonical_zip_inventory import CANONICAL_ZIP_SHA256, _extract, _unsafe_member
from qts.data.mt5_history_acquisition import MANIFEST_FILENAME, sha256_file
from qts.research.xauusd_state_scan import render_state_report, scan_dataset, write_report


def _fail(output: Path, markdown: Path, status: str, detail: str) -> int:
    report = {
        "schema": "qts.xauusd_state_scan.v1",
        "status": status,
        "detail": detail,
        "decision": "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "timestamp_basis": {"status": "BLOCKED", "evidence": detail},
        "hypotheses": {},
        "hypothesis_generators": [],
        "safety": {"confirm_live": False, "orders_submitted": 0, "DEMO_EXECUTION": "DISABLED"},
    }
    write_report(report, output)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_state_report(report) + "\n", encoding="utf-8")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args(argv)
    zip_path = Path(args.zip)
    output = Path(args.output)
    markdown = Path(args.markdown)
    if not zip_path.is_file():
        return _fail(output, markdown, "ARCHIVE_ABSENT", f"{zip_path} is not a file")
    digest = sha256_file(zip_path)
    if digest != CANONICAL_ZIP_SHA256:
        return _fail(output, markdown, "CHECKSUM_MISMATCH", "zip SHA-256 does not match; archive was not extracted")
    with zipfile.ZipFile(zip_path) as zf:
        unsafe = [info.filename for info in zf.infolist() if _unsafe_member(info.filename)]
        if unsafe:
            return _fail(output, markdown, "ARCHIVE_UNSAFE", "extraction refused")
        _extract(zf, Path(args.work_dir))
    manifests = sorted(Path(args.work_dir).rglob(MANIFEST_FILENAME))
    if not manifests:
        return _fail(output, markdown, "LAYOUT_UNAVAILABLE", "no acquisition manifest after extraction")
    report = scan_dataset(manifests[0].parent)
    report["verified_zip_sha256"] = digest
    report["checksum_match"] = True
    write_report(report, output)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_state_report(report) + "\n", encoding="utf-8")
    summary = {
        "decision": report["decision"],
        "strategy_promoted": report["strategy_promoted"],
        "held_out_span_opened": report["held_out_span_opened"],
        "hypotheses": {key: value.get("status") for key, value in report["hypotheses"].items()},
        "hypothesis_generators": len(report.get("hypothesis_generators") or []),
        "timestamp_basis": report["timestamp_basis"]["status"],
        "rows": report.get("rows"),
        "cutoff_time_msc": (report.get("window") or {}).get("cutoff_time_msc"),
    }
    output.with_name("xauusd_state_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
