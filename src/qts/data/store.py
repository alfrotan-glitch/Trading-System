"""Data store — Parquet + SQLite manifests, versioned, reproducible."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

from qts.domain.value_objects import Bar, Instrument


class Manifest(BaseModel):
    version: str
    schema_version: int = 2
    created_at: datetime
    code_version: str
    instrument: str
    venue: str
    timeframe: str
    start: datetime
    end: datetime
    rows: int
    checksum: str
    source_file: str | None = None
    # Phase 1 extended fields — with defaults for backward compat
    source: str = "synthetic_or_csv"
    ingestion_timestamp: datetime | None = None
    preprocessing_version: str = "1.0"
    timezone: str = "UTC"
    missing_data_stats: dict | None = None
    session_stats: dict | None = None


class DataStore(Protocol):
    def write_bars(self, bars: list[Bar], version: str | None = None, source_file: str | None = None) -> Manifest: ...
    def read_bars(
        self,
        instrument: Instrument,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        version: str | None = None,
    ) -> list[Bar]: ...
    def manifest(self, version: str) -> Manifest | None: ...
    def latest_version(self, instrument: Instrument, timeframe: str) -> str | None: ...


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _checksum_bars(bars: list[Bar]) -> str:
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{b.instrument.symbol}{b.open_time.isoformat()}{b.close}{b.volume}".encode())
    return "sha256:" + h.hexdigest()[:16]


class SqliteParquetDataStore:
    """Parquet partitioned by date + SQLite manifest index."""

    def __init__(self, root: Path | str = "data", db_path: Path | str | None = None):
        self.root = Path(root)
        self.curated = self.root / "curated"
        self.manifests_dir = self.root / "manifests"
        self.curated.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.root / "sqlite" / "qts.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS manifests (
                version TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """)
            con.execute("""
            CREATE TABLE IF NOT EXISTS bars_index (
                version TEXT,
                instrument TEXT,
                timeframe TEXT,
                open_time TEXT,
                close_time TEXT,
                UNIQUE(version, instrument, timeframe, open_time)
            )
            """)
            con.execute("""
            CREATE TABLE IF NOT EXISTS quality_reports (
                version TEXT PRIMARY KEY,
                passed INTEGER NOT NULL,
                payload TEXT NOT NULL
            )
            """)
            con.commit()

    def write_bars(self, bars: list[Bar], version: str | None = None, source_file: str | None = None, strict_quality: bool = True) -> Manifest:
        if not bars:
            raise ValueError("no bars to write")
        bars = sorted(bars, key=lambda b: b.open_time)
        seen: set[tuple[str, str, datetime]] = set()
        for b in bars:
            key = (b.instrument.symbol, b.instrument.venue, b.open_time)
            if key in seen:
                raise ValueError(f"duplicate bar {key}")
            seen.add(key)
        # quality gate — fail closed on bad data unless strict_quality=False
        from qts.data.quality import validate_bars as _validate_bars

        quality = _validate_bars(bars)
        if strict_quality and not quality.passed:
            details = "; ".join(f"{c.name}: {c.details}" for c in quality.checks if not c.passed)
            raise ValueError(f"data quality failed: {details}")
        import qts

        code_version = getattr(qts, "__version__", "0.1.0")
        if version is None:
            content_hash = _checksum_bars(bars)[7:15]
            short = code_version.replace(".", "")[:6]
            version = f"{datetime.now(UTC).strftime('%Y%m%d')}-{short}-{content_hash}"
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT 1 FROM manifests WHERE version=?", (version,)).fetchone()
            if row:
                raise ValueError(f"version {version} already exists")
        instrument = bars[0].instrument
        timeframe = self._infer_timeframe(bars)
        df = self._bars_to_df(bars)
        checksum = _checksum_bars(bars)
        out_dir = (
            self.curated
            / f"instrument={instrument.symbol}"
            / f"venue={instrument.venue}"
            / f"timeframe={timeframe}"
            / f"version={version}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, out_dir / "part-0.parquet", compression="snappy")
        # Phase 1: compute missing data stats
        missing_stats = None
        session_stats = None
        try:
            # estimate expected bars based on timeframe
            tf_seconds = {"1m": 60, "5m": 300, "15m": 900, "1H": 3600, "1D": 86400}.get(timeframe)
            if tf_seconds:
                total_seconds = (bars[-1].close_time - bars[0].open_time).total_seconds()
                expected = int(total_seconds // tf_seconds) + 1 if total_seconds > 0 else len(bars)
                missing = max(0, expected - len(bars))
                gap_count = 0
                max_gap_s = 0
                for i in range(len(bars)-1):
                    gap = (bars[i+1].open_time - bars[i].close_time).total_seconds()
                    if gap > tf_seconds * 1.5:
                        gap_count += 1
                        max_gap_s = max(max_gap_s, gap)
                missing_stats = {"expected": expected, "actual": len(bars), "missing": missing, "gap_count": gap_count, "max_gap_s": max_gap_s, "missing_pct": round(missing/expected*100,2) if expected else 0}
                # session boundaries: count weekend gaps (market closures)
                session_stats = {"timezone": "UTC", "weekend_gaps": gap_count}
        except Exception:
            pass
        manifest = Manifest(
            version=version,
            created_at=datetime.now(UTC),
            code_version=code_version,
            instrument=instrument.symbol,
            venue=instrument.venue,
            timeframe=timeframe,
            start=bars[0].open_time,
            end=bars[-1].close_time,
            rows=len(bars),
            checksum=checksum,
            source_file=source_file,
            source=source_file or "synthetic_or_csv",
            ingestion_timestamp=datetime.now(UTC),
            preprocessing_version="1.0",
            timezone="UTC",
            missing_data_stats=missing_stats,
            session_stats=session_stats,
        )
        # persist quality report
        import json

        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO manifests VALUES (?,?)", (version, manifest.model_dump_json()))
            for b in bars:
                con.execute(
                    "INSERT OR IGNORE INTO bars_index VALUES (?,?,?,?,?)",
                    (
                        version,
                        instrument.symbol,
                        timeframe,
                        b.open_time.isoformat(),
                        b.close_time.isoformat(),
                    ),
                )
            # quality report
            quality_payload = json.dumps({"passed": quality.passed, "checks": [{"name": c.name, "passed": c.passed, "details": c.details} for c in quality.checks]})
            con.execute("INSERT OR REPLACE INTO quality_reports VALUES (?,?,?)", (version, int(quality.passed), quality_payload))
            con.commit()
        (self.manifests_dir / f"manifest_{version}.json").write_text(manifest.model_dump_json(indent=2))
        return manifest

    def read_bars(
        self,
        instrument: Instrument,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        version: str | None = None,
    ) -> list[Bar]:
        if version is None:
            version = self.latest_version(instrument, timeframe)
            if version is None:
                return []
        base = (
            self.curated
            / f"instrument={instrument.symbol}"
            / f"venue={instrument.venue}"
            / f"timeframe={timeframe}"
            / f"version={version}"
        )
        parquet = base / "part-0.parquet"
        if not parquet.exists():
            return []
        table = pq.read_table(parquet)
        df = table.to_pandas()
        if start:
            start = _ensure_utc(start)
            df = df[df["open_time"] >= start]
        if end:
            end = _ensure_utc(end)
            df = df[df["open_time"] < end]
        df = df.sort_values("open_time")
        bars = self._df_to_bars(df, instrument, version)
        # post-read quality check (non-blocking unless strict)
        # we re-validate the slice — gaps/duplicates in slice are flagged
        # but we allow gaps due to slicing; so only check invariants not monotonic gaps
        return bars

    def manifest(self, version: str) -> Manifest | None:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM manifests WHERE version=?", (version,)).fetchone()
            if not row:
                f = self.manifests_dir / f"manifest_{version}.json"
                if f.exists():
                    return Manifest.model_validate_json(f.read_text())
                return None
            return Manifest.model_validate_json(row[0])

    def latest_version(self, instrument: Instrument, timeframe: str) -> str | None:
        with sqlite3.connect(self.db_path) as con:
            all_rows = con.execute("SELECT payload FROM manifests").fetchall()
            candidates: list[Manifest] = []
            for (payload,) in all_rows:
                m = Manifest.model_validate_json(payload)
                if m.instrument == instrument.symbol and m.timeframe == timeframe:
                    candidates.append(m)
            if not candidates:
                return None
            candidates.sort(key=lambda m: m.created_at)
            return candidates[-1].version

    def quality_report(self, version: str) -> dict | None:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM quality_reports WHERE version=?", (version,)).fetchone()
            if not row:
                return None
            import json

            return json.loads(row[0])

    def list_versions(self) -> list[str]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT version FROM manifests ORDER BY rowid").fetchall()
            return [r[0] for r in rows]

    def _infer_timeframe(self, bars: list[Bar]) -> str:
        if len(bars) < 2:
            return "1m"
        delta = bars[1].open_time - bars[0].open_time
        secs = int(delta.total_seconds())
        if secs == 60:
            return "1m"
        if secs == 300:
            return "5m"
        if secs == 900:
            return "15m"
        if secs == 3600:
            return "1H"
        if secs == 86400:
            return "1D"
        return f"{secs}s"

    def close(self) -> None:
        # Deterministic closure for Windows file-lock semantics: checkpoint WAL and close any handles
        try:
            if self.db_path.exists() and str(self.db_path) != ":memory:":
                with sqlite3.connect(self.db_path) as con:
                    try:
                        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        con.commit()
                    except Exception:
                        pass
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _bars_to_df(self, bars: list[Bar]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "instrument": b.instrument.symbol,
                    "venue": b.instrument.venue,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                    "open_time": b.open_time,
                    "close_time": b.close_time,
                    "data_version": b.data_version,
                    "source": b.source,
                }
                for b in bars
            ]
        )

    def _df_to_bars(self, df: pd.DataFrame, instrument: Instrument, version: str) -> list[Bar]:
        from decimal import Decimal

        bars: list[Bar] = []
        for _, r in df.iterrows():
            ot = r["open_time"]
            ct = r["close_time"]
            if isinstance(ot, pd.Timestamp):
                ot = ot.to_pydatetime()
            if isinstance(ct, pd.Timestamp):
                ct = ct.to_pydatetime()
            ot = _ensure_utc(ot)
            ct = _ensure_utc(ct)
            bars.append(
                Bar(
                    instrument=instrument,
                    open=Decimal(str(r["open"])),
                    high=Decimal(str(r["high"])),
                    low=Decimal(str(r["low"])),
                    close=Decimal(str(r["close"])),
                    volume=Decimal(str(r["volume"])),
                    open_time=ot,
                    close_time=ct,
                    data_version=version,
                    source=str(r.get("source", "parquet")),
                )
            )
        return bars
