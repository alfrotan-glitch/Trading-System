"""Clean-clone data bootstrap regression suite.

Covers the failure classes discovered in the Windows clean-clone audit:

1. PHANTOM VERSIONS — a manifest (SQLite row or JSON file) existing WITHOUT
   readable curated parquet must never count as a usable dataset.
2. FABRICATION — bootstrap must never invent bars (no hardcoded-price
   "synthetic fallback") to make setup appear successful.
3. IDEMPOTENCY — repeated bootstrap runs reuse the existing usable version
   instead of failing on duplicate version ids or creating duplicates.
4. TRUTHFUL LABELING — the bootstrap fixture is SYNTHETIC (GBM seed=42) and
   must be labeled as such end to end (manifest, bars, CLI output).
5. FAIL-CLOSED — missing fixture / zero-bar fixture / invalid fixture must
   fail with actionable messages and leave no dataset version behind.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from qts.data.bootstrap import DATA_CLASSES, bootstrap_data, classify_source
from qts.data.store import SqliteParquetDataStore

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "data" / "fixtures" / "XAUUSD_1H_500.csv"


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Fresh data root + copied fixture, mimicking a clean clone."""
    root = tmp_path / "data"
    (root / "fixtures").mkdir(parents=True)
    fx = root / "fixtures" / "XAUUSD_1H_500.csv"
    shutil.copy(FIXTURE, fx)
    return root, fx


def test_bootstrap_clean_clone_ingests_and_verifies(tmp_path):
    root, fx = _workspace(tmp_path)
    res = bootstrap_data(root=root, fixture=fx)
    assert res.status == "INGESTED"
    assert res.ok
    assert res.bars == 500
    assert res.data_class == "SYNTHETIC"
    assert res.source.startswith("SYNTHETIC:fixture:")
    store = SqliteParquetDataStore(root=root)
    try:
        assert store.version_usable(res.version)
        assert res.version in store.list_usable_versions()
        m = store.manifest(res.version)
        assert m is not None
        # provenance label persisted in manifest AND bars
        assert m.source.startswith("SYNTHETIC:fixture:")
        from qts.domain.value_objects import Instrument

        bars = store.read_bars(Instrument(symbol="XAUUSD", venue="MT5"), "1H", version=res.version)
        assert len(bars) == 500
        assert all(b.source.startswith("SYNTHETIC:fixture:") for b in bars)
    finally:
        store.close()


def test_bootstrap_idempotent_second_run_reuses_version(tmp_path):
    root, fx = _workspace(tmp_path)
    r1 = bootstrap_data(root=root, fixture=fx)
    r2 = bootstrap_data(root=root, fixture=fx)
    assert r1.ok and r2.ok
    assert r2.status == "READY"  # no writes on second run
    assert r2.version == r1.version
    store = SqliteParquetDataStore(root=root)
    try:
        # exactly one version — no duplicates created
        versions = list(store.list_versions())
        assert len(versions) == 1
    finally:
        store.close()


def test_bootstrap_third_run_after_deleting_generated_data(tmp_path):
    root, fx = _workspace(tmp_path)
    r1 = bootstrap_data(root=root, fixture=fx)
    assert r1.ok
    # delete generated data (curated + sqlite + manifests), keep fixture
    shutil.rmtree(root / "curated")
    shutil.rmtree(root / "sqlite")
    shutil.rmtree(root / "manifests")
    r3 = bootstrap_data(root=root, fixture=fx)
    assert r3.ok
    assert r3.bars == 500
    store = SqliteParquetDataStore(root=root)
    try:
        assert store.version_usable(r3.version)
    finally:
        store.close()


def test_phantom_manifest_is_never_usable(tmp_path):
    """A version row/manifest alone is NOT proof of data (clean-clone root cause)."""
    root, fx = _workspace(tmp_path)
    res = bootstrap_data(root=root, fixture=fx)
    version = res.version
    # destroy the curated parquet but keep the manifest registry -> phantom
    parquet = (
        root / "curated" / "instrument=XAUUSD" / "venue=MT5" / "timeframe=1H" / f"version={version}" / "part-0.parquet"
    )
    parquet.unlink()
    store = SqliteParquetDataStore(root=root)
    try:
        assert store.manifest(version) is not None  # registry still resolves it
        assert not store.version_usable(version)  # ... but it is NOT usable
        assert version not in store.list_usable_versions()
    finally:
        store.close()
    # bootstrap must recover truthfully: report phantom + re-ingest a usable version
    res2 = bootstrap_data(root=root, fixture=fx)
    assert res2.ok
    assert any("NO readable bars" in m for m in res2.messages), res2.messages
    store2 = SqliteParquetDataStore(root=root)
    try:
        assert store2.version_usable(res2.version)
    finally:
        store2.close()


