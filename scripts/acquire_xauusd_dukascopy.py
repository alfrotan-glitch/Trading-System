#!/usr/bin/env python
"""Acquire the pinned real XAUUSD mid-price history (Dukascopy-derived) into QTS.

WHY THIS EXISTS
---------------
Every research claim needs a provenance-qualified real dataset.  The reachable,
reproducible source of real XAUUSD bid/ask-derived history is the GitHub mirror
``vudo805/forex-price-simulator`` pinned below, which publishes Dukascopy
tick-derived 15-minute *mid-price* OHLC bars (mid = (bid + ask) / 2) with
per-bar tick counts, refreshed daily (LAG_DAYS=2) by the upstream project.

This script is acquisition + provenance only:
  * verifies the pinned SHA-256 of every source parquet byte,
  * exports the native 15-minute bars unchanged (no repair, no interpolation),
  * exports a documented 1-hour aggregation of the same bars,
  * optionally registers both through the existing pipeline (``ingest_csv``).

Missing bars stay missing: UTC hours with no underlying 15-minute bars are
simply absent from the exports.  The CSVs land in ``data/raw/`` (gitignored by
repo convention); the run report is the machine-checkable provenance record.

Usage
-----
    python scripts/acquire_xauusd_dukascopy.py --source-dir /path/to/clone
    python scripts/acquire_xauusd_dukascopy.py --source-dir /path/to/clone --ingest
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = "vudo805/forex-price-simulator"
COMMIT = "4d6f15543e6285fad91fd57fe42f716bc7273075"
COMMIT_DATE = "2026-09-18T08:05:21+00:00"
FEED_NOTE = (
    "Dukascopy XAU/USD tick feed fetched by the upstream project's downloader "
    "(datafeed.dukascopy.com, 20-byte '>iiiff' tick records, POINT_VALUE 1000); exported bars "
    "are 15-minute MID-price OHLC (mid = (bid + ask) / 2) with per-bar tick counts"
)
LICENSE_NOTE = (
    "The upstream repository ships NO LICENSE file and states none: treat the data as "
    "unlicensed upstream content, internal research use only, no redistribution"
)
AGGREGATION_RULE = (
    "1H bars are deterministic aggregations of the exported 15m bars on UTC hour boundaries: "
    "open = first 15m open, high = max, low = min, close = last 15m close, volume = sum of "
    "15m tick counts. Hours with fewer than four underlying 15m bars (session edges and "
    "market closures) are retained as-is; empty hours are absent"
)

SOURCE_15M = f"REAL:dukascopy:vudo805@{COMMIT[:7]}:XAUUSD:15m:mid-from-bid-ask-ticks"
SOURCE_1H = f"REAL:dukascopy:vudo805@{COMMIT[:7]}:XAUUSD:1H:aggregate-of-15m-mid-bars"

# Pinned SHA-256 of every source parquet file at COMMIT.  Any byte change is a
# different dataset and must be re-reviewed before it may enter QTS.
EXPECTED_SHA256: dict[str, str] = {
    "XAUUSD_2025-08.parquet": "e650d23cc05194ecb72bf7a748a96823e495850a6b94fac517c29031139c9e37",
    "XAUUSD_2025-09.parquet": "48f7e1d2f5fd2f943580628f736898238b9a998fa4752cbe703ef32779ad345e",
    "XAUUSD_2025-10.parquet": "4533939d9c7ae6e979575e753938f71661ffbe9096e61172040ba1230d9781dc",
    "XAUUSD_2025-11.parquet": "016517904b326a5348795254a7559606d8ae1c882691c399374658a511390cd8",
    "XAUUSD_2025-12.parquet": "e8ad92ba1b1bba37c7fa82577fd27b4faa836ea7f669581ce80f42ca830533a2",
    "XAUUSD_2026-01.parquet": "de17f9c5316678125a9a272fed203b45f52cfe071633b66c548ebf5db826437a",
    "XAUUSD_2026-02.parquet": "1978ce53545f31fd1f6adc5ab33bd447a7a174aa8b71485edf6bd13b792b7954",
    "XAUUSD_2026-03.parquet": "8fba205494b4a068c8803192733d022d81feff082b9668e2a310e23f98ac969e",
    "XAUUSD_2026-04.parquet": "f1b48a9c7c3b9deca60ff2f3856619cd672ebcc2e2d91741fd304cdee18f1486",
    "XAUUSD_2026-05.parquet": "f8ddcae5e23ce1dd0553ada5526bfe6185b5ffc87ace7721acb1cbe0ad517f3b",
    "XAUUSD_2026-06.parquet": "6a404b415cb921943b8419893db3361725180d86ef2c5ed67555b5b1e0d3ce37",
    "XAUUSD_2026-07.parquet": "2f7751b028f183839ec4d3d23a94e5b6de571d00ff14978d73290ae850c6f854",
    "XAUUSD_2026-08.parquet": "5645380ddd0c1a4b0e3cfefbcc283fd3670ea05267978023b7faa590e3c67a3a",
    "XAUUSD_2026-09.parquet": "6b51ceb0fa34f12353a75859ff33179b901138db9d18183ff4db415cabd97da8",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pinned(source_dir: Path) -> tuple[object, dict[str, dict[str, object]]]:
    """Read, verify and concatenate the pinned parquet files (fail closed)."""
    import pandas as pd

    expected = set(EXPECTED_SHA256)
    present = {p.name for p in source_dir.glob("*.parquet")}
    if present != expected:
        raise SystemExit(
            f"source file set mismatch in {source_dir}: "
            f"missing={sorted(expected - present)} unexpected={sorted(present - expected)}"
        )
    frames = []
    per_file: dict[str, dict[str, object]] = {}
    for name in sorted(expected):
        path = source_dir / name
        digest = sha256_file(path)
        if digest != EXPECTED_SHA256[name]:
            raise SystemExit(f"sha256 mismatch for {name}: {digest} != pinned {EXPECTED_SHA256[name]}")
        frame = pd.read_parquet(path, columns=["open", "high", "low", "close", "ticks"])
        frames.append(frame)
        per_file[name] = {"sha256": digest, "rows": int(len(frame))}
    data = pd.concat(frames).sort_index()
    data.index = data.index.tz_localize("UTC") if data.index.tz is None else data.index.tz_convert("UTC")
    if data.index.has_duplicates:
        raise SystemExit("source series has duplicate timestamps — refusing to ingest")
    if not data.index.is_monotonic_increasing:
        raise SystemExit("source series is not monotonic — refusing to ingest")
    if data[["open", "high", "low", "close", "ticks"]].isna().any().any():
        raise SystemExit("source series contains NaN values — refusing to ingest")
    if bool((data["ticks"] < 0).any()):
        raise SystemExit("source series contains negative tick counts — refusing to ingest")
    return data, per_file


def write_bars_csv(data: object, path: Path) -> None:
    """Write time,open,high,low,close,volume (volume = source tick count)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    index = data.index.tz_convert("UTC")  # type: ignore[attr-defined]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        for ts, row in zip(index, data.itertuples(index=False), strict=True):  # type: ignore[attr-defined]
            writer.writerow(
                [
                    ts.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    repr(float(row.open)),
                    repr(float(row.high)),
                    repr(float(row.low)),
                    repr(float(row.close)),
                    int(row.ticks),
                ]
            )


