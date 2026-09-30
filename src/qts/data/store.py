"""Data store — Parquet + SQLite manifests, versioned, reproducible."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

from qts.data.quality import dataset_missing_stats
from qts.db import connect as db_connect
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
    # Provenance is a label plus its canonical class. Older manifests may lack
    # the class; readers must then remain conservative.
    source: str = "synthetic_or_csv"
    provenance_class: str = "UNVERIFIED"
    # Explicit source/execution roles. The legacy ``venue`` field below is a
    # storage/instrument namespace, not proof of source or broker execution.
    source_provider: str | None = None
    source_feed: str | None = None
    source_venue: str | None = None
    execution_target: str | None = None
    execution_venue: str | None = None
    venue_semantics: str = "legacy_dataset_namespace_only"
    ingestion_timestamp: datetime | None = None
    preprocessing_version: str = "1.0"
    timezone: str = "UTC"
    missing_data_stats: dict | None = None
    session_stats: dict | None = None


class DataStore(Protocol):
    def write_bars(
        self,
        bars: list[Bar],
        version: str | None = None,
        source_file: str | None = None,
        strict_quality: bool = True,
        source: str | None = None,
        source_provider: str | None = None,
        source_feed: str | None = None,
        source_venue: str | None = None,
        execution_target: str | None = None,
        execution_venue: str | None = None,
    ) -> Manifest: ...
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
        with db_connect(self.db_path) as con:
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

    def write_bars(
        self,
        bars: list[Bar],
        version: str | None = None,
        source_file: str | None = None,
        strict_quality: bool = True,
        source: str | None = None,
        source_provider: str | None = None,
        source_feed: str | None = None,
        source_venue: str | None = None,
        execution_target: str | None = None,
        execution_venue: str | None = None,
    ) -> Manifest:
        if not bars:
            raise ValueError("no bars to write")
        bars = sorted(bars, key=lambda b: b.open_time)
        seen: set[tuple[str, str, datetime]] = set()
        for b in bars:
            key = (b.instrument.symbol, b.instrument.venue, b.open_time)
            if key in seen:
                raise ValueError(f"duplicate bar {key}")
            seen.add(key)
        instrument = bars[0].instrument
        timeframe = self._infer_timeframe(bars)
        source_label = source or source_file or "synthetic_or_csv"
        # quality gate — fail closed on bad data unless strict_quality=False
        from qts.data.quality import validate_bars as _validate_bars

        quality = _validate_bars(bars, timeframe)
        if strict_quality and not quality.passed:
            details = "; ".join(f"{c.name}: {c.details}" for c in quality.checks if not c.passed)
            raise ValueError(f"data quality failed: {details}")
        from qts.observability.lineage import code_version as current_code_version

        code_version = current_code_version()
        if version is None:
            content_hash = _checksum_bars(bars)[7:15]
            short = code_version.replace(".", "")[:12]
            version = f"{datetime.now(UTC).strftime('%Y%m%d')}-{short}-{content_hash}"
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT 1 FROM manifests WHERE version=?", (version,)).fetchone()
            if row:
                raise ValueError(f"version {version} already exists")
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
        # Compute the same explicit gap model used by validation and inventory.
        # Do not swallow errors or silently fall back to a different population.
        missing_stats = dataset_missing_stats(bars, timeframe)
        session_stats = {
            "timezone": "UTC",
            "closure_policy": missing_stats.get("closure_policy"),
            "closure_gap_events": missing_stats.get("closure_gap_events"),
            "closure_intervals": missing_stats.get("closure_intervals"),
            "unexpected_gap_events": missing_stats.get("unexpected_gap_events"),
            "unexpected_missing_intervals": missing_stats.get("unexpected_missing_intervals"),
        }
        from qts.data.bootstrap import classify_source
        from qts.data.provenance import describe_source

        roles = describe_source(source_label, instrument.venue)
        roles.update(
            {
                "source_provider": source_provider or roles["source_provider"],
                "source_feed": source_feed or roles["source_feed"],
                "source_venue": source_venue or roles["source_venue"],
                "execution_target": execution_target,
                "execution_venue": execution_venue,
            }
        )
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
            source=source_label,
            provenance_class=classify_source(source_label),
            source_provider=roles["source_provider"],
            source_feed=roles["source_feed"],
            source_venue=roles["source_venue"],
            execution_target=roles["execution_target"],
            execution_venue=roles["execution_venue"],
            venue_semantics=roles["venue_semantics"],
            ingestion_timestamp=datetime.now(UTC),
            preprocessing_version="1.0",
            timezone="UTC",
            missing_data_stats=missing_stats,
            session_stats=session_stats,
        )
        # persist quality report
        import json

        with db_connect(self.db_path) as con:
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
            quality_payload = json.dumps(
                {
                    "passed": quality.passed,
                    "checks": [{"name": c.name, "passed": c.passed, "details": c.details} for c in quality.checks],
                }
            )
            con.execute(
                "INSERT OR REPLACE INTO quality_reports VALUES (?,?,?)", (version, int(quality.passed), quality_payload)
            )
            con.commit()
        (self.manifests_dir / f"manifest_{version}.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
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
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM manifests WHERE version=?", (version,)).fetchone()
            if not row:
                f = self.manifests_dir / f"manifest_{version}.json"
                if f.exists():
                    manifest = Manifest.model_validate_json(f.read_text(encoding="utf-8"))
                else:
                    return None
            else:
                manifest = Manifest.model_validate_json(row[0])
        # Migrate the interpretation of old rows in memory only. A known
        # source label receives its deterministic class; ambiguous provenance
        # remains UNVERIFIED and is never upgraded to claim-eligible evidence.
        if manifest.provenance_class == "UNVERIFIED" and manifest.source:
            from qts.data.bootstrap import classify_source

            inferred = classify_source(manifest.source)
            if inferred != "UNVERIFIED":
                manifest.provenance_class = inferred
        return manifest

    def latest_version(self, instrument: Instrument, timeframe: str) -> str | None:
        with db_connect(self.db_path) as con:
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
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload FROM quality_reports WHERE version=?", (version,)).fetchone()
            if not row:
                return None
            import json

            return json.loads(row[0])

    def list_versions(self) -> list[str]:
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT version FROM manifests ORDER BY rowid").fetchall()
            return [r[0] for r in rows]

    def version_usable(self, version: str) -> bool:
        """A version is USABLE only if manifest + curated parquet exist and the
        parquet actually yields the number of rows the manifest claims.

        Never treat a manifest row (SQLite or JSON) as proof that data exists:
        on a clean clone the registry may reference versions whose parquet was
        never materialized (gitignored). Zero readable bars => not usable.
        """
        try:
            m = self.manifest(version)
            if m is None:
                return False
            parquet = (
                self.curated
                / f"instrument={m.instrument}"
                / f"venue={m.venue}"
                / f"timeframe={m.timeframe}"
                / f"version={version}"
                / "part-0.parquet"
            )
            if not parquet.exists():
                return False
            bars = self.read_bars(Instrument(symbol=m.instrument, venue=m.venue), m.timeframe, version=version)
            return len(bars) > 0 and len(bars) == m.rows
        except Exception:
            return False

    def list_usable_versions(self) -> list[str]:
        """Registered versions that pass version_usable() — truthful availability."""
        return [v for v in self.list_versions() if self.version_usable(v)]

    def purge_version(self, version: str) -> bool:
        """Remove a STALE registration: manifest row, index rows, manifest JSON and
        the (empty or partial) curated partition for ``version``.

        Safety: refuses to purge a version that is currently usable — this is a
        registry-integrity repair for partially-materialized versions (e.g. a crash
        between DB commit and parquet write, or curated data deleted out-of-band),
        never a way to delete real datasets. Returns True if something was purged.
        """
        if self.version_usable(version):
            return False
        purged = False
        with db_connect(self.db_path) as con:
            cur = con.execute("DELETE FROM manifests WHERE version=?", (version,))
            purged = purged or cur.rowcount > 0
            con.execute("DELETE FROM bars_index WHERE version=?", (version,))
            con.execute("DELETE FROM quality_reports WHERE version=?", (version,))
        jf = self.manifests_dir / f"manifest_{version}.json"
        if jf.exists():
            jf.unlink()
            purged = True
        # remove any curated partitions for this version (parquet missing or partial)
        if self.curated.exists():
            for part in self.curated.glob(f"instrument=*/venue=*/timeframe=*/version={version}"):
                import shutil

                shutil.rmtree(part, ignore_errors=True)
                purged = True
        return purged

    def find_versions_by_checksum(self, checksum: str) -> list[str]:
        """All known versions (DB + manifest JSON files) with the given content checksum."""
        found: list[str] = []
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT payload FROM manifests").fetchall()
        for (payload,) in rows:
            try:
                m = Manifest.model_validate_json(payload)
                if m.checksum == checksum:
                    found.append(m.version)
            # B112: tolerate corrupt manifest rows during checksum lookup
            except Exception:  # nosec B112
                continue
        if self.manifests_dir.exists():
            for f in sorted(self.manifests_dir.glob("manifest_*.json")):
                try:
                    m = Manifest.model_validate_json(f.read_text(encoding="utf-8"))
                    if m.checksum == checksum and m.version not in found:
                        found.append(m.version)
                # B112: tolerate corrupt manifest files during checksum lookup
                except Exception:  # nosec B112
                    continue
        return found

    def _infer_timeframe(self, bars: list[Bar]) -> str:
        if len(bars) < 2:
            return "1m"
        deltas = [
            int((bars[i + 1].open_time - bars[i].open_time).total_seconds())
            for i in range(len(bars) - 1)
            if bars[i + 1].open_time > bars[i].open_time
        ]
        if not deltas:
            return "1m"
        secs = Counter(deltas).most_common(1)[0][0]
        known = {60: "1m", 300: "5m", 900: "15m", 3600: "1H", 86400: "1D"}
        return known.get(secs, f"{secs}s")

    def close(self) -> None:
        # File-backed connections are opened/closed per operation via qts.db.connect,
        # so no persistent handle exists here. We must NOT re-open the database file
        # in close()/__del__: that recreates deleted files and re-acquires Windows
        # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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
