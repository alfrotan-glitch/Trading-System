"""Data quality gates and explicit gap/coverage semantics.

The quality layer distinguishes nominal calendar absence from recognized market
closures and from unexpected missing observations.  A low *number of gap
transitions* is not sufficient: the quality gate uses the duration/fraction of
unexpected missing intervals as well.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from qts.domain.value_objects import Bar

MAX_UNEXPECTED_MISSING_FRACTION = 0.02
_TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1H": 3600, "1D": 86400}


@dataclass
class QualityCheck:
    name: str
    passed: bool
    details: str = ""


@dataclass
class DataQualityReport:
    passed: bool
    checks: list[QualityCheck]


@dataclass(frozen=True)
class GapSemantics:
    """One auditable classification of gaps between observed bars.

    ``calendar_span_*`` treats every nominal cadence slot between the first and
    last observed bar as expected.  ``closure_*`` is the subset recognized by
    the supplied schedule policy.  ``unexpected_*`` is everything else and is
    the only population eligible for a quality PASS.  A broker/session
    calendar is not inferred from the OHLC data; the default policy recognizes
    weekend boundaries only.
    """

    cadence_seconds: int | None
    cadence_basis: str
    observed_bars: int
    gap_events: int | None
    calendar_span_expected_intervals: int | None
    calendar_span_missing_intervals: int | None
    calendar_span_missing_pct: float | None
    closure_gap_events: int | None
    closure_intervals: int | None
    unexpected_gap_events: int | None
    unexpected_missing_intervals: int | None
    active_span_expected_intervals: int | None
    active_span_missing_intervals: int | None
    active_span_missing_pct: float | None
    max_gap_duration_s: float | None
    max_unexpected_gap_duration_s: float | None
    max_unexpected_missing_intervals: int | None
    closure_policy: str

    def as_dict(self) -> dict[str, object]:
        return {
            "cadence_seconds": self.cadence_seconds,
            "cadence_basis": self.cadence_basis,
            "observed_bars": self.observed_bars,
            "gap_events": self.gap_events,
            "calendar_span_expected_intervals": self.calendar_span_expected_intervals,
            "calendar_span_missing_intervals": self.calendar_span_missing_intervals,
            "calendar_span_missing_pct": self.calendar_span_missing_pct,
            "closure_gap_events": self.closure_gap_events,
            "closure_intervals": self.closure_intervals,
            "unexpected_gap_events": self.unexpected_gap_events,
            "unexpected_missing_intervals": self.unexpected_missing_intervals,
            "active_span_expected_intervals": self.active_span_expected_intervals,
            "active_span_missing_intervals": self.active_span_missing_intervals,
            "active_span_missing_pct": self.active_span_missing_pct,
            "max_gap_duration_s": self.max_gap_duration_s,
            "max_unexpected_gap_duration_s": self.max_unexpected_gap_duration_s,
            "max_unexpected_missing_intervals": self.max_unexpected_missing_intervals,
            "closure_policy": self.closure_policy,
            # Compatibility aliases.  They intentionally point to the
            # unexpected population, not to all calendar absence.
            "gap_count": self.unexpected_gap_events,
            "missing_intervals": self.unexpected_missing_intervals,
            "missing_pct": self.active_span_missing_pct,
            # Legacy manifest keys retained for reader compatibility.  New
            # code must use the explicit names above; these aliases describe
            # calendar-span absence unless otherwise stated.
            "expected": self.calendar_span_expected_intervals,
            "actual": self.observed_bars,
            "missing": self.calendar_span_missing_intervals,
            "max_gap_s": self.max_gap_duration_s,
            "common_delta_s": self.cadence_seconds,
        }


def _infer_cadence_seconds(bars: list[Bar], timeframe: str | None) -> tuple[int | None, str]:
    if timeframe in _TIMEFRAME_SECONDS:
        return _TIMEFRAME_SECONDS[timeframe], "declared_timeframe"
    if len(bars) < 2:
        return None, "unavailable"
    deltas = [
        int((bars[i + 1].open_time - bars[i].open_time).total_seconds())
        for i in range(len(bars) - 1)
        if bars[i + 1].open_time > bars[i].open_time
    ]
    if not deltas:
        return None, "unavailable"
    return Counter(deltas).most_common(1)[0][0], "modal_observed_open_delta"


def _overlaps_known_closure(
    start: datetime,
    end: datetime,
    closure_intervals: Iterable[tuple[datetime, datetime]] | None,
) -> bool:
    if closure_intervals is None:
        return False
    for closure_start, closure_end in closure_intervals:
        closure_start = closure_start.astimezone(UTC)
        closure_end = closure_end.astimezone(UTC)
        if closure_start < end and closure_end > start:
            return True
    return False


def _is_weekend_closure(previous: datetime, following: datetime, delta_s: float, cadence_s: int) -> bool:
    """Recognize only the calendar weekend boundary, conservatively.

    We do not label arbitrary multi-day holes as closures.  Without a broker
    session/holiday calendar, those remain unexpected and therefore block the
    quality gate.  Friday→Sunday and Friday→Monday boundaries are the only
    default closure semantics.
    """
    if delta_s <= cadence_s:
        return False
    return previous.weekday() == 4 and following.weekday() in (0, 5, 6)


def analyze_gap_semantics(
    bars: list[Bar],
    timeframe: str | None = None,
    *,
    closure_intervals: Iterable[tuple[datetime, datetime]] | None = None,
) -> GapSemantics:
    """Classify nominal intervals without treating closures as observations.

    ``closure_intervals`` is optional explicit schedule evidence.  It is not
    guessed from OHLC.  With no schedule supplied, only the weekend boundary
    policy is applied; holidays and broker-specific closures remain
    unexpected/unavailable rather than being silently forgiven.
    """
    cadence_s, cadence_basis = _infer_cadence_seconds(bars, timeframe)
    policy = "weekend_boundary_only"
    if closure_intervals is not None:
        policy = "weekend_boundary_plus_explicit_intervals"
    if cadence_s is None or len(bars) < 2:
        return GapSemantics(
            cadence_seconds=cadence_s,
            cadence_basis=cadence_basis,
            observed_bars=len(bars),
            gap_events=0 if len(bars) < 2 else None,
            calendar_span_expected_intervals=len(bars) if bars else None,
            calendar_span_missing_intervals=0 if bars else None,
            calendar_span_missing_pct=0.0 if bars else None,
            closure_gap_events=0 if bars else None,
            closure_intervals=0 if bars else None,
            unexpected_gap_events=0 if bars else None,
            unexpected_missing_intervals=0 if bars else None,
            active_span_expected_intervals=len(bars) if bars else None,
            active_span_missing_intervals=0 if bars else None,
            active_span_missing_pct=0.0 if bars else None,
            max_gap_duration_s=0.0 if bars else None,
            max_unexpected_gap_duration_s=0.0 if bars else None,
            max_unexpected_missing_intervals=0 if bars else None,
            closure_policy=policy,
        )

    ordered = sorted(bars, key=lambda b: b.open_time)
    calendar_expected = max(
        1,
        int(round((ordered[-1].open_time - ordered[0].open_time).total_seconds() / cadence_s)) + 1,
    )
    gap_events = closure_events = 0
    closure_intervals_count = unexpected_events = unexpected_missing = 0
    max_gap_duration = max_unexpected_duration = 0.0
    max_unexpected_slots = 0

    for previous, following in pairwise(ordered):
        delta_s = (following.open_time - previous.open_time).total_seconds()
        if delta_s <= cadence_s:
            continue
        gap_events += 1
        missing_slots = max(0, int(round(delta_s / cadence_s)) - 1)
        gap_duration_s = max(0.0, delta_s - cadence_s)
        max_gap_duration = max(max_gap_duration, gap_duration_s)
        missing_start = previous.open_time + timedelta(seconds=cadence_s)
        is_closure = _is_weekend_closure(previous.open_time, following.open_time, delta_s, cadence_s)
        is_closure = is_closure or _overlaps_known_closure(missing_start, following.open_time, closure_intervals)
        if is_closure:
            closure_events += 1
            closure_intervals_count += missing_slots
        else:
            unexpected_events += 1
            unexpected_missing += missing_slots
            max_unexpected_duration = max(max_unexpected_duration, gap_duration_s)
            max_unexpected_slots = max(max_unexpected_slots, missing_slots)

    calendar_missing = max(0, calendar_expected - len(ordered))
    active_expected = len(ordered) + unexpected_missing
    return GapSemantics(
        cadence_seconds=cadence_s,
        cadence_basis=cadence_basis,
        observed_bars=len(ordered),
        gap_events=gap_events,
        calendar_span_expected_intervals=calendar_expected,
        calendar_span_missing_intervals=calendar_missing,
        calendar_span_missing_pct=round(calendar_missing / calendar_expected * 100, 2),
        closure_gap_events=closure_events,
        closure_intervals=closure_intervals_count,
        unexpected_gap_events=unexpected_events,
        unexpected_missing_intervals=unexpected_missing,
        active_span_expected_intervals=active_expected,
        active_span_missing_intervals=unexpected_missing,
        active_span_missing_pct=round(unexpected_missing / active_expected * 100, 2) if active_expected else 0.0,
        max_gap_duration_s=max_gap_duration,
        max_unexpected_gap_duration_s=max_unexpected_duration,
        max_unexpected_missing_intervals=max_unexpected_slots,
        closure_policy=policy,
    )


def _gap_quality_check(bars: list[Bar], timeframe: str | None = None) -> QualityCheck:
    stats = analyze_gap_semantics(bars, timeframe)
    if stats.unexpected_missing_intervals is None or stats.active_span_missing_pct is None:
        return QualityCheck("no_missing_bars", False, "gap semantics unavailable")
    passed = stats.active_span_missing_pct <= MAX_UNEXPECTED_MISSING_FRACTION * 100
    if passed:
        details = (
            f"{stats.unexpected_gap_events} unexpected gap events; "
            f"{stats.unexpected_missing_intervals} missing intervals "
            f"({stats.active_span_missing_pct:.2f}% of active expected span); "
            f"{stats.closure_gap_events} closure events excluded"
        )
    else:
        details = (
            f"{stats.unexpected_gap_events} unexpected gap events; "
            f"{stats.unexpected_missing_intervals} missing intervals "
            f"({stats.active_span_missing_pct:.2f}% of active expected span) exceeds "
            f"{MAX_UNEXPECTED_MISSING_FRACTION * 100:.2f}% limit; "
            f"{stats.closure_gap_events} recognized closure events excluded"
        )
    return QualityCheck("no_missing_bars", passed, details)


def validate_bars(bars: list[Bar], timeframe: str | None = None) -> DataQualityReport:
    checks: list[QualityCheck] = []
    if not bars:
        return DataQualityReport(passed=False, checks=[QualityCheck("non_empty", False, "no bars")])
    mono = all(bars[i].open_time < bars[i + 1].open_time for i in range(len(bars) - 1))
    checks.append(QualityCheck("monotonic_time", mono, "" if mono else "open_time not strictly increasing"))
    tz_ok = all(b.open_time.tzinfo is not None and b.close_time.tzinfo is not None for b in bars)
    checks.append(QualityCheck("tz_aware", tz_ok, "" if tz_ok else "naive timestamp"))
    from datetime import datetime

    now = datetime.now(UTC)
    no_future = all(b.close_time <= now for b in bars)
    checks.append(QualityCheck("no_future", no_future, "" if no_future else "future bar detected"))
    ohlc_ok = all(
        b.high >= b.low and b.high >= b.open and b.high >= b.close and b.low <= b.open and b.low <= b.close
        for b in bars
    )
    checks.append(
        QualityCheck("ohlc_invariants", ohlc_ok, "" if ohlc_ok else "high < low or open/close outside high-low")
    )
    price_ok = all(
        b.open > Decimal("0") and b.high > Decimal("0") and b.low > Decimal("0") and b.close > Decimal("0")
        for b in bars
    )
    checks.append(QualityCheck("positive_prices", price_ok, "" if price_ok else "price <=0"))
    abnormal = 0
    for b in bars:
        if b.close != Decimal("0") and float((b.high - b.low) / b.close) > 0.10:
            abnormal += 1
    spread_ok = abnormal <= len(bars) * 0.05
    checks.append(QualityCheck("abnormal_spreads", spread_ok, "" if spread_ok else f"{abnormal} bars >10% range"))
    seen = set()
    dup = False
    for b in bars:
        key = (b.instrument.symbol, b.open_time)
        if key in seen:
            dup = True
            break
        seen.add(key)
    checks.append(QualityCheck("no_duplicates", not dup, "duplicate open_time" if dup else ""))
    sym_ok = len({(b.instrument.symbol, b.instrument.venue) for b in bars}) == 1
    checks.append(QualityCheck("single_symbol", sym_ok, "" if sym_ok else "multiple symbols in one dataset"))
    checks.append(_gap_quality_check(bars, timeframe))
    session_ok = all(
        0 < (b.close_time - b.open_time).total_seconds() <= 86400 * 2
        for b in bars
    )
    checks.append(QualityCheck("session_boundaries", session_ok, "" if session_ok else "bar duration invalid"))
    stale_count = sum(
        1
        for i in range(1, len(bars))
        if bars[i].close == bars[i - 1].close and bars[i].volume == Decimal("0")
    )
    stale_ok = stale_count <= len(bars) * 0.1
    checks.append(
        QualityCheck(
            "no_broker_artifacts", stale_ok, f"{stale_count} stale zero-volume repeats" if not stale_ok else ""
        )
    )
    vol_ok = all(b.volume >= 0 for b in bars)
    checks.append(QualityCheck("volume_non_negative", vol_ok, "" if vol_ok else "negative volume"))
    return DataQualityReport(passed=all(c.passed for c in checks), checks=checks)


def dataset_missing_stats(
    bars: list[Bar],
    timeframe: str = "1H",
    *,
    closure_intervals: Iterable[tuple[datetime, datetime]] | None = None,
) -> dict[str, object]:
    """Return explicit calendar, closure, active-span and unexpected metrics."""
    if not bars:
        return {
            "status": "UNAVAILABLE",
            "reason": "no readable bars",
            "observed_bars": 0,
            "calendar_span_expected_intervals": None,
            "calendar_span_missing_intervals": None,
            "active_span_expected_intervals": None,
            "active_span_missing_intervals": None,
            "unexpected_gap_events": None,
        }
    stats = analyze_gap_semantics(bars, timeframe, closure_intervals=closure_intervals)
    result = stats.as_dict()
    result.update({"status": "MEASURED", "timezone": "UTC", "reason": None})
    return result
