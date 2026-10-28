"""Fail CI if tracked project files contain Arabic-script text or retired guide names.

All operator-facing messages, source code and documentation are English-only.
Historical binary files are preserved and never decoded as source.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ARABIC_BLOCKS = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFC),
)


def is_arabic_script(text: str) -> bool:
    return any(
        start <= ord(character) <= end
        for character in text
        for start, end in ARABIC_BLOCKS
    )


def check(root: Path) -> list[str]:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode("utf-8").split("\0")
    errors: list[str] = []
    for relative in filter(None, tracked):
        if "_DARI" in relative.upper():
            errors.append(f"{relative}: retired language-specific filename")
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            if is_arabic_script(line):
                errors.append(f"{relative}:{line_number}: Arabic-script text")
                if len(errors) >= 100:
                    return errors
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    violations = check(root)
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(f"Source language check failed: {len(violations)} issue(s)", file=sys.stderr)
        return 1
    print("Source language check passed: tracked files contain no Arabic-script text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
