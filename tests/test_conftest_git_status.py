"""Regression: the test-suite git guard must see every dirty path.

Bug (fixed 2026-10-11): ``_git_status_paths`` split ``git status -z`` output on the
two characters backslash+'0' instead of NUL, so the whole listing became one bogus
path and dirty files went unseen by the guard.

Import-isolation note (fixed 2026-10-11, Agent 4): this test used a bare
``import conftest`` and ``monkeypatch.setattr``. When a pytest worker collects
``tests/integration`` first, that directory's ``conftest.py`` occupies the
top-level module name ``conftest``, and ``tests/conftest.py`` is then never
imported under any name in that worker (reproduced deterministically with
``pytest tests/integration tests/test_conftest_git_status.py`` and on the pristine
baseline under ``pytest -n auto``): the bare import bound to the INTEGRATION
conftest and failed with ``AttributeError: ... has no attribute '_REPO_ROOT'``.
The parser is therefore exercised in a fresh subprocess where only ``tests/`` is
on ``sys.path``, so ``import conftest`` is unambiguous, and ``_REPO_ROOT`` is
overridden explicitly in the child.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

_CHILD = """
import pathlib, sys
sys.path.insert(0, {tests_dir!r})
import conftest
conftest._REPO_ROOT = pathlib.Path({repo!r})
print(repr(sorted(conftest._git_status_paths())))
"""


def _git(cwd, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_git_status_guard_sees_every_dirty_path(tmp_path) -> None:
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

    proc = subprocess.run(
        [sys.executable, "-c", _CHILD.format(tests_dir=str(TESTS_DIR), repo=str(repo))],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    paths = set(ast.literal_eval(proc.stdout.strip().splitlines()[-1]))

    assert {"tracked_a.txt", "untracked_c.txt", "renamed.txt"} <= paths
    # The rename origin is not a dirty file of its own; it must not be reported.
    assert "to_rename.txt" not in paths
    # Clean files must not appear.
    assert "tracked_b.txt" not in paths
