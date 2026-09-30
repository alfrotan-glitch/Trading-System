"""Shared CLI helpers."""

from __future__ import annotations


def observatory_db_path() -> str:
    """Callable Click default — anchored at the state root, never at cwd."""
    from qts.config.paths import artifact_path

    return str(artifact_path("observatory_db"))
