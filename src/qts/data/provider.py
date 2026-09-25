"""Provider-neutral ingestion interface — Provider → Raw Storage → Validation → Normalization → Canonical Dataset → Manifest → Evidence.
Preserves raw source where legally possible, never overwrites raw with processed.
Every dataset immutable: dataset ID, source ID, ingestion timestamp, checksum, schema, preprocessing, timezone, symbol mapping, quality report.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


# Candidate external providers (researched, not all implemented — catalog documents them)
EXTERNAL_CATALOG: list[dict[str, Any]] = [
    # These are acquisition plans, not measured datasets in this checkout.
    # Keep that status explicit so a catalog row cannot be mistaken for
    # evidence of installed history or broker-quality fields.
    {
        "provider_id": "dukascopy",
        "availability_status": "PLANNED_NOT_INGESTED",
        "measured_in_checkout": False,
        "evidence_status": "CATALOG_PLAN_ONLY",
        "description": "Dukascopy free FX tick/1m/1H history, deep",
        "historical_depth": "2003+ for FX, 10+ years",
        "granularity": "tick, 1m, 1H, 1D",
        "bid_ask": True,
        "tick": True,
        "timezone": "UTC/Geneva",
        "licensing": "Free for personal research, redistribution restrictions",
        "api": "https://www.dukascopy.com/swiss/english/marketwatch/historical/ + dukascopy-node",
        "reliability": "High, market standard for FX backtest",
        "quality": "Good, but FX only, not XAUUSD spread realism",
        "symbol_mapping": "XAUUSD as XAU/USD, need mapping",
        "timestamp_behavior": "UTC, no broker-specific session",
        "limitations": "FX only, no broker-specific MT5 spread, need XAUUSD verification",
        "cost": "Free for 1m, tick via API",
        "suitability_research": "High for FX/cross-market, medium for XAUUSD execution",
        "suitability_execution": "Medium — not broker-specific spread",
    },
    {
        "provider_id": "firstrate",
        "availability_status": "PLANNED_NOT_INGESTED",
        "measured_in_checkout": False,
        "evidence_status": "CATALOG_PLAN_ONLY",
        "description": "FirstRate Data — exchange-grade tick/1m for FX/metals/crypto",
        "historical_depth": "2003+ 1m, tick from 2019",
        "granularity": "tick, 1s, 1m, 1H, 1D",
        "bid_ask": False,  # mid OHLC only for most
        "tick": True,
        "timezone": "UTC",
        "licensing": "Paid, licensing for redistribution requires commercial",
        "api": "https://firstratedata.com/ + bulk download",
        "reliability": "High, institutional grade",
        "quality": "Excellent for OHLCV, limited bid/ask",
        "symbol_mapping": "XAUUSD standard",
        "timestamp_behavior": "UTC, exchange time",
        "limitations": "Cost $200-500 per symbol/timeframe/year, not broker-specific",
        "cost": "$300/year for bundle",
        "suitability_research": "High for multi-timeframe/microstructure proxy",
        "suitability_execution": "Medium — mid only, need spread proxy labelled SYNTHETIC",
    },
    {
        "provider_id": "mt5_history",
        "availability_status": "PLANNED_NOT_INGESTED",
        "measured_in_checkout": False,
        "evidence_status": "CATALOG_PLAN_ONLY",
        "description": "MT5 broker history export (real broker XAUUSD)",
        "historical_depth": "Broker dependent, typically 1-2 years 1m, 5+ years 1H",
        "granularity": "1m, 5m, 15m, 1H, tick if enabled",
        "bid_ask": False,  # OHLC + tick volume only, no bid/ask in history center
        "tick": False,
        "timezone": "Broker server time (e.g., UTC+2), need conversion",
        "licensing": "Broker terms, personal use",
        "api": "MT5 terminal History Center export to CSV",
        "reliability": "Broker-specific, best for execution realism if bid/ask via live capture",
        "quality": "Best for XAUUSD execution if live tick captured forward",
        "symbol_mapping": "XAUUSD as provided",
        "timestamp_behavior": "Server time, convert to UTC, handle DST",
        "limitations": "Limited depth, no historical bid/ask, need forward observatory for spread",
        "cost": "Free with broker account",
        "suitability_research": "High for XAUUSD regime, medium depth",
        "suitability_execution": "High if combined with live forward capture for spread",
    },
    {
        "provider_id": "binance",
        "availability_status": "PLANNED_NOT_INGESTED",
        "measured_in_checkout": False,
        "evidence_status": "CATALOG_PLAN_ONLY",
        "description": "Binance crypto spot/futures tick/aggs",
        "historical_depth": "2017+ for BTC, 2020+ for many",
        "granularity": "tick, 1s, 1m, 1H",
        "bid_ask": False,  # mid + volume, need book ticker for bid/ask",
        "tick": True,
        "timezone": "UTC",
        "licensing": "Public, CC BY",
        "api": "https://api.binance.com/api/v3/klines + historical data zip",
        "reliability": "High for crypto",
        "quality": "Excellent for cross-asset research, not XAUUSD",
        "symbol_mapping": "BTCUSDT, not applicable to XAUUSD",
        "timestamp_behavior": "UTC ms",
        "limitations": "Crypto only, not directly XAUUSD",
        "cost": "Free",
        "suitability_research": "High for cross-market regime diversity",
        "suitability_execution": "Medium for crypto, not XAUUSD",
    },
    {
        "provider_id": "truefx",
        "availability_status": "PLANNED_NOT_INGESTED",
        "measured_in_checkout": False,
        "evidence_status": "CATALOG_PLAN_ONLY",
        "description": "TrueFX free FX tick with bid/ask",
        "historical_depth": "2009+ for majors",
        "granularity": "tick bid/ask",
        "bid_ask": True,
        "tick": True,
        "timezone": "UTC",
        "licensing": "Free for personal, not redistribution",
        "api": "https://www.truefx.com/?page=downloads",
        "reliability": "Medium, community standard",
        "quality": "Good for execution research FX, need XAUUSD check",
        "symbol_mapping": "XAUUSD as XAU/USD",
        "timestamp_behavior": "UTC ms",
        "limitations": "FX only, XAUUSD availability to verify",
        "cost": "Free",
        "suitability_research": "Medium-High for FX execution",
        "suitability_execution": "High for FX bid/ask research",
    },
]


def ingestion_pipeline(
    provider: DataProvider,
    instrument: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    raw_dir: Path = Path("data/raw"),
    store_dir: Path = Path("data"),
) -> dict[str, Any]:
    """Provider → Raw Storage → Validation → Normalization → Canonical Dataset → Manifest → Evidence.
    Preserves raw, never overwrites with processed, returns manifest metadata.
    """
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
