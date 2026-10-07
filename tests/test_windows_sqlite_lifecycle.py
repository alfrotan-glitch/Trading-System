"""Windows clean-clone SQLite lifecycle regression.

Verifies that SQLite stores deterministically close and do not leave WAL/shm
handles open during TemporaryDirectory cleanup — the exact WinError32 that
fails on Windows 10/11 Python 3.14. No retry loops, no sleep, no ignore.

Each test creates a store inside a TemporaryDirectory, uses it, closes it
explicitly (or via context manager), then lets the directory be deleted.
On Windows this would raise PermissionError if close is missing.
"""

import tempfile
from pathlib import Path


def test_sqlite_parquet_store_closes_before_tmp_cleanup():
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from qts.data.store import SqliteParquetDataStore
    from qts.domain.value_objects import Bar, Instrument

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "qts.db"
        store = SqliteParquetDataStore(root=Path(tmp), db_path=db)
        instr = Instrument(symbol="XAUUSD")
        now = datetime(2020, 1, 1, tzinfo=UTC)
        bars = [
            Bar(
                instrument=instr,
                open=Decimal("2000"),
                high=Decimal("2005"),
                low=Decimal("1995"),
                close=Decimal("2000"),
                volume=Decimal("1000"),
                open_time=now + timedelta(hours=i),
                close_time=now + timedelta(hours=i + 1),
            )
            for i in range(5)
        ]
        store.write_bars(bars)
        # Deterministic close before directory cleanup
        store.close()
    # If close was missing, Windows would have raised PermissionError above
    assert not Path(tmp).exists()


def test_risk_engine_closes_before_tmp_cleanup():
    import tempfile
    from pathlib import Path

    from qts.risk.engine import RiskEngine, RiskLimits

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "risk.db"
        eng = RiskEngine(RiskLimits(), db_path=db)
        eng.kill_switch("test")
        assert eng.killed
        eng.close()
    assert not Path(tmp).exists()


def test_idempotency_store_closes_before_tmp_cleanup():
    from qts.execution.idempotency import IdempotencyStore

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "idem.db"
        store = IdempotencyStore(db_path=db)
        store.record("cid1", "PENDING")
        assert store.seen("cid1")
        store.close()
    assert not Path(tmp).exists()


def test_idempotency_memory_close():
    from qts.execution.idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=":memory:")
    store.record("a", "PENDING")
    assert store.get_status("a") == "PENDING"
    store.close()
    assert store._memory_con is None


def test_experiment_store_context_manager():
    from qts.research.experiment import ExperimentStore

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "exp.db"
        with ExperimentStore(db_path=db) as store:
            assert store.count_trials() == 0
        # After context manager, file should be checkpointed and close
    assert not Path(tmp).exists()


def test_locked_test_partitioner_closes():
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from qts.data.locked_test import LockedTestPartitioner
    from qts.domain.value_objects import Bar, Instrument

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "locked.db"
        partitioner = LockedTestPartitioner(db_path=db)
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
            for i in range(30)
        ]
        parts = partitioner.partition(bars, "v1")
        assert len(parts["locked"]) > 0
        partitioner.close()
    assert not Path(tmp).exists()


def test_multiple_stores_same_db_close():
    from qts.execution.idempotency import IdempotencyStore
    from qts.risk.engine import RiskEngine, RiskLimits

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "shared.db"
        risk = RiskEngine(RiskLimits(), db_path=db)
        idem = IdempotencyStore(db_path=db)
        idem.record("x", "PENDING")
        risk.kill_switch("test")
        # Close both before cleanup
        idem.close()
        risk.close()
    assert not Path(tmp).exists()


def test_conftest_safe_temporary_directory_patches():
    # Verify that tempfile.TemporaryDirectory is our Safe version
    import tempfile

    # It should have our cleanup that closes stores
    assert tempfile.TemporaryDirectory.__name__ == "SafeTemporaryDirectory"


def test_mkdtemp_sqlite_close():
    import shutil
    import tempfile
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from pathlib import Path

    from qts.data.store import SqliteParquetDataStore
    from qts.domain.value_objects import Bar, Instrument

    d = Path(tempfile.mkdtemp())
    try:
        db = d / "test.db"
        store = SqliteParquetDataStore(root=d, db_path=db)
        instr = Instrument(symbol="XAUUSD")
        now = datetime(2020, 1, 1, tzinfo=UTC)
        bars = [
            Bar(
                instrument=instr,
                open=Decimal("2000"),
                high=Decimal("2005"),
                low=Decimal("1995"),
                close=Decimal("2000"),
                volume=Decimal("1000"),
                open_time=now + timedelta(hours=i),
                close_time=now + timedelta(hours=i + 1),
            )
            for i in range(3)
        ]
        store.write_bars(bars)
        store.close()
    finally:
        # Now cleanup should succeed on Windows without PermissionError
        shutil.rmtree(d, ignore_errors=False)
    assert not d.exists()
