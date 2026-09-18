"""Tests for the data-adequacy gate — reject insufficient/synthetic/stale data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.domain.value_objects import Bar, Instrument
from qts.research.impulse.adequacy import (
    MIN_BARS_REAL_CLAIMS,
    MIN_EVENTS_FOR_INFERENCE,
    MIN_EVENTS_PER_SIDE,
    assess_data_adequacy,
)

INSTR = Instrument(symbol="XAUUSD")
T0 = datetime(2020, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 16, tzinfo=UTC)


def mkbar(i: int, base: datetime = T0) -> Bar:
    return Bar(
        instrument=INSTR,
        open=Decimal("2000"),
        high=Decimal("2001"),
        low=Decimal("1999"),
        close=Decimal("2000"),
        open_time=base + timedelta(hours=i),
        close_time=base + timedelta(hours=i + 1),
    )


def mkbar_min(i: int, base: datetime = T0) -> Bar:
    return Bar(
        instrument=INSTR,
        open=Decimal("2000"),
        high=Decimal("2001"),
        low=Decimal("1999"),
        close=Decimal("2000"),
        open_time=base + timedelta(minutes=i),
        close_time=base + timedelta(minutes=i + 1),
    )


def _check(report, rid: str):
    return next(c for c in report.checks if c.requirement_id == rid)


class TestAdequacyGate:
    def test_synthetic_source_blocks(self):
        bars = [mkbar(i) for i in range(100)]
        r = assess_data_adequacy(bars, "v1", "SYNTHETIC:fixture:x", now=NOW)
        assert r.data_class == "SYNTHETIC"
        assert not _check(r, "R1-REAL-PROVENANCE").passed
        assert not r.adequate_for_real_claims

    def test_unlabeled_source_treated_as_synthetic(self):
        bars = [mkbar(i) for i in range(100)]
        r = assess_data_adequacy(bars, "v1", None, now=NOW)
        assert r.data_class == "SYNTHETIC"
        assert not r.adequate_for_real_claims

    def test_insufficient_depth_blocks(self):
        bars = [mkbar(i) for i in range(500)]
        r = assess_data_adequacy(bars, "v1", "real_exchange_history_export", now=NOW)
        assert r.data_class == "REAL"
        assert not _check(r, "R2-DEPTH").passed
        assert not r.adequate_for_real_claims

    def test_insufficient_span_blocks(self):
        # enough minute bars for the count requirement, but span < 180 days
        base = NOW - timedelta(days=2)
        bars = [mkbar_min(i, base=base) for i in range(MIN_BARS_REAL_CLAIMS)]
        r = assess_data_adequacy(bars, "v1", "real_exchange_history_export", now=NOW)
        assert not _check(r, "R3-REGIME-COVERAGE").passed
        assert not r.adequate_for_real_claims

    def test_stale_data_blocks(self):
        # hourly bars ending 2020, assessed in 2026
        bars = [mkbar(i) for i in range(MIN_BARS_REAL_CLAIMS)]
        r = assess_data_adequacy(bars, "v1", "real_exchange_history_export", now=NOW)
        assert not _check(r, "R4-FRESHNESS").passed
        assert not r.adequate_for_real_claims

    def test_insufficient_events_blocks(self):
        base = NOW - timedelta(hours=MIN_BARS_REAL_CLAIMS + 10)
        bars = [mkbar(i, base=base) for i in range(MIN_BARS_REAL_CLAIMS)]
        r = assess_data_adequacy(
            bars,
            "v1",
            "real_exchange_history_export",
            now=NOW,
            measured_events_total=10,
            measured_events_long=5,
            measured_events_short=5,
        )
        assert not _check(r, "R6-EVENT-SUFFICIENCY").passed
        assert not r.adequate_for_real_claims

    def test_one_sided_events_block(self):
        base = NOW - timedelta(hours=MIN_BARS_REAL_CLAIMS + 10)
        bars = [mkbar(i, base=base) for i in range(MIN_BARS_REAL_CLAIMS)]
        r = assess_data_adequacy(
            bars,
            "v1",
            "real_exchange_history_export",
            now=NOW,
            measured_events_total=MIN_EVENTS_FOR_INFERENCE,
            measured_events_long=MIN_EVENTS_FOR_INFERENCE,
            measured_events_short=0,
        )
        assert not _check(r, "R6-EVENT-SUFFICIENCY").passed

    def test_fully_adequate_real_dataset_passes(self):
        base = NOW - timedelta(hours=MIN_BARS_REAL_CLAIMS + 10)
        bars = [mkbar(i, base=base) for i in range(MIN_BARS_REAL_CLAIMS)]
        r = assess_data_adequacy(
            bars,
            "v1",
            "real_exchange_history_export",
            now=NOW,
            measured_events_total=MIN_EVENTS_FOR_INFERENCE,
            measured_events_long=MIN_EVENTS_PER_SIDE + 20,
            measured_events_short=MIN_EVENTS_PER_SIDE + 20,
        )
        assert r.adequate_for_real_claims
        # R5 (execution data) must still be REPORTED as unmet-but-non-blocking
        r5 = _check(r, "R5-EXECUTION-DATA")
        assert not r5.passed
        assert not r5.blocking_for_real_claims

    def test_report_lists_minimum_requirements_explicitly(self):
        bars = [mkbar(i) for i in range(50)]
        r = assess_data_adequacy(bars, "v1", "fixture", now=NOW)
        d = r.as_dict()
        assert d["adequate_for_real_claims"] is False
        for c in d["checks"]:
            assert c["minimum"]  # every requirement states its minimum
            assert c["observed"]  # and what was actually observed
        unmet = r.unmet_requirements
        assert any(c.requirement_id == "R1-REAL-PROVENANCE" for c in unmet)
        assert any(c.requirement_id == "R2-DEPTH" for c in unmet)
