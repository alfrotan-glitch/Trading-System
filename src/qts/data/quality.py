"""Data quality gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from qts.domain.value_objects import Bar


@dataclass
class QualityCheck:
    name: str
    passed: bool
    details: str = ""


@dataclass
class DataQualityReport:
    passed: bool
    checks: list[QualityCheck]


def validate_bars(bars: list[Bar]) -> DataQualityReport:
    checks: list[QualityCheck] = []
    if not bars:
        return DataQualityReport(passed=False, checks=[QualityCheck("non_empty", False, "no bars")])
    # monotonic
    mono = all(bars[i].open_time < bars[i + 1].open_time for i in range(len(bars) - 1))
    checks.append(QualityCheck("monotonic_time", mono, "" if mono else "open_time not strictly increasing"))
    # no future (check close_time <= now UTC)
    from datetime import datetime

    now = datetime.now(UTC)
    no_future = all(b.close_time <= now for b in bars)
    checks.append(QualityCheck("no_future", no_future, "" if no_future else "future bar detected"))
    # OHLC invariants (redundant with Bar validator but check again)
    ohlc_ok = all(
        b.high >= b.low and b.high >= b.open and b.high >= b.close and b.low <= b.open and b.low <= b.close
        for b in bars
    )
    checks.append(QualityCheck("ohlc_invariants", ohlc_ok))
    # duplicates
    seen = set()
    dup = False
    for b in bars:
        k = (b.instrument.symbol, b.open_time)
        if k in seen:
            dup = True
            break
        seen.add(k)
    checks.append(QualityCheck("no_duplicates", not dup, "duplicate open_time" if dup else ""))
    # tz-aware
    tz_ok = all(b.open_time.tzinfo is not None for b in bars)
    checks.append(QualityCheck("tz_aware", tz_ok))
    # volume >=0
    vol_ok = all(b.volume >= 0 for b in bars)
    checks.append(QualityCheck("volume_non_negative", vol_ok))
    passed = all(c.passed for c in checks)
    return DataQualityReport(passed=passed, checks=checks)
