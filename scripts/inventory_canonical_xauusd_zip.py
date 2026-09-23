#!/usr/bin/env python3
"""Inventory the canonical XAUUSD tick zip. Does not claim an edge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qts.data.canonical_zip_inventory import (
    CANONICAL_ZIP_SHA256,
    exit_code,
    inventory_zip,
    write_inventory,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed inventory of the canonical XAUUSD zip")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-sha256", default=CANONICAL_ZIP_SHA256)
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    report = inventory_zip(args.zip, expected_sha256=args.expected_sha256, work_dir=args.work_dir)
    write_inventory(report, args.output)
    print(f"status={report['status']} checksum_match={report['checksum_match']} edge_claim={report['edge_claim']}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
