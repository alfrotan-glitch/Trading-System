"""Regression: the test-suite git guard must see every dirty path.

Bug (fixed 2026-10-11): ``_git_status_paths`` split ``git status -z`` output on the
two characters backslash+'0' instead of NUL, so the whole listing became one bogus
path and dirty files went unseen by the guard.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _root_test_conftest(pytestconfig: pytest.Config):
    """Find the root test conftest by path, not the ambiguous module name.

    The integration test directory has its own ``conftest.py``. Importing the
    bare name ``conftest`` makes this test order-dependent when pytest has
    already loaded that sibling plugin.
    """
    target = Path(__file__).resolve().parent / "conftest.py"
    matches = [
        plugin
        for plugin in pytestconfig.pluginmanager.get_plugins()
        if getattr(plugin, "__file__", None) is not None and Path(plugin.__file__).resolve() == target
    ]
    assert len(matches) == 1, f"expected one root test conftest at {target}, found {len(matches)}"
    return matches[0]


def _git(cwd, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_git_status_guard_sees_every_dirty_path(tmp_path, monkeypatch, pytestconfig) -> None:
    conftest = _root_test_conftest(pytestconfig)
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
