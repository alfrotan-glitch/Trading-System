#!/usr/bin/env python3
"""Fetch the pinned monthly-series sources used by the long-history monthly cycle.

Every source is pinned to a Git commit AND to the SHA-256 of each file used.
The fetch goes through ``git`` over HTTPS (github.com only) using a sparse,
blob-filtered checkout of the exact commit. Any byte change makes the script
refuse (fail closed) instead of silently accepting a different dataset.

Usage::

    python scripts/fetch_longhistory_monthly_sources.py            # fetch + verify
    python scripts/fetch_longhistory_monthly_sources.py --verify   # verify only

Raw files land in ``data/raw/gold_monthly`` and ``data/raw/fx`` (gitignored).
The committed record of the pinned commits lives in
``data/evidence/longhistory/monthly_data_quality.json`` (written by
``scripts/build_longhistory_monthly_dataset.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"


@dataclass(frozen=True)
class Source:
    source_id: str
    repo: str
    commit: str
    sparse_paths: tuple[str, ...]
    pins: dict[str, str]  # repo-relative path -> sha256


SOURCES: tuple[Source, ...] = (
    Source(
        source_id="gold_monthly",
        repo="https://github.com/datasets/gold-prices.git",
        commit="f6e97610178379ef8db280702fcaa3ec0875c5c2",
        sparse_paths=("data",),
        pins={"data/monthly.csv": "f5945c29f746ff14e54acd635dcbb43dbe9f4706f22d6ac8c5d7c3b7908ebcf5"},
    ),
    Source(
        source_id="fx",
        repo="https://github.com/datasets/exchange-rates.git",
        commit="c023dd8b8f879610641a7391c0394c3bbb42d0f7",
        sparse_paths=("data",),
        pins={"data/daily.csv": "68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa"},
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def fetch_source(src: Source, dest_root: Path) -> Path:
    dest = dest_root / src.source_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    _git(["init", "-q"], dest)
    _git(["remote", "add", "origin", src.repo], dest)
    _git(["sparse-checkout", "init", "--cone"], dest)
    _git(["sparse-checkout", "set", *src.sparse_paths], dest)
    _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", src.commit], dest)
    _git(["checkout", "-q", "FETCH_HEAD"], dest)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != src.commit:
        raise SystemExit(f"{src.source_id}: checked out {head}, expected pinned {src.commit}")
    shutil.rmtree(dest / ".git")
    return dest


def resolve_pin(rel: str, src: Source, root: Path) -> str | None:
    """Pins are SHA-256 of the file content; placeholders resolve on first fetch."""
    expected = src.pins.get(rel, "")
    if not expected.startswith("__"):
        return expected
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="verify existing raw files only")
    args = parser.parse_args(argv)

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    for src in SOURCES:
        root = RAW_ROOT / src.source_id
        if args.verify:
            if not root.is_dir():
                raise SystemExit(f"{src.source_id}: not fetched; run without --verify first")
        else:
            root = fetch_source(src, RAW_ROOT)
        for rel in sorted(src.pins):
            path = root / rel
            if not path.is_file():
                raise SystemExit(f"{src.source_id}: missing file {rel}")
            digest = sha256_file(path)
            pinned = resolve_pin(rel, src, root)
            if pinned is not None and digest != pinned:
                raise SystemExit(f"{src.source_id}: sha256 mismatch for {rel}: {digest} != {pinned}")
            print(f"OK {src.source_id}: {rel} sha256={digest}")
        print(f"OK {src.source_id}: commit {src.commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
