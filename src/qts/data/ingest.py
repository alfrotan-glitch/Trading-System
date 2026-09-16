"""CSV ingestion → DataStore."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import AssetClass, Bar, Instrument


def ingest_csv(
    path: Path | str,
    instrument: str,
    timeframe: str,
    venue: str = "MT5",
    store: SqliteParquetDataStore | None = None,
    source: str | None = None,
) -> str:
    """Ingest a CSV of bars into the store.

    ``source`` is the provenance label recorded on every Bar and in the manifest
    (e.g. ``SYNTHETIC:fixture:XAUUSD_1H_500.csv``). Data classes must never be
    conflated: a SYNTHETIC dataset can never masquerade as REAL broker history.

    Encoding is forced to UTF-8 (BOM-tolerant via ``utf-8-sig``) so ingestion is
    identical on Windows (cp1252 default locale) and POSIX. Fails closed on an
    empty/zero-bar file — a fixture with zero usable bars is never promoted to a
    dataset version.
    """
    path = Path(path)
    if store is None:
        store = SqliteParquetDataStore()
    instr = Instrument(symbol=instrument, venue=venue, asset_class=AssetClass.METAL)
    bars: list[Bar] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # flexible columns: open_time / close_time or time
            ot_raw = row.get("open_time") or row.get("time") or row.get("timestamp")
            ct_raw = row.get("close_time")
            if not ot_raw:
                raise ValueError(f"missing open_time in row {row}")
            ot = datetime.fromisoformat(ot_raw.replace("Z", "+00:00"))
            if ot.tzinfo is None:
                ot = ot.replace(tzinfo=UTC)
            if ct_raw:
                ct = datetime.fromisoformat(ct_raw.replace("Z", "+00:00"))
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=UTC)
            else:
                # infer close from timeframe
                tf_map = {"1m": 1, "5m": 5, "15m": 15, "1H": 60, "1D": 1440}
                mins = tf_map.get(timeframe, 60)
                from datetime import timedelta

                ct = ot + timedelta(minutes=mins)
            bars.append(
                Bar(
                    instrument=instr,
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=Decimal(str(row.get("volume", "1000"))),
                    open_time=ot,
                    close_time=ct,
                    data_version="ingest",
                    source=source or str(path),
                )
            )
    if not bars:
        raise ValueError(
            f"no usable bars in {path} — file parsed but contained zero data rows; "
            "refusing to create a dataset version (fail closed)"
        )
    manifest = store.write_bars(bars, source_file=str(path), source=source)
    return manifest.version
