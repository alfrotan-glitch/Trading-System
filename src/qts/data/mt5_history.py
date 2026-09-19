"""Lossless, read-only MT5 historical tick acquisition and deferred analysis.

The acquisition path has one job: query MT5 and persist every returned field and
row.  It deliberately does not calculate row hashes, duplicates, spreads, or
quality statistics.  ``analyze_mt5_dataset`` is a separate local-only pass over
the completed Parquet dataset.

A Parquet *directory* is used instead of a single writer stream.  Each bounded
MT5 response becomes one immutable Parquet file.  This keeps interruption
restart-safe, avoids a giant in-memory list, and lets a future MT5 schema field
be preserved in its own chunk instead of being silently dropped.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import random
import shutil
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

SCHEMA_VERSION = "qts.mt5_raw_tick_acquisition.v1"
ANALYSIS_SCHEMA_VERSION = "qts.mt5_raw_tick_analysis.v1"
DEFAULT_CHUNK_HOURS = 24
_REQUIRED_FIELDS = ("time", "time_msc")
_QUOTE_FIELDS = ("bid", "ask", "last", "volume", "flags", "volume_real")


class AcquisitionError(RuntimeError):
    """The raw acquisition could not be completed."""


class SchemaDriftError(AcquisitionError):
    """MT5 returned a schema change that was not silently discarded."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def _json_scalar(value: Any) -> Any:
    """Convert provider scalar wrappers without changing stored Arrow values."""
    item = getattr(value, "item", None)
    if callable(item):
        with contextlib.suppress(Exception):
            value = item()
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def returned_field_names(rows: Any) -> list[str]:
    """Return the exact field inventory exposed by this MT5 response.

    Real MetaTrader5 responses are numpy structured arrays, so this reads the
    dtype without iterating over rows.  Mapping/list fallbacks exist for tests
    and adapter implementations and retain the union of mapping keys.
    """
    names = getattr(getattr(rows, "dtype", None), "names", None)
    if names:
        return [str(name) for name in names]
    try:
        first = rows[0]
    except (IndexError, KeyError, TypeError):
        return []
    if isinstance(first, Mapping):
        fields: list[str] = []
        for row in rows:
            for key in row:
                key = str(key)
                if key not in fields:
                    fields.append(key)
        return fields
    tuple_fields: Any = getattr(first, "_fields", None)
    if tuple_fields:
        return [str(field) for field in tuple_fields]
    # MT5 is the authoritative supported provider.  An object response with
    # no discoverable schema is unsafe to acquire rather than partially save.
    object_fields = getattr(first, "__dict__", {})
    if object_fields:
        return [str(field) for field in object_fields]
    raise AcquisitionError("MT5 response has no discoverable structured schema")