def test_missing_fixture_fails_closed_without_fabrication(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    missing = root / "fixtures" / "does_not_exist.csv"
    res = bootstrap_data(root=root, fixture=missing)
    assert res.status == "FAILED"
    assert not res.ok
    assert res.version is None
    assert any("not found" in m and "no data was fabricated" in m for m in res.messages)
    store = SqliteParquetDataStore(root=root)
    try:
        assert store.list_versions() == []  # nothing invented
    finally:
        store.close()


def test_zero_bar_fixture_is_never_promoted(tmp_path):
    root = tmp_path / "data"
    (root / "fixtures").mkdir(parents=True)
    fx = root / "fixtures" / "empty.csv"
    with open(fx, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "venue", "open", "high", "low", "close", "volume", "open_time", "close_time"])
    res = bootstrap_data(root=root, fixture=fx)
    assert res.status == "FAILED"
    assert any("zero usable bars" in m for m in res.messages)
    store = SqliteParquetDataStore(root=root)
    try:
        assert store.list_versions() == []
    finally:
        store.close()


def test_invalid_fixture_rejected_by_quality_gate(tmp_path):
    root, fx = _workspace(tmp_path)
    # corrupt OHLC invariant (high < low) — quality gate must reject
    with open(fx, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[10]["high"], rows[10]["low"] = "1000.00", "3000.00"
    with open(fx, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    res = bootstrap_data(root=root, fixture=fx)
    assert res.status == "FAILED"
    assert any("ingest failed" in m or "quality" in m.lower() for m in res.messages)
    store = SqliteParquetDataStore(root=root)
    try:
        assert store.list_usable_versions() == []
    finally:
        store.close()


def test_cli_bootstrap_exit_codes_and_output(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from qts.cli import main

    root, fx = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["data", "bootstrap"])
    assert result.exit_code == 0, result.output
    assert "INGESTED" in result.output
    assert "SYNTHETIC" in result.output
    # second invocation: READY, idempotent
    result2 = runner.invoke(main, ["data", "bootstrap"])
    assert result2.exit_code == 0, result2.output
    assert "READY" in result2.output


def test_cli_bootstrap_fails_closed_missing_fixture(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from qts.cli import main

    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["data", "bootstrap"])
    assert result.exit_code == 1
    assert "FAILED" in result.output


def test_cli_health_reports_truthful_usability(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from qts.cli import main

    root, fx = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    # before bootstrap: honest "none usable" report
    r0 = runner.invoke(main, ["health"])
    assert r0.exit_code == 0
    assert "usable versions: 0 of 0" in r0.output
    assert "qts data bootstrap" in r0.output
    bootstrap_data(root=root, fixture=fx)
    r1 = runner.invoke(main, ["health"])
    assert r1.exit_code == 0
    assert "usable versions: 1 of 1" in r1.output
    assert "class=SYNTHETIC" in r1.output
    # phantom: remove parquet -> health must demote it, never claim usable
    version_dirs = list((root / "curated" / "instrument=XAUUSD" / "venue=MT5" / "timeframe=1H").iterdir())
    shutil.rmtree(version_dirs[0])
    r2 = runner.invoke(main, ["health"])
    assert r2.exit_code == 0
    assert "usable versions: 0 of 1" in r2.output
    assert "NOT usable" in r2.output


def test_classify_source_covers_all_data_classes():
    assert classify_source("SYNTHETIC:fixture:x.csv") == "SYNTHETIC"
    assert classify_source("synthetic_gbm") == "SYNTHETIC"
    assert classify_source("mt5_history_export.csv") == "BROKER-DERIVED"
    assert classify_source("MODEL-DERIVED:predictions") == "MODEL-DERIVED"
    assert classify_source("imputed:gaps") == "IMPUTED"
    assert classify_source("estimated:spread") == "ESTIMATED"
    assert classify_source("REAL:dukascopy") == "REAL"
    # fail-safe: unknown/None provenance is NEVER treated as REAL
    assert classify_source(None) != "REAL"
    assert classify_source("some_random_file.csv") != "REAL"
    for c in DATA_CLASSES:
        assert isinstance(c, str)


def test_fixture_is_synthetic_gbm_and_documented():
    """Provenance truth: the committed fixture is byte-identical to GBM(seed=42).

    It must therefore never be represented as real market history anywhere.
    """
    from qts.data.synthetic import generate_gbm_bars

    bars = generate_gbm_bars(periods=500, timeframe_minutes=60, seed=42)
    with open(FIXTURE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(bars) == 500
    for b, r in zip(bars, rows, strict=True):
        assert f"{float(r['close']):.2f}" == f"{float(b.close):.2f}"
