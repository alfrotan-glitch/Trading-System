"""The ``qts edge readiness`` command — the gate that runs before the benchmark.

It must fail closed with a non-zero exit when the data cannot support a claim,
so that a scripted pipeline cannot carry on as if it could.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from qts.cli.edge import edge


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_a_retention_ceiling_below_the_minimum_fails_closed(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "30",
                                  "--source-label", "MT5_HISTORY"])
    assert result.exit_code == 1
    assert "NOT READY FOR CLAIMS" in result.output
    assert "B3-DEPTH" in result.output
    assert "FAIL" in result.output


def test_the_report_says_how_much_history_would_be_needed(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "30",
                                  "--source-label", "MT5_HISTORY"])
    assert "calendar days of history" in result.output


def test_a_deep_enough_ceiling_passes(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "1000",
                                  "--source-label", "MT5_HISTORY"])
    assert result.exit_code == 0, result.output


def test_the_command_reports_the_preregistered_minimums(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "30"])
    assert "Frozen candidate set verified (3 hypotheses)" in result.output
    assert "5,000 bars" in result.output or "5000 bars" in result.output


def test_the_json_payload_is_emitted_for_the_audit_trail(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "30"])
    assert '"schema": "qts.benchmark_readiness.v1"' in result.output
    assert '"ready_for_claims": false' in result.output


def test_synthetic_data_is_refused_wherever_it_is_declared(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "1000",
                                  "--source-label", "SYNTHETIC:fixture:XAUUSD_1H_500.csv"])
    assert result.exit_code == 1
    assert "B1-REAL-PROVENANCE" in result.output


def test_an_existing_dataset_can_be_assessed(runner: CliRunner, tmp_path, monkeypatch) -> None:
    """The repository's synthetic fixture is assessed — and refused.

    The store is built inside ``tmp_path`` rather than read from the
    repository. Reading the ambient store made this test assert whatever
    happened to have been ingested last, which is why ingesting real history
    broke it: "latest" resolved to a real 1H dataset, the output no longer
    said SYNTHETIC, and a test about refusing synthetic data failed for
    having no synthetic data. Building the fixture here makes the assertion
    about the actual contract again — synthetic history must be refused.
    """
    from pathlib import Path

    from qts.data.ingest import ingest_csv
    from qts.data.store import SqliteParquetDataStore

    store = SqliteParquetDataStore(root=tmp_path / "data")
    ingest_csv(
        Path("data/fixtures/XAUUSD_1H_500.csv"),
        instrument="XAUUSD",
        timeframe="1H",
        venue="MT5",
        store=store,
        source="SYNTHETIC:fixture:XAUUSD_1H_500.csv",
    )
    # The CLI imports the store class inside the command, so patching the
    # module attribute is what redirects it.
    monkeypatch.setattr("qts.data.store.SqliteParquetDataStore", lambda *a, **kw: store)

    result = runner.invoke(edge, ["readiness"])
    assert result.exit_code == 1, result.output
    assert "NOT READY FOR CLAIMS" in result.output
    assert "SYNTHETIC" in result.output


def test_the_verdict_is_parseable_json(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "30",
                                  "--source-label", "MT5_HISTORY"])
    tail = result.output[result.output.index("{\n"):]
    payload = json.loads(tail[: tail.rindex("}") + 1])
    assert payload["ready_for_claims"] is False
    assert "B3-DEPTH" in payload["unmet_blocking_requirements"]


def _fifteen_min_csv(path) -> None:
    """A small 15m series. The 1H fixture cannot be reused as 15m: its cadence
    fails the quality gate, and a test that cannot build its own premise would
    end up asserting whatever the gate happens to reject."""
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    lines = ["time,open,high,low,close,volume"]
    for i in range(600):
        t = start + timedelta(minutes=15 * i)
        px = 2000.0 + (i % 40)
        lines.append(
            f"{t.isoformat()},{px},{px + 1.5},{px - 1.5},{px + 0.5},100"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ingest(store, path, timeframe: str, source: str) -> None:
    from qts.data.ingest import ingest_csv

    ingest_csv(
        path,
        instrument="XAUUSD",
        timeframe=timeframe,
        venue="MT5",
        store=store,
        source=source,
    )


def test_the_timeframe_selects_the_dataset_it_reports_on(runner, tmp_path, monkeypatch):
    """`--timeframe` must choose a dataset, never relabel whichever is last.

    Ingesting one instrument at several timeframes registers one version per
    timeframe. Taking the newest version and overriding only the timeframe
    label reported a 6,513-bar 1H dataset under a "timeframe=15m" verdict —
    a confident report about the wrong data, which is worse than no report.
    """
    from qts.data.store import SqliteParquetDataStore

    store = SqliteParquetDataStore(root=tmp_path / "data")
    fifteen = tmp_path / "15m.csv"
    _fifteen_min_csv(fifteen)
    _ingest(store, fifteen, "15m", "SYNTHETIC:fixture:15m")
    _ingest(store, "data/fixtures/XAUUSD_1H_500.csv", "1H", "SYNTHETIC:fixture:1H")
    monkeypatch.setattr("qts.data.store.SqliteParquetDataStore", lambda *a, **kw: store)

    result = runner.invoke(edge, ["readiness", "--timeframe", "15m"])
    assert result.exit_code in (0, 1), result.output
    assert "15m" in result.output
    # The provenance quoted must be the 15m ingest, not the 1H one.
    assert "SYNTHETIC:fixture:15m" in result.output
    assert "SYNTHETIC:fixture:1H" not in result.output


def test_without_a_timeframe_the_candidate_timeframe_is_preferred(runner, tmp_path, monkeypatch):
    """The frozen candidates are defined on 15m; that is the sensible default."""
    from qts.data.store import SqliteParquetDataStore

    store = SqliteParquetDataStore(root=tmp_path / "data")
    fifteen = tmp_path / "15m.csv"
    _fifteen_min_csv(fifteen)
    _ingest(store, fifteen, "15m", "SYNTHETIC:fixture:15m")
    _ingest(store, "data/fixtures/XAUUSD_1H_500.csv", "1H", "SYNTHETIC:fixture:1H")
    monkeypatch.setattr("qts.data.store.SqliteParquetDataStore", lambda *a, **kw: store)

    result = runner.invoke(edge, ["readiness"])
    assert result.exit_code in (0, 1), result.output
    assert "SYNTHETIC:fixture:15m" in result.output


def test_a_single_dataset_is_still_assessed_on_its_own_timeframe(runner, tmp_path, monkeypatch):
    """No match on the wanted timeframe must not become 'no answer'."""
    from qts.data.store import SqliteParquetDataStore

    store = SqliteParquetDataStore(root=tmp_path / "data")
    _ingest(store, "data/fixtures/XAUUSD_1H_500.csv", "1H", "SYNTHETIC:fixture:1H")
    monkeypatch.setattr("qts.data.store.SqliteParquetDataStore", lambda *a, **kw: store)

    result = runner.invoke(edge, ["readiness"])
    assert result.exit_code == 1, result.output
    assert "SYNTHETIC" in result.output
    assert "1H" in result.output
