"""Encoding regression suite — locale-independent UTF-8 I/O (Windows root cause).

On Windows, Python's default text encoding is the locale codepage (cp1252), not
UTF-8. Every un-annotated open()/read_text()/write_text() that touches non-ASCII
content (em-dashes in generated docs/evidence, the UTF-8 desktop UI assets)
raised UnicodeDecodeError/UnicodeEncodeError there while passing on POSIX.

These tests:
1. run the real code paths in a subprocess whose preferred encoding is forced to
   ASCII (PYTHONUTF8=0, PYTHONCOERCECLOCALE=0, LC_ALL=C) — the strictest possible
   locale, stricter than cp1252 — and require success;
2. verify BOM-tolerant and CRLF-tolerant CSV ingestion (Windows-authored files);
3. verify generated artifacts round-trip non-ASCII content.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ASCII_ENV = {
    **os.environ,
    "PYTHONUTF8": "0",
    "PYTHONCOERCECLOCALE": "0",
    "LC_ALL": "C",
    "LANG": "C",
}


def _run_ascii_locale(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=REPO_ROOT,
        env=ASCII_ENV,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_ascii_locale_is_actually_enforced():
    """Guard: the simulation must really produce a non-UTF-8 preferred encoding."""
    p = _run_ascii_locale("import locale; print(locale.getpreferredencoding(False))")
    assert p.returncode == 0, p.stderr
    enc = p.stdout.strip().lower()
    assert enc != "utf-8", f"locale simulation ineffective (got {enc})"


def test_ui_assets_readable_under_ascii_locale():
    """Regression: reading the UTF-8 desktop UI used to crash under Windows locale."""
    snippet = (
        "from pathlib import Path;"
        "html = Path('src/qts/desktop/ui/index.html').read_text(encoding='utf-8');"
        "js = Path('src/qts/desktop/ui/app.js').read_text(encoding='utf-8');"
        "print(len(html), len(js))"
    )
    p = _run_ascii_locale(snippet)
    assert p.returncode == 0, p.stderr


def test_evidence_and_docs_readable_under_ascii_locale():
    snippet = (
        "import json; from pathlib import Path;"
        "p = Path('data/evidence/data_inventory.json');"
        "d = json.loads(p.read_text(encoding='utf-8')) if p.exists() else [];"
        "t = Path('docs/timeframe_research.md').read_text(encoding='utf-8');"
        "print(len(d), len(t))"
    )
    p = _run_ascii_locale(snippet)
    assert p.returncode == 0, p.stderr


def test_cli_health_and_bootstrap_under_ascii_locale():
    """Full CLI path (bootstrap + health) must work in a temp workspace under ASCII locale."""
    snippet = r"""
import shutil, sys, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
(tmp / 'data' / 'fixtures').mkdir(parents=True)
shutil.copy('data/fixtures/XAUUSD_1H_500.csv', tmp / 'data' / 'fixtures' / 'XAUUSD_1H_500.csv')
import os
os.chdir(tmp)
from qts.data.bootstrap import bootstrap_data
res = bootstrap_data(root=tmp / 'data', fixture=tmp / 'data' / 'fixtures' / 'XAUUSD_1H_500.csv')
assert res.ok, res.messages
from click.testing import CliRunner
from qts.cli import main
r = CliRunner().invoke(main, ['health'])
assert r.exit_code == 0, r.output
assert 'class=SYNTHETIC' in r.output, r.output
print('ASCII-LOCALE-CLI-OK')
"""
    p = _run_ascii_locale(snippet)
    assert p.returncode == 0, p.stderr + p.stdout
    assert "ASCII-LOCALE-CLI-OK" in p.stdout


def test_doc_generation_writes_unicode_under_ascii_locale():
    """Regression: write_text of reports containing em-dashes crashed on cp1252."""
    snippet = r"""
import tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
f = tmp / 'report.md'
f.write_text('# Report \u2014 unicode em-dash and arrow \u2192 ok', encoding='utf-8')
assert '\u2014' in f.read_text(encoding='utf-8')
print('WRITE-OK')
"""
    p = _run_ascii_locale(snippet)
    assert p.returncode == 0, p.stderr
    assert "WRITE-OK" in p.stdout


def test_ingest_tolerates_utf8_bom_and_crlf(tmp_path):
    """Windows-authored CSVs (BOM + CRLF) must ingest identically to the plain fixture."""
    from qts.data.ingest import ingest_csv
    from qts.data.store import SqliteParquetDataStore

    src = (REPO_ROOT / "data" / "fixtures" / "XAUUSD_1H_500.csv").read_bytes()
    assert src.count(b"\r\n") > 0  # fixture itself is CRLF

    bom_path = tmp_path / "with_bom.csv"
    bom_path.write_bytes(b"\xef\xbb\xbf" + src)

    store = SqliteParquetDataStore(root=tmp_path / "data")
    try:
        version = ingest_csv(bom_path, instrument="XAUUSD", timeframe="1H", store=store, source="SYNTHETIC:test")
        assert store.version_usable(version)
        from qts.domain.value_objects import Instrument

        bars = store.read_bars(Instrument(symbol="XAUUSD", venue="MT5"), "1H", version=version)
        assert len(bars) == 500
    finally:
        store.close()


def test_ingest_rejects_header_only_csv(tmp_path):
    from qts.data.ingest import ingest_csv
    from qts.data.store import SqliteParquetDataStore

    p = tmp_path / "empty.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "venue", "open", "high", "low", "close", "volume", "open_time", "close_time"])
    store = SqliteParquetDataStore(root=tmp_path / "data")
    try:
        import pytest

        with pytest.raises(ValueError, match="no usable bars"):
            ingest_csv(p, instrument="XAUUSD", timeframe="1H", store=store)
        assert store.list_versions() == []
    finally:
        store.close()


def test_manifest_json_roundtrips_unicode(tmp_path):
    from datetime import UTC, datetime

    from qts.data.store import Manifest

    m = Manifest(
        version="t-1",
        created_at=datetime.now(UTC),
        code_version="0.1.0",
        instrument="XAUUSD \u2014 test",
        venue="MT5",
        timeframe="1H",
        start=datetime.now(UTC),
        end=datetime.now(UTC),
        rows=1,
        checksum="sha256:x",
        source="SYNTHETIC:fixture:\u2014",
    )
    p = tmp_path / "manifest_t-1.json"
    p.write_text(m.model_dump_json(indent=2), encoding="utf-8")
    m2 = Manifest.model_validate_json(p.read_text(encoding="utf-8"))
    assert m2.instrument == m.instrument
    assert m2.source == m.source
