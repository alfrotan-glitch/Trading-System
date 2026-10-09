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
    """Assesses the repository's own dataset — and refuses it."""
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path))
    result = runner.invoke(edge, ["readiness"])
    # Either the store has a version to assess, or it says so plainly; neither
    # may report readiness on the synthetic fixture.
    if "no dataset versions available" in result.output:
        assert result.exit_code == 2
    else:
        assert result.exit_code == 1
        assert "SYNTHETIC" in result.output


def test_the_verdict_is_parseable_json(runner: CliRunner) -> None:
    result = runner.invoke(edge, ["readiness", "--ceiling-days", "30",
                                  "--source-label", "MT5_HISTORY"])
    tail = result.output[result.output.index("{\n"):]
    payload = json.loads(tail[: tail.rindex("}") + 1])
    assert payload["ready_for_claims"] is False
    assert "B3-DEPTH" in payload["unmet_blocking_requirements"]
