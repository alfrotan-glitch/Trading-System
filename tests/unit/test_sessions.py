"""The XAUUSD session calendar — the schedule evidence the quality gate requires.

The gate refuses on principle to infer closures from the data it grades, so
this calendar is the thing that lets real market history pass. Getting it
wrong in either direction matters: too few closures and real data is rejected
as defective, too many and genuinely missing bars are forgiven.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qts.data.sessions import (
    CALENDAR_ID,
    SYMBOL,
    closure_intervals,
    describe,
    is_scheduled_closure,
)


def _utc(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# the daily maintenance break and US daylight saving
# --------------------------------------------------------------------------- #


def test_the_daily_break_is_22_00_utc_during_us_winter() -> None:
    """17:00 New York in EST (UTC-5) is 22:00 UTC."""
    intervals = closure_intervals(_utc(2026, 1, 5), _utc(2026, 1, 6))
    breaks = [(s, e) for s, e in intervals if (e - s) == timedelta(hours=1)]
    assert breaks, "a daily one-hour break must exist"
    assert all(s.hour == 22 for s, _ in breaks), [s.hour for s, _ in breaks]


def test_the_daily_break_is_21_00_utc_during_us_summer() -> None:
    """17:00 New York in EDT (UTC-4) is 21:00 UTC."""
    intervals = closure_intervals(_utc(2026, 7, 6), _utc(2026, 7, 7))
    breaks = [(s, e) for s, e in intervals if (e - s) == timedelta(hours=1)]
    assert all(s.hour == 21 for s, _ in breaks), [s.hour for s, _ in breaks]


def test_the_break_tracks_the_dst_transitions_of_2025_and_2026() -> None:
    """Nov 2025 switches to EST and Mar 2026 back to EDT. The data shows this."""
    winter = closure_intervals(_utc(2025, 11, 10), _utc(2025, 11, 11))
    summer = closure_intervals(_utc(2026, 4, 10), _utc(2026, 4, 11))
    winter_hour = {s.hour for s, e in winter if (e - s) == timedelta(hours=1)}
    summer_hour = {s.hour for s, e in summer if (e - s) == timedelta(hours=1)}
    assert winter_hour == {22}
    assert summer_hour == {21}


# --------------------------------------------------------------------------- #
# the weekend
# --------------------------------------------------------------------------- #


def test_the_weekend_closes_friday_and_reopens_sunday() -> None:
    intervals = closure_intervals(_utc(2026, 1, 1), _utc(2026, 1, 15))
    weekends = [(s, e) for s, e in intervals if (e - s) > timedelta(hours=24)]
    assert weekends, "a multi-day weekend closure must exist"
    for start, end in weekends:
        assert start.weekday() == 4, "weekend closure starts Friday"
        assert end.weekday() == 6, "weekend closure ends Sunday"


def test_a_saturday_moment_is_always_a_scheduled_closure() -> None:
    assert is_scheduled_closure(_utc(2026, 1, 10, 12, 0)) is True


def test_a_wednesday_afternoon_is_not_a_scheduled_closure() -> None:
    assert is_scheduled_closure(_utc(2026, 1, 7, 14, 0)) is False


# --------------------------------------------------------------------------- #
# fail-closed behaviour
# --------------------------------------------------------------------------- #


def test_an_unmodelled_symbol_is_refused_not_silently_defaulted() -> None:
    """A calendar invented for gold must never be applied to something else."""
    with pytest.raises(ValueError, match="no session calendar"):
        closure_intervals(_utc(2026, 1, 1), _utc(2026, 1, 2), symbol="EURUSD")


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        closure_intervals(datetime(2026, 1, 1), datetime(2026, 1, 2))


def test_an_inverted_range_yields_nothing() -> None:
    assert closure_intervals(_utc(2026, 1, 5), _utc(2026, 1, 1)) == []


def test_intervals_are_clipped_to_the_requested_span() -> None:
    start, end = _utc(2026, 1, 5, 12), _utc(2026, 1, 6, 12)
    for s, e in closure_intervals(start, end):
        assert s < end and e > start


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #


def test_describe_records_the_calendar_identity_and_basis() -> None:
    d = describe()
    assert d["calendar_id"] == CALENDAR_ID
    assert d["symbol"] == SYMBOL
    assert d["timezone"] == "America/New_York"
    assert "confirmation" in d


# --------------------------------------------------------------------------- #
# the property that actually unblocked ingestion
# --------------------------------------------------------------------------- #


def test_the_calendar_explains_a_week_of_real_gold_bars() -> None:
    """Every 15m bar in a real week is either inside a session or a closure.

    This is the check that matters: if the calendar left gaps unexplained, the
    quality gate would still reject the dataset as 6% missing.
    """
    from pathlib import Path

    import pandas as pd

    path = Path("data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv")
    if not path.exists():
        pytest.skip("acquired dataset not present on this machine")

    frame = pd.read_csv(path, parse_dates=["time"])
    window = frame[
        (frame.time >= pd.Timestamp("2026-01-05", tz="UTC"))
        & (frame.time < pd.Timestamp("2026-01-12", tz="UTC"))
    ]
    if window.empty:
        pytest.skip("window not covered by the acquired dataset")

    moment = window.time.min().to_pydatetime()
    end = window.time.max().to_pydatetime()
    intervals = closure_intervals(moment, end)

    unexplained = 0
    for ts in window.time:
        t = ts.to_pydatetime()
        if any(s <= t < e for s, e in intervals):
            unexplained += 1
    # A real bar must never fall inside a scheduled closure.
    assert unexplained == 0, f"{unexplained} bars fall inside a declared closure"


def test_store_manifest_and_inventory_preserve_session_calendar_closures(tmp_path) -> None:
    """When ingested with session_calendar='XAUUSD', manifest and inventory must use it."""
    from datetime import timedelta
    from decimal import Decimal

    from qts.data.inventory import generate_inventory
    from qts.data.store import SqliteParquetDataStore
    from qts.domain.value_objects import Bar, Instrument

    instr = Instrument(symbol="XAUUSD", venue="MT5")
    # Monday 2026-01-05 20:00..21:45 UTC (before 22:00 UTC / 17:00 EST break)
    # and 23:00..23:45 UTC (after 23:00 UTC / 18:00 EST reopen).
    opens = [
        datetime(2026, 1, 5, 20, 0, tzinfo=UTC) + timedelta(minutes=15 * i)
        for i in range(8)
    ] + [
        datetime(2026, 1, 5, 23, 0, tzinfo=UTC) + timedelta(minutes=15 * i)
        for i in range(4)
    ]
    bars = [
        Bar(
            instrument=instr,
            open=Decimal("4000"),
            high=Decimal("4001"),
            low=Decimal("3999"),
            close=Decimal("4000.5"),
            volume=Decimal("10"),
            open_time=t,
            close_time=t + timedelta(minutes=15),
        )
        for t in opens
    ]
    data_root = tmp_path / "data"
    store = SqliteParquetDataStore(root=data_root)
    manifest = store.write_bars(
        bars,
        source="REAL:test:xauusd_15m",
        session_calendar="XAUUSD",
    )
    assert manifest.session_calendar == "XAUUSD"
    assert manifest.missing_data_stats["closure_policy"] == "weekend_boundary_plus_explicit_intervals"
    assert manifest.missing_data_stats["unexpected_missing_intervals"] == 0
    assert manifest.session_stats["unexpected_missing_intervals"] == 0

    inv = generate_inventory(root=data_root)
    assert len(inv) == 1
    assert inv[0]["quality_passed"] is True
    assert inv[0]["session_calendar"] == "XAUUSD"
    assert "session_calendar=XAUUSD" in inv[0]["market_closure_handling"]
    assert inv[0]["gaps"]["unexpected_missing_intervals"] == 0
    assert inv[0]["gaps"]["closure_policy"] == "weekend_boundary_plus_explicit_intervals"

    from qts.data.audit import audit_data_sources

    audit = audit_data_sources(root=data_root)
    assert audit["available_sources"][0]["timestamp_quality"]["session_calendar"] == "XAUUSD"

    from qts.research.readiness import assess_bars, assess_dataset

    readiness = assess_dataset(store, manifest.version)
    assert readiness.quality_passed is True
    assert readiness.timeframe == "15m"
    assert not any("DATA_QUALITY_FAILED" in r for r in readiness.reasons)

    # Also verify _infer_timeframe when bars[0] -> bars[1] crosses a session break
    leading_gap_bars = bars[7:]  # 21:45 UTC followed by 23:00 UTC, then 23:15 UTC
    lead_readiness = assess_bars(
        leading_gap_bars,
        data_version="v-lead",
        source_label="REAL:test:xauusd_15m",
        session_calendar="XAUUSD",
    )
    assert lead_readiness.timeframe == "15m"
    assert lead_readiness.quality_passed is True



