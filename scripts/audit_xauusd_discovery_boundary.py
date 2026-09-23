#!/usr/bin/env python3
"""Metadata-only audit of the already published canonical XAUUSD release ZIP.

This is NOT the H-DIR-01 runner. It hashes the ZIP as opaque bytes, reads its
central directory and opens *only manifest.json*. It must never open, extract,
scan or decode a quote/Parquet member, whether discovery or held-out. The
purpose is to decide if a discovery view can consist of unchanged whole parts.
If the split is inside a part, STOP: this tool must not probe its quote rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

SOURCE_RELEASE = "dataset-xauusd-730d-20260919"
SOURCE_ASSET = "XAUUSD_730d_20260919T114013Z.zip"
SOURCE_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
DATASET_SHA256 = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
PUBLISHED_MANIFEST_SHA256 = "d9a61ad583002c6e24f2ad04aee6399e6ec00a9a47928712a7c3f4418e15972f"
TIME_MIN = 1_726_746_013_452
TIME_MAX = 1_789_775_939_790
CUTOFF = 1_764_563_969_254
ROWS = 139_930_971
DISCOVERY_ROWS = 70_834_426
LOCKED_ROWS = ROWS - DISCOVERY_ROWS
SCHEMA = "qts.xauusd_discovery_boundary_audit.v1"
PART = re.compile(r"parts/part-([0-9]{6})\.parquet\Z")


class MetadataAuditBlocked(ValueError):
    """No access boundary can be attested from this source metadata."""


def sha256_file(path: Path) -> str:
    """Opaque compressed bytes ONLY; never decodes or inspects a quote row."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1 << 20), b""):
            digest.update(data)
    return digest.hexdigest()


def dataset_digest(part_hashes: dict[str, str]) -> str:
    """The acquisition ledger's v1 definition; metadata hashes, not file reads."""
    digest = hashlib.sha256(b"qts.mt5_raw_tick_dataset.v1\n")
    for name in sorted(part_hashes):
        digest.update(f"{name} {part_hashes[name]}\n".encode())
    return digest.hexdigest()


def _safe_member(name: str) -> str:
    relative = name.replace("\\", "/")
    if relative.startswith("/") or ":" in relative[:3] or ".." in Path(relative).parts:
        raise MetadataAuditBlocked("ZIP central directory contains an unsafe member name")
    return relative


