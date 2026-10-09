"""State root must not change when the CLI is launched from another cwd."""

from pathlib import Path

from qts.config.paths import artifact_path, state_root


def test_state_root_does_not_switch_to_foreign_cwd_with_data_directory(
    monkeypatch, tmp_path: Path
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    foreign_cwd = tmp_path / "foreign"
    (foreign_cwd / "data").mkdir(parents=True)
    # A deployment that requires one canonical root across arbitrary launch
    # directories pins it explicitly; a foreign data/ tree must not override it.
    monkeypatch.setenv("QTS_STATE_ROOT", str(repo_root))
    monkeypatch.chdir(foreign_cwd)

    assert state_root() == repo_root
    assert artifact_path("micro") == repo_root / "data/evidence/micro.json"