def aggregate_1h(data: object) -> object:
    """Deterministic UTC-hour aggregation of the 15m bars (see AGGREGATION_RULE)."""
    grouped = data.groupby(data.index.floor("1h"), sort=True)  # type: ignore[attr-defined]
    return grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        ticks=("ticks", "sum"),
        n_15m=("ticks", "size"),
    )


def _csv_facts(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as fh:
        header = next(fh).strip()
        rows = 0
        first: str | None = None
        last: str | None = None
        for line in fh:
            rows += 1
            first = first or line.strip()
            last = line.strip()
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": rows,
        "header": header,
        "first_data_row": first,
        "last_data_row": last,
    }


def _find_registered(store: object, source_label: str, csv_path: str) -> dict[str, object] | None:
    """Return an existing registration for this exact source label + export path."""
    for version in store.list_usable_versions():  # type: ignore[attr-defined]
        manifest = store.manifest(version)  # type: ignore[attr-defined]
        if manifest is None:
            continue
        if manifest.source == source_label and manifest.source_file == csv_path:
            return {
                "version": version,
                "checksum": manifest.checksum,
                "rows": manifest.rows,
                "timeframe": manifest.timeframe,
                "source": manifest.source,
                "provenance_class": manifest.provenance_class,
                "start": manifest.start.isoformat(),
                "end": manifest.end.isoformat(),
            }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire the pinned Dukascopy-derived XAUUSD mid dataset")
    parser.add_argument("--source-dir", required=True, help="local clone of the pinned upstream repository")
    parser.add_argument("--out-dir", default="data/raw", help="CSV export directory (gitignored)")
    parser.add_argument(
        "--report", default="data/evidence/xauusd_dukascopy_acquisition.json", help="acquisition report path"
    )
    parser.add_argument("--ingest", action="store_true", help="register both exports through ingest_csv")
    parser.add_argument("--instrument", default="XAUUSD")
    parser.add_argument("--venue", default="MT5", help="system instrument venue (provenance lives in source label)")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    out_dir = Path(args.out_dir)
    data, per_file = load_pinned(source_dir)

    csv_15m = out_dir / "xauusd_dukascopy_15m_mid_20250806_20260916.csv"
    csv_1h = out_dir / "xauusd_dukascopy_1h_mid_agg_20250806_20260916.csv"
    write_bars_csv(data, csv_15m)
    hourly = aggregate_1h(data)
    write_bars_csv(hourly, csv_1h)

    counts = hourly["n_15m"].value_counts().to_dict()
    report: dict[str, object] = {
        "schema": "qts.data_acquisition.v1",
        "acquired_at": datetime.now(UTC).isoformat(),
        "source": {
            "repository": REPO,
            "commit": COMMIT,
            "commit_date": COMMIT_DATE,
            "instrument": "XAUUSD",
            "feed": FEED_NOTE,
            "license": LICENSE_NOTE,
            "files": per_file,
        },
        "coverage": {
            "start": data.index[0].isoformat(),
            "end": data.index[-1].isoformat(),
            "rows_15m": int(len(data)),
            "span_days": round((data.index[-1] - data.index[0]).total_seconds() / 86400.0, 2),
            "gaps_are_absent_not_filled": True,
        },
        "exports": {
            "15m": _csv_facts(csv_15m),
            "1h": _csv_facts(csv_1h),
            "aggregation_1h": AGGREGATION_RULE,
            "hours_15m_bar_counts": {str(k): int(v) for k, v in sorted(counts.items())},
        },
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_report() -> None:
        report_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    _write_report()  # export record is written even if registration fails below

    if args.ingest:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from qts.data.ingest import ingest_csv
        from qts.data.store import SqliteParquetDataStore

        store = SqliteParquetDataStore()
        registered: dict[str, object] = {}
        for label, path, timeframe, source_label in (
            ("15m", csv_15m, "15m", SOURCE_15M),
            ("1h", csv_1h, "1H", SOURCE_1H),
        ):
            existing = _find_registered(store, source_label, str(path))
            if existing is not None:
                registered[label] = {**existing, "status": "already_registered"}
                print(f"{label}: already registered as {existing['version']} (same source label and export path)")
                continue
            try:
                version = ingest_csv(
                    path,
                    instrument=args.instrument,
                    timeframe=timeframe,
                    venue=args.venue,
                    store=store,
                    source=source_label,
                )
            except ValueError as exc:
                # Fail-closed pipeline: the existing quality/strictness gates rejected
                # this export.  The rejection is recorded as evidence — never worked around.
                registered[label] = {
                    "status": "rejected_by_ingest_gate",
                    "reason": str(exc),
                    "csv": str(path),
                    "source_label": source_label,
                }
                print(f"{label}: REJECTED by the existing ingest/quality gate: {exc}")
                continue
            manifest = store.manifest(version)
            if manifest is None:  # pragma: no cover - defensive
                raise SystemExit(f"manifest missing for freshly ingested version {version}")
            registered[label] = {
                "status": "registered",
                "version": version,
                "checksum": manifest.checksum,
                "rows": manifest.rows,
                "timeframe": manifest.timeframe,
                "source": manifest.source,
                "provenance_class": manifest.provenance_class,
                "start": manifest.start.isoformat(),
                "end": manifest.end.isoformat(),
            }
            print(f"registered {label}: version={version} rows={manifest.rows} class={manifest.provenance_class}")
        report["ingest"] = registered
        # Store-derived registry record (source of truth, independent of this
        # run's idempotency): every usable version whose provenance label is
        # one of this acquisition's labels.
        registry: dict[str, object] = {}
        for label, source_label in (("15m", SOURCE_15M), ("1h", SOURCE_1H)):
            found = []
            for version in store.list_usable_versions():
                manifest = store.manifest(version)
                if manifest is not None and manifest.source == source_label:
                    found.append(
                        {
                            "version": version,
                            "checksum": manifest.checksum,
                            "rows": manifest.rows,
                            "timeframe": manifest.timeframe,
                            "venue": manifest.venue,
                            "instrument": manifest.instrument,
                            "provenance_class": manifest.provenance_class,
                            "source_file": manifest.source_file,
                            "start": manifest.start.isoformat(),
                            "end": manifest.end.isoformat(),
                        }
                    )
            registry[label] = found
        report["registry"] = registry
        _write_report()

    print(f"15m export: {csv_15m} rows={report['exports']['15m']['rows']}")  # type: ignore[index]
    print(f"1H  export: {csv_1h} rows={report['exports']['1h']['rows']}")  # type: ignore[index]
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
