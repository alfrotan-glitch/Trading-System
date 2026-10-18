"""Read-only indicator snapshot contract for the frozen DEMO trend provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.research.demo_trend_snapshot import completed_bar_snapshot
from qts.research.demo_trend_tsmom import DEFAULT_PARAMS

T0 = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def test_seeded_latest_bar_cross_is_descriptive_only():
    bars = [(T0 + STEP * i, Decimal("100")) for i in range(48)]
    bars.append((T0 + STEP * 48, Decimal("120")))

    snapshot = completed_bar_snapshot(DEFAULT_PARAMS, bars, source="unit-test")

    assert snapshot["status"] == "AVAILABLE"
    assert snapshot["trend_state"] == "BULLISH"
    assert snapshot["latest_completed_cross"] == "BUY"
    assert snapshot["actionable_signal"] is False
    assert snapshot["last_completed_bar"] == bars[-1][0].isoformat()
    assert "not emitted" in snapshot["note"]


def test_incomplete_history_is_warming_up_and_indicator_values_stay_unavailable():
    bars = [(T0 + STEP * i, Decimal("100")) for i in range(12)]

    snapshot = completed_bar_snapshot(DEFAULT_PARAMS, bars, source="unit-test-short")

    assert snapshot["status"] == "WARMING_UP"
    assert snapshot["completed_bars"] == 12
    assert snapshot["required_bars"] == 49
    assert snapshot["trend_state"] == "UNAVAILABLE"
    assert snapshot["latest_completed_cross"] == "UNAVAILABLE"
    assert snapshot["fast_ema"] is None
    assert snapshot["slow_ema"] is None
    assert snapshot["actionable_signal"] is False


def test_invalid_history_is_refused_as_a_whole():
    unaligned = T0 + timedelta(minutes=1)

    snapshot = completed_bar_snapshot(DEFAULT_PARAMS, [(unaligned, Decimal("100"))], source="unit-test-bad")

    assert snapshot["status"] == "UNAVAILABLE"
    assert snapshot["trend_state"] == "UNAVAILABLE"
    assert snapshot["actionable_signal"] is False
    assert "not aligned" in snapshot["reason"]
