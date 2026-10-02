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
import hashlib
import os
import pathlib
import subprocess
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
                # This store's backing file lives inside the directory being
                # torn down right now — nothing later in the session can
                # still need to close it again. Without this, `_tracked_stores`
                # only ever grows (every store construction in the whole
                # session registers one, closing never discards one), so by
                # the back half of a long run this loop — and the
                # `_mkdtemp_dirs` loop below it, run on EVERY test's teardown
                # — iterates thousands of already-closed, already-irrelevant
                # objects per test. Measured: by test #1400 of 1479,
                # `_tracked_stores` held 1461 entries and the per-test
                # teardown hook alone (not fixture teardown, just this hook)
                # had grown from 0.07s to 0.89s, with 147s of cumulative
                # `gc.collect()` time across the run.
                _tracked_stores.discard(obj)
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
    # Close any mkdtemp-tracked stores whose owning directory is already gone
    # (its `with TemporaryDirectory():` block exited, or `mkdtemp()` was
    # cleaned up by hand, during the test's own `call` phase) — the second
    # loop below only revisits directories that still exist, so a store
    # outliving its now-deleted directory by one teardown cycle still needs
    # a close pass here.
    closed_anything = False
    try:
        for obj in list(_tracked_stores):
            try:
                db = _get_db_path(obj)
                if db is None:
                    continue
                for d in list(_mkdtemp_dirs):
                    if db.startswith(d):
                        _close_obj(obj)
                        _tracked_stores.discard(obj)
                        closed_anything = True
                        break
            except Exception:
                pass
    except Exception:
        pass
    # Close stores whose directory still exists, then drop any `_mkdtemp_dirs`
    # entry that is gone from disk (tempfile names are unique per call, so a
    # removed path never needs rechecking). Without this prune, `_mkdtemp_dirs`
    # and `_tracked_stores` only ever grow for the rest of the session — every
    # `tempfile.mkdtemp()` / store construction adds an entry, nothing ever
    # removed one — so this hook's cost became O(every tempdir/store EVER
    # created) on every remaining test's teardown. Measured on the full
    # suite before this fix: by test #1400 of 1479, `_mkdtemp_dirs` held 92
    # entries and `_tracked_stores` held 1461, this hook alone (not fixture
    # teardown) had grown from 0.07s to 0.89s per call, and the trailing
    # unconditional `gc.collect()` below had cost 147s cumulatively — on a
    # suite whose total measured teardown time was 810 of 945 seconds.
    for d in list(_mkdtemp_dirs):
        try:
            p = pathlib.Path(d)
            if p.exists():
                _close_tracked_in_dir(d)
                closed_anything = True
            else:
                _mkdtemp_dirs.discard(d)
        except Exception:
            pass
    # `gc.collect()` is the actual Windows-safety step (a store's `.close()`
    # already releases its OS file handle deterministically per `qts.db.connect`;
    # this is the belt-and-suspenders pass for anything still referencing a
    # connection object via a Python-level cycle) — only needed when this
    # teardown actually closed something, which `_close_tracked_in_dir` above
    # already does for the live-directory case. Running it unconditionally,
    # every test, regardless of whether anything was closed, was the
    # dominant cost measured above.
    if closed_anything:
        gc.collect()


DEMO_ENV_VARS = (
    "QTS_MODE",
    "QTS_DEMO_AUTHORIZATION",
    "QTS_DEMO_REGISTRY",
    "QTS_DEMO_IDENTITY_PIN",
    "QTS_SETUP_FILE",
    "QTS_STATE_ROOT",
    "QTS_DB_PATH",
)


