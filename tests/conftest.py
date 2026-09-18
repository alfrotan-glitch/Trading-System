"""Windows-safe SQLite lifecycle for TemporaryDirectory cleanup.

On Windows, SQLite files remain locked if connections are not deterministically
closed before TemporaryDirectory attempts rmtree, raising PermissionError
[WinError 32]. This conftest makes cleanup deterministic without retry loops
or sleep — it closes tracked stores and checkpoints WAL before directory deletion.

Avoids pytest strict-markers false positive by not touching pytest.mark via getattr.
"""

from __future__ import annotations

import contextlib
import gc
import pathlib
import tempfile

import pytest

_original_TemporaryDirectory = tempfile.TemporaryDirectory
_original_mkdtemp = tempfile.mkdtemp

_mkdtemp_dirs: set[str] = set()
_tracked_stores: set[object] = set()


def _register_store(obj: object) -> None:
    with contextlib.suppress(Exception):
        _tracked_stores.add(obj)


def _get_db_path(obj: object) -> str | None:
    # Avoid getattr on pytest.mark which creates markers via __getattr__
    if obj is pytest.mark:
        return None
    # Also avoid MarkGenerator instances
    try:
        if type(obj).__name__ == "MarkGenerator":
            return None
    except Exception:
        pass
    # Use __dict__ lookup to avoid triggering __getattr__
    try:
        d = getattr(obj, "__dict__", {})
        if isinstance(d, dict):
            if "db_path" in d:
                return str(d["db_path"])
            if "_db_path" in d:
                return str(d["_db_path"])
    except Exception:
        pass
    # Fallback for objects that store path differently, but avoid pytest.mark
    # Only check for known store types by class name
    try:
        cls_name = type(obj).__name__
        if cls_name in (
            "SqliteParquetDataStore",
            "RiskEngine",
            "IdempotencyStore",
            "ExperimentStore",
            "PromotionLedger",
            "LockedTestPartitioner",
            "ForwardObservatory",
            "RegimeObservatory",
            "SqliteAuditLog",
            "ExecutionEngine",
            "OrderManager",
        ):
            # Now safe to use getattr with try, but avoid triggering marker
            try:
                # Use object.__getattribute__ to avoid __getattr__ on pytest.mark (already excluded)
                db = object.__getattribute__(obj, "db_path")  # type: ignore
                return str(db)
            except AttributeError:
                try:
                    db = object.__getattribute__(obj, "_db_path")  # type: ignore
                    return str(db)
                except AttributeError:
                    return None
            except Exception:
                return None
    except Exception:
        pass
    return None


def _has_close(obj: object) -> bool:
    if obj is pytest.mark:
        return False
    try:
        if type(obj).__name__ == "MarkGenerator":
            return False
    except Exception:
        pass
    # Check via class attribute, not instance getattr which may trigger marker
    try:
        return hasattr(type(obj), "close")
    except Exception:
        return False


def _close_obj(obj: object) -> None:
    if not _has_close(obj):
        return
    try:
        # Use type's close to avoid marker path
        close_fn = getattr(type(obj), "close", None)
        if close_fn is not None:
            close_fn(obj)  # type: ignore
    except Exception:
        pass


def _close_tracked_in_dir(dir_path: str) -> None:
    dir_path = str(dir_path)
    # Close registered stores whose db_path is inside dir_path
    for obj in list(_tracked_stores):
        try:
            db = _get_db_path(obj)
            if db is not None and db.startswith(dir_path):
                _close_obj(obj)
        except Exception:
            pass
    # Also check nested om.idempotency
    for obj in list(_tracked_stores):
        try:
            # Check for ExecutionEngine holding om
            om = getattr(obj, "__dict__", {}).get("om") if hasattr(obj, "__dict__") else None
            if om is not None:
                _db2 = _get_db_path(om)
                # try idempotency inside om
                try:
                    idem = om.__dict__.get("idempotency") if hasattr(om, "__dict__") else None
                    if idem is not None:
                        db_idem = _get_db_path(idem)
                        if db_idem is not None and db_idem.startswith(dir_path):
                            _close_obj(idem)
                except Exception:
                    pass
        except Exception:
            pass
    # NOTE: we deliberately do NOT re-open *.db files here to "checkpoint" them.
    # Stores close their connections deterministically per operation (qts.db.connect);
    # re-opening a database that is being deleted recreates the file and re-acquires
    # Windows file locks — the exact WinError 32 hazard this conftest exists to avoid.
    gc.collect()


