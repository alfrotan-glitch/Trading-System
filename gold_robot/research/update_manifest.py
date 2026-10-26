"""Rebuild/check canonical SHA-256 manifest for the Windows MT5 research source package.

Usage:
    python gold_robot/research/update_manifest.py --check  # CI, no modifications
    python gold_robot/research/update_manifest.py --write  # maintainer action
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "SOURCE_CHECKSUMS.json"
TOPLEVEL = {"README.md", "README.txt", "CHECK_BROKER.bat", "MAKE_REPORT.bat",
            "INSTALL_ROBOT.bat", "SETUP_MT5_GOLD.bat"}
INCLUDED = {
    "mt5_robot": {".mq5", ".mqh", ".ps1"},
    "research": {".py", ".mq5", ".ps1", ".json"},
    "tests": {".py", ".mq5", ".ps1"},
    "docs": {".md", ".txt", ".json"},
}


def source_paths() -> list[Path]:
    paths: list[Path] = []
    for filename in sorted(TOPLEVEL):
        p = ROOT / filename
        if not p.is_file():
            raise FileNotFoundError(f"Missing package file: {p}")
        paths.append(p)
    for dirname, suffixes in INCLUDED.items():
        for path in sorted((ROOT / dirname).iterdir()):
            if (path.is_file() and path.suffix.lower() in suffixes
                    and path != MANIFEST):
                paths.append(path)
    return sorted(paths, key=lambda p: p.relative_to(ROOT).as_posix())


def generate() -> dict[str, list[dict[str, object]]]:
    entries = []
    for path in source_paths():
        data = path.read_bytes()
        entries.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return {"sha256_files": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--check", action="store_true")
    options.add_argument("--write", action="store_true")
    args = parser.parse_args()
    generated = generate()
    if args.check:
        if not MANIFEST.is_file():
            raise SystemExit("Missing canonical source manifest")
        actual = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if actual != generated:
            present = {r["path"]: r for r in actual.get("sha256_files", [])}
            expected = {r["path"]: r for r in generated["sha256_files"]}
            changed = sorted(p for p in set(present) | set(expected)
                             if present.get(p) != expected.get(p))
            raise SystemExit("Source manifest stale or incomplete: " + ", ".join(changed))
        print(f"Source manifest valid: {len(generated['sha256_files'])} files")
        return 0
    MANIFEST.write_text(json.dumps(generated, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote source manifest: {len(generated['sha256_files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
