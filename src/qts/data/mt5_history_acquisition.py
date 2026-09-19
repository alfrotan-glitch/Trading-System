"""Read-only MT5 historical tick acquisition layer — acquire first, analyze later.

Governing principle
-------------------
**ACQUIRE FIRST. ANALYZE SECOND. Never make acquisition depend on heavy
analysis.**

The earlier probe (``scripts/probe_mt5_history.py``) performed a heavy per-row
audit (JSON serialization, SHA-256 per row, duplicate analysis, spread
statistics) while MT5 was still being queried.  A multi-hour run was
interrupted inside that audit.  This module removes all per-row work from the
acquisition path.  Acquisition is exactly:

    query -> receive -> preserve every row losslessly -> persist -> integrity metadata

All expensive quality analysis lives in :mod:`qts.data.mt5_history_analysis`
and runs afterwards, from the stored local dataset, with no MT5 dependency.

Guarantees
----------
* **Lossless** — rows are preserved through a documented numpy -> Arrow ->
  Parquet mapping of the *exact* structured dtype MT5 returned.  No field is
  selected, dropped, renamed, rescaled, deduplicated, resampled, interpolated,
  or timezone-normalized.  Future MT5-returned fields survive automatically.
  Every committed chunk is verified by reading the written Parquet back and
  comparing each column element-wise (vectorized, not per-row-Python).
* **Interrupt-safe / restart-safe** — one immutable Parquet part per chunk,
  written to a ``.part`` temp file then atomically renamed.  A fsync'd
  ``manifest.json`` is updated after every committed chunk with
  ``status: IN_PROGRESS``.  Only a fully closed dataset ever reaches
  ``status: COMPLETE``.  An interrupted run retries only missing chunks on the
  next invocation (chunk ids are deterministic bounds, so resume is stable).
* **Bounded memory** — the requested window is decomposed into bounded time
  chunks (default 24h).  Chunks that fail or are oversized are recursively
  halved down to a floor; failures at the floor are recorded, never hidden.
* **Fail-closed / read-only** — the only MT5 calls used are
  ``account_info``, ``terminal_info``, ``symbol_info``, ``symbol_select``,
  ``copy_ticks_range`` and ``last_error``.  Acquisition refuses a non-DEMO
  account.  No order API exists in this file (structurally tested).

Nothing here registers the dataset for research, runs the frozen study, or
claims execution evidence.  Raw datasets are private broker data and must stay
out of Git (``.gitignore``: ``data/raw/mt5_ticks/``); only bounded metadata and
digests leave the machine.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# Constants / vocabulary
# ---------------------------------------------------------------------------

ACQUISITION_SCHEMA = "qts.mt5_raw_tick_acquisition.v1"
MANIFEST_FILENAME = "manifest.json"
DEFAULT_DATASET_ROOT = Path("data/raw/mt5_ticks")

# Dataset-level status vocabulary (see docs/mt5_history_acquisition.md).
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_COMPLETE = "COMPLETE"  # every chunk resolved; >= 1 row returned
STATUS_EMPTY_COMPLETE = "EMPTY_COMPLETE"  # every chunk resolved with a successful 0-row response
STATUS_PARTIAL_INTERRUPTED = "PARTIAL_INTERRUPTED"  # operator/timeout stop (external interruption)
STATUS_PARTIAL_QUERY_ERROR = "PARTIAL_QUERY_ERROR"  # >=1 chunk failed at the split floor / failure abort
STATUS_FAILED_SHUTDOWN = "FAILED_SHUTDOWN"  # MT5 connection lost mid-run

FINAL_STATUSES = frozenset(
    {
        STATUS_COMPLETE,
        STATUS_EMPTY_COMPLETE,
        STATUS_PARTIAL_INTERRUPTED,
        STATUS_PARTIAL_QUERY_ERROR,
        STATUS_FAILED_SHUTDOWN,
    }
)

#: The complete set of MT5 functions this layer is allowed to call.  A
#: structural test enforces this allowlist (no order APIs, no history-order
#: APIs — quote history only).
ALLOWED_MT5_CALLS = frozenset(
    {
        "last_error",
        "account_info",
        "terminal_info",
        "symbol_info",
        "symbol_select",
        "copy_ticks_range",
    }
)

READ_ONLY_STATEMENT = (
    "Acquisition is OBSERVE_ONLY / read-only: the only MT5 calls issued are "
    + ", ".join(sorted(ALLOWED_MT5_CALLS))
    + ". No order API is reachable from this layer; DEMO_EXECUTION remains "
    "DISABLED BY POLICY and LIVE remains LOCKED."
)


class AcquisitionRefused(RuntimeError):
    """Fail-closed refusal (non-DEMO account, missing symbol, ...)."""


class Mt5ConnectionLost(RuntimeError):
    """terminal_info() failed mid-run: the terminal/broker connection is gone."""


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dump_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically (same-directory tmp + os.replace) and fsync."""
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(rendered)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    """Streaming whole-file SHA-256 (the integrity anchor; bytes, not rows)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_digest(parts: Mapping[str, str]) -> str:
    """Deterministic dataset digest: SHA-256 over ``"<part> <sha256>\n"`` lines.

    The definition is deliberately simple and documented so anyone holding the
    raw files can recompute it independently of this code.
    """
    digest = hashlib.sha256()
    digest.update(b"qts.mt5_raw_tick_dataset.v1\n")
    for name in sorted(parts):
        digest.update(f"{name} {parts[name]}\n".encode())
    return digest.hexdigest()


def describe_structured_dtype(rows: Any) -> dict[str, str]:
    """Exact field -> numpy dtype map of the returned structured array."""
    dtype = getattr(rows, "dtype", None)
    names = getattr(dtype, "names", None)
    if not names or dtype is None:
        raise TypeError(f"MT5 rows are not a numpy structured array (dtype={dtype!r})")
    return {str(name): str(dtype.fields[name][0]) for name in names}


def _chunk_id(start_utc: datetime, end_utc: datetime) -> str:
    return f"{start_utc.isoformat()}..{end_utc.isoformat()}"


# ---------------------------------------------------------------------------
# Chunk planning
# ---------------------------------------------------------------------------


def plan_base_chunks(start_utc: datetime, end_utc: datetime, chunk: timedelta) -> list[dict[str, Any]]:
    """Decompose [start_utc, end_utc) oldest-first into bounded half-open chunks.

    Chunk id == the raw bounds string; deterministic across restarts, which is
    what makes resume stable.
    """
    if end_utc <= start_utc:
        raise ValueError(f"empty window: {start_utc!r}..{end_utc!r}")
    if chunk <= timedelta(0):
        raise ValueError("chunk size must be positive")
    chunks: list[dict[str, Any]] = []
    cursor = start_utc
    index = 0
    while cursor < end_utc:
        stop = min(cursor + chunk, end_utc)
        chunks.append(
            {
                "index": index,
                "id": _chunk_id(cursor, stop),
                "start_utc": cursor.isoformat(),
                "end_utc": stop.isoformat(),
                "span_hours": round((stop - cursor).total_seconds() / 3600.0, 6),
            }
        )
        cursor = stop
        index += 1
    return chunks


# ---------------------------------------------------------------------------
# Raw dataset writer
# ---------------------------------------------------------------------------


class RawTickDatasetWriter:
    """Append bounded chunk parts to one immutable raw tick dataset.

    Layout::

        <dataset_dir>/
            manifest.json          # fsync'd after every committed chunk
            parts/part-000000.parquet
            parts/part-000001.parquet
            ...

    A chunk is committed only when its parquet part exists under its final
    name AND the fsync'd manifest ledger records it.  A crash between the two
    leaves a ``*.parquet.part-<pid>`` temp file that is discarded on open.
    """

    def __init__(
        self,
        dataset_dir: Path,
        manifest: dict[str, Any],
        *,
        verify_written_chunks: bool = True,
    ) -> None:
        self.dataset_dir = dataset_dir
        self.manifest = manifest
        self.verify = verify_written_chunks

    # -- construction -------------------------------------------------------

    @classmethod
    def create(
        cls,
        dataset_dir: Path,
        *,
        symbol_requested: str,
        symbol_actual: str,
        environment: dict[str, Any],
        request: dict[str, Any],
        software: dict[str, Any],
    ) -> RawTickDatasetWriter:
        dataset_dir = Path(dataset_dir)
        if dataset_dir.exists() and any(dataset_dir.iterdir()):
            raise FileExistsError(
                f"dataset dir {dataset_dir} already exists; open it for resume or pass force=True to the caller"
            )
        parts_dir = dataset_dir / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {
            "schema": ACQUISITION_SCHEMA,
            "status": STATUS_IN_PROGRESS,
            "created_at_utc": _utc_now().isoformat(),
            "updated_at_utc": _utc_now().isoformat(),
            "closed_at_utc": None,
            "read_only": True,
            "read_only_statement": READ_ONLY_STATEMENT,
            "orders_submitted": 0,
            "order_send_called": False,
            "symbol": {"requested": symbol_requested, "actual": symbol_actual},
            "environment": environment,
            "observation_mode": "OBSERVE_ONLY",
            "request": request,
            "software": software,
            "returned_fields": None,
            "returned_dtype_map": None,
            "schema_note": (
                "Every field MT5 returned is preserved with its exact numpy dtype; no field is selected, "
                "dropped, renamed, or transformed. Parquet columns map 1:1 (numpy int64->arrow int64, "
                "uint32->arrow uint32, float64->arrow double, ...)."
            ),
            "timestamp_basis": (
                "RAW: 'time' and 'time_msc' are stored exactly as MT5 returned them (integer epoch seconds "
                "and milliseconds by MT5 convention). No UTC normalization, offset inference, or timezone "
                "conversion was applied to any value."
            ),
            "timestamp_interpretation_confirmed": False,
            "acquisition_started_at_utc": _utc_now().isoformat(),
            "acquisition_ended_at_utc": None,
            "chunks_committed": 0,
            "chunks_failed": 0,
            "chunks_resolved": 0,
            "chunks_total_resolved_vs_planned_note": (
                "Base plan is static; failed/oversized chunks are recursively halved, so the resolved chunk "
                "count can exceed the base plan size. 'complete' means every resolved chunk is committed."
            ),
            "row_count": 0,
            "raw_time_min": None,
            "raw_time_max": None,
            "raw_time_msc_min": None,
            "raw_time_msc_max": None,
            "parts": [],
            "failed_chunks": [],
            "dataset_files_size_bytes": 0,
            "dataset_sha256": None,
            "dataset_digest_definition": (
                "SHA-256 over the header line 'qts.mt5_raw_tick_dataset.v1\\n' followed by one "
                "'<part-name> <part-sha256>\\n' line per part, sorted by part name."
            ),
            "interruptions": 0,
            "resumed_from_previous_run": False,
            "mt5_error_last": None,
        }
        writer = cls(dataset_dir, manifest)
        writer._persist()
        return writer

    @classmethod
    def open_existing(cls, dataset_dir: Path) -> RawTickDatasetWriter:
        dataset_dir = Path(dataset_dir)
        manifest_path = dataset_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise FileNotFoundError(f"no acquisition manifest at {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != ACQUISITION_SCHEMA:
            raise ValueError(f"unsupported acquisition manifest schema in {manifest_path}: {manifest.get('schema')!r}")
        if manifest.get("status") in {STATUS_COMPLETE, STATUS_EMPTY_COMPLETE}:
            raise FileExistsError(f"dataset at {dataset_dir} is already final ({manifest.get('status')})")
        # Discard orphaned temp parts from a crashed run — a part is evidence
        # only once the ledger records it.
        parts_dir = dataset_dir / "parts"
        if parts_dir.exists():
            for orphan in parts_dir.glob("*.parquet.part-*"):
                orphan.unlink(missing_ok=True)
        manifest["resumed_from_previous_run"] = True
        manifest["interruptions"] = int(manifest.get("interruptions") or 0) + 1
        manifest["status"] = STATUS_IN_PROGRESS
        writer = cls(dataset_dir, manifest)
        writer._persist()
        return writer

    # -- properties ---------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.dataset_dir / MANIFEST_FILENAME

    @property
    def _parts_dir(self) -> Path:
        return self.dataset_dir / "parts"

    def completed_chunk_ids(self) -> set[str]:
        """Chunk ids whose committed parts are recorded in the ledger."""
        return {part["chunk"]["id"] for part in self.manifest["parts"]}

    def failed_chunk_ids(self) -> set[str]:
        return {chunk["id"] for chunk in self.manifest["failed_chunks"]}

    # -- appending ----------------------------------------------------------

    def append_chunk(
        self,
        chunk: Mapping[str, Any],
        rows: Any,
        *,
        mt5_error: str | None = None,
    ) -> dict[str, Any]:
        """Persist one chunk's rows exactly as returned by MT5.

        Zero per-row Python work: structured array -> Arrow table (column
        views) -> Parquet part -> vectorized read-back equality check.
        """
        if self.manifest["status"] != STATUS_IN_PROGRESS:
            raise RuntimeError(f"cannot append to dataset in status {self.manifest['status']}")
        if not isinstance(rows, np.ndarray) or rows.dtype.names is None:
            raise TypeError(
                "rows must be a numpy structured array exactly as returned by MT5 "
                f"copy_ticks_range; got {type(rows).__name__}. Refusing to synthesize fields."
            )
        if chunk["id"] in self.completed_chunk_ids():
            raise ValueError(f"chunk {chunk['id']} is already committed")
        dtype_map = describe_structured_dtype(rows)
        existing_map = self.manifest.get("returned_dtype_map")
        if existing_map is None:
            self.manifest["returned_fields"] = list(rows.dtype.names)
            self.manifest["returned_dtype_map"] = dtype_map
        elif existing_map != dtype_map:
            raise ValueError(
                f"chunk {chunk['id']} schema drift: {dtype_map} != committed {existing_map}; "
                "refusing to mix heterogeneous responses into one raw dataset"
            )

        seq = len(self.manifest["parts"])
        part_name = f"part-{seq:06d}.parquet"
        final_path = self._parts_dir / part_name
        tmp_path = self._parts_dir / f"{part_name}.part-{os.getpid()}"

        # numpy structured array -> Arrow: one zero-copy-ish column per field.
        # No values are transformed; only the in-memory container changes.
        columns = {name: rows[name] for name in rows.dtype.names}
        table = pa.table(columns)
        pq.write_table(table, tmp_path, compression="zstd")
        part_sha = sha256_file(tmp_path)
        part_size = tmp_path.stat().st_size

        lossless_verified: bool | None = None
        if self.verify:
            back = pq.read_table(tmp_path).to_pandas(zero_copy_only=False)
            lossless_verified = all(
                np.array_equal(
                    np.ascontiguousarray(rows[name]),
                    back[name].to_numpy(),
                    equal_nan=True,
                )
                for name in rows.dtype.names
            )
            if not lossless_verified:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"chunk {chunk['id']}: written Parquet part failed the lossless round-trip check; "
                    "chunk NOT committed (fail-closed)"
                )

        row_count = int(rows.shape[0])
        stats: dict[str, Any] = {}
        if row_count:
            # O(1) vectorized bounds for provenance (no per-row analysis).
            if "time" in rows.dtype.names:
                stats["raw_time_min"] = int(np.min(rows["time"]))
                stats["raw_time_max"] = int(np.max(rows["time"]))
            if "time_msc" in rows.dtype.names:
                stats["raw_time_msc_min"] = int(np.min(rows["time_msc"]))
                stats["raw_time_msc_max"] = int(np.max(rows["time_msc"]))

        os.replace(tmp_path, final_path)  # atomic same-dir commit of the part
        with final_path.open("rb") as fh:  # fsync data blocks before ledger
            os.fsync(fh.fileno())

        part_record = {
            "part": part_name,
            "path": str(final_path),
            "sha256": part_sha,
            "size_bytes": part_size,
            "rows": row_count,
            "chunk": {
                "id": chunk["id"],
                "start_utc": chunk["start_utc"],
                "end_utc": chunk["end_utc"],
                "span_hours": chunk.get("span_hours"),
            },
            "lossless_roundtrip_verified": lossless_verified,
            "mt5_error_if_any": mt5_error,
            "committed_at_utc": _utc_now().isoformat(),
        }
        m = self.manifest
        m["parts"].append(part_record)
        m["chunks_committed"] = int(m["chunks_committed"]) + 1
        m["chunks_resolved"] = int(m["chunks_resolved"]) + 1
        m["row_count"] = int(m["row_count"]) + row_count
        m["dataset_files_size_bytes"] = int(m["dataset_files_size_bytes"]) + part_size
        if mt5_error:
            m["mt5_error_last"] = mt5_error
        for key in ("raw_time_min", "raw_time_max", "raw_time_msc_min", "raw_time_msc_max"):
            if key not in stats:
                continue
            prior = m.get(key)
            if prior is None:
                m[key] = stats[key]
            elif key.endswith("_min"):
                m[key] = min(prior, stats[key])
            else:
                m[key] = max(prior, stats[key])
        m["updated_at_utc"] = _utc_now().isoformat()
        self._persist()
        return part_record

    def record_failed_chunk(self, chunk: Mapping[str, Any], *, error: str) -> None:
        """Record a chunk that failed at the split floor (kept as evidence)."""
        m = self.manifest
        m["failed_chunks"].append(
            {
                "id": chunk["id"],
                "start_utc": chunk["start_utc"],
                "end_utc": chunk["end_utc"],
                "span_hours": chunk.get("span_hours"),
                "error": error,
                "failed_at_utc": _utc_now().isoformat(),
            }
        )
        m["chunks_failed"] = int(m["chunks_failed"]) + 1
        m["chunks_resolved"] = int(m["chunks_resolved"]) + 1
        m["mt5_error_last"] = error
        m["updated_at_utc"] = _utc_now().isoformat()
        self._persist()

    # -- closing ------------------------------------------------------------

    def finalize(self, status: str) -> dict[str, Any]:
        if status not in FINAL_STATUSES:
            raise ValueError(f"invalid final status {status!r}")
        m = self.manifest
        m["status"] = status
        m["acquisition_ended_at_utc"] = _utc_now().isoformat()
        m["closed_at_utc"] = m["acquisition_ended_at_utc"]
        m["updated_at_utc"] = m["acquisition_ended_at_utc"]
        m["dataset_sha256"] = dataset_digest({p["part"]: p["sha256"] for p in m["parts"]})
        m["dataset_files_size_bytes"] = sum(int(p["size_bytes"]) for p in m["parts"])
        self._persist()
        return self.manifest

    def _persist(self) -> None:
        _dump_json_atomic(self.manifest_path, self.manifest)


# ---------------------------------------------------------------------------
# Acquisition driver
# ---------------------------------------------------------------------------


def _last_error_repr(mt5: Any) -> str:
    with contextlib.suppress(Exception):
        return repr(mt5.last_error())
    return "last_error() unavailable"


def require_read_only_demo(mt5: Any) -> dict[str, Any]:
    """Fail closed unless the connected account is verifiably DEMO."""
    account = mt5.account_info()
    if account is None:
        raise AcquisitionRefused(f"account_info() returned None ({_last_error_repr(mt5)}) — refusing acquisition")
    demo_constant = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    trade_mode = getattr(account, "trade_mode", None)
    if demo_constant is None:
        raise AcquisitionRefused("ACCOUNT_TRADE_MODE_DEMO constant unavailable — refusing acquisition")
    if trade_mode != demo_constant:
        raise AcquisitionRefused(
            f"account trade_mode={trade_mode!r} != DEMO ({demo_constant!r}); acquisition is DEMO-only — REFUSED"
        )
    return {
        "environment": "DEMO",
        "account_trade_mode_raw": trade_mode,
        "is_demo": True,
        "server": getattr(account, "server", None),
        "login_recorded": False,
        "statement": "account trade_mode matches ACCOUNT_TRADE_MODE_DEMO; DEMO-only acquisition permitted",
    }


def resolve_symbol(mt5: Any, requested: str) -> str:
    """Resolve the exact broker symbol; fail closed when it does not exist."""
    info = mt5.symbol_info(requested)
    if info is None:
        raise AcquisitionRefused(
            f"symbol_info({requested!r}) returned None ({_last_error_repr(mt5)}). "
            "Pass the exact broker symbol (e.g. --symbol XAUUSD@); run scripts/probe_mt5_history.py "
            "to list candidates. REFUSED."
        )
    actual = str(getattr(info, "name", requested))
    with contextlib.suppress(Exception):
        mt5.symbol_select(actual, True)
    return actual


def terminal_identity(mt5: Any) -> dict[str, Any]:
    terminal = mt5.terminal_info()
    if terminal is None:
        raise Mt5ConnectionLost(f"terminal_info() returned None ({_last_error_repr(mt5)})")
    return {
        "build": getattr(terminal, "build", None),
        "name": getattr(terminal, "name", None),
        "company": getattr(terminal, "company", None),
        "path": getattr(terminal, "path", None),
    }


def software_identity(mt5: Any | None = None) -> dict[str, Any]:
    """Best-effort software/probe version identity for provenance."""
    import platform
    import subprocess

    from qts import __version__ as qts_version

    commit = None
    dirty = None
    with contextlib.suppress(Exception):
        root = Path(__file__).resolve().parents[3]
        env = {**os.environ, "LC_ALL": "C"}
        result = subprocess.run(  # nosec B404 B603 B607 — fixed argv, best-effort provenance
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
        status = subprocess.run(  # nosec B404 B603 B607 — fixed argv, best-effort provenance
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        if status.returncode == 0:
            dirty = bool(status.stdout.strip())
    identity: dict[str, Any] = {
        "probe": "qts.data.mt5_history_acquisition",
        "qts_version": qts_version,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pyarrow_version": pa.__version__,
        "repository_commit": commit,
        "git_working_tree_dirty_at_run": dirty,
    }
    if mt5 is not None:
        identity["mt5_package_version"] = getattr(mt5, "__version__", None)
    return identity


class _TimeBudget:
    def __init__(self, max_seconds: float | None) -> None:
        self.deadline = (time.monotonic() + max_seconds) if max_seconds else None

    @property
    def exhausted(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline


def acquire_window(
    mt5: Any,
    *,
    symbol_requested: str,
    symbol_actual: str,
    environment: dict[str, Any],
    start_utc: datetime,
    end_utc: datetime,
    dataset_dir: Path,
    flags: Any,
    chunk: timedelta = timedelta(hours=24),
    min_chunk: timedelta = timedelta(minutes=60),
    max_chunk_rows: int = 5_000_000,
    max_failed_chunks: int = 64,
    max_runtime_seconds: float | None = None,
    budget: _TimeBudget | None = None,
    sleep_between_chunks: Callable[[], None] | None = None,
    verify_written_chunks: bool = True,
) -> dict[str, Any]:
    """Acquire one historical window chunk-by-chunk into an immutable dataset.

    Returns the final manifest.  Never raises on MT5 data failures — every
    outcome is recorded in the manifest status so an interruption can never be
    mistaken for a complete acquisition.  Raises only on local misuse.
    """
    dataset_dir = Path(dataset_dir)
    if (dataset_dir / MANIFEST_FILENAME).exists():
        writer = RawTickDatasetWriter.open_existing(dataset_dir)
        if writer.verify != verify_written_chunks:
            writer.verify = verify_written_chunks
    else:
        request = {
            "start_utc": start_utc.isoformat(),
            "end_utc": end_utc.isoformat(),
            "window_days": round((end_utc - start_utc).total_seconds() / 86400.0, 6),
            "flags_repr": repr(flags),
            "flags_semantics": "pass-through of the caller's copy_ticks_range flags (COPY_TICKS_ALL recommended)",
            "chunk_hours_requested": round(chunk.total_seconds() / 3600.0, 6),
            "min_chunk_minutes": round(min_chunk.total_seconds() / 60.0, 6),
            "max_chunk_rows": max_chunk_rows,
            "chunk_bounds_semantics": (
                "Requested half-open [start, end) day-aligned chunks, oldest first; the broker's boundary "
                "inclusivity is UNVERIFIED, so a tick landing exactly on a boundary may legitimately appear in "
                "two parts. Boundary repeats are retained by design (no deduplication) and measured by the "
                "deferred analysis layer."
            ),
        }
        writer = RawTickDatasetWriter.create(
            dataset_dir,
            symbol_requested=symbol_requested,
            symbol_actual=symbol_actual,
            environment=environment,
            request=request,
            software=software_identity(mt5),
        )

    budget = budget or _TimeBudget(max_runtime_seconds)
    base_plan = plan_base_chunks(start_utc, end_utc, chunk)
    done = writer.completed_chunk_ids()
    failed = writer.failed_chunk_ids()
    # LIFO stack; the earliest unresolved chunk sits on top.  Adaptive splits
    # push (right, left) so the left half is processed depth-first before its
    # right sibling and before all later base chunks — this keeps the
    # discovered data boundary contiguous, oldest first.
    pending: list[dict[str, Any]] = [
        c for c in reversed(base_plan) if c["id"] not in done and c["id"] not in failed
    ]

    copy_ticks_range = getattr(mt5, "copy_ticks_range", None)
    if not callable(copy_ticks_range):
        raise AcquisitionRefused("copy_ticks_range is not exposed by the MT5 module — refusing acquisition")

    interrupted = False  # external stop: operator keyboard interrupt or time budget
    interruption_reason: str | None = None
    failure_abort = False  # internal stop: too many chunk failures (a query-error outcome)
    connection_lost = False
    n_committed_this_run = 0

    while pending:
        if budget.exhausted:
            interrupted = True
            interruption_reason = "time_budget_exhausted"
            break
        item = pending.pop()
        c_start = datetime.fromisoformat(item["start_utc"])
        c_end = datetime.fromisoformat(item["end_utc"])
        if sleep_between_chunks is not None:
            sleep_between_chunks()
        error: str | None = None
        try:
            rows = copy_ticks_range(symbol_actual, c_start, c_end, flags)
        except KeyboardInterrupt:
            interrupted = True
            interruption_reason = "keyboard_interrupt"
            break
        except Exception as exc:  # noqa: BLE001 — every remote failure becomes ledger evidence
            rows = None
            error = f"exception:{type(exc).__name__}: {exc}"
        else:
            if rows is None:
                error = _last_error_repr(mt5)

        row_count: int | None
        if rows is None:
            row_count = None
        elif not isinstance(rows, np.ndarray) or rows.dtype.names is None:
            # Refuse to coerce a malformed response into "rows": MT5's
            # structured array is the contract for lossless preservation.
            error = f"malformed_response:{type(rows).__name__}"
            row_count = None
        else:
            row_count = int(rows.shape[0])

        if (row_count is None or row_count > max_chunk_rows) and (c_end - c_start) > min_chunk:
            # Adaptive split: halve and retry children first (depth-first).
            mid = c_start + (c_end - c_start) / 2
            left = {
                "index": item["index"],
                "id": _chunk_id(c_start, mid),
                "start_utc": c_start.isoformat(),
                "end_utc": mid.isoformat(),
                "span_hours": round((mid - c_start).total_seconds() / 3600.0, 6),
            }
            right = {
                "index": item["index"],
                "id": _chunk_id(mid, c_end),
                "start_utc": mid.isoformat(),
                "end_utc": c_end.isoformat(),
                "span_hours": round((c_end - mid).total_seconds() / 3600.0, 6),
            }
            if right["id"] not in done and right["id"] not in failed:
                pending.append(right)
            if left["id"] not in done and left["id"] not in failed:
                pending.append(left)
            continue

        if row_count is None:
            writer.record_failed_chunk(item, error=error or "unknown_query_error")
            done = writer.completed_chunk_ids()
            failed = writer.failed_chunk_ids()
            if len(failed) > max_failed_chunks:
                failure_abort = True
                interruption_reason = f"max_failed_chunks_exceeded({max_failed_chunks})"
                break
            continue
        if row_count > max_chunk_rows:
            writer.record_failed_chunk(
                item,
                error=f"oversized_chunk:{row_count}_rows_exceeds_max_chunk_rows_{max_chunk_rows}_at_split_floor",
            )
            failed = writer.failed_chunk_ids()
            done = writer.completed_chunk_ids()
            if len(failed) > max_failed_chunks:
                failure_abort = True
                interruption_reason = f"max_failed_chunks_exceeded({max_failed_chunks})"
                break
            continue

        part = writer.append_chunk(item, rows, mt5_error=error if row_count == 0 else None)
        del rows
        n_committed_this_run += 1
        done.add(part["chunk"]["id"])
        if n_committed_this_run % 32 == 0:
            # Liveness probe: a dead terminal mid-run must not be reported as data.
            try:
                if mt5.terminal_info() is None:
                    connection_lost = True
                    break
            except Exception:  # noqa: BLE001
                connection_lost = True
                break

    if interruption_reason:
        writer.manifest.setdefault("notes", []).append(
            f"run stopped early: {interruption_reason}; dataset is PARTIAL and resumable"
        )

    if connection_lost:
        status = STATUS_FAILED_SHUTDOWN
    elif failure_abort:
        status = STATUS_PARTIAL_QUERY_ERROR
    elif interrupted:
        status = STATUS_PARTIAL_INTERRUPTED
    elif writer.manifest["chunks_failed"]:
        status = STATUS_PARTIAL_QUERY_ERROR
    elif writer.manifest["row_count"] == 0:
        status = STATUS_EMPTY_COMPLETE
    else:
        status = STATUS_COMPLETE

    return writer.finalize(status)
