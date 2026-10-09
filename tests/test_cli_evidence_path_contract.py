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
        "audit_jsonl": "logs/audit.jsonl",
        "paper_cli_db": "data/sqlite/paper_cli.db",
        "paper_cli_idemp_db": "data/sqlite/paper_cli_idemp.db",
        "paper_cli_risk_db": "data/sqlite/paper_cli_risk.db",
        "shadow_cli_db": "data/sqlite/shadow_cli.db",
        "shadow_cli_idemp_db": "data/sqlite/shadow_cli_idemp.db",
        "shadow_cli_risk_db": "data/sqlite/shadow_cli_risk.db",
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



def test_cli_durable_writers_use_registered_artifact_paths() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src/qts/cli/ops.py").read_text(encoding="utf-8")

    for artifact in (
        "dry_run",
        "micro",
        "paper_trades",
        "shadow_intents",
        "paper_cli_db",
        "paper_cli_idemp_db",
        "paper_cli_risk_db",
        "shadow_cli_db",
        "shadow_cli_idemp_db",
        "shadow_cli_risk_db",
        "db",
        "audit_jsonl",
    ):
        assert f'artifact_path("{artifact}")' in source

    for relative_write in (
        'Path("data/evidence/dry_run.json")',
        'Path("data/evidence/micro.json")',
        'Path("data/evidence/paper_trades.json")',
        'Path("data/evidence/shadow_intents.json")',
        'Path("data/sqlite/paper_cli.db")',
        'Path("data/sqlite/shadow_cli.db")',
    ):
        assert relative_write not in source
