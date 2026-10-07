"""Property-based tests for impulse research invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from qts.domain.value_objects import Bar, Instrument
from qts.research.impulse.definitions import (
    _DETECTORS,
    PRE_REGISTERED_FAMILIES,
    WARMUP_BARS,
    detect_events,
)
from qts.research.impulse.measurement import MeasurementParams, measure_event

INSTR = Instrument(symbol="XAUUSD")
T0 = datetime(2020, 1, 1, tzinfo=UTC)


@st.composite
def bar_series(draw, min_size: int = 90, max_size: int = 140):
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    p = draw(st.floats(min_value=500.0, max_value=3000.0))
    sigma = draw(st.floats(min_value=0.0005, max_value=0.02))
    bars = []
    for i in range(n):
        step = draw(st.floats(min_value=-3.0, max_value=3.0)) * sigma * p
        o = p
        c = max(1.0, p + step)
        body_hi, body_lo = max(o, c), min(o, c)
        wick = abs(draw(st.floats(min_value=0.0, max_value=1.0))) * sigma * p
        h = body_hi + wick
        low = max(0.5, body_lo - wick)
        bars.append(
            Bar(
                instrument=INSTR,
                open=Decimal(str(round(o, 2))),
                high=Decimal(str(round(h, 2))),
                low=Decimal(str(round(low, 2))),
                close=Decimal(str(round(c, 2))),
                open_time=T0 + timedelta(hours=i),
                close_time=T0 + timedelta(hours=i + 1),
            )
        )
        p = c
    return bars


@settings(max_examples=15, deadline=None)
@given(bars=bar_series())
def test_events_agree_with_prefix_detection(bars):
    """Every reported event equals the detector's answer on bars[:i+1] —
    detections are reproducible from causally available information only."""
    for fam in PRE_REGISTERED_FAMILIES[:4]:  # keep runtime bounded; unit tests cover all
        det = _DETECTORS[fam.definition]
        for i, d in detect_events(bars, fam):
            assert i >= WARMUP_BARS
            assert det(bars[: i + 1], **fam.params) == d


@settings(max_examples=15, deadline=None)
@given(bars=bar_series(min_size=110))
def test_mfe_monotone_in_horizon(bars):
    """A longer measurement window can never DECREASE the maximum favorable
    excursion (it observes a superset of the path)."""
    i = WARMUP_BARS + 2
    if len(bars) <= i + 20:
        return
    p1 = MeasurementParams(horizon_bars=6, latency_bars=1, atr_window=14)
    p2 = MeasurementParams(horizon_bars=12, latency_bars=1, atr_window=14)
    m1 = measure_event(bars, i, "LONG", "F", p1, 3.4)
    m2 = measure_event(bars, i, "LONG", "F", p2, 3.4)
    if m1.decision_state == "DETECTED_MEASURED" and m2.decision_state == "DETECTED_MEASURED":
        assert m2.mfe_bps >= m1.mfe_bps - 1e-9


@settings(max_examples=15, deadline=None)
@given(bars=bar_series(min_size=110), cost=st.floats(min_value=0.0, max_value=50.0))
def test_net_equals_gross_minus_declared_cost(bars, cost):
    """Net expectancy is always gross minus the DECLARED round-turn cost —
    no hidden adjustments anywhere in the measurement path."""
    i = WARMUP_BARS + 2
    if len(bars) <= i + 20:
        return
    p = MeasurementParams(horizon_bars=12, latency_bars=1, atr_window=14)
    m = measure_event(bars, i, "SHORT", "F", p, cost)
    if m.decision_state == "DETECTED_MEASURED":
        assert abs((m.net_return_bps or 0) - ((m.horizon_return_bps or 0) - cost)) < 1e-6
