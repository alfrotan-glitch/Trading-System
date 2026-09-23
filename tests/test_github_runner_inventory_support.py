"""The runner support commands must not extract or invent an inventory."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.github_runner_inventory_support import disk_is_sufficient, main


def test_disk_bound_requires_reserve() -> None:
    assert disk_is_sufficient(2_000, 1_000, reserve_bytes=1_000) is True
    assert disk_is_sufficient(1_999, 1_000, reserve_bytes=1_000) is False


def test_disk_preflight_reads_central_directory_and_does_not_extract(tmp_path: Path) -> None:
    archive = tmp_path / "ticks.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("parts/part-000000.parquet", b"not-extracted")
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "disk.json"
    code = main(
        [
            "disk-preflight",
            "--zip",
            str(archive),
            "--work-dir",
            str(work),
            "--output",
            str(output),
        ]
    )
    record = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert record["zip_open"] == "CENTRAL_DIRECTORY_ONLY"
    assert record["member_count"] == 1
    assert "extracted" not in record
    assert not (work / "parts").exists()
    assert list(work.iterdir()) == []