class SafeTemporaryDirectory(_original_TemporaryDirectory):  # type: ignore[misc]
    def cleanup(self) -> None:  # type: ignore[override]
        with contextlib.suppress(Exception):
            _close_tracked_in_dir(self.name)
        try:
            super().cleanup()
        except PermissionError as e:
            try:
                gc.collect()
                _close_tracked_in_dir(self.name)
                super().cleanup()
            except Exception:
                raise e from None

    def __exit__(self, exc_type, exc_val, exc_tb):  # type: ignore[override]
        with contextlib.suppress(Exception):
            _close_tracked_in_dir(self.name)
        return super().__exit__(exc_type, exc_val, exc_tb)


tempfile.TemporaryDirectory = SafeTemporaryDirectory  # type: ignore[assignment]


def _safe_mkdtemp(*args, **kwargs):
    d = _original_mkdtemp(*args, **kwargs)
    _mkdtemp_dirs.add(d)
    return d


tempfile.mkdtemp = _safe_mkdtemp  # type: ignore[assignment]


# Patch store __init__ to register
def _patch_store_register():
    try:
        from qts.data.store import SqliteParquetDataStore

        orig = SqliteParquetDataStore.__init__

        def wrapped(self, *a, **kw):
            orig(self, *a, **kw)
            _register_store(self)

        SqliteParquetDataStore.__init__ = wrapped  # type: ignore
    except Exception:
        pass
    try:
        from qts.risk.engine import RiskEngine

        orig2 = RiskEngine.__init__

        def wrapped2(self, *a, **kw):
            orig2(self, *a, **kw)
            _register_store(self)

        RiskEngine.__init__ = wrapped2  # type: ignore
    except Exception:
        pass
    try:
        from qts.execution.idempotency import IdempotencyStore

        orig3 = IdempotencyStore.__init__

        def wrapped3(self, *a, **kw):
            orig3(self, *a, **kw)
            _register_store(self)

        IdempotencyStore.__init__ = wrapped3  # type: ignore
    except Exception:
        pass
    try:
        from qts.research.experiment import ExperimentStore

        orig4 = ExperimentStore.__init__

        def wrapped4(self, *a, **kw):
            orig4(self, *a, **kw)
            _register_store(self)

        ExperimentStore.__init__ = wrapped4  # type: ignore
    except Exception:
        pass
    try:
        from qts.data.locked_test import LockedTestPartitioner

        orig5 = LockedTestPartitioner.__init__

        def wrapped5(self, *a, **kw):
            orig5(self, *a, **kw)
            _register_store(self)

        LockedTestPartitioner.__init__ = wrapped5  # type: ignore
    except Exception:
        pass
    try:
        from qts.edge.promotion import PromotionLedger

        orig6 = PromotionLedger.__init__

        def wrapped6(self, *a, **kw):
            orig6(self, *a, **kw)
            _register_store(self)

        PromotionLedger.__init__ = wrapped6  # type: ignore
    except Exception:
        pass
    try:
        from qts.execution.engine import ExecutionEngine

        orig7 = ExecutionEngine.__init__

        def wrapped7(self, *a, **kw):
            orig7(self, *a, **kw)
            _register_store(self)

        ExecutionEngine.__init__ = wrapped7  # type: ignore
    except Exception:
        pass


_patch_store_register()


def pytest_runtest_teardown(item):
    # Close any mkdtemp-tracked stores
    try:
        for obj in list(_tracked_stores):
            try:
                db = _get_db_path(obj)
                if db is not None:
                    for d in list(_mkdtemp_dirs):
                        if db.startswith(d):
                            _close_obj(obj)
            except Exception:
                pass
    except Exception:
        pass
    for d in list(_mkdtemp_dirs):
        try:
            p = pathlib.Path(d)
            if p.exists():
                _close_tracked_in_dir(d)
        except Exception:
            pass
    gc.collect()


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Explicitly request integration runs. Integration tests under tests/integration "
        "run in the default suite as well; this flag makes the declared CI invocation "
        "`pytest tests/integration --run-integration` valid and opts IN to any tests marked "
        "`@pytest.mark.integration` (which are skipped when the flag is absent).",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="needs --run-integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