@pytest.fixture(autouse=True)
def restore_demo_environment():
    """Keep DEMO env vars test-local.

    Several DEMO helpers set ``QTS_DEMO_REGISTRY`` (and friends) through
    ``os.environ``, which is never undone. The leak made results depend on test
    ORDER: a test asserting an empty registry could silently see another
    module's registered policy (and vice versa), which is how a "shipped
    registry" assertion came to inspect a temporary fixture entry.
    """
    saved = {name: os.environ.get(name) for name in DEMO_ENV_VARS}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Opt in to tests explicitly marked integration. Tests under tests/integration "
        "run in the default suite. This flag keeps `pytest tests/integration --run-integration` "
        "valid and also runs any test marked `@pytest.mark.integration`.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip only an explicit ``@pytest.mark.integration``.

    Pytest 9 puts every parent directory name into ``item.keywords``. Matching
    the word ``integration`` therefore skipped the entire ``tests/integration``
    tree in the default suite (119 tests) even though those files are not
    marked. That was an accidental coverage loss, not an intentional skip.
    """
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="needs --run-integration")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)


# ---------------------------------------------------------------------------
# Repository-evidence immutability guard
# ---------------------------------------------------------------------------
# ``data/evidence/*.json`` is the audit trail (README: "evidence is audit
# trail"; the repository's standing invariants forbid deleting, hiding or
# rewriting failed/blocked/inconvenient evidence). Several of those exports are
# documented as "derived, regenerable" — but their canonical SQLite stores are
# gitignored, so on a fresh clone the committed export is the ONLY surviving
# record. A test that re-derives one from an empty local store therefore
# destroys real evidence while still passing.
#
# That happened: ``test_forward_manifest_has_required_fields`` overwrote
# ``data/evidence/forward_observation_manifest.json`` (real MT5 DEMO session
# FS-f374b6, 13222 ticks, ENDED_ON_ERRORS) with an all-zero manifest.
#
# Tests must be side-effect-free on the repository working tree. This guard
# hashes every git-tracked file at session start and fails the session if the
# run changed or deleted any of them. It only reports changes made DURING the
# session, so a pre-existing dirty working tree is not blamed on the tests.

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _guard_tracked_files() -> list[pathlib.Path]:
    """Git-tracked files to protect, or [] when this is not a usable checkout."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    names = proc.stdout.decode("utf-8", "replace").split("\0")
    out: list[pathlib.Path] = []
    for name in names:
        if not name:
            continue
        p = _REPO_ROOT / name
        # only files that exist right now can be part of the baseline
        if p.is_file():
            out.append(p)
    return out


def _guard_digest(path: pathlib.Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@pytest.fixture(scope="session", autouse=True)
def repository_tracked_files_must_not_be_modified_by_tests():
    """Fail the session if the test run mutated or deleted tracked files."""
    baseline: dict[pathlib.Path, str] = {}
    for path in _guard_tracked_files():
        digest = _guard_digest(path)
        if digest is not None:
            baseline[path] = digest
    yield
    if not baseline:
        return  # not a usable git checkout — nothing to compare against

    mutated: list[str] = []
    deleted: list[str] = []
    for path, want in baseline.items():
        got = _guard_digest(path)
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if got is None:
            deleted.append(rel)
        elif got != want:
            mutated.append(rel)
    if mutated or deleted:
        lines = [
            "the test suite modified the repository working tree; tests must be",
            "side-effect-free on tracked files (committed data/evidence/*.json is",
            "the audit trail and is NOT regenerable once its gitignored canonical",
            "store is absent). Point derived exports at tmp_path instead.",
        ]
        if mutated:
            lines.append("modified: " + ", ".join(sorted(mutated)))
        if deleted:
            lines.append("deleted: " + ", ".join(sorted(deleted)))
        pytest.fail("\n".join(lines), pytrace=False)


# ---------------------------------------------------------------------------
# Shared DEMO operator environment
# ---------------------------------------------------------------------------
# ``demo_env`` builds one hermetic operator environment (authorization,
# registry, setup, DB, audit log, kill-switch self test — all inside
# ``tmp_path``) so no test can touch the operator's real state. Only the
# ``tests/integration`` suite requests it; fixtures are opt-in by name, so
# exposing it tree-wide costs nothing.
#
# It is re-exported HERE rather than from ``tests/integration/conftest.py``
# deliberately. pytest 9 matches a fixture to a test by the IDENTITY of the
# collector node that owns it (``FixtureDef.node in node.iter_parents()``),
# and it re-creates the ``Dir`` node for a subdirectory when that directory is
# revisited after a sibling argument. So with an interleaved invocation like
#
#     pytest tests/integration/a.py tests/test_b.py tests/integration/c.py
#
# the third argument got a SECOND ``Dir('tests/integration')`` object, the
# owning node no longer matched, and every ``demo_env`` test in it failed with
# "fixture 'demo_env' not found" — 13 spurious errors with nothing wrong.
# ``Dir('tests')`` is the shared common ancestor in every ordering, so owning
# the fixture at this level makes the suite immune to the argument order.
from demo_harness import demo_env  # noqa: E402, F401  (pytest fixture, re-exported)
