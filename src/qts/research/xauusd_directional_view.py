"""Fail-closed access to an *independently attested discovery-only* quote view.

Do not point this at the canonical full zip, an extracted full dataset, or a
part that crosses the locked cutoff. Authentication is a pinned manifest digest
registered separately from the view, not the view's self-asserted source label.
No quote column is read until every part and row group passes preflight.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from qts.research.xauusd_directional import (
    DirectionalScan,
    DiscoveryDataError,
    DiscoveryIdentity,
    LockedSpanRefused,
    evaluate,
)

CANONICAL_IDENTITY = DiscoveryIdentity()
AUTHORITY_SCHEMA = "qts.xauusd_discovery_view_authority.v1"
VIEW_SCHEMA = "qts.xauusd_discovery_view.v1"
PART_NAME = re.compile(r"part-[0-9]{6}\.parquet\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ViewAccessBlocked(ValueError):
    """The source cannot be proven discovery-only before reading quotes."""


class ViewBoundaryViolation(ViewAccessBlocked):
    """An unexpectedly locked timestamp was read: invalidate the attempt."""


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def _safe_path(root: Path, name: str) -> Path:
    if not PART_NAME.fullmatch(name):
        raise ViewAccessBlocked("discovery part name/path must be a simple part-NNNNNN.parquet")
    if root.is_symlink() or (root / "parts").is_symlink():
        raise ViewAccessBlocked("discovery view cannot contain symlink directories")
    part = root / "parts" / name
    if part.is_symlink() or not part.is_file():
        raise ViewAccessBlocked("missing or symlinked discovery part")
    return part


def preflight_view(
    view_dir: Path, authority: dict[str, Any], *, identity: DiscoveryIdentity = CANONICAL_IDENTITY
) -> tuple[list[Path], str]:
    """Validate provenance, all file digests and *every* row-group time bound first.

    The source view itself must have been registered independently; otherwise
    a self-described discovery manifest would be trivial to fabricate. Only
    parquet footers/time_msc metadata and discovery-view bytes are read here.
    If any part overlaps the cutoff, no bid/ask column is ever read.
    """
    root = Path(view_dir)
    if not root.is_dir() or root.is_symlink():
        raise ViewAccessBlocked("discovery-only directory absent or symlinked")
    if authority.get("schema") != AUTHORITY_SCHEMA or not DIGEST.fullmatch(str(authority.get("view_manifest_sha256"))):
        raise ViewAccessBlocked("no pinned discovery-view manifest authority")
    for key, expected in (
        ("source_zip_sha256", identity.zip_sha256),
        ("source_dataset_sha256", identity.dataset_sha256),
        ("cutoff_time_msc", identity.cutoff),
        ("discovery_rows", identity.rows),
    ):
        if authority.get(key) != expected:
            raise ViewAccessBlocked("authority does not match the registered source/split")
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ViewAccessBlocked("discovery-view manifest absent or symlinked")
    manifest_hash = _sha256(manifest_path)
    if manifest_hash != authority["view_manifest_sha256"]:
        raise ViewAccessBlocked("discovery-view manifest digest is not independently pinned")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ViewAccessBlocked("discovery-view manifest is unreadable") from exc
    if manifest.get("schema") != VIEW_SCHEMA or manifest.get("status") != "COMPLETE_DISCOVERY_ONLY":
        raise ViewAccessBlocked("view is not a completed discovery-only dataset")
    for key, expected in (
        ("source_zip_sha256", identity.zip_sha256),
        ("source_dataset_sha256", identity.dataset_sha256),
        ("cutoff_time_msc", identity.cutoff),
        ("time_msc_min", identity.time_min),
        ("discovery_rows", identity.rows),
        ("source_rows", identity.source_rows),
    ):
        if manifest.get(key) != expected:
            raise ViewAccessBlocked("view provenance or global row coverage differs from published inventory")
    parts = manifest.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ViewAccessBlocked("view part inventory is empty")
    if (root / "parts").is_symlink():
        raise ViewAccessBlocked("parts directory is symlinked")
    paths: list[Path] = []
    part_digests: list[str] = []
    index = 0
    previous_stamp: int | None = None
    seen_names: set[str] = set()
    for item in parts:
        if not isinstance(item, dict):
            raise ViewAccessBlocked("invalid part inventory record")
        name = item.get("part")
        if not isinstance(name, str) or name in seen_names:
            raise ViewAccessBlocked("duplicate/invalid part name")
        seen_names.add(name)
        # Refuse an admitted mixed part using the pinned manifest alone,
        # without even opening that Parquet file's metadata or bytes.
        if (
            type(item.get("min_time_msc")) is not int
            or type(item.get("max_time_msc")) is not int
            or item["min_time_msc"] < identity.time_min
            or item["max_time_msc"] >= identity.cutoff
        ):
            raise ViewAccessBlocked("attested part time bounds touch the locked span")
        path = _safe_path(root, name)
        if item.get("first_global_row") != index or type(item.get("rows")) is not int or item["rows"] <= 0:
            raise ViewAccessBlocked("discovery row identity is missing or discontinuous")
        index += item["rows"]
        if not DIGEST.fullmatch(str(item.get("sha256"))):
            raise ViewAccessBlocked("discovery part digest is absent")
        try:
            parquet = pq.ParquetFile(path)
        except (OSError, pa.ArrowException) as exc:
            raise ViewAccessBlocked("discovery part is not readable Parquet") from exc
        meta = parquet.metadata
        schema = parquet.schema_arrow
        if not {"time_msc", "bid", "ask"}.issubset(schema.names):
            raise ViewAccessBlocked("view part lacks required raw quote fields")
        if not pa.types.is_int64(schema.field("time_msc").type):
            raise ViewAccessBlocked("time_msc is not the unchanged int64 acquisition field")
        if not all(pa.types.is_float64(schema.field(name).type) for name in ("bid", "ask")):
            raise ViewAccessBlocked("bid/ask must be unaltered float64 quote fields")
        if meta.num_rows != item["rows"] or meta.num_row_groups == 0:
            raise ViewAccessBlocked("discovery part count does not match attested manifest")
        ts_column = parquet.schema.names.index("time_msc")
        part_min = None
        part_max = None
        for group in range(meta.num_row_groups):
            row_group = meta.row_group(group)
            column = row_group.column(ts_column)
            stats = column.statistics
            if row_group.num_rows == 0 or stats is None or not stats.has_min_max or stats.null_count != 0:
                raise ViewAccessBlocked("cannot prove that every row group is wholly inside discovery")
            lo, hi = int(stats.min), int(stats.max)
            if lo < identity.time_min or hi >= identity.cutoff or lo > hi:
                raise ViewAccessBlocked("row group touches the locked span or lacks valid bounds")
            if previous_stamp is not None and lo < previous_stamp:
                raise ViewAccessBlocked("discovery view row groups are not in original ascending order")
            previous_stamp = hi
            part_min = lo if part_min is None else part_min
            part_max = hi
        if item.get("min_time_msc") != part_min or item.get("max_time_msc") != part_max:
            raise ViewAccessBlocked("part time bounds disagree with attested Parquet metadata")
        paths.append(path)
        part_digests.append(item["sha256"])
    if index != identity.rows or not paths or int(parts[0]["min_time_msc"]) != identity.time_min:
        raise ViewAccessBlocked("incomplete discovery prefix or count differs from verified inventory")
    # Only after ALL row-group bounds are proven inside discovery do we hash
    # part bytes. A mixed boundary part is never read as a quote or hash input.
    for path, digest in zip(paths, part_digests, strict=True):
        if _sha256(path) != digest:
            raise ViewAccessBlocked("discovery part digest differs from independently pinned manifest")
    return paths, manifest_hash


def scan_attested_view(
    view_dir: Path, authority: dict[str, Any], *, identity: DiscoveryIdentity = CANONICAL_IDENTITY
) -> dict[str, Any]:
    """No quote reading until preflight succeeds on ALL parts; never touch zip."""
    paths, manifest_hash = preflight_view(view_dir, authority, identity=identity)
    scan = DirectionalScan(identity.time_min, identity.cutoff)
    try:
        for path in paths:
            parquet = pq.ParquetFile(path)
            for group in range(parquet.metadata.num_row_groups):
                # Defensive second boundary check on the actual time column,
                # BEFORE reading bid/ask even if the signed footer was corrupt.
                time = parquet.read_row_group(group, columns=["time_msc"]).column("time_msc").to_numpy()
                stamps = np.asarray(time, dtype=np.int64)
                if np.any(stamps >= identity.cutoff):
                    raise ViewBoundaryViolation("time_msc crossed the locked cutoff; quote columns not read")
                batch = parquet.read_row_group(group, columns=["bid", "ask"])
                scan.add_batch(batch.column("bid").to_numpy(), batch.column("ask").to_numpy(), stamps)
    except LockedSpanRefused as exc:
        raise ViewBoundaryViolation("an unexpectedly locked timestamp invalidated this attempt") from exc
    except DiscoveryDataError as exc:
        raise ViewAccessBlocked("discovery view failed its immutable quality checks") from exc
    if scan.rows != identity.rows:
        raise ViewAccessBlocked("discovery-only row count changed after preflight")
    report = evaluate(scan, complete_rows=identity.rows)
    report["view"] = {
        "view_manifest_sha256": manifest_hash,
        "part_count": len(paths),
        "source_zip_sha256": identity.zip_sha256,
        "source_dataset_sha256": identity.dataset_sha256,
        "source_discovery_rows": identity.rows,
        "source_cutoff_time_msc": identity.cutoff,
        "original_row_order_preserved": True,
    }
    return report
