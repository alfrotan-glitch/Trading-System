"""Windows regression: the promotion workflow must release promo.db before
TemporaryDirectory cleanup.

Root cause of the Windows-only failure (Python 3.13, WinError 32):
``test_one_way_promotion`` simulated manual SQL edits with two raw
``with sqlite3.connect(promo.db) as con:`` blocks. The sqlite3 connection
context manager commits/rolls back but does NOT close the connection, so both
OS file handles survived (referenced by function locals) until
``TemporaryDirectory.__exit__`` ran its strict ``rmtree`` — which on Windows
fails with ``PermissionError [WinError 32]`` while any handle is open. POSIX
unlink succeeds on open files, which is why the leak was invisible on Linux.

Fix layer: every file-backed SQLite open goes through ``qts.db.connect``
(guaranteed close in ``finally``), and the structural guard in
``tests/test_db_lifecycle.py`` now scans ``tests/`` too, so a raw file-backed
``sqlite3.connect`` can never re-enter the codebase on any platform.

This suite proves deterministically — identically on Windows and POSIX, not
by relying on delete semantics — that after the full one-way promotion
workflow there is no live SQLite connection holding the promotion database
open when the temporary directory cleanup runs.
"""

from __future__ import annotations

import gc
import sqlite3
import tempfile
from pathlib import Path

import pytest

from qts.db import connect as db_connect
from qts.edge.promotion import PromotionLedger, PromotionState


def _open_connections_to(target: Path) -> list[sqlite3.Connection]:
    """Return every live sqlite3.Connection that currently holds *target* open.

    Platform-independent proof: scans all interpreter objects for connections
    whose ``PRAGMA database_list`` names the target file. Closed connections
    raise and hold no handle, so they are excluded.
    """
    gc.collect()
    hits: list[sqlite3.Connection] = []
    for obj in gc.get_objects():
        if not isinstance(obj, sqlite3.Connection):
            continue
        try:
            rows = obj.execute("PRAGMA database_list").fetchall()
        except sqlite3.Error:
            continue  # closed/unusable connection holds no OS handle
        for row in rows:
            if row[2] and Path(str(row[2])) == target:
                hits.append(obj)
                break
    return hits


def test_promotion_workflow_releases_promo_db_before_tempdir_cleanup():
    """The exact workflow that failed on Windows, then a strict-handle proof."""
    with tempfile.TemporaryDirectory() as tmp:  # strict cleanup: no ignore_errors, no retry
        db = Path(tmp) / "promo.db"
        ledger = PromotionLedger(db_path=db)
        sid = "release-s"

        # one-way ladder, mirroring test_one_way_promotion exactly
        assert ledger.get_state(sid) == PromotionState.RESEARCH
        with pytest.raises(ValueError, match="not allowed"):
            ledger.transition(sid, PromotionState.VALIDATED)  # no skip
        ledger.transition(sid, PromotionState.CANDIDATE)
        assert ledger.get_state(sid) == PromotionState.CANDIDATE
        ledger.transition(sid, PromotionState.VALIDATED)
        assert ledger.get_state(sid) == PromotionState.VALIDATED
        ledger.suspend_on_anomaly(sid, reason="drawdown breach")
        assert ledger.get_state(sid) == PromotionState.SUSPENDED
        ledger.transition(sid, PromotionState.RESEARCH)  # backwards on anomaly
        assert ledger.get_state(sid) == PromotionState.RESEARCH

        # manual-edit simulation exactly as in test_one_way_promotion — the two
        # opens that previously leaked Windows file handles
        with db_connect(db) as con:
            con.execute(
                "UPDATE promotion_state SET state=? WHERE strategy_id=?",
                (PromotionState.LIVE_ELIGIBLE.value, sid),
            )
        with db_connect(db) as con:
            con.execute(
                "UPDATE promotion_state SET state=? WHERE strategy_id=?",
                (PromotionState.RESEARCH.value, sid),
            )
        with pytest.raises(ValueError):
            ledger.transition(sid, PromotionState.LIVE_ELIGIBLE)  # jump still refused

        assert db.exists(), "workflow must have really used promo.db (test not vacuous)"
        ledger.close()

        # deterministic proof, identical on Windows and POSIX: no live
        # connection holds promo.db open while the temp dir is still alive
        leaked = _open_connections_to(db)
        assert leaked == [], f"promotion DB still held open before temp cleanup: {leaked!r}"
        assert db.exists()
    # exiting the TemporaryDirectory above performs the real OS deletion with a
    # strict rmtree: on Windows this is precisely the step that raised
    # PermissionError [WinError 32] when a handle leaked.


def test_handle_detector_catches_a_leaked_connection():
    """Negative control: the release proof above must never be vacuous.

    This is the only sanctioned raw file-backed ``sqlite3.connect`` in tests
    (allowlisted in tests/test_db_lifecycle.py): it intentionally reproduces
    the original leak, asserts the detector catches it, then closes the
    connection deterministically before the temp dir exits.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "leak.db"
        with db_connect(db) as con:
            con.execute("CREATE TABLE t (x INTEGER)")
        assert _open_connections_to(db) == []

        leaked = sqlite3.connect(db)  # intentional leak, closed in finally
        try:
            found = _open_connections_to(db)
            assert len(found) == 1, "detector failed to see an open connection"
            assert found[0] is leaked
        finally:
            leaked.close()
        assert _open_connections_to(db) == []


def test_db_connect_closes_handle_when_body_raises():
    """qts.db.connect must release the file handle even on the error path."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "raise.db"
        with pytest.raises(RuntimeError), db_connect(db) as con:
            con.execute("CREATE TABLE t (x INTEGER)")
            raise RuntimeError("boom")
        assert _open_connections_to(db) == []
