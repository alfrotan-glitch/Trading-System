"""Run preregistered discovery-window tests on the canonical zip.

The zip is hashed before extraction. Rows are not repaired. The locked span
is not aggregated by the hypothesis tests. This script does not promote a
strategy and does not submit an order.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from qts.data.canonical_zip_inventory import CANONICAL_ZIP_SHA256, _extract, _unsafe_member
from qts.data.mt5_history_acquisition import MANIFEST_FILENAME, sha256_file
from qts.research.xauusd_tick_discovery import render_research_state, scan_dataset, write_report


def _fail(output: Path, markdown: Path, status: str, detail: str) -> int:
    report = {
        "schema": "qts.xauusd_tick_discovery.v1",
        "status": status,
        "detail": detail,
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "decision": "INCONCLUSIVE",
        "safety": {"confirm_live": False, "orders_submitted": 0, "DEMO_EXECUTION": "DISABLED"},
    }
    write_report(report, output)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_research_state(report) + "\n", encoding="utf-8")
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
        return _fail(output, markdown, "CHECKSUM_MISMATCH", "zip SHA-256 does not match the canonical digest; not extracted")
    with zipfile.ZipFile(zip_path) as zf:
        unsafe = [info.filename for info in zf.infolist() if _unsafe_member(info.filename)]
        if unsafe:
            return _fail(output, markdown, "ARCHIVE_UNSAFE", "extraction refused")
        dest = Path(args.work_dir)
        _extract(zf, dest)
    manifests = sorted(dest.rglob(MANIFEST_FILENAME))
    if not manifests:
        return _fail(output, markdown, "LAYOUT_UNAVAILABLE", "no acquisition manifest after extraction")
    report = scan_dataset(manifests[0].parent)
    report["verified_zip_sha256"] = digest
    report["checksum_match"] = True
    write_report(report, output)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_research_state(report) + "\n", encoding="utf-8")
    summary = {
        "decision": report["decision"],
        "edge_claim": report["edge_claim"],
        "strategy_promoted": report["strategy_promoted"],
        "H-MS-01": report["hypotheses"]["H-MS-01"]["verdict"],
        "H-MS-02": report["hypotheses"]["H-MS-02"]["verdict"],
        "H-TOD-01": report["hypotheses"]["H-TOD-01"],
    }
    output.with_name("xauusd_discovery_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
