"""Regression tests for CLI evidence artifact path anchoring."""

from pathlib import Path

from qts.config.paths import ENV_OVERRIDES, RELATIVE_DEFAULTS, artifact_path


def test_cli_evidence_artifacts_are_registered_and_state_root_anchored(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path))
    expected = {
        "dry_run": "data/evidence/dry_run.json",
        "micro": "data/evidence/micro.json",
        "paper_trades": "data/evidence/paper_trades.json",
        "shadow_intents": "data/evidence/shadow_intents.json",
    }

    for name, relative_path in expected.items():
        assert RELATIVE_DEFAULTS[name] == relative_path
        assert artifact_path(name) == tmp_path / relative_path
        assert ENV_OVERRIDES[name]


def test_cli_evidence_artifact_environment_overrides_are_honoured(
    monkeypatch, tmp_path: Path
) -> None:
    override = tmp_path / "operator-evidence" / "micro.json"
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("QTS_MICRO_EVIDENCE_PATH", str(override))

    assert artifact_path("micro") == override