def audit_zip(
    path: Path,
    *,
    expected_sha: str = SOURCE_SHA256,
    expected_manifest_sha: str = PUBLISHED_MANIFEST_SHA256,
    expected_dataset_sha: str = DATASET_SHA256,
    expected_rows: int = ROWS,
    discovery_rows: int = DISCOVERY_ROWS,
) -> dict[str, Any]:
    """A manifest-only audit. The only ZipFile.open call MUST name manifest.json."""
    if not path.is_file():
        raise MetadataAuditBlocked("archive not available for metadata-only audit")
    actual_hash = sha256_file(path)
    if actual_hash != expected_sha:
        raise MetadataAuditBlocked("opaque archive SHA-256 differs from the published source")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()  # ZIP *container metadata*, not quote rows
        if len(infos) != len({_safe_member(info.filename) for info in infos}):
            raise MetadataAuditBlocked("duplicate ZIP member names after separator normalization")
        members = {_safe_member(info.filename): info for info in infos}
        if "manifest.json" not in members or members["manifest.json"].file_size > 2_000_000:
            raise MetadataAuditBlocked("bounded acquisition manifest missing")
        # The single allowed member open: no Parquet member is extracted or decoded.
        manifest_bytes = archive.read(members["manifest.json"])
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != expected_manifest_sha:
            raise MetadataAuditBlocked("manifest SHA-256 differs from the independently published gap evidence")
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise MetadataAuditBlocked("acquisition manifest must be an object")
        if manifest.get("schema") != "qts.mt5_raw_tick_acquisition.v1" or manifest.get("status") != "COMPLETE":
            raise MetadataAuditBlocked("acquisition manifest schema/status not final")
        if manifest.get("row_count") != expected_rows:
            raise MetadataAuditBlocked("manifest row count differs from verified inventory")
        if manifest.get("raw_time_msc_min") != TIME_MIN or manifest.get("raw_time_msc_max") != TIME_MAX:
            raise MetadataAuditBlocked("manifest time range differs from verified inventory")
        if manifest.get("dataset_sha256") != expected_dataset_sha:
            raise MetadataAuditBlocked("manifest dataset digest differs from published provenance")
        parts = manifest.get("parts")
        if not isinstance(parts, list) or not parts or len(parts) > 20_000:
            raise MetadataAuditBlocked("acquisition part ledger absent or unexpectedly large")
        part_hashes: dict[str, str] = {}
        cumulative = 0
        boundary: dict[str, Any] | None = None
        earlier: dict[str, Any] | None = None
        exact_boundary: dict[str, Any] | None = None
        for idx, part in enumerate(parts):
            if not isinstance(part, dict) or not isinstance(part.get("chunk"), dict):
                raise MetadataAuditBlocked("invalid part/chunk record")
            name = part.get("part")
            match = PART.fullmatch("parts/" + str(name))
            if match is None or int(match.group(1)) != idx or name in part_hashes:
                raise MetadataAuditBlocked("non-contiguous or invalid original part ledger")
            count, length, digest = part.get("rows"), part.get("size_bytes"), part.get("sha256")
            if type(count) is not int or count < 0 or type(length) is not int or length < 0:
                raise MetadataAuditBlocked("part count or byte size invalid")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise MetadataAuditBlocked("part SHA-256 absent from original ledger")
            source = members.get("parts/" + name)
            if source is None or source.file_size != length:
                raise MetadataAuditBlocked("ledger part absent or length differs from ZIP central directory")
            part_hashes[name] = digest
            before, cumulative = cumulative, cumulative + count
            summary = {
                "part_index": idx,
                "part": name,
                "rows": count,
                "global_row_start_inclusive": before,
                "global_row_end_exclusive": cumulative,
            }
            if before < discovery_rows < cumulative:
                boundary = {
                    **summary,
                    "discovery_rows_within_part": discovery_rows - before,
                    "locked_rows_within_part": cumulative - discovery_rows,
                    "chunk_request_start": (part.get("chunk") or {}).get("start_utc"),
                    "chunk_request_end": (part.get("chunk") or {}).get("end_utc"),
                }
            if cumulative < discovery_rows:
                earlier = summary
            if cumulative == discovery_rows:
                exact_boundary = summary
        if cumulative != expected_rows or dataset_digest(part_hashes) != expected_dataset_sha:
            raise MetadataAuditBlocked("part row sum or acquisition dataset digest differs from verified source")
        if set(members) != {"manifest.json", *("parts/" + p for p in part_hashes)}:
            raise MetadataAuditBlocked("ZIP contains an unledgered member")
        if discovery_rows <= 0 or discovery_rows >= expected_rows:
            raise MetadataAuditBlocked("discovery split is out of range")
        if boundary is None and exact_boundary is None:
            raise MetadataAuditBlocked("discovery prefix cannot be located in the original part ledger")
        return {
            "schema": SCHEMA,
            "source": {
                "release": SOURCE_RELEASE,
                "asset": SOURCE_ASSET,
                "zip_sha256": actual_hash,
                "manifest_sha256": manifest_hash,
                "dataset_sha256": expected_dataset_sha,
            },
            "published_boundary": {
                "time_msc_min": TIME_MIN,
                "cutoff_time_msc_exclusive": CUTOFF,
                "time_msc_max": TIME_MAX,
                "rows_total": expected_rows,
                "rows_discovery": discovery_rows,
                "rows_held_out_not_read": expected_rows - discovery_rows,
            },
            "manifest_part_count": len(parts),
            "exact_immutable_part_boundary": exact_boundary is not None,
            "discovery_end_part": exact_boundary,
            "straddling_part": boundary,
            "previous_complete_part": earlier,
            "disposition": (
                "EXACT_PART_BOUNDARY_VIEW_REQUIRES_SEPARATE_VERIFICATION"
                if exact_boundary is not None
                else "NO_SAFE_DISCOVERY_VIEW_FROM_IMMUTABLE_PARTS"
            ),
            "held_out_quote_members_opened": 0,
            "quote_rows_decoded": 0,
            "inspection_scope": (
                "SHA-256 of opaque compressed ZIP bytes; ZIP central-directory metadata; "
                "manifest.json only. No Parquet/quote member was opened, extracted or decoded."
            ),
            "h_dir_01_ran": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canonical XAUUSD manifest-only discovery boundary audit")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit_zip(args.zip)
    except (MetadataAuditBlocked, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        result = {
            "schema": SCHEMA,
            "disposition": "BOUNDARY_NOT_ESTABLISHED",
            "reason": str(exc),
            "held_out_quote_members_opened": 0,
            "quote_rows_decoded": 0,
            "h_dir_01_ran": False,
        }
        code = 2
    else:
        code = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"disposition": result["disposition"], "h_dir_01_ran": False, "held_out_quote_members_opened": 0}))
    return code


if __name__ == "__main__":
    sys.exit(main())
