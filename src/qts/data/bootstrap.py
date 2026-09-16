"""Deterministic, truthful data bootstrap for clean clones.

Design rules (non-negotiable):

* A registered version (SQLite row or manifest JSON) is NEVER assumed usable.
  Usable = manifest + curated parquet exist and yield the claimed rows.
* A fixture with zero usable bars is never promoted to a dataset version.
* No data is ever fabricated to make setup "succeed". If the fixture is
  missing or invalid, bootstrap FAILS with a clear, actionable message.
* The bootstrap fixture ``data/fixtures/XAUUSD_1H_500.csv`` is SYNTHETIC
  (GBM, seed=42, s0=2000 — byte-identical to ``generate_gbm_bars``). It is
  ingested with an explicit ``SYNTHETIC:`` provenance label and can never
  satisfy gates that require REAL market history.
* Idempotent: repeated runs reuse the existing usable version instead of
  creating duplicates, regardless of the calendar date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument

# Provenance classes used across the system. Every dataset must map to exactly one.
DATA_CLASSES = (
    "REAL",  # genuine broker/exchange historical or live data
    "SYNTHETIC",  # generated locally (GBM/trending/fixture), never real
    "SIMULATED",  # paper/simulator fills, not venue-executed
    "ESTIMATED",  # inferred statistic, not an observation
    "IMPUTED",  # filled-in missing values
    "BROKER-DERIVED",  # computed from broker data (e.g. spread proxy)
    "MODEL-DERIVED",  # output of a model, not an observation
)

FIXTURE_RELPATH = Path("fixtures/XAUUSD_1H_500.csv")
# Kept for backward compatibility (repo-CWD default). bootstrap_data() itself
# resolves the fixture RELATIVE TO `root` so non-default roots never silently
# read the repository's fixture.
DEFAULT_FIXTURE = Path("data") / FIXTURE_RELPATH


def classify_source(source: str | None) -> str:
    """Map a manifest/bar source label to exactly one provenance class."""
    if not source:
        return "SYNTHETIC"  # unlabeled legacy writes came from synthetic generators
    s = source.lower()
    if "synthetic" in s or "fixture" in s or "gbm" in s or "synth" in s:
        return "SYNTHETIC"
    if "mt5_history" in s or "broker" in s:
        return "BROKER-DERIVED"
    if "model" in s:
        return "MODEL-DERIVED"
    if "imputed" in s:
        return "IMPUTED"
    if "estimated" in s:
        return "ESTIMATED"
    if s.startswith("real"):
        return "REAL"
    return "SYNTHETIC"  # fail-safe: unverified provenance is NEVER treated as REAL


@dataclass
class BootstrapResult:
    status: str  # READY | INGESTED | FAILED
    version: str | None = None
    bars: int = 0
    data_class: str = "SYNTHETIC"
    source: str | None = None
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("READY", "INGESTED")


def _stale_version_for(exc: ValueError, store: SqliteParquetDataStore) -> str | None:
    """Extract the version id from a 'version X already exists' error, returning it
    only if that version is registered but NOT usable (i.e. genuinely stale)."""
    import re

    m = re.search(r"version (\S+) already exists", str(exc))
    if not m:
        return None
    v = m.group(1)
    if store.manifest(v) is not None and not store.version_usable(v):
        return v
    return None


def bootstrap_data(
    root: Path | str = "data",
    fixture: Path | str | None = None,
    instrument: str = "XAUUSD",
    timeframe: str = "1H",
    venue: str = "MT5",
    store: SqliteParquetDataStore | None = None,
) -> BootstrapResult:
    """Ensure at least one USABLE dataset version exists for instrument/timeframe.

    Deterministic and idempotent:
      1. If a usable version already exists -> READY (no writes).
      2. Else ingest the fixture with an explicit SYNTHETIC label -> INGESTED,
         verified usable before success is reported.
      3. Fixture missing/empty/invalid -> FAILED. Never fabricate bars.
    """
    store = store if store is not None else SqliteParquetDataStore(root=root)
    if fixture is None:
        fixture = Path(root) / FIXTURE_RELPATH
    fixture = Path(fixture)
    result = BootstrapResult(status="FAILED")
    instr = Instrument(symbol=instrument, venue=venue)

    def _registered() -> list[str]:
        versions: list[str] = []
        for v in store.list_versions():
            m = store.manifest(v)
            if m and m.instrument == instrument and m.timeframe == timeframe:
                versions.append(v)
        return versions

    # 1. existing usable version wins (idempotency across dates and reruns)
    usable = list(store.list_usable_versions())
    for v in usable:
        m = store.manifest(v)
        if m and m.instrument == instrument and m.timeframe == timeframe:
            bars = store.read_bars(instr, timeframe, version=v)
            result.status = "READY"
            result.version = v
            result.bars = len(bars)
            result.source = m.source
            result.data_class = classify_source(m.source)
            result.messages.append(
                f"usable version {v}: {len(bars)} bars, class={result.data_class} (source={m.source})"
            )
            return result

    # 2. report phantom/stale registrations truthfully
    for v in _registered():
        result.messages.append(
            f"registered version {v} has NO readable bars (manifest without curated parquet) — not usable"
        )

    # 3. fixture presence and validity — fail closed, never fabricate
    if not fixture.exists():
        result.messages.append(
            f"fixture {fixture} not found — cannot bootstrap; no data was fabricated. "
            "Restore the fixture (git checkout -- data/fixtures) or ingest real data via `qts data ingest`."
        )
        return result

    # zero-usable-bars guard BEFORE any write: parse and count rows
    import csv

    with open(fixture, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
    if not rows:
        result.messages.append(
            f"fixture {fixture} contains zero usable bars — refused (a zero-bar fixture is never promoted to a dataset version)"
        )
        return result

    # 4. ingest with explicit SYNTHETIC provenance
    from qts.data.ingest import ingest_csv

    source_label = f"SYNTHETIC:fixture:{fixture.name}"
    try:
        version = ingest_csv(
            fixture, instrument=instrument, timeframe=timeframe, venue=venue, store=store, source=source_label
        )
    except ValueError as e:
        # duplicate version (same content already written earlier): reuse iff usable
        for v in store.list_usable_versions():
            m = store.manifest(v)
            if m and m.instrument == instrument and m.timeframe == timeframe:
                bars = store.read_bars(instr, timeframe, version=v)
                result.status = "READY"
                result.version = v
                result.bars = len(bars)
                result.source = m.source
                result.data_class = classify_source(m.source)
                result.messages.append(f"ingest reported duplicate ({e}); reused usable version {v}")
                return result
        # stale registration: the version id is taken but its data is NOT usable
        # (partial failure — e.g. curated parquet deleted or never materialized).
        # Deterministic repair: purge the stale registration (never usable data —
        # purge_version refuses that) and re-ingest once.
        stale = _stale_version_for(e, store)
        if stale is not None and store.purge_version(stale):
            result.messages.append(
                f"purged stale registration {stale} (registered without readable bars) and re-ingesting"
            )
            try:
                version = ingest_csv(
                    fixture, instrument=instrument, timeframe=timeframe, venue=venue, store=store, source=source_label
                )
            except ValueError as e2:
                result.messages.append(f"re-ingest after purge failed: {e2}")
                return result
        else:
            result.messages.append(f"ingest failed: {e}")
            return result

    # 5. verify truthfully — a version row alone is NOT proof of data
    if not store.version_usable(version):
        result.messages.append(f"ingest created version {version} but it is NOT usable — refusing to report success")
        return result
    m = store.manifest(version)
    bars = store.read_bars(instr, timeframe, version=version)
    result.status = "INGESTED"
    result.version = version
    result.bars = len(bars)
    result.source = source_label
    result.data_class = "SYNTHETIC"
    result.messages.append(f"ingested {len(bars)} bars from fixture {fixture} as version {version}")
    result.messages.append(
        "NOTE: bootstrap data is SYNTHETIC (GBM seed=42) — it is NOT real market history and "
        "NEVER satisfies real-data requirements for demo_forward/live eligibility."
    )
    _ = m
    return result
