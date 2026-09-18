from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.data.quality import analyze_gap_semantics, dataset_missing_stats, validate_bars
from qts.domain.value_objects import Bar, Instrument

INSTRUMENT = Instrument(symbol="XAUUSD", venue="MT5")


def make_bars(opens: list[datetime], timeframe: str = "1H") -> list[Bar]:
    duration = {"15m": timedelta(minutes=15), "1H": timedelta(hours=1)}[timeframe]
    return [
        Bar(
            instrument=INSTRUMENT,
            open=Decimal("2000"),
            high=Decimal("2001"),
            low=Decimal("1999"),
            close=Decimal("2000.5"),
            volume=Decimal("1"),
            open_time=open_time,
            close_time=open_time + duration,
        )
        for open_time in opens
    ]


def test_one_huge_missing_block_fails_even_with_one_gap_event():
    base = datetime(2020, 1, 1, tzinfo=UTC)
    bars = make_bars([base, base + timedelta(hours=1), base + timedelta(days=10)])

    stats = dataset_missing_stats(bars, "1H")

    assert stats["gap_events"] == 1
    assert stats["unexpected_gap_events"] == 1
    assert stats["unexpected_missing_intervals"] == 238
    assert stats["active_span_missing_pct"] > 2.0
    report = validate_bars(bars, "1H")
    assert not next(check for check in report.checks if check.name == "no_missing_bars").passed


def test_many_single_interval_gaps_use_duration_not_only_event_count():
    base = datetime(2020, 1, 1, tzinfo=UTC)
    missing_indexes = {10, 40, 70}
    opens = [base + timedelta(hours=i) for i in range(100) if i not in missing_indexes]

    stats = analyze_gap_semantics(make_bars(opens), "1H")

    assert stats.gap_events == 3
    assert stats.unexpected_gap_events == 3
    assert stats.unexpected_missing_intervals == 3
    assert stats.active_span_missing_pct == 3.0
    report = validate_bars(make_bars(opens), "1H")
    assert not next(check for check in report.checks if check.name == "no_missing_bars").passed


def test_weekend_closure_is_not_an_unexpected_missing_interval():
    friday = datetime(2020, 1, 3, 23, tzinfo=UTC)
    sunday = datetime(2020, 1, 5, 22, tzinfo=UTC)
    stats = analyze_gap_semantics(make_bars([friday, sunday]), "1H")

    assert stats.gap_events == 1
    assert stats.closure_gap_events == 1
    assert stats.closure_intervals == 46
    assert stats.unexpected_gap_events == 0
    assert stats.unexpected_missing_intervals == 0
    assert stats.active_span_missing_pct == 0.0
    assert validate_bars(make_bars([friday, sunday]), "1H").passed


def test_high_gap_event_count_of_legitimate_weekends_does_not_fail():
    start = datetime(2020, 1, 5, 22, tzinfo=UTC)  # Sunday open
    end = datetime(2020, 1, 31, 23, tzinfo=UTC)
    opens: list[datetime] = []
    current = start
    while current <= end:
        if current.weekday() != 5 and not (current.weekday() == 6 and current.hour < 22):
            opens.append(current)
        current += timedelta(hours=1)

    bars = make_bars(opens)
    stats = analyze_gap_semantics(bars, "1H")

    assert stats.closure_gap_events == 3
    assert stats.unexpected_gap_events == 0
    assert stats.unexpected_missing_intervals == 0
    assert validate_bars(bars, "1H").passed


def test_closure_and_unexpected_gap_are_reported_separately():
    friday = datetime(2020, 1, 3, 23, tzinfo=UTC)
    sunday = datetime(2020, 1, 5, 22, tzinfo=UTC)
    sunday_late = datetime(2020, 1, 5, 23, tzinfo=UTC)
    monday_open = datetime(2020, 1, 6, 0, tzinfo=UTC)
    monday_gap_start = datetime(2020, 1, 6, 1, tzinfo=UTC)
    monday_after_gap = datetime(2020, 1, 6, 4, tzinfo=UTC)
    bars = make_bars([friday, sunday, sunday_late, monday_open, monday_gap_start, monday_after_gap])

    stats = dataset_missing_stats(bars, "1H")

    assert stats["closure_gap_events"] == 1
    assert stats["closure_intervals"] == 46
    assert stats["unexpected_gap_events"] == 1
    assert stats["unexpected_missing_intervals"] == 2
    assert stats["calendar_span_missing_intervals"] == 48


def test_explicit_daily_market_closure_requires_schedule_evidence():
    monday = datetime(2020, 1, 6, tzinfo=UTC)
    wednesday = datetime(2020, 1, 8, tzinfo=UTC)
    bars = make_bars([monday, wednesday])

    without_schedule = analyze_gap_semantics(bars, "1H")
    with_schedule = analyze_gap_semantics(
        bars,
        "1H",
        closure_intervals=[(datetime(2020, 1, 7, tzinfo=UTC), wednesday)],
    )

    assert without_schedule.unexpected_missing_intervals == 47
    assert without_schedule.closure_intervals == 0
    assert with_schedule.unexpected_missing_intervals == 0
    assert with_schedule.closure_intervals == 47
    assert with_schedule.closure_policy == "weekend_boundary_plus_explicit_intervals"


def test_calendar_span_and_active_span_are_distinct():
    friday = datetime(2020, 1, 3, 23, tzinfo=UTC)
    sunday = datetime(2020, 1, 5, 22, tzinfo=UTC)
    stats = dataset_missing_stats(make_bars([friday, sunday]), "1H")

    assert stats["calendar_span_missing_intervals"] == 46
    assert stats["calendar_span_missing_pct"] > 90.0
    assert stats["active_span_missing_intervals"] == 0
    assert stats["active_span_missing_pct"] == 0.0
