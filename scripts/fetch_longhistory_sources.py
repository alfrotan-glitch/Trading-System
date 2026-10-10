#!/usr/bin/env python3
"""Fetch the pinned public XAUUSD history sources used by the long-history research.

Every source is pinned to a Git commit AND to the SHA-256 of each file used.
The fetch goes through ``git`` over HTTPS (github.com only), using a sparse,
blob-filtered checkout of the exact commit. Any byte change makes the script
refuse (fail closed) instead of silently accepting a different dataset.

Usage::

    python scripts/fetch_longhistory_sources.py            # fetch + verify
    python scripts/fetch_longhistory_sources.py --verify   # verify only

Raw files land in ``data/raw/longhistory/`` (gitignored). The provenance
manifest is written to ``data/evidence/longhistory/source_manifest.json``
(committed, small, no price data).

Sources and their status are documented in
``docs/research/longhistory_data_provenance_2026-10-10.md``. Nothing here
makes a source claim-admissible: each source carries the provenance class that
its own documentation supports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "longhistory"
MANIFEST_PATH = REPO_ROOT / "data" / "evidence" / "longhistory" / "source_manifest.json"


@dataclass(frozen=True)
class Source:
    source_id: str
    repo: str
    commit: str
    sparse_paths: tuple[str, ...]
    pins: dict[str, str]  # repo-relative path -> sha256
    license_note: str


YUAN_PINS = {
    "OHLC/XAUUSD/PT15M/20220309_154500-20220311_114500.csv": "b9675cff3fe006b8aff38ce9911161852c7aa5e1eb7ee4520326c5ecacc14abe",
    "OHLC/XAUUSD/PT15M/20220311_120000-20220502_134500.csv": "c459c27ddb48843e521cd8743e0600e908d006d55579aa75c1f8bd18d88068df",
    "OHLC/XAUUSD/PT15M/20220502_140000-20220623_154500.csv": "65710e6535a8ad9c836b8df459176d682df872372f851966b9fe6ac1b1d5647e",
    "OHLC/XAUUSD/PT15M/20220623_160000-20220812_204500.csv": "3700320c5d57a4ce79894ba92bfe5b4e75108928f7e62860df3c366d6604b3a0",
    "OHLC/XAUUSD/PT15M/20220814_220000-20221005_194500.csv": "694b4a6867da5a01567b20878adc486b3e711e24b50d95619a3e3a28ec39054e",
    "OHLC/XAUUSD/PT15M/20221005_200000-20221125_183000.csv": "bcf1628a6d0bb01504814a0daa402325e8feb0894b1d066581759fc7bd06edba",
    "OHLC/XAUUSD/PT15M/20221127_230000-20230117_234500.csv": "84c689902b155b9363ce20f90972b2d437dd9c720089573dab49070588662c8b",
    "OHLC/XAUUSD/PT15M/20230118_000000-20230310_214500.csv": "0c6026e53ae6eeecebe85ea045a91c0fb03e7f05713bcff1e74fbf78eacfcd23",
    "OHLC/XAUUSD/PT15M/20230312_220000-20230502_034500.csv": "36dc6d8a9783411cc62e3b167a1f483378b3c7d48c14893f20b9625a6a32f042",
    "OHLC/XAUUSD/PT15M/20230502_040000-20230623_054500.csv": "4b232657cc9102db9a9000df506030772a063d650e1f8ed45ac3f83a8c29b320",
    "OHLC/XAUUSD/PT15M/20230623_060000-20230814_074500.csv": "771998de288f4ca1a4eba5c71f2782a8c72807b27876c1b03acc7358cf5a6417",
    "OHLC/XAUUSD/PT15M/20230814_080000-20231005_094500.csv": "5cacdff117adda1d752b4afcec9903b843570c5830e53d01ae91baa4f5b0f278",
    "OHLC/XAUUSD/PT15M/20231005_100000-20231124_183000.csv": "393df62a588c3c55d2a23714f58916c312dfdfed2b14ff4107f251c4a840e26b",
    "OHLC/XAUUSD/PT15M/20231126_230000-20240117_134500.csv": "1289d95014f9345d42635c8973538afaeb0ce74797ea1acb32921d60a90ee477",
    "OHLC/XAUUSD/PT15M/20240117_140000-20240308_214500.csv": "969c5001f71b3a8082ca311e10bf41ca9148632e5d96459cdadfedafc2b5bd5c",
    "OHLC/XAUUSD/PT15M/20240310_220000-20240419_204500.csv": "99841cbe081f2985ed50e45bfed822d329a5157ca2cc3c2cd007154cb65d6567",
}

DUKA_PINS = {
    "data/XAUUSD/XAUUSD_2025-08.parquet": "e650d23cc05194ecb72bf7a748a96823e495850a6b94fac517c29031139c9e37",
    "data/XAUUSD/XAUUSD_2025-09.parquet": "48f7e1d2f5fd2f943580628f736898238b9a998fa4752cbe703ef32779ad345e",
    "data/XAUUSD/XAUUSD_2025-10.parquet": "4533939d9c7ae6e979575e753938f71661ffbe9096e61172040ba1230d9781dc",
    "data/XAUUSD/XAUUSD_2025-11.parquet": "016517904b326a5348795254a7559606d8ae1c882691c399374658a511390cd8",
    "data/XAUUSD/XAUUSD_2025-12.parquet": "e8ad92ba1b1bba37c7fa82577fd27b4faa836ea7f669581ce80f42ca830533a2",
    "data/XAUUSD/XAUUSD_2026-01.parquet": "de17f9c5316678125a9a272fed203b45f52cfe071633b66c548ebf5db826437a",
    "data/XAUUSD/XAUUSD_2026-02.parquet": "1978ce53545f31fd1f6adc5ab33bd447a7a174aa8b71485edf6bd13b792b7954",
    "data/XAUUSD/XAUUSD_2026-03.parquet": "8fba205494b4a068c8803192733d022d81feff082b9668e2a310e23f98ac969e",
    "data/XAUUSD/XAUUSD_2026-04.parquet": "f1b48a9c7c3b9deca60ff2f3856619cd672ebcc2e2d91741fd304cdee18f1486",
    "data/XAUUSD/XAUUSD_2026-05.parquet": "f8ddcae5e23ce1dd0553ada5526bfe6185b5ffc87ace7721acb1cbe0ad517f3b",
    "data/XAUUSD/XAUUSD_2026-06.parquet": "6a404b415cb921943b8419893db3361725180d86ef2c5ed67555b5b1e0d3ce37",
    "data/XAUUSD/XAUUSD_2026-07.parquet": "2f7751b028f183839ec4d3d23a94e5b6de571d00ff14978d73290ae850c6f854",
    "data/XAUUSD/XAUUSD_2026-08.parquet": "5645380ddd0c1a4b0e3cfefbcc283fd3670ea05267978023b7faa590e3c67a3a",
    "data/XAUUSD/XAUUSD_2026-09.parquet": "6b51ceb0fa34f12353a75859ff33179b901138db9d18183ff4db415cabd97da8",
}

SOURCES: tuple[Source, ...] = (
    Source(
        source_id="basemax_xauusd_15m",
        repo="BaseMax/XAUUSD-LSTM",
        commit="43f4177e701fdf3643cc02413e4337932af57401",
        sparse_paths=("XAU_15m_data.csv",),
        pins={"XAU_15m_data.csv": "9a924d80f620059d704238e2feb541454436a90595a521ce0fd30cef6a788c8c"},
        license_note="MIT (repository LICENSE). The CSV states it is derived from a Kaggle dataset "
        "(novandraanugrah/xauusd-gold-price-historical-data-2004-2024); the upstream vendor of the "
        "bars and that Kaggle licence could NOT be verified from this environment.",
    ),
    Source(
        source_id="ejtraderlabs_xauusd_m15_d1",
        repo="ejtraderLabs/historical-data",
        commit="fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd",
        sparse_paths=("XAUUSD",),
        pins={
            "XAUUSD/XAUUSDm15.csv": "4a179fd47494169508165ae74e5d7c642647ace83cb048947193770927621d9e",
            "XAUUSD/XAUUSDd1.csv": "d3da2122fded57f0c78afb38db580565052cd85cff30581e5f812fa5b0b0a305",
        },
        license_note="Apache-2.0 (repository LICENSE). The repository does not state the upstream "
        "bar source. Prices are stored x100 (points); the M15 series is identical to the BaseMax series "
        "after /100, so it is NOT an independent source.",
    ),
    Source(
        source_id="yuan_public_xauusd_15m",
        repo="No-Trade-No-Life/Yuan-Public-Data",
        commit="b7ff758fb8ad928fe9fa3b7ebc154df53ba9aa5a",
        sparse_paths=("OHLC/XAUUSD/PT15M",),
        pins=YUAN_PINS,
        license_note="MIT (repository LICENSE). README: data 'has no guarantee of accuracy or completeness'. "
        "Timestamps are explicit UTC (RFC3339 Z). Upstream provider not stated.",
    ),
    Source(
        source_id="dukascopy_mirror_xauusd_15m",
        repo="vudo805/forex-price-simulator",
        commit="4d6f15543e6285fad91fd57fe42f716bc7273075",
        sparse_paths=("data/XAUUSD",),
        pins=DUKA_PINS,
        license_note="No LICENSE file in the upstream repository (treated as internal research use only, "
        "no redistribution). Dukascopy XAU/USD tick feed, 15m mid-price bars, UTC.",
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
    """Sparse, blob-filtered checkout of ``src.commit`` into ``dest_root/<source_id>``."""
    dest = dest_root / src.source_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    url = f"https://github.com/{src.repo}.git"
    _git(["init", "-q"], dest)
    _git(["remote", "add", "origin", url], dest)
    _git(["sparse-checkout", "init", "--cone"], dest)
    _git(["sparse-checkout", "set", *src.sparse_paths], dest)
    _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", src.commit], dest)
    _git(["checkout", "-q", "FETCH_HEAD"], dest)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != src.commit:
        raise SystemExit(f"{src.source_id}: checked out {head}, expected pinned {src.commit}")
    shutil.rmtree(dest / ".git")  # keep only the verified working files
    return dest


def verify_source(src: Source, root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rel, expected in sorted(src.pins.items()):
        path = root / rel
        if not path.is_file():
            raise SystemExit(f"{src.source_id}: missing pinned file {rel}")
        digest = sha256_file(path)
        if digest != expected:
            raise SystemExit(f"{src.source_id}: sha256 mismatch for {rel}: {digest} != pinned {expected}")
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": digest})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="verify existing raw files only, do not fetch")
    args = parser.parse_args(argv)

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema": "qts.longhistory.source_manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "raw_root": "data/raw/longhistory (gitignored)",
        "sources": [],
    }
    entries: list[dict[str, object]] = []
    for src in SOURCES:
        if args.verify:
            root = RAW_ROOT / src.source_id
            if not root.is_dir():
                raise SystemExit(f"{src.source_id}: not fetched; run without --verify first")
        else:
            root = fetch_source(src, RAW_ROOT)
        files = verify_source(src, root)
        entries.append(
            {
                "source_id": src.source_id,
                "repo": f"https://github.com/{src.repo}",
                "commit": src.commit,
                "license_note": src.license_note,
                "files": files,
            }
        )
        print(f"OK {src.source_id}: {len(files)} file(s) verified at {src.commit[:12]}")
    manifest["sources"] = entries
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"manifest: {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
