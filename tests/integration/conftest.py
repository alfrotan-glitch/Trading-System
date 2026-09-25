"""Fixtures shared by the DEMO execution integration tests.

``demo_env`` builds one hermetic operator environment (authorization, registry,
setup, DB, audit log, kill-switch self test — all inside ``tmp_path``) so no
test can touch the operator's real state.
"""

from __future__ import annotations

from demo_harness import demo_env  # noqa: F401  (pytest fixture)
