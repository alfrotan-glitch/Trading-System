# 5 — Data Architecture

**Principle:** Data is a first-class, versioned, auditable subsystem. If you cannot state WHAT/WHEN/FROM WHERE/WHICH VERSION for which experiment, the experiment is invalid.

## 5.1 Data Types

| Type | Granularity | Source (v1) | Future |
|------|-------------|-------------|--------|
| Bars | 1m, 5m, 15m, 1H, 1D | MT5 history, CSV seed, Parquet | Ducascopy, Polygon, IB |
| Ticks | bid/ask | MT5 live, synthetic from bars (spread model) | L2 |
| Corporate actions | — | No-op for XAUUSD | Equity splits/divs |
| Sessions | London/NY/etc | Config | Exchange calendar |

## 5.2 Storage

```
data/
  raw/                # immutable ingested files, checksummed
  curated/
    instrument=XAUUSD/venue=MT5/timeframe=1m/
      date=2024-01-01/part-0.parquet
  manifests/
    manifest_<version>.json
  sqlite/
    qts.db            # DataStore lineage, bars index, quality checks
```

- **Parquet** partitioned by `(instrument, venue, timeframe, date)`, dictionary + Snappy, `event_time` sorted.
- **SQLite WAL** for manifests, lineage, quality results. `qts.db` is portable.
- **Manifest** per version: `{version, created_at, code_version, instrument, venue, timeframe, start, end, rows, checksum, source, provenance_class, source_provider, source_feed, source_venue, execution_target, execution_venue, schema_version}` plus `quality_report` (stored in SQLite `quality_reports` with `passed` + per-check details). Legacy `venue` is a dataset/storage namespace; source and execution roles are separate and nullable.
- **Version** = `YYYYMMDD-<git_short>-<content_hash8>` e.g. `20260101-a1b2c3d-9f3e2a1b`. Data is immutable; new ingest → new version.

## 5.3 Normalization

- All timestamps → UTC, tz-aware, ns. `open_time` inclusive, `close_time` exclusive.
- Prices → `Decimal` with instrument `tick_size` quantization; volumes → `Decimal`.
- Missing bars: explicitly marked, never interpolated silently. Quality layer flags.
- Duplicates: detected by `(instrument, open_time, timeframe)` unique index; ingestion rejects duplicates unless `allow_overwrite=false`.
- Schema validation: Pydantic `Bar` + `pandera` DataFrame schema on ingest.
- Provenance: every `Bar` carries `data_version` + `source`.

## 5.4 Quality Gates (run on ingest & on read) — Enforced (Phase 1)

- Schema: required columns, types, UTC tz, no NaN.
- Temporal: monotonic `open_time`, no future bars beyond `now()`, gap detection, duplicate `(symbol, venue, open_time)` unique.
- Price: `high>=low`, `high>=open,close`, `low<=open,close`, tick_size quantization via `Bar.quantize()`.
- Volume: >=0.
- Staleness: `max(event_time) < now - threshold` → alert.
- Outlier: z-score on returns vs rolling median (flag, not drop).

Implementation: `validate_bars(bars)` in `src/qts/data/quality.py`; `SqliteParquetDataStore.write_bars(..., strict_quality=True)` runs it and raises `ValueError("data quality failed: ...")` fail-closed if any check fails. Quality report is persisted in SQLite `quality_reports` and on filesystem via manifest JSON, queryable via `store.quality_report(version)`. `read_bars` post-validates slice invariants (OHLC). Config `strict_quality` (Settings) controls ingest vs permissive read. `qts data validate --version` surfaces report and exits 2 on FAIL.

## 5.5 Time & Session

- `market_sessions.yaml` defines XAUUSD sessions (00:00 UTC continuous but London 08-16, NY 13-21). Regime detectors may condition on session.
- No local timezone; broker time → UTC at adapter edge.

## 5.6 Provenance & Reproducibility

Every experiment records `data_version`. Re-running with same `data_version` yields identical bars (Parquet content hash verified). Data diff tool: `qts data diff --versions v1 v2`.

Lineage: `Bar.data_version → Manifest → Raw files (checksums) → Ingest code_version`.

## 5.7 Live Feed

- `MT5DataFeed` subscribes via MT5 callback or polling; ticks/bars normalized to domain `Bar/Tick` before bus emit.
- Backpressure: bounded queue; on overflow, drop oldest + emit `DataLossAlert` + pause strategy (NO_TRADE).
- Reconnect: exponential backoff, state recovery via `DataStore` last bar.

## 5.8 Leakage Prevention

- Data access is via `DataSlice` bounded by `experiment.train_end`. Validator enforces that strategy code never queries beyond slice.
- Feature Store computes features only on train slice; transform applied to test via fitted params.
- Purged cross-validation embargo respected at DataStore query layer.

## 5.9 Example Manifest

```json
{
  "version": "20240916-a1b2c3d-9f3e2a1b",
  "schema_version": 1,
  "created_at": "2024-09-16T12:00:00Z",
  "code_version": "a1b2c3d",
  "sources": [{
    "instrument": "XAUUSD",
    "venue": "MT5",
    "timeframe": "1m",
    "start": "2020-01-01T00:00:00Z",
    "end": "2024-09-15T23:59:00Z",
    "rows": 2456789,
    "checksum": "sha256:...",
    "source_file": "raw/mt5_XAUUSD_1m_2020-2024.csv"
  }]
}
```

## 5.10 Operational

- `qts data ingest --source csv --path raw/... --instrument XAUUSD --timeframe 1m`
- `qts data validate --version <ver>`
- `qts data export --version <ver> --format parquet --out data/curated/`
