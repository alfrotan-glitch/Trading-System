"""Windows setup-script reproducibility regression suite.

Failure classes covered (root causes from the Windows clean-clone audit):

1. ENCODING — Windows PowerShell 5.1 reads BOM-less .ps1 files as ANSI
   (cp1252) and mis-parses UTF-8 characters; .ps1 files must be UTF-8 WITH BOM.
   cmd.exe parses .bat files in the OEM codepage; .bat files must be pure ASCII.
2. LINE ENDINGS — cmd.exe/PowerShell scripts must be checked out as CRLF on
   Windows deterministically (via .gitattributes), independent of the user's
   core.autocrlf setting.
3. FABRICATION — setup must never contain a "synthetic fallback" that invents
   bars at hardcoded prices, and must never hardcode date-derived dataset
   version ids (they differ per clone day — hidden non-reproducibility).
4. FAIL-CLOSED — setup must gate on `qts data bootstrap` exit code and on the
   pytest exit code, never printing "Setup Complete" after a failure.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

PS1_FILES = ["setup_windows.ps1", "create_shortcut.ps1"]
BAT_FILES = ["setup_windows.bat", "run_qts.bat", "run_tests.bat", "launch_desktop.bat", "build_windows.bat"]

VERSION_ID_RE = re.compile(r"\b\d{8}-\d{3}-[0-9a-f]{8}\b")


def _bytes(name: str) -> bytes:
    return (SCRIPTS / name).read_bytes()


class TestPowerShellEncoding:
    def test_ps1_files_have_utf8_bom(self):
        """PS 5.1 requires a BOM to interpret the file as UTF-8."""
        for name in PS1_FILES:
            data = _bytes(name)
            assert data.startswith(b"\xef\xbb\xbf"), f"{name} must be UTF-8 with BOM for PowerShell 5.1"
            # body must decode cleanly as UTF-8
            data[3:].decode("utf-8")

    def test_ps1_files_use_crlf(self):
        for name in PS1_FILES:
            data = _bytes(name)
            lf_only = data.count(b"\n") - data.count(b"\r\n")
            assert lf_only == 0, f"{name} must use CRLF line endings end-to-end"

    def test_ps1_no_powershell7_only_syntax(self):
        """Scripts must parse under Windows PowerShell 5.1."""
        forbidden = {
            "ternary operator": re.compile(r"\?\s*:\s"),
            "null-coalescing ??": re.compile(r"\?\?"),
            "null-conditional ?.": re.compile(r"\?\.\w"),
            "ForEach-Object -Parallel": re.compile(r"-Parallel\b"),
            "&& pipeline chain": re.compile(r"&&"),
            "|| pipeline chain": re.compile(r"\|\|"),
        }
        for name in PS1_FILES:
            text = _bytes(name)[3:].decode("utf-8")
            # strip comment lines to avoid false positives from prose
            code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
            for label, pat in forbidden.items():
                assert not pat.search(code), f"{name} uses PS7-only syntax: {label}"

    def test_ps1_never_hardcodes_dataset_version_ids(self):
        for name in PS1_FILES:
            text = _bytes(name)[3:].decode("utf-8")
            assert not VERSION_ID_RE.search(text), f"{name} hardcodes a date-derived version id"

    def test_setup_ps1_has_no_fabricated_data_fallback(self):
        text = _bytes("setup_windows.ps1")[3:].decode("utf-8")
        assert "synthetic_fallback" not in text
        assert "Decimal('2000')" not in text and 'Decimal("2000")' not in text
        # must delegate data establishment to the truthful bootstrap command
        assert "data bootstrap" in text


class TestBatchEncoding:
    def test_bat_files_are_pure_ascii(self):
        for name in BAT_FILES:
            data = _bytes(name)
            non_ascii = sorted({b for b in data if b > 127})
            assert not non_ascii, f"{name} contains non-ASCII bytes {non_ascii} (cmd.exe OEM codepage hazard)"

    def test_bat_files_use_crlf(self):
        for name in BAT_FILES:
            data = _bytes(name)
            lf_only = data.count(b"\n") - data.count(b"\r\n")
            assert lf_only == 0, f"{name} must use CRLF line endings end-to-end"

    def test_setup_bat_never_hardcodes_dataset_version_ids(self):
        text = _bytes("setup_windows.bat").decode("ascii")
        assert not VERSION_ID_RE.search(text)

    def test_setup_bat_gates_on_bootstrap_and_tests(self):
        text = _bytes("setup_windows.bat").decode("ascii")
        assert "-m qts data bootstrap" in text
        # fail-closed: bootstrap failure must exit nonzero before "Setup Complete"
        bootstrap_idx = text.index("data bootstrap")
        complete_idx = text.index("=== Setup Complete ===")
        between = text[bootstrap_idx:complete_idx]
        assert "if errorlevel 1" in between
        assert "-m pytest" in text
        pytest_idx = text.index("-m pytest")
        assert "if errorlevel 1" in text[pytest_idx:complete_idx]


class TestGitAttributes:
    def test_gitattributes_pins_windows_script_line_endings(self):
        attr = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert re.search(r"\*\.ps1\s+text\s+eol=crlf", attr)
        assert re.search(r"\*\.bat\s+text\s+eol=crlf", attr)


class TestSetupIdempotencyContract:
    """The setup contract is enforced at the Python layer it delegates to.

    The .ps1/.bat both call `qts data bootstrap`; its idempotency (first run
    ingests, second run reuses, third run after data deletion re-ingests) is
    covered by tests/test_clean_clone_bootstrap.py. Here we assert the scripts
    contain no hidden manual repair steps (no direct store surgery, no inline
    python that writes bars).
    """

    def test_no_inline_python_writing_bars_in_scripts(self):
        for name in ["setup_windows.ps1", "setup_windows.bat"]:
            raw = _bytes(name)
            text = raw.decode("utf-8-sig")
            assert "write_bars" not in text, f"{name} performs inline store surgery"
            assert "Bar(" not in text, f"{name} constructs bars inline"
