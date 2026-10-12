"""Regression: the test-suite git guard must see every dirty path.

Bug (fixed 2026-10-11): ``_git_status_paths`` split ``git status -z`` output on the
two characters backslash+'0' instead of NUL, so the whole listing became one bogus
path and dirty files went unseen by the guard.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("_root_conftest", Path(__file__).with_name("conftest.py"))
assert _SPEC is not None and _SPEC.loader is not None
conftest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(conftest)


def _git(cwd, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_git_status_guard_sees_every_dirty_path(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked_a.txt").write_text("a\n", encoding="utf-8")
    (repo / "tracked_b.txt").write_text("b\n", encoding="utf-8")
    (repo / "to_rename.txt").write_text("r\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")

    (repo / "tracked_a.txt").write_text("changed\n", encoding="utf-8")  # modified
    (repo / "untracked_c.txt").write_text("new\n", encoding="utf-8")  # untracked
    _git(repo, "mv", "to_rename.txt", "renamed.txt")  # staged rename

    monkeypatch.setattr(conftest, "_REPO_ROOT", repo)
    paths = conftest._git_status_paths()

    assert {"tracked_a.txt", "untracked_c.txt", "renamed.txt"} <= paths
    # The rename origin is not a dirty file of its own; it must not be reported.
    assert "to_rename.txt" not in paths
    # Clean files must not appear.
    assert "tracked_b.txt" not in paths
