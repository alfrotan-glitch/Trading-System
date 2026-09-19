from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.data.provenance import describe_source
from qts.data.store import Manifest, SqliteParquetDataStore
from qts.domain.value_objects import Bar, Instrument


def _bars() -> list[Bar]:
    instrument = Instrument(symbol="XAUUSD", venue="MT5")
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [
        Bar(
            instrument=instrument,
            open=Decimal("2000"),
            high=Decimal("2001"),
            low=Decimal("1999"),
            close=Decimal("2000.5"),
            volume=Decimal("1"),
            open_time=start + timedelta(hours=i),
            close_time=start + timedelta(hours=i + 1),
        )
        for i in range(3)
    ]


def test_dukascopy_source_is_not_mistaken_for_mt5_execution(tmp_path):
    store = SqliteParquetDataStore(root=tmp_path / "data", db_path=tmp_path / "qts.db")
    manifest = store.write_bars(
        _bars(),
        source="REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks",
        source_file="data/raw/xauusd.csv",
    )

    assert manifest.provenance_class == "REAL"
    assert manifest.venue == "MT5"
    assert manifest.venue_semantics == "legacy_dataset_namespace_only"
    assert manifest.source_provider == "Dukascopy-derived upstream mirror"
    assert manifest.source_venue == "Dukascopy XAU/USD feed"
    assert manifest.source_feed == "Dukascopy XAU/USD tick feed; exported mid-price OHLC"
    assert manifest.execution_target is None
    assert manifest.execution_venue is None


def test_ambiguous_source_fails_closed_in_role_metadata():
    roles = describe_source("external.csv", "MT5")

    assert roles["source_provider"] is None
    assert roles["source_feed"] is None
    assert roles["source_venue"] is None
    assert roles["execution_target"] is None
    assert roles["execution_venue"] is None
    assert roles["venue_semantics"] == "legacy_dataset_namespace_only"


def test_legacy_manifest_without_new_roles_remains_readable():
    legacy = {
        "version": "legacy",
        "created_at": "2020-01-01T00:00:00+00:00",
        "code_version": "0.1.0",
        "instrument": "XAUUSD",
        "venue": "MT5",
        "timeframe": "1H",
        "start": "2020-01-01T00:00:00+00:00",
        "end": "2020-01-01T01:00:00+00:00",
        "rows": 1,
        "checksum": "sha256:legacy",
        "source": "REAL:dukascopy:legacy",
        "provenance_class": "REAL",
    }

    manifest = Manifest.model_validate(legacy)

    assert manifest.source == "REAL:dukascopy:legacy"
    assert manifest.source_provider is None
    assert manifest.execution_target is None