def _row_value(row: Any, field: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(field)
    try:
        return row[field]
    except (IndexError, KeyError, TypeError):
        return getattr(row, field, None)


def _table_from_rows(rows: Any, fields: list[str]) -> pa.Table:
    """Convert one response to Arrow while retaining provider columns verbatim."""
    names = getattr(getattr(rows, "dtype", None), "names", None)
    arrays: list[pa.Array] = []
    for field in fields:
        if names and field in names:
            # Arrow reads the numpy field dtype directly; no Python row/list
            # representation is created on the real MT5 path.
            arrays.append(pa.array(rows[field]))
        else:
            arrays.append(pa.array([_row_value(row, field) for row in rows]))
    return pa.Table.from_arrays(arrays, names=fields)


def _timestamp_summary(row: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {field: _json_scalar(_row_value(row, field)) for field in _REQUIRED_FIELDS if field in fields}


def _schema_inventory(schema: pa.Schema) -> list[dict[str, Any]]:
    return [{"name": field.name, "arrow_type": str(field.type), "nullable": field.nullable} for field in schema]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _dataset_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.parquet") if p.is_file())


def hash_dataset(path: Path) -> tuple[str, int]:
    """Hash the persisted Parquet files, not rows or derived values."""
    digest = hashlib.sha256()
    total_size = 0
    for file_path in _dataset_files(path):
        relative = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with file_path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                total_size += len(block)
    return digest.hexdigest(), total_size


def iter_chunks(start_utc: datetime, end_utc: datetime, chunk_hours: int) -> Iterable[tuple[datetime, datetime]]:
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("historical bounds must be timezone-aware UTC datetimes")
    start_utc = start_utc.astimezone(UTC)
    end_utc = end_utc.astimezone(UTC)
    if start_utc >= end_utc:
        raise ValueError("historical start must be before end")
    if chunk_hours <= 0:
        raise ValueError("chunk_hours must be positive")
    cursor = start_utc
    step = timedelta(hours=chunk_hours)
    while cursor < end_utc:
        chunk_end = min(cursor + step, end_utc)
        yield cursor, chunk_end
        cursor = chunk_end


def _base_metadata(
    *,
    acquisition_id: str,
    output_path: Path,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    chunk_hours: int,
    context: Mapping[str, Any] | None,
    started_at: datetime,
) -> dict[str, Any]:
    source = dict(context or {})
    source.setdefault("requested_symbol", symbol)
    source.setdefault("actual_symbol", None)
    source.setdefault("environment", "DEMO (operator must verify)")
    source.setdefault("observation_mode", "OBSERVE_ONLY")
    source.setdefault("execution_policy", "DEMO_EXECUTION = DISABLED BY POLICY; LIVE = LOCKED")
    return {
        "schema": SCHEMA_VERSION,
        "acquisition_id": acquisition_id,
        "status": "IN_PROGRESS",
        "read_only": True,
        "orders_submitted": 0,
        "order_send_called": False,
        "dataset_path": str(output_path.resolve()),
        "metadata_path": str(Path(str(output_path) + ".metadata.json").resolve()),
        "source": source,
        "request": {
            "symbol": symbol,
            "start_utc": start_utc.astimezone(UTC).isoformat(),
            "end_utc": end_utc.astimezone(UTC).isoformat(),
            "timestamp_arguments_are_utc_labels_only": True,
            "boundary_status": "UNKNOWN_UNTIL_ADJACENT_WINDOWS_ARE_ACQUIRED",
        },
        "returned_schema": [],
        "required_fields": dict.fromkeys(_REQUIRED_FIELDS, False),
        "row_count": 0,
        "coverage": {
            "first_returned_row_timestamps": None,
            "last_returned_row_timestamps": None,
            "coverage_basis": "raw first/last row in acquisition order; no timestamp normalization",
        },
        "acquisition": {
            "started_at_utc": started_at.isoformat(),
            "ended_at_utc": None,
            "chunk_hours": chunk_hours,
            "boundary_policy": "non-overlapping requested intervals; every row returned by every query is retained; no boundary deduplication",
            "chunks": [],
        },
        "integrity": {
            "raw_dataset_sha256": None,
            "dataset_file_size_bytes": None,
            "hash_scope": "sorted persisted Parquet relative paths and bytes",
        },
        "timestamp_basis": {
            "raw_fields_preserved": True,
            "interpretation": "UNVERIFIED",
            "normalization_applied": False,
            "note": "Historical MT5 time/time_msc remain raw provider values. Current observation offset was not applied.",
        },
        "analysis": {"status": "NOT_RUN", "report_path": None},
    }


def acquire_mt5_ticks(
    mt5: Any,
    *,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    output_path: str | Path,
    chunk_hours: int = DEFAULT_CHUNK_HOURS,
    context: Mapping[str, Any] | None = None,
    flags: Any | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Acquire every row returned by bounded MT5 queries into a Parquet dataset.

    The final dataset is atomically renamed into place only after every chunk
    succeeds.  A query error or interrupt leaves a clearly marked partial
    staging directory and metadata; it can never look like a complete file.
    Existing final datasets are never replaced unless ``overwrite=True``.
    """
    output = Path(output_path)
    metadata_path = Path(str(output) + ".metadata.json")
    partial_dirs = list(output.parent.glob(f".{output.name}.partial-*"))
    partial_meta = list(output.parent.glob(f".{output.name}.partial-*.metadata.json"))
    if output.exists() or metadata_path.exists() or partial_dirs or partial_meta:
        if not overwrite:
            raise FileExistsError(f"refusing to replace existing or incomplete acquisition: {output}")
        if output.is_dir():
            shutil.rmtree(output)
        elif output.exists():
            output.unlink()
        metadata_path.unlink(missing_ok=True)
        for path in partial_dirs + partial_meta:
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    acquisition_id = uuid.uuid4().hex
    staging = output.parent / f".{output.name}.partial-{acquisition_id}"
    partial_metadata = output.parent / f".{output.name}.partial-{acquisition_id}.metadata.json"
    staging.mkdir()
    started_at = utc_now()
    metadata = _base_metadata(
        acquisition_id=acquisition_id,
        output_path=output,
        symbol=symbol,
        start_utc=start_utc,
        end_utc=end_utc,
        chunk_hours=chunk_hours,
        context=context,
        started_at=started_at,
    )
    metadata["partial_dataset_path"] = str(staging.resolve())
    _write_json(partial_metadata, metadata)
    mt5_flags = flags if flags is not None else getattr(mt5, "COPY_TICKS_ALL", None)
    metadata["request"]["mt5_copy_ticks_flags"] = _json_scalar(mt5_flags)

    try:
        if mt5_flags is None:
            metadata["status"] = "MT5_QUERY_ERROR"
            metadata["failure"] = {"type": "AcquisitionError", "message": "MT5 COPY_TICKS_ALL is unavailable"}
            metadata["acquisition"]["ended_at_utc"] = utc_now().isoformat()
            shutil.rmtree(staging, ignore_errors=True)
            _write_json(metadata_path, metadata)
            partial_metadata.unlink(missing_ok=True)
            return metadata
        for index, (chunk_start, chunk_end) in enumerate(iter_chunks(start_utc, end_utc, chunk_hours)):
            request = {
                "index": index,
                "start_utc": chunk_start.isoformat(),
                "end_utc": chunk_end.isoformat(),
                "status": "IN_PROGRESS",
            }
            metadata["acquisition"]["chunks"].append(request)
            _write_json(partial_metadata, metadata)
            try:
                rows = mt5.copy_ticks_range(symbol, chunk_start, chunk_end, mt5_flags)
            except Exception as exc:
                request.update({"status": "MT5_QUERY_ERROR", "error": f"{type(exc).__name__}: {exc}"})
                last_error = getattr(mt5, "last_error", None)
                if callable(last_error):
                    request["mt5_last_error"] = repr(last_error())
                metadata["status"] = "PARTIAL" if metadata["row_count"] else "MT5_QUERY_ERROR"
                raise AcquisitionError(request["error"]) from exc
            if rows is None:
                request["status"] = "MT5_QUERY_ERROR"
                last_error = getattr(mt5, "last_error", None)
                request["mt5_last_error"] = repr(last_error()) if callable(last_error) else None
                metadata["status"] = "PARTIAL" if metadata["row_count"] else "MT5_QUERY_ERROR"
                _write_json(partial_metadata, metadata)
                raise AcquisitionError("MT5 returned no response for a historical chunk")
            row_count = len(rows)
            if row_count == 0:
                request.update({"status": "NO_DATA", "row_count": 0})
                _write_json(partial_metadata, metadata)
                continue
            fields = returned_field_names(rows)
            table = _table_from_rows(rows, fields)
            schema = _schema_inventory(table.schema)
            if not metadata["returned_schema"]:
                metadata["returned_schema"] = schema
                metadata["required_fields"] = {field: field in fields for field in _REQUIRED_FIELDS}
            elif metadata["returned_schema"] != schema:
                request.update({"status": "SCHEMA_DRIFT", "row_count": row_count, "returned_schema": schema})
                # Persist the unexpected response separately so no received raw
                # rows disappear, while refusing to call the main dataset complete.
                drift_file = staging / f"schema-drift-{index:08d}.parquet"
                pq.write_table(table, drift_file, compression="zstd", use_dictionary=False)
                metadata["status"] = "SCHEMA_DRIFT"
                metadata["unpersisted_or_drift_files"] = [drift_file.name]
                _write_json(partial_metadata, metadata)
                raise SchemaDriftError("MT5 returned a schema change; acquisition is incomplete")
            chunk_file = staging / f"chunk-{index:08d}.parquet"
            temporary = chunk_file.with_suffix(".parquet.tmp")
            pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=False)
            os.replace(temporary, chunk_file)
            first = _timestamp_summary(rows[0], fields)
            last = _timestamp_summary(rows[-1], fields)
            request.update({"status": "RESPONSE_PERSISTED", "row_count": row_count, "fields": fields})
            metadata["row_count"] += row_count
            if metadata["coverage"]["first_returned_row_timestamps"] is None:
                metadata["coverage"]["first_returned_row_timestamps"] = first
            metadata["coverage"]["last_returned_row_timestamps"] = last
            _write_json(partial_metadata, metadata)

        if metadata["row_count"] == 0:
            metadata["status"] = "NO_DATA"
            metadata["dataset_path"] = None
            metadata["acquisition"]["ended_at_utc"] = utc_now().isoformat()
            shutil.rmtree(staging, ignore_errors=True)
            _write_json(metadata_path, metadata)
            partial_metadata.unlink(missing_ok=True)
            return metadata

        digest, size = hash_dataset(staging)
        metadata["integrity"].update({"raw_dataset_sha256": digest, "dataset_file_size_bytes": size})
        metadata["status"] = "COMPLETE"
        metadata["acquisition"]["ended_at_utc"] = utc_now().isoformat()
        os.replace(staging, output)
        metadata.pop("partial_dataset_path", None)
        _write_json(metadata_path, metadata)
        partial_metadata.unlink(missing_ok=True)
        return metadata
    except BaseException as exc:
        if metadata.get("status") == "IN_PROGRESS":
            metadata["status"] = "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED"
        metadata["acquisition"]["ended_at_utc"] = utc_now().isoformat()
        metadata["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        _write_json(partial_metadata, metadata)
        raise


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class _OnlineStats:
    def __init__(self, sample_size: int = 100_000) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None
        self.sample: list[float] = []
        self.sample_size = sample_size
        self.random = random.Random(0)

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        if len(self.sample) < self.sample_size:
            self.sample.append(value)
        else:
            position = self.random.randrange(self.count)
            if position < self.sample_size:
                self.sample[position] = value

    def as_dict(self) -> dict[str, Any]:
        if not self.count:
            return {"count": 0, "min": None, "mean": None, "stddev": None, "median_sample": None, "p95_sample": None, "max": None}
        ordered = sorted(self.sample)
        def percentile(q: float) -> float:
            if len(ordered) == 1:
                return ordered[0]
            position = (len(ordered) - 1) * q
            low, high = math.floor(position), math.ceil(position)
            return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
        return {
            "count": self.count,
            "min": self.minimum,
            "mean": self.mean,
            "stddev": math.sqrt(self.m2 / (self.count - 1)) if self.count > 1 else 0.0,
            "median_sample": percentile(0.5),
            "p95_sample": percentile(0.95),
            "max": self.maximum,
            "quantiles_note": f"median/p95 from deterministic reservoir sample capped at {self.sample_size:,}; min/mean/max exact",
        }


def _canonical_bytes(values: Mapping[str, Any]) -> bytes:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")


def analyze_mt5_dataset(dataset_path: str | Path, *, metadata_path: str | Path | None = None) -> dict[str, Any]:
    """Analyze a completed local Parquet dataset without importing MT5."""
    dataset = Path(dataset_path)
    files = _dataset_files(dataset)
    if not files:
        raise FileNotFoundError(f"no Parquet chunks found under {dataset}")
    schemas = [pq.read_schema(path) for path in files]
    unified = pa.unify_schemas(schemas)
    table_dataset = ds.dataset(files, format="parquet", schema=unified)
    fields = [field.name for field in unified]
    quote_fields = [field for field in _QUOTE_FIELDS if field in fields]
    has_time_msc = "time_msc" in fields
    has_bid_ask = "bid" in fields and "ask" in fields
    row_count = 0
    first_timestamps: dict[str, Any] | None = None
    last_timestamps: dict[str, Any] | None = None
    min_time: float | None = None
    max_time: float | None = None
    previous_time: float | None = None
    non_monotonic = 0
    identical_full_row_excess = 0
    seen_hashes: dict[bytes, list[bytes]] = {}
    same_groups = 0
    same_excess = 0
    distinct_same_timestamp = 0
    current_stamp: float | None = None
    current_group_count = 0
    current_group_hashes: set[bytes] = set()
    current_first_quote: bytes | None = None
    consecutive_identical_quote = 0
    previous_quote: bytes | None = None
    invalid_bid = invalid_ask = ask_below_bid = zero_spread = negative_spread = 0
    spread = _OnlineStats()
    price_jumps = _OnlineStats()
    previous_mid: float | None = None
    gap_counts = {"over_1h": 0, "over_6h": 0, "over_24h": 0}
    largest_gap: float | None = None

    def finish_group() -> None:
        nonlocal same_groups, same_excess
        if current_group_count > 1:
            same_groups += 1
            same_excess += current_group_count - 1

    scanner = table_dataset.scanner(batch_size=65_536, use_threads=True)
    for batch in scanner.to_batches():
        columns = {field: batch.column(field).to_pylist() for field in fields}
        for index in range(batch.num_rows):
            row_count += 1
            row = {field: columns[field][index] for field in fields}
            timestamp = _number(row.get("time_msc")) if has_time_msc else None
            if first_timestamps is None:
                first_timestamps = {field: _json_scalar(row.get(field)) for field in _REQUIRED_FIELDS if field in fields}
            last_timestamps = {field: _json_scalar(row.get(field)) for field in _REQUIRED_FIELDS if field in fields}
            row_hash_body = _canonical_bytes(row)
            row_hash = hashlib.blake2b(row_hash_body, digest_size=16).digest()
            if timestamp is not None:
                min_time = timestamp if min_time is None else min(min_time, timestamp)
                max_time = timestamp if max_time is None else max(max_time, timestamp)
                if previous_time is not None:
                    delta = timestamp - previous_time
                    if delta < 0:
                        non_monotonic += 1
                    elif delta > 0:
                        largest_gap = delta if largest_gap is None else max(largest_gap, delta)
                        if delta > 3_600_000:
                            gap_counts["over_1h"] += 1
                        if delta > 21_600_000:
                            gap_counts["over_6h"] += 1
                        if delta > 86_400_000:
                            gap_counts["over_24h"] += 1
                previous_time = timestamp
                if timestamp != current_stamp:
                    finish_group()
                    current_stamp = timestamp
                    current_group_count = 1
                    current_group_hashes = {row_hash}
                    current_first_quote = _canonical_bytes({field: row.get(field) for field in quote_fields})
                else:
                    current_group_count += 1
                    if row_hash in current_group_hashes:
                        # Full-row repeats are counted independently above.
                        pass
                    else:
                        current_group_hashes.add(row_hash)
                    quote_body = _canonical_bytes({field: row.get(field) for field in quote_fields})
                    if quote_body != current_first_quote:
                        distinct_same_timestamp += 1
            prior_bodies = seen_hashes.setdefault(row_hash, [])
            if row_hash_body in prior_bodies:
                identical_full_row_excess += 1
            else:
                prior_bodies.append(row_hash_body)
            bid = _number(row.get("bid"))
            ask = _number(row.get("ask"))
            if bid is not None and bid <= 0:
                invalid_bid += 1
            if ask is not None and ask <= 0:
                invalid_ask += 1
            if bid is not None and ask is not None:
                if ask < bid:
                    ask_below_bid += 1
                difference = ask - bid
                if difference == 0:
                    zero_spread += 1
                if difference < 0:
                    negative_spread += 1
                if bid > 0 and ask > 0 and difference >= 0:
                    mid = (bid + ask) / 2
                    if mid > 0:
                        spread.add(difference / mid * 10_000)
                        if previous_mid is not None:
                            price_jumps.add(abs(mid - previous_mid) / previous_mid * 10_000)
                        previous_mid = mid
            quote_body = _canonical_bytes({field: row.get(field) for field in quote_fields})
            if quote_body == previous_quote:
                consecutive_identical_quote += 1
            previous_quote = quote_body
    finish_group()
    digest, size = hash_dataset(dataset)
    metadata: dict[str, Any] | None = None
    provenance: dict[str, Any] = {"status": "NOT_PROVIDED"}
    if metadata_path is not None:
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        expected = metadata.get("integrity", {}).get("raw_dataset_sha256")
        provenance = {
            "status": "VALID" if metadata.get("status") == "COMPLETE" and expected == digest and metadata.get("row_count") == row_count else "FAILED",
            "metadata_status": metadata.get("status"),
            "metadata_row_count": metadata.get("row_count"),
            "analyzed_row_count": row_count,
            "metadata_sha256": expected,
            "analyzed_dataset_sha256": digest,
        }
    schema_variants = [
        {"file": path.name, "fields": _schema_inventory(schema)}
        for path, schema in zip(files, schemas, strict=True)
    ]
    return {
        "schema": ANALYSIS_SCHEMA_VERSION,
        "dataset_path": str(dataset.resolve()),
        "row_count": row_count,
        "actual_coverage": {
            "first_returned_row_timestamps": first_timestamps,
            "last_returned_row_timestamps": last_timestamps,
            "raw_time_msc_min": min_time,
            "raw_time_msc_max": max_time,
            "timestamp_basis": "RAW_TIME_MSC; historical UTC interpretation remains unverified",
        },
        "schema_integrity": {
            "fields": fields,
            "required_fields": {field: field in fields for field in _REQUIRED_FIELDS},
            "bid_ask_present": has_bid_ask,
            "consistent_across_chunks": len({tuple(item["name"] for item in _schema_inventory(schema)) for schema in schemas}) == 1,
            "variants": schema_variants,
        },
        "ordering": {"non_monotonic_time_msc_count": non_monotonic, "rows_analyzed_in_persisted_chunk_order": True},
        "duplicates": {
            "identical_full_row_excess_count": identical_full_row_excess,
            "same_time_msc_groups": same_groups,
            "same_time_msc_excess_rows": same_excess,
            "same_time_msc_distinct_quote_rows": distinct_same_timestamp,
            "consecutive_identical_quote_state_excess_rows": consecutive_identical_quote,
            "semantics": "all rows retained; equal time_msc and standing quotes are not automatically duplicates",
        },
        "quote_quality": {
            "invalid_bid_count": invalid_bid,
            "invalid_ask_count": invalid_ask,
            "ask_below_bid_count": ask_below_bid,
            "zero_spread_count": zero_spread,
            "negative_spread_count": negative_spread,
            "spread_bps": spread.as_dict(),
        },
        "timestamp_coverage": {
            "gap_delta_units": "raw time_msc delta; assumed millisecond unit from field name, not UTC conversion",
            "largest_positive_delta": largest_gap,
            "gaps_over_1h": gap_counts["over_1h"],
            "gaps_over_6h": gap_counts["over_6h"],
            "gaps_over_24h": gap_counts["over_24h"],
            "closure_interpretation": "NOT_CLASSIFIED; no broker session/holiday calendar was supplied",
        },
        "price_jump_diagnostics": {
            "absolute_mid_change_bps": price_jumps.as_dict(),
            "threshold_classification": "NOT_A_QUALITY_GATE; no jump threshold is asserted",
        },
        "integrity": {"raw_dataset_sha256": digest, "dataset_file_size_bytes": size},
        "provenance_validation": provenance,
        "research_prerequisites": {
            "historical_bid_ask_coverage": "PRESENT" if has_bid_ask else "ABSENT",
            "timestamp_basis": "BLOCKED_UNVERIFIED",
            "spread_quality": "MEASURED_NOT_GATED",
            "execution_fill_evidence": "NOT_PRESENT_IN_QUOTE_DATA",
            "slippage": "NOT_PRESENT",
            "latency": "NOT_PRESENT",
            "realized_transaction_costs": "NOT_PRESENT",
            "frozen_research_modified": False,
            "r5_solved": False,
        },
    }


def write_analysis_report(report: Mapping[str, Any], output_path: str | Path) -> None:
    _write_json(Path(output_path), dict(report))
