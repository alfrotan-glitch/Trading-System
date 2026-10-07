#!/usr/bin/env python3
"""Support commands for the GitHub-hosted canonical-zip inventory job.

These commands do not download the release, do not extract members, and do
not repair rows. The workflow calls them only after the runner has the zip.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
RESERVE_BYTES = 1_000_000_000


def disk_is_sufficient(free_bytes: int, uncompressed_bytes: int, reserve_bytes: int = RESERVE_BYTES) -> bool:
    return free_bytes >= uncompressed_bytes + reserve_bytes


def _code_identity(module: str) -> dict[str, str]:
    return {
        "git_sha": os.environ.get("GITHUB_SHA", "UNAVAILABLE"),
        "execution_host": os.environ.get("QTS_INVENTORY_EXECUTION_HOST", "UNAVAILABLE"),
        "module": module,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def measure_disk(zip_path: Path, work_dir: Path) -> dict[str, Any]:
    """Read the zip central directory only. Does not extract."""
    usage = shutil.disk_usage(work_dir)
    record: dict[str, Any] = {
        "schema": "qts.runner_disk.v1",
        "zip_bytes": zip_path.stat().st_size if zip_path.is_file() else 0,
        "disk_path": str(work_dir),
        "disk_total": usage.total,
        "disk_free": usage.free,
        "reserve_bytes": RESERVE_BYTES,
        "zip_open": "NOT_OPENED",
        "sufficient": None,
    }
    if not zip_path.is_file():
        record["zip_open"] = "ABSENT"
        return record
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            uncompressed = sum(info.file_size for info in infos)
            record["zip_open"] = "CENTRAL_DIRECTORY_ONLY"
            record["member_count"] = len(infos)
            record["uncompressed_bytes"] = uncompressed
            record["largest_member_bytes"] = max((info.file_size for info in infos), default=0)
            record["sufficient"] = disk_is_sufficient(usage.free, uncompressed)
    except zipfile.BadZipFile as exc:
        record["zip_open"] = "UNREADABLE"
        record["error"] = str(exc)
    return record


def disk_insufficient_report(disk: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "qts.canonical_zip_inventory.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "canonical_release": "dataset-xauusd-730d-20260919",
        "canonical_asset": "XAUUSD_730d_20260919T114013Z.zip",
        "expected_sha256": EXPECTED_SHA256,
        "verified_sha256": EXPECTED_SHA256,
        "checksum_match": True,
        "bytes_present": disk.get("zip_bytes"),
        "status": "DISK_INSUFFICIENT",
        "extracted": False,
        "repairs_applied": [],
        "defects": [
            {
                "code": "DISK_INSUFFICIENT",
                "detail": (
                    "checksum matched; extraction was not attempted because runner free space "
                    "is below uncompressed size plus reserve"
                ),
                "repaired": False,
            }
        ],
        "inventory": None,
        "datasets": [],
        "edge_claim": "NOT ESTABLISHED",
        "decision_supported": False,
        "code_identity": _code_identity("scripts.github_runner_inventory_support"),
        "provenance": "zip SHA-256 matched on the GitHub-hosted runner; rows were not extracted, read, or repaired",
        "runner_disk": disk,
    }


def missing_report() -> dict[str, Any]:
    return {
        "schema": "qts.canonical_zip_inventory.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "canonical_release": "dataset-xauusd-730d-20260919",
        "canonical_asset": "XAUUSD_730d_20260919T114013Z.zip",
        "expected_sha256": EXPECTED_SHA256,
        "verified_sha256": None,
        "checksum_match": False,
        "bytes_present": 0,
        "status": "UNAVAILABLE",
        "extracted": False,
        "repairs_applied": [],
        "defects": [
            {
                "code": "RUNNER_STOPPED_BEFORE_INVENTORY",
                "detail": "the GitHub-hosted job did not produce an inventory report",
                "repaired": False,
            }
        ],
        "inventory": None,
        "datasets": [],
        "edge_claim": "NOT ESTABLISHED",
        "decision_supported": False,
        "code_identity": _code_identity("scripts.github_runner_inventory_support"),
        "provenance": "NOT ESTABLISHED — the runner did not verify the archive",
    }


def summary_of(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": report.get("status"),
        "checksum_match": report.get("checksum_match"),
        "verified_sha256": report.get("verified_sha256"),
        "bytes_present": report.get("bytes_present"),
        "extracted": report.get("extracted"),
        "edge_claim": report.get("edge_claim"),
        "decision_supported": report.get("decision_supported"),
        "defect_codes": [item.get("code") for item in report.get("defects") or []],
        "dataset_count": len(report.get("datasets") or []),
    }
    datasets = report.get("datasets") or []
    if datasets:
        content = datasets[0].get("content") or {}
        summary["row_count"] = content.get("row_count")
        summary["time_msc_min"] = content.get("time_msc_min")
        summary["time_msc_max"] = content.get("time_msc_max")
        summary["recomputed_dataset_sha256"] = datasets[0].get("recomputed_dataset_sha256")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub-hosted inventory support. Does not download or extract.")
    sub = parser.add_subparsers(dest="command", required=True)

    disk = sub.add_parser("disk-preflight")
    disk.add_argument("--zip", required=True, type=Path)
    disk.add_argument("--work-dir", required=True, type=Path)
    disk.add_argument("--output", required=True, type=Path)

    blocked = sub.add_parser("disk-insufficient-report")
    blocked.add_argument("--disk-json", required=True, type=Path)
    blocked.add_argument("--output", required=True, type=Path)

    missing = sub.add_parser("missing-report")
    missing.add_argument("--output", required=True, type=Path)

    summarize = sub.add_parser("summary")
    summarize.add_argument("--inventory", required=True, type=Path)
    summarize.add_argument("--output", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "disk-preflight":
        record = measure_disk(args.zip, args.work_dir)
        _write(args.output, record)
        print(json.dumps(record))
        if record["sufficient"] is False:
            return 4
        return 0
    if args.command == "disk-insufficient-report":
        disk_record = json.loads(args.disk_json.read_text(encoding="utf-8"))
        _write(args.output, disk_insufficient_report(disk_record))
        return 0
    if args.command == "missing-report":
        _write(args.output, missing_report())
        return 0
    report = json.loads(args.inventory.read_text(encoding="utf-8"))
    payload = summary_of(report)
    _write(args.output, payload)
    text = json.dumps(payload, indent=2)
    print("BEGIN_QTS_INVENTORY_SUMMARY")
    print(text)
    print("END_QTS_INVENTORY_SUMMARY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
