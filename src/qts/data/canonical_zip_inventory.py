"""Fail-closed identity inventory for the canonical XAUUSD tick zip.

The archive is the research input. This module verifies its bytes, extracts
them only after the expected SHA-256 matches, and reports measured defects.
It does not sort, drop, interpolate, or otherwise repair rows, and it does
not emit an edge claim.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import (
    MANIFEST_FILENAME,
    dataset_digest,
    sha256_file,
)
from qts.data.mt5_history_analysis import validate_dataset_integrity

CANONICAL_RELEASE = "dataset-xauusd-730d-20260919"
CANONICAL_ASSET = "XAUUSD_730d_20260919T114013Z.zip"
CANONICAL_ZIP_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
# Digest published with the gap disposition. It identifies extracted dataset
# bytes, not the zip. A match is a comparison, not a substitute for the zip hash.
PUBLISHED_DATASET_DIGEST = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"

INVENTORY_SCHEMA = "qts.canonical_zip_inventory.v1"
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024 * 1024
MEMBER_LIST_CAP = 2000
GAP_THRESHOLDS_MS = (1_000, 60_000, 3_600_000, 86_400_000)
SPREAD_BINS_BPS = (0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 1000.0)
BATCH_ROWS = 500_000


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _code_identity() -> dict[str, Any]:
    commit = os.environ.get("GITHUB_SHA")
    if not commit:
        commit = "UNAVAILABLE"
    return {
        "git_sha": commit,
        "execution_host": os.environ.get("QTS_INVENTORY_EXECUTION_HOST", "UNAVAILABLE"),
        "module": "qts.data.canonical_zip_inventory",
    }


def _base_report(zip_path: Path, expected_sha256: str) -> dict[str, Any]:
    return {
        "schema": INVENTORY_SCHEMA,
        "generated_at_utc": _utc_now(),
        "canonical_release": CANONICAL_RELEASE,
        "canonical_asset": CANONICAL_ASSET,
        "zip_path": str(zip_path),
        "expected_sha256": expected_sha256,
        "verified_sha256": None,
        "checksum_match": False,
        "bytes_present": zip_path.stat().st_size if zip_path.is_file() else 0,
        "status": "UNAVAILABLE",
        "extracted": False,
        "repairs_applied": [],
        "defects": [],
        "inventory": None,
        "datasets": [],
        "edge_claim": "NOT ESTABLISHED",
        "decision_supported": False,
        "code_identity": _code_identity(),
        "provenance": "NOT ESTABLISHED",
    }


def _defect(code: str, detail: str, *, repaired: bool = False) -> dict[str, Any]:
    return {"code": code, "detail": detail, "repaired": repaired}


def _unsafe_member(name: str) -> bool:
    if name.startswith(("/", "\\")) or ":" in name[:3]:
        return True
    parts = Path(name).parts
    return any(part == ".." for part in parts)


def _member_summary(zf: zipfile.ZipFile) -> dict[str, Any]:
    infos = zf.infolist()
    listed = [
        {
            "name": info.filename,
            "compressed_bytes": info.compress_size,
            "uncompressed_bytes": info.file_size,
            "is_dir": info.is_dir(),
        }
        for info in infos[:MEMBER_LIST_CAP]
    ]
    return {
        "member_count": len(infos),
        "members_listed": len(listed),
        "members_truncated": len(infos) > MEMBER_LIST_CAP,
        "compressed_bytes": sum(info.compress_size for info in infos),
        "uncompressed_bytes": sum(info.file_size for info in infos),
        "members": listed,
    }


def _extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        if info.is_dir():
            (dest / info.filename).mkdir(parents=True, exist_ok=True)
            continue
        target = dest / info.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, target.open("wb") as out:
            while True:
                block = src.read(1 << 20)
                if not block:
                    break
                out.write(block)


def _stream_dataset(dataset_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Measure quote and time defects without rewriting or retaining every row."""
    parts = manifest.get("parts") or []
    fields_present: set[str] = set()
    rows = 0
    time_msc_min: int | None = None
    time_msc_max: int | None = None
    non_monotonic = 0
    same_ms_excess = 0
    identical_adjacent = 0
    invalid_bid = 0
    invalid_ask = 0
    ask_below_bid = 0
    zero_spread = 0
    negative_spread = 0
    spread_count = 0
    spread_sum = 0.0
    spread_min: float | None = None
    spread_max: float | None = None
    hist = np.zeros(len(SPREAD_BINS_BPS), dtype=np.int64)
    gap_counts = {str(threshold // 1000): 0 for threshold in GAP_THRESHOLDS_MS}
    largest: list[tuple[int, int, int]] = []
    prev_stamp: int | None = None
    prev_quote: tuple[Any, ...] | None = None
    missing_columns: list[str] = []

    for part in parts:
        path = dataset_dir / "parts" / part["part"]
        if not path.exists():
            missing_columns.append(f"missing-part:{part['part']}")
            continue
        parquet = pq.ParquetFile(path)
        names = set(parquet.schema_arrow.names)
        fields_present |= names
        needed = [name for name in ("time_msc", "bid", "ask", "last", "volume", "flags") if name in names]
        if "time_msc" not in names or "bid" not in names or "ask" not in names:
            missing_columns.append(f"incomplete-schema:{part['part']}")
        for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=needed or None):
            columns = {name: batch.column(name).to_numpy(zero_copy_only=False) for name in batch.schema.names}
            n = batch.num_rows
            rows += n
            stamps = columns.get("time_msc")
            bid = columns.get("bid")
            ask = columns.get("ask")
            if stamps is not None:
                stamps = np.asarray(stamps, dtype=np.int64)
                time_msc_min = int(stamps.min()) if time_msc_min is None else min(time_msc_min, int(stamps.min()))
                time_msc_max = int(stamps.max()) if time_msc_max is None else max(time_msc_max, int(stamps.max()))
                if prev_stamp is None:
                    deltas = np.diff(stamps)
                    left = stamps[:-1]
                    right = stamps[1:]
                else:
                    chained = np.concatenate(([np.int64(prev_stamp)], stamps))
                    deltas = np.diff(chained)
                    left = chained[:-1]
                    right = stamps
                if deltas.size:
                    non_monotonic += int(np.count_nonzero(deltas < 0))
                    same_ms_excess += int(np.count_nonzero(deltas == 0))
                    positive = deltas > 0
                    for threshold in GAP_THRESHOLDS_MS:
                        gap_counts[str(threshold // 1000)] += int(np.count_nonzero(deltas >= threshold))
                    if positive.any():
                        k = min(10, int(np.count_nonzero(positive)))
                        idx = np.flatnonzero(positive)
                        top = idx[np.argpartition(deltas[idx], -k)[-k:]]
                        for i in top.tolist():
                            largest.append((int(deltas[i]), int(left[i]), int(right[i])))
                prev_stamp = int(stamps[-1])
            if bid is not None and ask is not None:
                bid_a = np.asarray(bid, dtype=np.float64)
                ask_a = np.asarray(ask, dtype=np.float64)
                invalid_bid += int(np.count_nonzero(bid_a <= 0))
                invalid_ask += int(np.count_nonzero(ask_a <= 0))
                ask_below_bid += int(np.count_nonzero(ask_a < bid_a))
                spread = ask_a - bid_a
                zero_spread += int(np.count_nonzero(spread == 0))
                negative_spread += int(np.count_nonzero(spread < 0))
                valid = (bid_a > 0) & (ask_a > 0) & (spread >= 0)
                if valid.any():
                    mid = (bid_a[valid] + ask_a[valid]) / 2.0
                    positive_mid = mid > 0
                    if positive_mid.any():
                        bps = (spread[valid][positive_mid] / mid[positive_mid]) * 10000.0
                        spread_count += int(bps.size)
                        spread_sum += float(bps.sum())
                        lo = float(bps.min())
                        hi = float(bps.max())
                        spread_min = lo if spread_min is None else min(spread_min, lo)
                        spread_max = hi if spread_max is None else max(spread_max, hi)
                        hist += np.histogram(bps, bins=(*SPREAD_BINS_BPS, np.inf))[0]
                quote_fields = []
                for name in ("bid", "ask", "last", "volume", "flags"):
                    if name in columns:
                        quote_fields.append(np.asarray(columns[name]))
                if quote_fields and stamps is not None:
                    # Adjacent identical quote state, carried across batches.
                    current = tuple(field[-1].item() for field in quote_fields)
                    if prev_quote is not None and quote_fields[0].size:
                        first_equal = all(field[0].item() == prev for field, prev in zip(quote_fields, prev_quote, strict=True))
                        if first_equal:
                            identical_adjacent += 1
                    if quote_fields[0].size > 1:
                        equal = np.ones(quote_fields[0].size - 1, dtype=bool)
                        for field in quote_fields:
                            equal &= field[1:] == field[:-1]
                        identical_adjacent += int(np.count_nonzero(equal))
                    prev_quote = current
    largest.sort(key=lambda item: -item[0])
    span_ms = None if time_msc_min is None or time_msc_max is None else time_msc_max - time_msc_min
    return {
        "row_count": rows,
        "fields_present": sorted(fields_present),
        "incomplete_parts": missing_columns,
        "time_msc_min": time_msc_min,
        "time_msc_max": time_msc_max,
        "span_ms": span_ms,
        "time_range_if_utc": {
            "start": datetime.fromtimestamp(time_msc_min / 1000.0, tz=UTC).isoformat() if time_msc_min else None,
            "end": datetime.fromtimestamp(time_msc_max / 1000.0, tz=UTC).isoformat() if time_msc_max else None,
            "basis": "PROVISIONAL_IF_UTC",
            "timestamp_interpretation_confirmed": manifest.get("timestamp_interpretation_confirmed"),
        },
        "tick_frequency": {
            "rows_per_second_over_span": (rows / (span_ms / 1000.0)) if span_ms else None,
            "note": "span average, not a session rate; gaps are included in the denominator",
        },
        "non_monotonic_time_msc_count": non_monotonic,
        "same_time_msc_excess_rows_adjacent": same_ms_excess,
        "consecutive_identical_quote_rows": identical_adjacent,
        "duplicate_scope": "ADJACENT_ONLY — rows were not globally deduplicated and were not rewritten",
        "invalid_bid_count": invalid_bid,
        "invalid_ask_count": invalid_ask,
        "ask_below_bid_count": ask_below_bid,
        "zero_spread_count": zero_spread,
        "negative_spread_count": negative_spread,
        "spread_bps": {
            "count": spread_count,
            "min": spread_min,
            "mean": (spread_sum / spread_count) if spread_count else None,
            "max": spread_max,
            "exact_median": "UNAVAILABLE",
            "histogram_bins_bps": [str(edge) for edge in (*SPREAD_BINS_BPS, "inf")],
            "histogram_counts": [int(v) for v in hist.tolist()],
            "abnormal_above_100_bps": int(hist[SPREAD_BINS_BPS.index(100.0) :].sum()) if spread_count else 0,
            "abnormal_definition": "diagnostic count of valid non-negative spreads above 100 bps; rows were not removed",
        },
        "gap_counts_at_least_seconds": gap_counts,
        "largest_gaps": [
            {"gap_ms": gap, "start_time_msc_raw": start, "end_time_msc_raw": end, "classification": "UNCLASSIFIED_SPACING"}
            for gap, start, end in largest[:10]
        ],
        "session_calendar": "UNAVAILABLE — timestamp basis is not confirmed, so session labels were not assigned",
        "timezone": "UNAVAILABLE — raw time_msc stored as returned; no offset was inferred or applied",
    }


def _dataset_record(dataset_dir: Path) -> dict[str, Any]:
    manifest_path = dataset_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity = validate_dataset_integrity(dataset_dir, recompute_hashes=True)
    part_hashes = {}
    for part in manifest.get("parts") or []:
        path = dataset_dir / "parts" / part["part"]
        if path.exists():
            part_hashes[part["part"]] = sha256_file(path)
    recomputed = dataset_digest(part_hashes) if part_hashes else None
    content = _stream_dataset(dataset_dir, manifest)
    defects: list[dict[str, Any]] = []
    if integrity["overall"] != "PASS":
        defects.append(_defect("INTEGRITY_FAIL", "acquisition manifest did not match recomputed files"))
    if manifest.get("status") != "COMPLETE":
        defects.append(_defect("ACQUISITION_NOT_COMPLETE", f"status={manifest.get('status')!r}"))
    if manifest.get("timestamp_interpretation_confirmed") is not True:
        defects.append(_defect("TIMESTAMP_BASIS_UNVERIFIED", "no UTC conversion was applied; session labels stay unavailable"))
    if content["ask_below_bid_count"] or content["negative_spread_count"]:
        defects.append(
            _defect(
                "INVERTED_OR_NEGATIVE_SPREAD",
                f"ask_below_bid={content['ask_below_bid_count']} negative_spread={content['negative_spread_count']}",
            )
        )
    if content["non_monotonic_time_msc_count"]:
        defects.append(
            _defect(
                "NON_MONOTONIC_TIMESTAMPS",
                f"count={content['non_monotonic_time_msc_count']}; rows were not sorted",
            )
        )
    return {
        "path": str(dataset_dir),
        "acquisition_status": manifest.get("status"),
        "manifest_dataset_sha256": manifest.get("dataset_sha256"),
        "recomputed_dataset_sha256": recomputed,
        "matches_published_gap_report_digest": recomputed == PUBLISHED_DATASET_DIGEST,
        "published_gap_report_digest": PUBLISHED_DATASET_DIGEST,
        "integrity": integrity,
        "content": content,
        "defects": defects,
        "repairs_applied": [],
    }


def inventory_zip(
    zip_path: str | Path,
    *,
    expected_sha256: str = CANONICAL_ZIP_SHA256,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Inventory one zip. Extraction happens only after the expected hash matches."""
    zip_path = Path(zip_path)
    report = _base_report(zip_path, expected_sha256)
    if not zip_path.is_file():
        report["defects"].append(_defect("ARCHIVE_ABSENT", f"{zip_path} is not a file"))
        report["provenance"] = "NOT ESTABLISHED — archive bytes were not present"
        return report

    digest = sha256_file(zip_path)
    report["verified_sha256"] = digest
    report["checksum_match"] = digest == expected_sha256.lower()
    if not report["checksum_match"]:
        report["status"] = "CHECKSUM_MISMATCH"
        report["defects"].append(
            _defect("CHECKSUM_MISMATCH", "zip SHA-256 does not match the expected canonical digest; archive was not extracted")
        )
        report["provenance"] = "NOT ESTABLISHED — checksum mismatch, no extraction"
        return report

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        report["status"] = "UNREADABLE_ZIP"
        report["defects"].append(_defect("UNREADABLE_ZIP", str(exc)))
        report["provenance"] = "checksum matched but the zip container could not be read; no repair attempted"
        return report

    with zf:
        summary = _member_summary(zf)
        report["inventory"] = summary
        unsafe = [item["name"] for item in summary["members"] if _unsafe_member(item["name"])]
        # members may be truncated; scan the full infolist for unsafe paths
        unsafe = [info.filename for info in zf.infolist() if _unsafe_member(info.filename)]
        if unsafe:
            report["status"] = "ARCHIVE_UNSAFE"
            report["defects"].append(_defect("ARCHIVE_PATH", f"refused to extract unsafe members: {unsafe[:10]}"))
            report["provenance"] = "checksum matched; extraction refused because a member path is unsafe"
            return report
        if summary["uncompressed_bytes"] > MAX_UNCOMPRESSED_BYTES:
            report["status"] = "ARCHIVE_TOO_LARGE"
            report["defects"].append(
                _defect("ARCHIVE_TOO_LARGE", f"uncompressed {summary['uncompressed_bytes']} exceeds {MAX_UNCOMPRESSED_BYTES}")
            )
            report["provenance"] = "checksum matched; extraction refused by the size bound"
            return report
        dest = Path(work_dir) if work_dir is not None else zip_path.parent / f".{zip_path.stem}.inventory-work"
        _extract(zf, dest)
    report["extracted"] = True
    report["extract_dir"] = str(dest)

    manifests = sorted(dest.rglob(MANIFEST_FILENAME))
    if not manifests:
        report["status"] = "LAYOUT_UNAVAILABLE"
        report["defects"].append(
            _defect("LAYOUT_UNAVAILABLE", "checksum matched and members were extracted, but no acquisition manifest.json was found")
        )
        report["provenance"] = "zip checksum verified; dataset layout is not the acquisition contract"
        return report

    datasets = [_dataset_record(path.parent) for path in manifests]
    report["datasets"] = datasets
    for dataset in datasets:
        report["defects"].extend(dataset["defects"])
    report["status"] = "INVENTORIED"
    report["provenance"] = (
        "zip SHA-256 matched the expected canonical digest; inventory was measured from extracted files; "
        "no row was repaired; timestamp basis was not inferred"
    )
    report["edge_claim"] = "NOT ESTABLISHED"
    report["decision_supported"] = False
    return report


def write_inventory(report: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


def exit_code(report: dict[str, Any]) -> int:
    """Non-zero when the archive cannot support an identity claim."""
    status = report.get("status")
    if status == "INVENTORIED":
        return 0
    if status == "CHECKSUM_MISMATCH":
        return 3
    if status == "UNAVAILABLE":
        return 2
    return 4
