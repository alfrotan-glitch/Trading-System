"""Unit tests for post-event path measurement (independent of detection)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.domain.value_objects import Bar, Instrument
from qts.research.impulse.costs import BASE_COSTS, CostAssumptions
from qts.research.impulse.measurement import (
    EventExclusion,
    MeasurementParams,
    RaceOutcome,
    atr_at,
    causal_vol_regime_labels,
    measure_event,
)

INSTR = Instrument(symbol="XAUUSD")
T0 = datetime(2020, 1, 1, tzinfo=UTC)
COST = 3.4  # bps round turn for arithmetic checks


def mkbar(i: int, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(
        instrument=INSTR,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(lo)),
        close=Decimal(str(c)),
        open_time=T0 + timedelta(hours=i),
        close_time=T0 + timedelta(hours=i + 1),
    )


def flat(n: int, price: float = 2000.0, start: int = 0, band: float = 0.5) -> list[Bar]:
    return [mkbar(start + i, price, price + band, price - band, price) for i in range(n)]


PARAMS = MeasurementParams(
    horizon_bars=5, latency_bars=1, atr_window=3, target_atr_multiple=1.0, adverse_atr_multiple=1.0
)


class TestATR:
    def test_atr_uses_only_bars_up_to_i(self):
        bars = flat(10, band=0.5)  # TR = 1.0 for all
        assert atr_at(bars, 5, window=3) == pytest.approx(1.0)
        # corrupting bars AFTER i must not change atr_at(i)
        bars2 = list(bars)
        bars2[6] = mkbar(6, 2000.0, 3000.0, 1000.0, 2500.0)
        assert atr_at(bars2, 5, window=3) == pytest.approx(1.0)

    def test_atr_none_before_warmup(self):
        bars = flat(5)
        assert atr_at(bars, 1, window=3) is None


class TestMeasureEventLong:
    """Detection index 3 (ATR warmup satisfied); latency 1 -> entry bar 4; horizon 5 -> path bars 5..9."""

    def _base(self) -> list[Bar]:
        # bars 0..3 quiet (TR=1.0 -> ATR=1.0 at i=3); bar 4 = entry close 2000.0
        bars = flat(4, price=2000.0, band=0.5)
        bars.append(mkbar(4, 2000.0, 2000.2, 1999.9, 2000.0))
        return bars

    def test_full_race_target(self):
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2000.3, 1999.9, 2000.1))  # step1: fav 0.3 < 1.0
        bars.append(mkbar(6, 2000.1, 2001.4, 2000.0, 2001.2))  # step2: fav 1.4 >= target
        bars.extend(flat(3, price=2001.2, start=7))
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.decision_state == "DETECTED_MEASURED"
        assert m.race_outcome == RaceOutcome.TARGET
        assert m.time_to_target_bars == 2
        assert m.time_to_adverse_bars is None
        assert m.duration_bars == 2
        assert m.target_hit is True and m.adverse_hit is False
        assert m.mfe_bps > 0
        assert m.entry_index == 4
        assert m.entry_price == pytest.approx(2000.0)
        assert m.detection_time == bars[3].close_time

    def test_adverse_hit_first(self):
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2000.2, 1998.5, 1998.8))  # adv 1.5 >= 1.0
        bars.extend(flat(4, price=1998.8, start=6))
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.race_outcome == RaceOutcome.ADVERSE
        assert m.time_to_adverse_bars == 1
        assert m.duration_bars == 1
        assert m.mae_bps >= m.adverse_bps

    def test_same_bar_ambiguity_resolves_adverse(self):
        """Both thresholds touched in one bar -> ADVERSE (conservative; intra-bar
        ordering is unknown from OHLC and must never be assumed favorable)."""
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2001.5, 1998.5, 2000.0))  # touches both
        bars.extend(flat(4, price=2000.0, start=6))
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.race_outcome == RaceOutcome.ADVERSE

    def test_neither_within_horizon(self):
        bars = self._base()
        bars.extend(flat(5, price=2000.0, start=5, band=0.2))  # fav/adv 0.2 < 1.0
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.race_outcome == RaceOutcome.NEITHER
        assert m.duration_bars == PARAMS.horizon_bars
        assert m.time_to_target_bars is None
        assert m.time_to_adverse_bars is None

    def test_horizon_return_and_net_arithmetic(self):
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2000.3, 1999.9, 2000.0))
        bars.append(mkbar(6, 2000.0, 2000.3, 1999.9, 2000.0))
        bars.append(mkbar(7, 2000.0, 2000.3, 1999.9, 2000.0))
        bars.append(mkbar(8, 2000.0, 2000.3, 1999.9, 2000.0))
        bars.append(mkbar(9, 2000.0, 2004.0, 1999.9, 2003.0))  # horizon exit close +3.0
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.horizon_return_bps == pytest.approx(15.0, abs=1e-6)
        assert m.net_return_bps == pytest.approx(15.0 - COST, abs=1e-6)
        assert m.continuation is True and m.reversal is False

    def test_excluded_when_insufficient_forward_bars(self):
        bars = self._base()
        bars.extend(flat(3, start=5))  # only 8 bars; path_end=9 out of range
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.decision_state == "DETECTED_EXCLUDED"
        assert m.exclusion == EventExclusion.INSUFFICIENT_FORWARD_BARS
        assert m.horizon_return_bps is None
        assert m.entry_price is None

    def test_excluded_when_atr_unavailable(self):
        """ATR warmup not satisfied -> fail closed by exclusion, never invent a threshold."""
        bars = flat(10)
        m = measure_event(bars, 0, "LONG", "F", PARAMS, COST)
        assert m.decision_state == "DETECTED_EXCLUDED"

    def test_latency_shifts_entry(self):
        bars = flat(4, price=2000.0, band=0.5)
        bars.append(mkbar(4, 2000.0, 2000.2, 1999.9, 2000.0))
        bars.append(mkbar(5, 2000.0, 2001.0, 1999.9, 2001.0))  # entry @ latency 2
        bars.extend(flat(5, price=2001.0, start=6))
        p2 = MeasurementParams(horizon_bars=5, latency_bars=2, atr_window=3)
        m = measure_event(bars, 3, "LONG", "F", p2, COST)
        assert m.entry_index == 5
        assert m.entry_price == pytest.approx(2001.0)

    def test_exact_boundary_is_measurable(self):
        bars = self._base()
        bars.extend(flat(PARAMS.horizon_bars, start=5))  # last index == entry+horizon
        m = measure_event(bars, 3, "LONG", "F", PARAMS, COST)
        assert m.decision_state == "DETECTED_MEASURED"


class TestMeasureEventShort:
    def _base(self) -> list[Bar]:
        bars = flat(4, price=2000.0, band=0.5)
        bars.append(mkbar(4, 2000.0, 2000.2, 1999.9, 2000.0))
        return bars

    def test_short_target(self):
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2000.1, 1998.6, 1998.8))  # fav for SHORT = 1.4
        bars.extend(flat(4, price=1998.8, start=6))
        m = measure_event(bars, 3, "SHORT", "F", PARAMS, COST)
        assert m.race_outcome == RaceOutcome.TARGET
        assert m.time_to_target_bars == 1

    def test_short_adverse_on_rally(self):
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2001.6, 1999.9, 2001.4))
        bars.extend(flat(4, price=2001.4, start=6))
        m = measure_event(bars, 3, "SHORT", "F", PARAMS, COST)
        assert m.race_outcome == RaceOutcome.ADVERSE

    def test_short_horizon_return_sign(self):
        bars = self._base()
        bars.append(mkbar(5, 2000.0, 2000.2, 1998.9, 1999.0))
        bars.append(mkbar(6, 1999.0, 1999.2, 1998.9, 1999.0))
        bars.append(mkbar(7, 1999.0, 1999.2, 1998.9, 1999.0))
        bars.append(mkbar(8, 1999.0, 1999.2, 1998.9, 1999.0))
        bars.append(mkbar(9, 1999.0, 1999.2, 1996.9, 1997.0))  # exit -3.0 -> SHORT +15bps
        m = measure_event(bars, 3, "SHORT", "F", PARAMS, COST)
        assert m.horizon_return_bps == pytest.approx(15.0, abs=1e-6)

    def test_invalid_direction_raises(self):
        bars = flat(10)
        with pytest.raises(ValueError):
            measure_event(bars, 0, "SIDEWAYS", "F", PARAMS, COST)


class TestRegimeLabels:
    def test_warmup_is_unknown(self):
        bars = flat(50)
        labels = causal_vol_regime_labels(bars, window=5, min_history=20)
        assert all(x == "UNKNOWN" for x in labels[:20])

    def test_labels_within_vocabulary(self):
        import numpy as np

        rng = np.random.default_rng(7)
        p = 2000.0
        bars = []
        for i in range(300):
            p *= 1 + float(rng.normal(0, 0.001 if i < 150 else 0.004))
            bars.append(mkbar(i, p, p * 1.001, p * 0.999, p))
        labels = causal_vol_regime_labels(bars, window=12, min_history=48)
        assert set(labels) <= {"LOW", "MID", "HIGH", "UNKNOWN"}
        # the high-vol second half must produce HIGH labels somewhere after warmup
        assert "HIGH" in labels[150:]


class TestCostModel:
    def test_round_turn_arithmetic(self):
        c = CostAssumptions(spread_bps=2.0, commission_bps_round_turn=0.4, slippage_bps_per_side=0.5)
        assert c.round_turn_cost_bps() == pytest.approx(3.4)
        assert c.net_bps(10.0) == pytest.approx(6.6)

    def test_multiplier_monotonicity(self):
        c = BASE_COSTS
        seq = [c.with_cost_multiplier(m).round_turn_cost_bps() for m in (0.5, 1.0, 1.5, 2.0)]
        assert seq == sorted(seq)
        assert seq[0] < seq[-1]

    def test_spread_multiplier_only_moves_spread(self):
        c = BASE_COSTS.with_spread_multiplier(2.0)
        assert c.spread_bps == pytest.approx(BASE_COSTS.spread_bps * 2)
        assert c.commission_bps_round_turn == BASE_COSTS.commission_bps_round_turn
        assert c.slippage_bps_per_side == BASE_COSTS.slippage_bps_per_side

    def test_latency_validation(self):
        with pytest.raises(ValueError):
            BASE_COSTS.with_latency(-1)
        with pytest.raises(ValueError):
            BASE_COSTS.with_cost_multiplier(0)

    def test_provenance_label_is_estimate(self):
        assert BASE_COSTS.provenance.startswith("ESTIMATED")
        assert BASE_COSTS.as_dict()["provenance"] == BASE_COSTS.provenance
