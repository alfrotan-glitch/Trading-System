"""Central SQLite connection helper — deterministic lifecycle, Windows-safe.

Every file-backed SQLite connection in the codebase MUST be opened through
``connect()``. Rationale (root cause of WinError 32 during temp-dir cleanup):

* ``with sqlite3.connect(path) as con:`` commits/rolls back but does NOT close
  the connection. Closure is left to CPython refcounting/GC, which on Windows
  keeps an OS file handle open at nondeterministic times. ``TemporaryDirectory``
  cleanup then fails with ``PermissionError [WinError 32]``.
* Re-opening a database inside ``close()``/``__del__`` recreates deleted files
  and re-acquires locks during interpreter shutdown.

``connect()`` preserves the transactional semantics of the sqlite3 connection
context manager (commit on success, rollback on exception) and additionally
guarantees ``con.close()`` on every exit path.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def connect(database: Path | str, **kwargs: Any) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection that is ALWAYS closed on context exit.

    Semantics match ``with sqlite3.connect(...) as con:`` (commit on success,
    rollback on error) plus deterministic ``close()`` — required on Windows
    where open handles block file/directory deletion.
    """
    con = sqlite3.connect(database, **kwargs)  # sqlite3 accepts str/Path
    try:
        with con:
            yield con
    finally:
        con.close()
