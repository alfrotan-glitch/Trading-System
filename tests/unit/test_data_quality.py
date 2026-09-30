from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.data.quality import validate_bars
from qts.domain.value_objects import Bar, Instrument


def test_quality_pass():
    instr = Instrument(symbol="XAUUSD")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            instrument=instr,
            open=Decimal("2000"),
            high=Decimal("2010"),
            low=Decimal("1990"),
            close=Decimal("2005"),
            open_time=now,
            close_time=now + timedelta(minutes=60),
        ),
        Bar(
            instrument=instr,
            open=Decimal("2005"),
            high=Decimal("2015"),
            low=Decimal("2000"),
            close=Decimal("2010"),
            open_time=now + timedelta(minutes=60),
            close_time=now + timedelta(minutes=120),
        ),
    ]
    report = validate_bars(bars)
    assert report.passed


def test_quality_fails_duplicate():
    instr = Instrument(symbol="XAUUSD")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    bar = Bar(
        instrument=instr,
        open=Decimal("2000"),
        high=Decimal("2010"),
        low=Decimal("1990"),
        close=Decimal("2005"),
        open_time=now,
        close_time=now + timedelta(minutes=60),
    )
    report = validate_bars([bar, bar])
    assert not report.passed
    assert any(c.name == "no_duplicates" and not c.passed for c in report.checks)


def test_quality_empty():
    report = validate_bars([])
    assert not report.passed
