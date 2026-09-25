"""Only synthetic ZIP fixtures: no broker archive/quote row is ever accessed."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.audit_xauusd_discovery_boundary import (
    CUTOFF,
    TIME_MAX,
    TIME_MIN,
    MetadataAuditBlocked,
    audit_zip,
    dataset_digest,
    sha256_file,
)


def _fixture(path: Path, *, first_rows: int = 3) -> dict[str, str]:
    payloads = [b"SYNTHETIC-NOT-PARQUET-A", b"SYNTHETIC-NOT-PARQUET-B"]
    hashes = {f"part-{i:06}.parquet": hashlib.sha256(p).hexdigest() for i, p in enumerate(payloads)}
    parts = [
        {
            "part": f"part-{i:06}.parquet",
            "rows": n,
            "size_bytes": len(payloads[i]),
            "sha256": hashes[f"part-{i:06}.parquet"],
            "chunk": {"start_utc": f"fake-{i}", "end_utc": f"fake-{i + 1}"},
        }
        for i, n in enumerate([first_rows, 10 - first_rows])
    ]
    manifest = {
        "schema": "qts.mt5_raw_tick_acquisition.v1",
        "status": "COMPLETE",
        "row_count": 10,
        "raw_time_msc_min": TIME_MIN,
        "raw_time_msc_max": TIME_MAX,
        "dataset_sha256": dataset_digest(hashes),
        "parts": parts,
    }
    manifest_bytes = (json.dumps(manifest) + "\n").encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for i, payload in enumerate(payloads):
            archive.writestr(f"parts\\part-{i:06}.parquet", payload)
        archive.writestr("manifest.json", manifest_bytes)
    return {
        "expected_sha": sha256_file(path),
        "expected_manifest_sha": hashlib.sha256(manifest_bytes).hexdigest(),
        "expected_dataset_sha": manifest["dataset_sha256"],
    }


def _guard_parquet_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    original = zipfile.ZipFile.open

    def refuse_parquet(self, name, *args, **kwargs):
        filename = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if filename != "manifest.json":
            raise AssertionError("NO QUOTE MEMBER MAY BE OPENED")
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", refuse_parquet)


def test_exact_part_boundary_only_reads_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "synthetic.zip"
    expected = _fixture(path)
    _guard_parquet_opens(monkeypatch)
    report = audit_zip(path, expected_rows=10, discovery_rows=3, **expected)
    assert report["exact_immutable_part_boundary"]
    assert report["discovery_end_part"]["part_index"] == 0
    assert report["disposition"] == "EXACT_PART_BOUNDARY_VIEW_REQUIRES_SEPARATE_VERIFICATION"
    assert report["quote_rows_decoded"] == report["held_out_quote_members_opened"] == 0
    assert report["published_boundary"]["cutoff_time_msc_exclusive"] == CUTOFF


def test_straddling_part_stops_without_opening_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "synthetic.zip"
    expected = _fixture(path, first_rows=5)
    _guard_parquet_opens(monkeypatch)
    report = audit_zip(path, expected_rows=10, discovery_rows=3, **expected)
    assert not report["exact_immutable_part_boundary"]
    assert report["straddling_part"]["discovery_rows_within_part"] == 3
    assert report["straddling_part"]["locked_rows_within_part"] == 2
    assert report["disposition"] == "NO_SAFE_DISCOVERY_VIEW_FROM_IMMUTABLE_PARTS"
    assert report["quote_rows_decoded"] == report["held_out_quote_members_opened"] == 0


def test_zip_or_manifest_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.zip"
    expected = _fixture(path)
    with pytest.raises(MetadataAuditBlocked, match="archive SHA-256"):
        audit_zip(
            path,
            expected_rows=10,
            discovery_rows=3,
            expected_sha="0" * 64,
            expected_manifest_sha=expected["expected_manifest_sha"],
            expected_dataset_sha=expected["expected_dataset_sha"],
        )
    with pytest.raises(MetadataAuditBlocked, match="manifest SHA-256"):
        audit_zip(
            path,
            expected_rows=10,
            discovery_rows=3,
            expected_sha=expected["expected_sha"],
            expected_manifest_sha="0" * 64,
            expected_dataset_sha=expected["expected_dataset_sha"],
        )
