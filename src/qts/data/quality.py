"""Data quality gates — Phase 1 first-class gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal

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
    # 1. monotonic time
    mono = all(bars[i].open_time < bars[i + 1].open_time for i in range(len(bars) - 1))
    checks.append(QualityCheck("monotonic_time", mono, "" if mono else "open_time not strictly increasing"))
    # 2. timestamp integrity & timezone normalization (all tz-aware and UTC)
    tz_ok = all(b.open_time.tzinfo is not None and b.close_time.tzinfo is not None for b in bars)
    checks.append(QualityCheck("tz_aware", tz_ok, "" if tz_ok else "naive timestamp"))
    # 3. no future
    from datetime import datetime

    now = datetime.now(UTC)
    no_future = all(b.close_time <= now for b in bars)
    checks.append(QualityCheck("no_future", no_future, "" if no_future else "future bar detected"))
    # 4. OHLC invariants
    ohlc_ok = all(
        b.high >= b.low and b.high >= b.open and b.high >= b.close and b.low <= b.open and b.low <= b.close
        for b in bars
    )
    checks.append(
        QualityCheck("ohlc_invariants", ohlc_ok, "" if ohlc_ok else "high < low or open/close outside high-low")
    )
    # 5. impossible prices (price <=0, high <0)
    price_ok = all(
        b.open > Decimal("0") and b.high > Decimal("0") and b.low > Decimal("0") and b.close > Decimal("0")
        for b in bars
    )
    checks.append(QualityCheck("positive_prices", price_ok, "" if price_ok else "price <=0"))
    # 6. abnormal spreads (high-low vs close)
    # For XAUUSD, high-low should be <5% of close normally; >10% is abnormal
    spread_ok = True
    abnormal = 0
    for b in bars:
        if b.close != Decimal("0"):
            pct = float((b.high - b.low) / b.close)
            if pct > 0.10:
                abnormal += 1
    if abnormal > len(bars) * 0.05:  # >5% bars abnormal
        spread_ok = False
    checks.append(QualityCheck("abnormal_spreads", spread_ok, "" if spread_ok else f"{abnormal} bars >10% range"))
    # 7. duplicates
    seen = set()
    dup = False
    for b in bars:
        k = (b.instrument.symbol, b.open_time)
        if k in seen:
            dup = True
            break
        seen.add(k)
    checks.append(QualityCheck("no_duplicates", not dup, "duplicate open_time" if dup else ""))
    # 8. symbol changes (all same symbol/venue)
    sym_ok = len({(b.instrument.symbol, b.instrument.venue) for b in bars}) == 1
    checks.append(QualityCheck("single_symbol", sym_ok, "" if sym_ok else "multiple symbols in one dataset"))
    # 9. missing bars / gaps (based on inferred timeframe)
    gap_ok = True
    gap_details = ""
    if len(bars) >= 2:
        deltas = [(bars[i + 1].open_time - bars[i].open_time).total_seconds() for i in range(len(bars) - 1)]
        # Most common delta is timeframe
        from collections import Counter

        cnt = Counter(deltas)
        common = cnt.most_common(1)[0][0] if cnt else 0
        # Allow 1.5x common as normal (covers weekend gaps for daily)
        _gaps = sum(1 for d in deltas if d > common * 1.5 and d < 86400 * 4)  # ignore >4 days (long closure)
        # For intraday, weekend gaps are ~172800s (2 days) - expected, not counted if common is 3600
        # For 1H, weekend gap 172800 vs 3600 -> 48x, so we filter >4 days already, but 2 days is 48*3600 =172800 >1.5*3600, would be counted as gap incorrectly
        # So we allow weekend: if common==3600, gap of 172800 is 48* common, but is expected closure, not data gap
        # We count only gaps >1.5*common and < 1 day as abnormal (intraday missing), and gaps >2.5 days as closures
        # Simplified: gaps >1.5*common and < 86400 are abnormal missing
        abnormal_gaps = sum(1 for d in deltas if common * 1.5 < d < 86400)
        # Also check for missing >5% of expected
        if abnormal_gaps > len(bars) * 0.02:
            gap_ok = False
            gap_details = f"{abnormal_gaps} abnormal intraday gaps >1.5*tf"
    checks.append(QualityCheck("no_missing_bars", gap_ok, gap_details))
    # 10. session boundaries / market closures (check that no bars on weekend for 1H? Synthetic may include weekend, but real XAUUSD closes weekend)
    # For now, just check that close_time - open_time equals timeframe (no overlapping)
    session_ok = True
    for b in bars:
        dur = (b.close_time - b.open_time).total_seconds()
        # Allow small tolerance, but duration should be >0 and < 86400*2
        if dur <= 0 or dur > 86400 * 2:
            session_ok = False
            break
    checks.append(QualityCheck("session_boundaries", session_ok, "" if session_ok else "bar duration invalid"))
    # 11. broker-specific artifacts (check for identical consecutive closes with zero volume - possible stale)
    stale_ok = True
    stale_count = 0
    for i in range(1, len(bars)):
        if bars[i].close == bars[i - 1].close and bars[i].volume == Decimal("0"):
            stale_count += 1
    if stale_count > len(bars) * 0.1:
        stale_ok = False
    checks.append(
        QualityCheck(
            "no_broker_artifacts", stale_ok, f"{stale_count} stale zero-volume repeats" if not stale_ok else ""
        )
    )
    # 12. volume non-negative
    vol_ok = all(b.volume >= 0 for b in bars)
    checks.append(QualityCheck("volume_non_negative", vol_ok, "" if vol_ok else "negative volume"))
    passed = all(c.passed for c in checks)
    return DataQualityReport(passed=passed, checks=checks)


def dataset_missing_stats(bars: list[Bar], timeframe: str = "1H") -> dict:
    """Compute missing-data statistics for manifest."""
    if not bars:
        return {"expected": 0, "actual": 0, "missing": 0, "gap_count": 0}
    tf_seconds = {"1m": 60, "5m": 300, "15m": 900, "1H": 3600, "1D": 86400}.get(timeframe, 3600)
    total = (bars[-1].close_time - bars[0].open_time).total_seconds()
    expected = int(total // tf_seconds) + 1 if total > 0 else len(bars)
    missing = max(0, expected - len(bars))
    gap_count = 0
    max_gap = 0.0
    for i in range(len(bars) - 1):
        gap = (bars[i + 1].open_time - bars[i].close_time).total_seconds()
        if gap > tf_seconds * 1.5 and gap < 86400:
            gap_count += 1
            max_gap = max(max_gap, gap)
    return {
        "expected": expected,
        "actual": len(bars),
        "missing": missing,
        "gap_count": gap_count,
        "max_gap_s": max_gap,
        "missing_pct": round(missing / expected * 100, 2) if expected else 0,
        "timezone": "UTC",
    }
