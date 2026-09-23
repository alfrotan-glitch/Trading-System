#!/usr/bin/env python
"""
Build a verifiable Discovery-only view from the canonical ZIP without touching held-out.

Selects only immutable whole parts whose global row interval lies entirely
before the previous complete part boundary (70,783,710). Never opens
part-000441 or any later part (which contain held-out rows).

The only ZipFile.open() call is for manifest.json; selected parts are
stream-copied via ZipFile.read() after ledger verification, and their
Parquet footers are checked for time_msc bounds before inclusion.
No quote bid/ask column is read beyond time_msc stats during building.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pyarrow.parquet as pq

# Canonical identity (same as H-DIR-01) but rows truncated to verifiable prefix
SOURCE_RELEASE = "dataset-xauusd-730d-20260919"
SOURCE_ASSET = "XAUUSD_730d_20260919T114013Z.zip"
SOURCE_ZIP_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
SOURCE_DATASET_SHA256 = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
MANIFEST_SHA256 = "d9a61ad583002c6e24f2ad04aee6399e6ec00a9a47928712a7c3f4418e15972f"
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
SOURCE_ROWS = 139930971
# H-DIR-02 verifiable discovery rows: previous_complete_part end
VERIFIABLE_ROWS = 70783710
# Straddling part that must NEVER be opened
STRADDLING_PART = "part-000441.parquet"
VIEW_SCHEMA = "qts.xauusd_discovery_view.v1"
AUTHORITY_SCHEMA = "qts.xauusd_discovery_view_authority.v1"

PART_RE = re.compile(r"parts/part-([0-9]{6})\.parquet\Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dataset_digest(part_hashes: dict[str, str]) -> str:
    h = hashlib.sha256(b"qts.mt5_raw_tick_dataset.v1\n")
    for name in sorted(part_hashes):
        h.update(f"{name} {part_hashes[name]}\n".encode())
    return h.hexdigest()


def build_view(zip_path: Path, view_dir: Path, authority_path: Path) -> dict:
    zip_path = Path(zip_path)
    view_dir = Path(view_dir)
    authority_path = Path(authority_path)

    # 1. Verify ZIP opaque SHA
    actual_zip_sha = sha256_file(zip_path)
    if actual_zip_sha != SOURCE_ZIP_SHA256:
        raise SystemExit(f"ZIP SHA mismatch: {actual_zip_sha} != {SOURCE_ZIP_SHA256}")

    manifest_bytes = None
    manifest_sha = None
    manifest = None
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        # Normalize names (ZIP uses backslashes in original, but central dir stores them)
        def safe_name(n: str) -> str:
            return n.replace("\\", "/")
        members = {safe_name(info.filename): info for info in infos}
        # Debug: log central directory shape without opening quotes
        print(f"ZIP central directory: {len(members)} members, sample: {list(members)[:3]}", file=sys.stderr)
        if "manifest.json" not in members:
            raise SystemExit(f"manifest.json missing; members sample {list(members)[:5]}")
        # Only allowed open: manifest.json
        manifest_bytes = z.read(members["manifest.json"])
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_sha != MANIFEST_SHA256:
            raise SystemExit(f"manifest SHA mismatch: {manifest_sha} != {MANIFEST_SHA256}")
        manifest = json.loads(manifest_bytes)
        if manifest.get("schema") != "qts.mt5_raw_tick_acquisition.v1" or manifest.get("status") != "COMPLETE":
            raise SystemExit("manifest not COMPLETE acquisition")
        if manifest.get("row_count") != SOURCE_ROWS:
            raise SystemExit("manifest row_count mismatch")
        if manifest.get("dataset_sha256") != SOURCE_DATASET_SHA256:
            raise SystemExit("dataset digest mismatch")

        parts_ledger = manifest.get("parts")
        if not isinstance(parts_ledger, list):
            raise SystemExit("parts ledger missing")

        # Verify ledger integrity and determine verifiable prefix
        part_hashes: dict[str, str] = {}
        cumulative = 0
        selected_indices = []
        previous_complete_end = None
        straddling_found = False
        for idx, part in enumerate(parts_ledger):
            name = part.get("part")
            rows = part.get("rows")
            sha = part.get("sha256")
            m = PART_RE.fullmatch("parts/" + str(name))
            if m is None or int(m.group(1)) != idx:
                raise SystemExit(f"non-contiguous part ledger at {idx}: {name}")
            # members are keyed as "parts/part-XXXXXX.parquet"
            if f"parts/{name}" not in members:
                # Empty parts may be missing from ZIP central directory; allow but log
                print(f"WARNING: parts/{name} not in ZIP central dir (rows={rows})", file=sys.stderr)
                if rows > 0:
                    raise SystemExit(f"ZIP member missing for non-empty part {name}")
            if not isinstance(rows, int) or rows < 0:
                raise SystemExit(f"invalid rows for {name}")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise SystemExit(f"invalid sha for {name}")
            # Track cumulative
            before = cumulative
            cumulative += rows
            part_hashes[name] = sha
            # Detect straddling part (should be part-000441 with before < VERIFIABLE_ROWS < cumulative? Actually verifiable is 70783710, and straddling global is [70783710, 70916415)
            # For our verifiable rows, the boundary is exactly at start of straddling part, so before == VERIFIABLE_ROWS for straddling.
            # So we select parts where cumulative <= VERIFIABLE_ROWS and rows>0
            if cumulative <= VERIFIABLE_ROWS and rows > 0:
                selected_indices.append(idx)
            if name == STRADDLING_PART:
                straddling_found = True
                # Verify that straddling part indeed straddles original 70834426, not verifiable 70783710
                # But for verifiable, it should be entirely after verifiable prefix
                if before != VERIFIABLE_ROWS:
                    raise SystemExit(f"straddling part start {before} != verifiable rows {VERIFIABLE_ROWS}")
                if rows != 132705:
                    # Allow but log
                    pass

        if cumulative != SOURCE_ROWS:
            raise SystemExit("ledger row sum mismatch")
        if dataset_digest(part_hashes) != SOURCE_DATASET_SHA256:
            raise SystemExit("dataset digest mismatch from ledger")
        if not straddling_found:
            raise SystemExit("straddling part not found")
        # Safety: ensure we never selected straddling part or later
        if any(parts_ledger[i]["part"] == STRADDLING_PART for i in selected_indices):
            raise SystemExit("selected straddling part — must never happen")

        # Now build view directory
        parts_dir = view_dir / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        view_parts = []
        first_global = 0
        part_min_global = None
        part_max_global = None
        previous_stamp = None
        for idx in selected_indices:
            part = parts_ledger[idx]
            name = part["part"]
            rows = part["rows"]
            sha = part["sha256"]
            member_name = f"parts/{name}"
            if member_name not in members:
                raise SystemExit(f"ZIP member missing for selected part {name}; looked for {member_name}")
            zip_info = members[member_name]

            # Extract without decompressing held-out member: we only extract selected
            # Use read() which decompresses only this member's bytes (fully discovery)
            data = z.read(zip_info)
            # Verify length matches? We check hash after writing
            tmp_path = parts_dir / name
            tmp_path.write_bytes(data)
            actual_part_sha = sha256_file(tmp_path)
            if actual_part_sha != sha:
                raise SystemExit(f"part SHA mismatch after extract for {name}: {actual_part_sha} != {sha}")

            # Parquet footer check: time_msc bounds must be < CUTOFF
            try:
                pf = pq.ParquetFile(tmp_path)
            except Exception as e:
                raise SystemExit(f"parquet read failed for {name}: {e}") from e
            meta = pf.metadata
            if meta.num_rows != rows:
                raise SystemExit(f"row count mismatch for {name}: {meta.num_rows} != {rows}")
            if "time_msc" not in pf.schema_arrow.names:
                raise SystemExit(f"time_msc missing in {name}")
            ts_idx = pf.schema_arrow.names.index("time_msc")
            part_min = None
            part_max = None
            for rg in range(meta.num_row_groups):
                rg_meta = meta.row_group(rg)
                col = rg_meta.column(ts_idx)
                stats = col.statistics
                if stats is None or not stats.has_min_max or stats.null_count != 0:
                    raise SystemExit(f"row-group time bounds missing for {name} rg {rg}")
                lo = int(stats.min)
                hi = int(stats.max)
                if lo < TIME_MIN or hi >= CUTOFF or lo > hi:
                    raise SystemExit(f"time bounds violate discovery for {name} rg {rg}: {lo}-{hi}")
                if previous_stamp is not None and lo < previous_stamp:
                    raise SystemExit(f"time not monotonic across parts at {name}")
                previous_stamp = hi
                part_min = lo if part_min is None else min(part_min, lo)
                part_max = hi if part_max is None else max(part_max, hi)
            if part_min is None or part_max is None:
                raise SystemExit(f"no time bounds for {name}")
            # Record view manifest entry
            view_parts.append(
                {
                    "part": name,
                    "rows": rows,
                    "sha256": sha,
                    "first_global_row": first_global,
                    "min_time_msc": part_min,
                    "max_time_msc": part_max,
                }
            )
            if part_min_global is None:
                part_min_global = part_min
            part_max_global = part_max
            first_global += rows

        if first_global != VERIFIABLE_ROWS:
            raise SystemExit(f"verifiable view row sum {first_global} != {VERIFIABLE_ROWS}")
        if not view_parts:
            raise SystemExit("no view parts selected")

        # Build view manifest
        view_manifest = {
            "schema": VIEW_SCHEMA,
            "status": "COMPLETE_DISCOVERY_ONLY",
            "source_release": SOURCE_RELEASE,
            "source_asset": SOURCE_ASSET,
            "source_zip_sha256": SOURCE_ZIP_SHA256,
            "source_manifest_sha256": MANIFEST_SHA256,
            "source_dataset_sha256": SOURCE_DATASET_SHA256,
            "time_msc_min": TIME_MIN,
            "time_msc_max": part_max_global,
            "cutoff_time_msc": CUTOFF,
            "discovery_rows": VERIFIABLE_ROWS,
            "source_rows": SOURCE_ROWS,
            "part_count": len(view_parts),
            "parts": view_parts,
        }

        view_manifest_path = view_dir / "manifest.json"
        view_manifest_path.write_text(json.dumps(view_manifest, indent=2) + "\n", encoding="utf-8")
        view_manifest_sha = sha256_file(view_manifest_path)

        # Build authority file
        authority = {
            "schema": AUTHORITY_SCHEMA,
            "source_zip_sha256": SOURCE_ZIP_SHA256,
            "source_dataset_sha256": SOURCE_DATASET_SHA256,
            "cutoff_time_msc": CUTOFF,
            "discovery_rows": VERIFIABLE_ROWS,
            "view_manifest_sha256": view_manifest_sha,
            # Additional provenance for audit
            "source_release": SOURCE_RELEASE,
            "source_asset": SOURCE_ASSET,
            "view_dir": str(view_dir),
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        authority_path.parent.mkdir(parents=True, exist_ok=True)
        authority_path.write_text(json.dumps(authority, indent=2) + "\n", encoding="utf-8")

        print(
            json.dumps(
                {
                    "view_dir": str(view_dir),
                    "part_count": len(view_parts),
                    "discovery_rows": VERIFIABLE_ROWS,
                    "view_manifest_sha256": view_manifest_sha,
                    "held_out_members_opened": 0,
                    "straddling_part_never_opened": STRADDLING_PART,
                }
            )
        )
        return authority


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build verifiable Discovery-only view (no held-out)")
    parser.add_argument("--zip", type=Path, required=True, help="canonical ZIP path")
    parser.add_argument("--view-dir", type=Path, required=True, help="output view directory")
    parser.add_argument("--authority-out", type=Path, required=True, help="output authority JSON path")
    args = parser.parse_args(argv)
    try:
        build_view(args.zip, args.view_dir, args.authority_out)
    except (SystemExit, OSError, zipfile.BadZipFile, ValueError) as e:
        print(json.dumps({"error": str(e), "held_out_members_opened": 0}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
