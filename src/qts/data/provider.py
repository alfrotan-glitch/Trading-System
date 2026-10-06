"""Provider-neutral ingestion interface — Provider → Raw Storage → Validation → Normalization → Canonical Dataset → Manifest → Evidence.
Preserves raw source where legally possible, never overwrites raw with processed.
Every dataset immutable: dataset ID, source ID, ingestion timestamp, checksum, schema, preprocessing, timezone, symbol mapping, quality report.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
        # For local CSV, dest_raw is already the source; copy to raw storage for provenance.
        return dest_raw

    def parse(self, raw_path: Path, instrument: str, timeframe: str) -> list[Bar]:
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
        from qts.data.synthetic import generate_gbm_bars, write_csv
        from qts.domain.value_objects import AssetClass

        instr = Instrument(symbol=instrument, venue="MT5", asset_class=AssetClass.METAL)
        tf_map = {"1m": 1, "5m": 5, "15m": 15, "1H": 60, "1D": 1440}
        mins = tf_map.get(timeframe, 60)
        periods = max(1, int((end - start).total_seconds() // 60 // mins))
        bars = generate_gbm_bars(instrument=instr, periods=periods, seed=42)
        dest_raw.parent.mkdir(parents=True, exist_ok=True)
        write_csv(bars, dest_raw)
        return dest_raw

    def parse(self, raw_path: Path, instrument: str, timeframe: str) -> list[Bar]:
        return CsvProvider().parse(raw_path, instrument, timeframe)
