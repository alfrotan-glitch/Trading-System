"""Adversarial lookahead tests for the impulse research layer.

These tests try to BREAK causality:

1. Prefix equivalence — a detector run on ``bars[:i+1]`` must agree with the
   direction recorded for index ``i`` by the full-series event scan.
2. Future corruption — arbitrarily mutating every bar AFTER index ``i`` must
   not change any detection at index <= i.
3. Measurement locality — mutating bars beyond the measurement window must not
   change the EventMeasurement for an event.
4. Locked-partition isolation — events detected inside the locked partition
   are discarded and never measured.
5. Warmup enforcement — no event is ever reported before WARMUP_BARS.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from qts.data.synthetic import generate_gbm_bars
from qts.domain.value_objects import Bar, Instrument
from qts.research.impulse.analysis import ImpulseResearchConfig, run_impulse_analysis
from qts.research.impulse.definitions import (
    PRE_REGISTERED_FAMILIES,
    WARMUP_BARS,
    detect_events,
)
from qts.research.impulse.measurement import MeasurementParams, measure_event

INSTR = Instrument(symbol="XAUUSD")


def _gbm(n: int = 400, seed: int = 11) -> list[Bar]:
    return generate_gbm_bars(instrument=INSTR, periods=n, timeframe_minutes=60, seed=seed)


def _corrupt_after(bars: list[Bar], i: int, seed: int = 99) -> list[Bar]:
    """Replace every bar after index i with wildly different (valid) bars."""
    rng = np.random.default_rng(seed)
    out = list(bars[: i + 1])
    last_close = float(bars[i].close)
    p = last_close * 1.5  # jump 50% — maximally different future
    for j in range(i + 1, len(bars)):
        p *= 1 + float(rng.normal(0, 0.02))
        hi, lo = p * 1.03, p * 0.97
        out.append(
            Bar(
                instrument=bars[j].instrument,
                open=Decimal(str(round(p * 0.99, 2))),
                high=Decimal(str(round(hi, 2))),
                low=Decimal(str(round(lo, 2))),
                close=Decimal(str(round(p, 2))),
                open_time=bars[j].open_time,
                close_time=bars[j].close_time,
            )
        )
    return out


def _vol_burst(bars: list[Bar], burst_len: int = 7) -> list[Bar]:
    """Calm bars with one short, sharp volatility episode near the end.

    ``detect_vol_expansion`` compares the last ``short_win`` (6) returns with
    the ``long_win`` (18) immediately before them, so only a BRIEF episode
    moves the ratio: a gradual regime change fills both windows and the
    quotient stays near 1. Plain GBM is homoscedastic, which is why IMP-VE-V
    (k=3.0) produced no events at all and its causality went unverified while
    the suite stayed green.

    The episode is a fixed zig-zag with upward drift and no RNG, sized well
    above the generator's own ~1.4% per-bar deviation so the ratio clears
    k=3.0 by a wide margin: it fires on every seed both callers use, rather
    than on the lucky ones.
    """
    steps = [0.10, -0.07, 0.10, -0.07, 0.10, -0.07, 0.10][:burst_len]
    start = len(bars) - burst_len - 4
    out = list(bars[:start])
    price = float(bars[start - 1].close)
    for offset, index in enumerate(range(start, len(bars))):
        step = steps[offset] if offset < len(steps) else 0.0005
        price *= 1 + step
        half = abs(step)
        out.append(
            Bar(
                instrument=bars[index].instrument,
                open=Decimal(str(round(price * (1 - half / 3), 2))),
                high=Decimal(str(round(price * (1 + half), 2))),
                low=Decimal(str(round(price * (1 - half), 2))),
                close=Decimal(str(round(price, 2))),
                open_time=bars[index].open_time,
                close_time=bars[index].close_time,
            )
        )
    return out


def _bars_with_events(fam, seeds: range, n: int) -> tuple[list[Bar], list[tuple[int, str]]]:
    """Find a deterministic series this family actually fires on.

    A pre-registered family that produces no events cannot have its causality
    checked, and skipping says nothing while looking green — so this fails
    instead. Both fixtures are tried before giving up.
    """
    for build in (lambda s: _gbm(n, seed=s), lambda s: _vol_burst(_gbm(n, seed=s))):
        for seed in seeds:
            bars = build(seed)
            events = detect_events(bars, fam)
            if events:
                return bars, events
    pytest.fail(
        f"{fam.family_id}: no events under either fixture across seeds "
        f"{seeds.start}..{seeds.stop - 1}, so prefix equivalence and future "
        f"corruption cannot be exercised for it. Supply a series this family "
        f"fires on rather than leaving its causality unverified."
    )


class TestPrefixEquivalence:
    @pytest.mark.parametrize("fam", PRE_REGISTERED_FAMILIES, ids=lambda f: f.family_id)
    def test_full_scan_matches_prefix_detection(self, fam):
        bars, events = _bars_with_events(fam, range(5, 15), 400)
        for i, direction in events[:10]:
            from qts.research.impulse.definitions import _DETECTORS

            det = _DETECTORS[fam.definition]
            assert det(bars[: i + 1], **fam.params) == direction


class TestFutureCorruption:
    @pytest.mark.parametrize("fam", PRE_REGISTERED_FAMILIES, ids=lambda f: f.family_id)
    def test_mutating_future_bars_cannot_change_past_detections(self, fam):
        bars, events = _bars_with_events(fam, range(7, 17), 360)
        cut = events[0][0]  # first event index
        corrupted = _corrupt_after(bars, cut)
        events_corrupt = detect_events(corrupted, fam)
        # every event at index <= cut must be identical
        assert [(i, d) for i, d in events if i <= cut] == [(i, d) for i, d in events_corrupt if i <= cut]

    def test_warmup_never_violated(self):
        bars = _gbm(300, seed=3)
        for fam in PRE_REGISTERED_FAMILIES:
            for i, _d in detect_events(bars, fam):
                assert i >= WARMUP_BARS


class TestMeasurementLocality:
    def test_mutating_bars_beyond_window_changes_nothing(self):
        bars = _gbm(200, seed=13)
        i = WARMUP_BARS + 5
        horizon, latency = 12, 1
        params = MeasurementParams(horizon_bars=horizon, latency_bars=latency, atr_window=14)
        m1 = measure_event(bars, i, "LONG", "F", params, 3.4)
        # corrupt everything strictly beyond the measurement window
        beyond = i + latency + horizon
        corrupted = _corrupt_after(bars, beyond)
        m2 = measure_event(corrupted, i, "LONG", "F", params, 3.4)
        assert m1 == m2

    def test_detection_times_are_bar_close_times(self):
        bars = _gbm(200, seed=17)
        fam = PRE_REGISTERED_FAMILIES[0]
        for i, _d in detect_events(bars, fam)[:5]:
            params = MeasurementParams(horizon_bars=12, latency_bars=1, atr_window=14)
            m = measure_event(bars, i, _d, fam.family_id, params, 3.4)
            if m.decision_state == "DETECTED_MEASURED":
                assert m.detection_time == bars[i].close_time


class TestLockedPartitionIsolation:
    def test_locked_events_discarded_and_never_measured(self, tmp_path):
        bars = _gbm(400, seed=21)
        n = len(bars)
        cfg = ImpulseResearchConfig(seed=42, n_boot=200)
        res = run_impulse_analysis(
            bars,
            data_version="TEST-LOCKED",
            provenance={"source_label": "synthetic:test"},
            cfg=cfg,
            ledger_db_path=None,
            data_root_db_path=tmp_path / "part.db",
        )
        assert res.locked_untouched is True
        v_end = res.split_boundaries["validation_end"]
        assert v_end < n
        # no recorded event may come from the locked region
        for r in res.results:
            for ev in r.events:
                assert ev["detection_index"] < v_end
                assert ev["split"] != "locked"
        assert res.totals["events_locked_discarded"] >= 0


class TestNoFabricationOnShortSeries:
    def test_short_series_raises_instead_of_inventing_events(self, tmp_path):
        bars = _gbm(75, seed=23)
        with pytest.raises(ValueError, match="too short"):
            run_impulse_analysis(
                bars,
                data_version="TEST-SHORT",
                provenance={},
                cfg=ImpulseResearchConfig(),
                data_root_db_path=tmp_path / "part.db",
            )
