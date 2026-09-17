"""Run lineage identity — binds evidence to the exact code that produced it.

Every session/evidence record should carry this string (finding #21/#42):
results that cannot be traced to a code version are not promotion-grade.
Resolution order: QTS_GIT_COMMIT env (set by launchers) > git rev-parse >
package version > "unknown" (never fabricated).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def git_commit() -> str | None:
    env_commit = os.getenv("QTS_GIT_COMMIT")
    if env_commit:
        return env_commit
    for candidate in (Path.cwd(), Path(__file__).resolve().parent):
        git_dir = candidate / ".git"
        if git_dir.exists():
            with contextlib.suppress(Exception):
                out = subprocess.run(
                    ["git", "-C", str(candidate), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                commit = out.stdout.strip()
                if commit:
                    return commit
    return None


def code_version() -> str:
    """Human-auditable code identity, e.g. ``0.1.0+1b7fbed`` or ``0.1.0+unknown``."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            base = version("qts")
        except PackageNotFoundError:
            base = "0.0.0-dev"
    except Exception:
        base = "0.0.0-dev"
    commit = git_commit()
    short = (commit or "unknown")[:12]
    return f"{base}+{short}"
