"""The canonical zip inventory must fail closed and must not repair rows."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fakes_mt5 import FakeMT5

from qts.data.canonical_zip_inventory import CANONICAL_ZIP_SHA256, inventory_zip
from qts.data.mt5_history_acquisition import acquire_window, dataset_digest, sha256_file


def _zip_bytes(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)


def test_missing_archive_is_unavailable_and_supports_no_decision(tmp_path: Path) -> None:
    report = inventory_zip(tmp_path / "missing.zip")
    assert report["status"] == "UNAVAILABLE"
    assert report["verified_sha256"] is None
    assert report["extracted"] is False
    assert report["edge_claim"] == "NOT ESTABLISHED"
    assert report["decision_supported"] is False
    assert report["repairs_applied"] == []
    assert report["expected_sha256"] == CANONICAL_ZIP_SHA256


def test_checksum_mismatch_does_not_extract(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    _zip_bytes(archive, {"manifest.json": b"{}"})
    work = tmp_path / "work"
    report = inventory_zip(archive, expected_sha256=CANONICAL_ZIP_SHA256, work_dir=work)
    assert report["status"] == "CHECKSUM_MISMATCH"
    assert report["checksum_match"] is False
    assert report["extracted"] is False
    assert not work.exists()
    assert report["inventory"] is None
    assert report["edge_claim"] == "NOT ESTABLISHED"


def test_matching_checksum_without_manifest_does_not_invent_a_dataset(tmp_path: Path) -> None:
    archive = tmp_path / "plain.zip"
    _zip_bytes(archive, {"readme.txt": b"not a tick dataset"})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    work = tmp_path / "work"
    report = inventory_zip(archive, expected_sha256=digest, work_dir=work)
    assert report["checksum_match"] is True
    assert report["status"] == "LAYOUT_UNAVAILABLE"
    assert report["extracted"] is True
    assert report["datasets"] == []
    assert report["decision_supported"] is False
    assert any(item["code"] == "LAYOUT_UNAVAILABLE" for item in report["defects"])
    assert (work / "readme.txt").read_bytes() == b"not a tick dataset"


def test_unsafe_member_is_not_extracted(tmp_path: Path) -> None:
    archive = tmp_path / "slip.zip"
    _zip_bytes(archive, {"../escape.txt": b"no"})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    work = tmp_path / "work"
    report = inventory_zip(archive, expected_sha256=digest, work_dir=work)
    assert report["status"] == "ARCHIVE_UNSAFE"
    assert report["extracted"] is False
    assert not (tmp_path / "escape.txt").exists()
    assert not (work / "escape.txt").exists()


def test_acquired_dataset_roundtrip_counts_defects_and_does_not_rewrite(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    fake = FakeMT5()
    end = datetime(2026, 9, 19, 12, tzinfo=UTC)
    acquire_window(
        fake,
        symbol_requested="XAUUSD@",
        symbol_actual="XAUUSD@",
        environment={"environment": "DEMO", "server": "WMMarkets-Demo", "is_demo": True},
        start_utc=end - timedelta(days=1),
        end_utc=end,
        dataset_dir=dataset_dir,
        flags=fake.COPY_TICKS_ALL,
        chunk=timedelta(hours=12),
        min_chunk=timedelta(minutes=60),
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    part_name = manifest["parts"][0]["part"]
    part = dataset_dir / "parts" / part_name
    before = part.read_bytes()
    table = pq.read_table(part)
    bid = table.column("bid").to_pylist()
    ask = table.column("ask").to_pylist()
    bid[0], ask[0] = 2000.0, 1999.0
    mutated = table.set_column(table.schema.get_field_index("bid"), "bid", pa.array(bid))
    mutated = mutated.set_column(mutated.schema.get_field_index("ask"), "ask", pa.array(ask))
    mutated_dir = tmp_path / "mutated"
    (mutated_dir / "parts").mkdir(parents=True)
    for existing in (dataset_dir / "parts").glob("*.parquet"):
        target = mutated_dir / "parts" / existing.name
        target.write_bytes(existing.read_bytes())
    pq.write_table(mutated, mutated_dir / "parts" / part_name)
    part_hashes = {path.name: sha256_file(path) for path in (mutated_dir / "parts").glob("*.parquet")}
    for record in manifest["parts"]:
        record["sha256"] = part_hashes[record["part"]]
        if record["part"] == part_name:
            record["rows"] = mutated.num_rows
    manifest["row_count"] = sum(int(record["rows"]) for record in manifest["parts"])
    manifest["dataset_sha256"] = dataset_digest(part_hashes)
    (mutated_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    archive = tmp_path / "ticks.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in mutated_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(mutated_dir).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    work = tmp_path / "work"
    report = inventory_zip(archive, expected_sha256=digest, work_dir=work)
    assert report["status"] == "INVENTORIED"
    assert report["checksum_match"] is True
    assert report["edge_claim"] == "NOT ESTABLISHED"
    assert report["decision_supported"] is False
    assert report["repairs_applied"] == []
    dataset = report["datasets"][0]
    assert dataset["content"]["ask_below_bid_count"] >= 1
    assert dataset["content"]["timezone"] .startswith("UNAVAILABLE")
    assert dataset["content"]["session_calendar"].startswith("UNAVAILABLE")
    assert any(item["code"] == "INVERTED_OR_NEGATIVE_SPREAD" for item in dataset["defects"])
    extracted_part = next((work / "parts").glob("*.parquet"))
    assert extracted_part.read_bytes() == (mutated_dir / "parts" / part.name).read_bytes()
    assert part.read_bytes() == before
