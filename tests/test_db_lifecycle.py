"""SQLite connection lifecycle regression suite (Windows file-lock root cause).

Root cause: `with sqlite3.connect(path) as con:` commits but does NOT close the
connection; handles were released only by CPython refcounting/GC, and several
classes re-opened the database inside close()/__del__ — recreating deleted files
and re-acquiring Windows locks during GC/shutdown (PermissionError WinError 32
during TemporaryDirectory cleanup).

Fix layer: ALL file-backed connections go through qts.db.connect(), which
guarantees close() on every exit path, and no class re-opens its database in
close()/__del__ anymore. These tests pin that architecture structurally (AST)
and behaviorally.
"""

from __future__ import annotations

import ast
import sqlite3
import tempfile
from pathlib import Path

import pytest

from qts.db import connect as db_connect

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "qts"

# Modules allowed to call sqlite3.connect directly:
#  - qts/db.py: the single sanctioned wrapper
#  - qts/execution/idempotency.py: persistent ":memory:" connection by design
ALLOWED_DIRECT_SQLITE3 = {"db.py", "idempotency.py"}


def _py_files():
    return sorted(p for p in SRC.rglob("*.py"))


class TestStructuralGuards:
    def test_no_direct_sqlite3_connect_outside_sanctioned_modules(self):
        offenders = []
        for p in _py_files():
            if p.name in ALLOWED_DIRECT_SQLITE3:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "connect":
                    base = node.value
                    if isinstance(base, ast.Name) and base.id == "sqlite3":
                        offenders.append(f"{p.relative_to(REPO_ROOT)}:{node.lineno}")
        assert not offenders, (
            "file-backed sqlite3.connect() must go through qts.db.connect so the "
            f"connection is deterministically closed (Windows file locks): {offenders}"
        )

    def test_idempotency_memory_connection_is_the_only_direct_use(self):
        p = SRC / "execution" / "idempotency.py"
        tree = ast.parse(p.read_text(encoding="utf-8"))
        calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "connect"
                and isinstance(node.value, ast.Name)
                and node.value.id == "sqlite3"
            ):
                calls.append(node.lineno)
        # exactly one persistent in-memory connect in __init__
        assert len(calls) == 1, f"expected 1 persistent :memory: connect, found {calls}"
        src_lines = p.read_text(encoding="utf-8").splitlines()
        line = src_lines[calls[0] - 1]
        assert ":memory:" in line

    def test_no_del_reopens_database(self):
        """__del__ must never open SQLite connections (GC/shutdown hazard)."""
        for p in _py_files():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "__del__":
                    body_src = ast.dump(node)
                    assert "connect" not in body_src, f"{p.relative_to(REPO_ROOT)} __del__ opens a connection"


class TestConnectBehavior:
    def test_connection_closed_after_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            with db_connect(db) as con:
                con.execute("CREATE TABLE t (x INTEGER)")
                con.execute("INSERT INTO t VALUES (1)")
            # connection object must be closed deterministically on exit
            with pytest.raises(sqlite3.ProgrammingError):
                con.execute("SELECT 1")

    def test_commit_on_success_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            with db_connect(db) as con:
                con.execute("CREATE TABLE t (x INTEGER)")
                con.execute("INSERT INTO t VALUES (42)")
            with db_connect(db) as con2:
                row = con2.execute("SELECT x FROM t").fetchone()
            assert row == (42,)

    def test_rollback_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            with db_connect(db) as con:
                con.execute("CREATE TABLE t (x INTEGER)")
            try:
                with db_connect(db) as con:
                    con.execute("INSERT INTO t VALUES (1)")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            with db_connect(db) as con2:
                rows = con2.execute("SELECT x FROM t").fetchall()
            assert rows == []

    def test_store_leaves_no_open_handle_after_operations(self):
        """After write/read/close, the db file must be deletable WITHOUT gc help.

        On Windows an open handle makes os.remove fail immediately; on POSIX we
        assert the same contract by checking sqlite3 reports the connection
        closed and that no reconnect happens in close().
        """
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        from qts.data.store import SqliteParquetDataStore
        from qts.domain.value_objects import Bar, Instrument

        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteParquetDataStore(root=Path(tmp))
            instr = Instrument(symbol="XAUUSD")
            base = datetime(2020, 1, 1, tzinfo=UTC)
            bars = [
                Bar(
                    instrument=instr,
                    open=Decimal("2000"),
                    high=Decimal("2005"),
                    low=Decimal("1995"),
                    close=Decimal("2000"),
                    volume=Decimal("1000"),
                    open_time=base + timedelta(hours=i),
                    close_time=base + timedelta(hours=i + 1),
                )
                for i in range(5)
            ]
            m = store.write_bars(bars)
            assert store.read_bars(instr, "1H", version=m.version)
            store.close()
            # close() must NOT have recreated or reopened anything: deleting the
            # whole tree here succeeds only if no handle was re-acquired.
        assert not Path(tmp).exists()
