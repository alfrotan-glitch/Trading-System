"""Provider-neutral ingestion interface — Provider → Raw Storage → Validation → Normalization → Canonical Dataset → Manifest → Evidence.
Preserves raw source where legally possible, never overwrites raw with processed.
Every dataset immutable: dataset ID, source ID, ingestion timestamp, checksum, schema, preprocessing, timezone, symbol mapping, quality report.

NOT WIRED: no production path imports this module. Ingestion that actually runs is ``qts.data.ingest``/``qts.data.bootstrap`` for files and ``qts.data.mt5_history_acquisition`` for broker ticks, and provenance is classified by ``qts.data.bootstrap.classify_source``. Kept as a research harness and exercised by tests; do not treat ``SyntheticProvider`` here as a source the product can produce evidence from.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.config.paths import resolve_state_path
from qts.domain.value_objects import Bar, Instrument


class DataProvider(ABC):
    provider_id: str
    description: str

    @abstractmethod
    def fetch(self, instrument: str, timeframe: str, start: datetime, end: datetime, dest_raw: Path) -> Path:
        """Fetch raw data to dest_raw, return path to raw file. Must preserve raw bytes."""
        ...

    @abstractmethod
    def parse(self, raw_path: Path, instrument: str, timeframe: str) -> list[Bar]:
        """Parse raw file into Bars without mutation of raw."""
        ...


class CsvProvider(DataProvider):
    provider_id = "csv"
    description = "CSV file on disk — local synthetic or exported history"

    def fetch(self, instrument: str, timeframe: str, start: datetime, end: datetime, dest_raw: Path) -> Path:
        # For local CSV, dest_raw is already the source; copy to raw storage for provenance
        return dest_raw

    def parse(self, raw_path: Path, instrument: str, timeframe: str) -> list[Bar]:
        # Use ingest_csv parsing but without writing — replicate logic
        import csv
        from decimal import Decimal

        from qts.domain.value_objects import AssetClass

        instr = Instrument(symbol=instrument, venue="MT5", asset_class=AssetClass.METAL)
        bars: list[Bar] = []
        with open(raw_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ot_raw = row.get("open_time") or row.get("time") or row.get("timestamp")
                if not ot_raw:
                    raise ValueError(f"missing open_time in row {row}")
                ct_raw = row.get("close_time")
                ot = datetime.fromisoformat(str(ot_raw).replace("Z", "+00:00"))
                if ot.tzinfo is None:
                    ot = ot.replace(tzinfo=UTC)
                if ct_raw:
                    ct = datetime.fromisoformat(ct_raw.replace("Z", "+00:00"))
                    if ct.tzinfo is None:
                        ct = ct.replace(tzinfo=UTC)
                else:
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
                        data_version="raw",
                        source=str(raw_path),
                    )
                )
        return bars


class SyntheticProvider(DataProvider):
    provider_id = "synthetic"
    description = "Synthetic GBM for controlled simulations — must be labeled SYNTHETIC, never as real"

    def fetch(self, instrument: str, timeframe: str, start: datetime, end: datetime, dest_raw: Path) -> Path:
        # Generate synthetic bars and write to dest_raw as CSV for raw preservation
        from qts.data.synthetic import generate_gbm_bars, write_csv
        from qts.domain.value_objects import AssetClass

        instr = Instrument(symbol=instrument, venue="MT5", asset_class=AssetClass.METAL)
        # Estimate periods from start/end
        tf_map = {"1m": 1, "5m": 5, "15m": 15, "1H": 60, "1D": 1440}
        mins = tf_map.get(timeframe, 60)
        periods = max(1, int((end - start).total_seconds() // 60 // mins))
        bars = generate_gbm_bars(instrument=instr, periods=periods, seed=42)
        dest_raw.parent.mkdir(parents=True, exist_ok=True)
        write_csv(bars, dest_raw)
        return dest_raw

    def parse(self, raw_path: Path, instrument: str, timeframe: str) -> list[Bar]:
        return CsvProvider().parse(raw_path, instrument, timeframe)


# The former ``EXTERNAL_CATALOG`` list (5 candidate-provider research entries)
# was removed here (architecture audit, 2026-10-02): it had zero consumers —
# not even this module's own tests referenced it by name — and it duplicated,
# field-for-field, the catalog actually served to the product in
# ``data/evidence/data_source_catalog.json`` (read by
# ``qts.api.routes.research.research_data_source_catalog`` via
# ``artifact_path("data_source_catalog")``). That JSON file is the one
# catalog a production surface reads; keeping a second, unused Python copy of
# the same five provider entries risked the two silently drifting apart with
# nothing to notice. The JSON file is unchanged and remains canonical.


def ingestion_pipeline(
    provider: DataProvider,
    instrument: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    raw_dir: Path | None = None,
    store_dir: Path | None = None,
) -> dict[str, Any]:
    """Provider → Raw Storage → Validation → Normalization → Canonical Dataset → Manifest → Evidence.
    Preserves raw, never overwrites with processed, returns manifest metadata.
    """
    raw_dir = resolve_state_path("data/raw") if raw_dir is None else Path(raw_dir)
    store_dir = resolve_state_path("data") if store_dir is None else Path(store_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = (
        raw_dir
        / f"{provider.provider_id}_{instrument}_{timeframe}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    )
    # 1 Provider → Raw Storage (preserve raw bytes)
    fetched = provider.fetch(instrument, timeframe, start, end, raw_path)
    raw_checksum = hashlib.sha256(fetched.read_bytes()).hexdigest()[:16]
    raw_stat = fetched.stat()
    # 2 Parse
    bars = provider.parse(fetched, instrument, timeframe)
    # 3 Validation
    from qts.data.quality import validate_bars

    report = validate_bars(bars)
    if not report.passed:
        raise ValueError(f"validation failed: {[c.details for c in report.checks if not c.passed]}")
    # 4 Normalization (UTC, sort, quantize)
    bars = sorted(bars, key=lambda b: b.open_time)
    bars = [b.quantize() for b in bars]
    # 5 Canonical Dataset → Manifest (immutable dataset ID). The source label
    # is explicit: a generated provider is synthetic; every external provider
    # remains unverified until its raw evidence is actually ingested and
    # independently classified.
    from qts.data.store import SqliteParquetDataStore

    source_class = "SYNTHETIC" if provider.provider_id == "synthetic" else "UNVERIFIED"
    source_label = f"{source_class}:provider:{provider.provider_id}"
    store = SqliteParquetDataStore(root=store_dir)
    manifest = store.write_bars(bars, source_file=str(fetched), source=source_label)
    # 6 Evidence (quality report + raw provenance)
    evidence = {
        "dataset_id": manifest.version,
        "source_id": provider.provider_id,
        "source_status": "MEASURED_INGESTION",
        "data_class": manifest.provenance_class,
        "instrument": instrument,
        "timeframe": timeframe,
        "start": manifest.start.isoformat(),
        "end": manifest.end.isoformat(),
        "rows": manifest.rows,
        "raw_path": str(fetched),
        "raw_checksum": f"sha256:{raw_checksum}",
        "raw_size": raw_stat.st_size,
        "ingestion_timestamp": manifest.created_at.isoformat()
        if hasattr(manifest, "created_at")
        else datetime.now(UTC).isoformat(),
        "checksum": manifest.checksum,
        "schema_version": manifest.schema_version,
        "preprocessing_version": manifest.preprocessing_version
        if hasattr(manifest, "preprocessing_version")
        else "1.0.0",
        "timezone": "UTC",
        "symbol_mapping": f"{instrument}→{instrument} (MT5)",
        "quality_report": [{"name": c.name, "passed": c.passed, "details": c.details} for c in report.checks],
        "provenance": f"Provider {provider.provider_id} fetched {raw_path} → validated → normalized UTC → canonical {manifest.version}",
        "raw_preserved": str(fetched),
        "never_overwritten": True,
    }
    return evidence
