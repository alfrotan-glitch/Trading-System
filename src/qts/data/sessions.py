"""Explicit XAUUSD trading-session calendar.

Why this exists
---------------
The quality gate (``qts.data.quality``) deliberately refuses to guess market
closures from OHLC data. Its docstring is explicit: ``closure_intervals`` is
"optional explicit schedule evidence. It is not guessed from OHLC."

That is the right call — a gate that infers closures from the very data it is
grading can always explain away its own missing bars. But the consequence is
that real XAUUSD history, which is closed for roughly a third of the calendar,
was rejected outright: the daily maintenance break was scored as missing data.

This module supplies the missing schedule evidence, from the market convention
rather than from a fit to the bars.

The schedule
------------
Spot gold (XAUUSD) trades:

* **Sunday 18:00 → Friday 17:00**, New York time, continuously, except
* a **daily maintenance break, 17:00 → 18:00** New York time.

All times are ``America/New_York``, so the calendar follows US daylight saving
automatically. In UTC the daily break therefore appears at **21:00 during US
DST and 22:00 otherwise** — which is precisely what the acquired Dukascopy
history shows, and is the strongest available confirmation that this schedule
is the right one:

* Aug–Oct 2025 (EDT): zero bars in the 21:00 UTC hour
* Nov 2025 – Feb 2026 (EST): zero bars in the 22:00 UTC hour
* Mar 2026: the transition month
* Apr 2026 onward (EDT): zero bars in the 21:00 UTC hour

Weekly open/close verified the same way: the earliest Sunday bar is 18:00 ET
and the latest Friday bar is 16:xx ET, across 58 weeks.

This is a two-parameter model (one weekly window, one daily break) anchored to
a public market convention — not a curve fitted to the gaps.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

#: Identifier recorded alongside any dataset graded with this calendar.
CALENDAR_ID = "xauusd.spot_metals.new_york.v1"

#: The only instrument this calendar is claimed to describe. Anything else
#: needs its own schedule; do not silently reuse this one.
SYMBOL = "XAUUSD"

WEEK_OPEN_WEEKDAY = 6  # Sunday
WEEK_OPEN_TIME = time(18, 0)
WEEK_CLOSE_WEEKDAY = 4  # Friday
WEEK_CLOSE_TIME = time(17, 0)
DAILY_BREAK_START = time(17, 0)
DAILY_BREAK_END = time(18, 0)


def _et_moment(day: date, moment: time) -> datetime:
    """Attach a New York wall-clock time to a calendar day, correctly over DST.

    17:00–18:00 local never coincides with a DST transition (those happen at
    02:00 local), so there is no ambiguous or non-existent local time here.
    """
    return datetime.combine(day, moment, tzinfo=_ET)


def closure_intervals(
    start: datetime,
    end: datetime,
    *,
    symbol: str = SYMBOL,
) -> list[tuple[datetime, datetime]]:
    """Every scheduled closure overlapping ``[start, end]``, as UTC pairs.

    Returns the weekend closure (Friday 17:00 ET → Sunday 18:00 ET) and the
    daily maintenance break (17:00–18:00 ET) for each day in range. Intervals
    may overlap — the Friday break is inside the weekend closure — which the
    consumer handles.

    Only ``XAUUSD`` is supported: raising for anything else is the whole point.
    A calendar invented for one instrument must never be quietly applied to
    another whose hours differ.
    """
    if symbol != SYMBOL:
        raise ValueError(
            f"no session calendar for {symbol!r}; only {SYMBOL!r} is modelled. "
            "Supply explicit closure intervals for any other instrument."
        )

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if end <= start:
        return []

    local_start = start.astimezone(_ET).date()
    local_end = end.astimezone(_ET).date()

    intervals: list[tuple[datetime, datetime]] = []
    day = local_start - timedelta(days=1)
    one_day = timedelta(days=1)

    while day <= local_end + one_day:
        # Daily maintenance break, every day of the week.
        break_start = _et_moment(day, DAILY_BREAK_START)
        break_end = _et_moment(day, DAILY_BREAK_END)
        intervals.append((break_start.astimezone(UTC), break_end.astimezone(UTC)))

        # Weekend: Friday 17:00 ET through Sunday 18:00 ET.
        if day.weekday() == WEEK_CLOSE_WEEKDAY:
            weekend_start = _et_moment(day, WEEK_CLOSE_TIME)
            weekend_end = _et_moment(
                day + timedelta(days=(WEEK_OPEN_WEEKDAY - WEEK_CLOSE_WEEKDAY) % 7 or 7),
                WEEK_OPEN_TIME,
            )
            intervals.append((weekend_start.astimezone(UTC), weekend_end.astimezone(UTC)))

        day += one_day

    return [(s, e) for s, e in intervals if s < end and e > start]


def is_scheduled_closure(moment: datetime, *, symbol: str = SYMBOL) -> bool:
    """Is ``moment`` inside a scheduled XAUUSD closure?"""
    window = timedelta(minutes=1)
    return any(
        start <= moment < end
        for start, end in closure_intervals(
            moment - window, moment + window, symbol=symbol
        )
    )


def describe(*, symbol: str = SYMBOL) -> dict[str, object]:
    """Machine-readable description of the calendar, for provenance records."""
    return {
        "calendar_id": CALENDAR_ID,
        "symbol": symbol,
        "basis": "public market convention, empirically confirmed against acquired history",
        "timezone": "America/New_York",
        "week_open": f"Sunday {WEEK_OPEN_TIME:%H:%M}",
        "week_close": f"Friday {WEEK_CLOSE_TIME:%H:%M}",
        "daily_break": f"{DAILY_BREAK_START:%H:%M}-{DAILY_BREAK_END:%H:%M}",
        "dst_handling": "carried by America/New_York; UTC offset of the break moves with US DST",
        "confirmation": (
            "acquired XAUUSD 15m history shows zero bars in the 21:00 UTC hour during US DST "
            "and zero in the 22:00 UTC hour otherwise; earliest Sunday bar is 18:00 ET and "
            "latest Friday bar is 16:xx ET, across 58 weeks"
        ),
    }
