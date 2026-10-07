"""Unit tests for pre-registered causal impulse detectors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.domain.value_objects import Bar, Instrument
from qts.research.impulse.definitions import (
    LONG,
    PRE_REGISTERED_FAMILIES,
    PRIMARY_HORIZON_BARS,
    SHORT,
    WARMUP_BARS,
    detect_events,
    detect_price_velocity,
    detect_range_breakout,
    detect_range_expansion,
    detect_vol_expansion,
)

INSTR = Instrument(symbol="XAUUSD")
T0 = datetime(2020, 1, 1, tzinfo=UTC)


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


def quiet_bars(n: int, start: int = 0, price: float = 2000.0, rng: float = 1.0) -> list[Bar]:
    """n narrow-range bars around `price` (range = rng)."""
    return [mkbar(start + i, price, price + rng / 2, price - rng / 2, price) for i in range(n)]


class TestPreRegistration:
    def test_exactly_ten_families_five_definitions(self):
        assert len(PRE_REGISTERED_FAMILIES) == 10
        defs = {f.definition for f in PRE_REGISTERED_FAMILIES}
        assert defs == {
            "range_expansion",
            "price_velocity",
            "vol_expansion",
            "range_breakout",
            "breakout_with_expansion",
        }
        for d in defs:
            roles = sorted(f.role for f in PRE_REGISTERED_FAMILIES if f.definition == d)
            assert roles == ["baseline", "variant"]

    def test_family_ids_unique(self):
        ids = [f.family_id for f in PRE_REGISTERED_FAMILIES]
        assert len(set(ids)) == len(ids)


class TestRangeExpansion:
    def test_fires_long_on_wide_up_bar(self):
        hist = quiet_bars(30, rng=1.0)
        i = len(hist)
        hist.append(mkbar(i, 2000.0, 2010.0, 1999.5, 2009.0))  # range 10.5 >> 2.5*1.0, up close
        assert detect_range_expansion(hist, k=2.5) == LONG

    def test_fires_short_on_wide_down_bar(self):
        hist = quiet_bars(30, rng=1.0)
        i = len(hist)
        hist.append(mkbar(i, 2000.0, 2000.5, 1990.0, 1991.0))
        assert detect_range_expansion(hist, k=2.5) == SHORT

    def test_does_not_fire_below_threshold(self):
        hist = quiet_bars(30, rng=1.0)
        i = len(hist)
        hist.append(mkbar(i, 2000.0, 2001.2, 1999.5, 2001.0))  # range 1.7 < 2.5
        assert detect_range_expansion(hist, k=2.5) is None

    def test_doji_wide_bar_has_no_direction(self):
        hist = quiet_bars(30, rng=1.0)
        i = len(hist)
        hist.append(mkbar(i, 2000.0, 2010.0, 1990.0, 2000.0))  # wide but close==open
        assert detect_range_expansion(hist, k=2.5) is None

    def test_insufficient_history_returns_none(self):
        hist = quiet_bars(5)
        assert detect_range_expansion(hist, k=2.5) is None


class TestPriceVelocity:
    def _noisy_hist(self, n: int = 80) -> list[Bar]:
        # deterministic small alternating moves so dispersion sigma is small but > 0
        bars = []
        p = 2000.0
        for i in range(n):
            p += 0.5 if i % 2 == 0 else -0.4
            bars.append(mkbar(i, p, p + 0.3, p - 0.3, p))
        return bars

    def test_fires_long_on_fast_up_move(self):
        hist = self._noisy_hist()
        c0 = float(hist[-1].close)
        i = len(hist)
        hist.append(mkbar(i, c0, c0 + 12.0, c0 - 0.2, c0 + 11.0))
        assert detect_price_velocity(hist, k=2.5) == LONG

    def test_fires_short_on_fast_down_move(self):
        hist = self._noisy_hist()
        c0 = float(hist[-1].close)
        i = len(hist)
        hist.append(mkbar(i, c0, c0 + 0.2, c0 - 12.0, c0 - 11.0))
        assert detect_price_velocity(hist, k=2.5) == SHORT

    def test_does_not_fire_on_normal_move(self):
        hist = self._noisy_hist()
        c0 = float(hist[-1].close)
        i = len(hist)
        hist.append(mkbar(i, c0, c0 + 0.8, c0 - 0.2, c0 + 0.5))
        assert detect_price_velocity(hist, k=2.5) is None

    def test_trigger_does_not_inflate_own_threshold(self):
        """The baseline dispersion must come from moves completed BEFORE bar i.
        A single huge move therefore still triggers (it is not diluted into
        its own threshold)."""
        hist = self._noisy_hist()
        c0 = float(hist[-1].close)
        i = len(hist)
        hist.append(mkbar(i, c0, c0 + 50.0, c0 - 0.2, c0 + 49.0))
        assert detect_price_velocity(hist, k=2.5) == LONG


class TestVolExpansion:
    def test_fires_on_volatility_burst_with_direction(self):
        bars = []
        p = 2000.0
        for i in range(60):  # long quiet regime
            bars.append(mkbar(i, p, p + 0.2, p - 0.2, p + 0.01))
            p += 0.01
        for _j in range(6):  # violent up burst
            p += 3.0
            i = len(bars)
            bars.append(mkbar(i, p - 3.0, p + 0.5, p - 3.2, p))
        assert detect_vol_expansion(bars, k=2.0) == LONG

    def test_no_fire_when_vol_stable(self):
        bars = []
        p = 2000.0
        for i in range(60):
            p += 0.5 if i % 2 == 0 else -0.5
            bars.append(mkbar(i, p, p + 0.6, p - 0.6, p))
        assert detect_vol_expansion(bars, k=2.0) is None


class TestRangeBreakout:
    def test_long_breakout(self):
        hist = quiet_bars(25, price=2000.0, rng=2.0)  # highs at 2001
        i = len(hist)
        hist.append(mkbar(i, 2000.5, 2003.0, 2000.0, 2002.5))  # close > max prior high
        assert detect_range_breakout(hist, lookback=20.0) == LONG

    def test_short_breakout(self):
        hist = quiet_bars(25, price=2000.0, rng=2.0)  # lows at 1999
        i = len(hist)
        hist.append(mkbar(i, 1999.5, 2000.0, 1997.0, 1997.5))
        assert detect_range_breakout(hist, lookback=20.0) == SHORT

    def test_close_inside_prior_range_no_fire(self):
        hist = quiet_bars(25, price=2000.0, rng=2.0)
        i = len(hist)
        hist.append(mkbar(i, 2000.0, 2000.9, 1999.2, 2000.5))
        assert detect_range_breakout(hist, lookback=20.0) is None

    def test_extremes_exclude_current_bar(self):
        """A bar whose own high is extreme must still be judged against PRIOR bars only."""
        hist = quiet_bars(25, price=2000.0, rng=2.0)
        i = len(hist)
        hist.append(mkbar(i, 2000.0, 2100.0, 1999.5, 2000.4))  # huge wick, close inside
        assert detect_range_breakout(hist, lookback=20.0) is None


class TestDetectEvents:
    def _series_with_one_impulse(self) -> list[Bar]:
        bars = quiet_bars(WARMUP_BARS + 10, rng=1.0)
        i = len(bars)
        bars.append(mkbar(i, 2000.0, 2012.0, 1999.5, 2011.0))
        bars.extend(quiet_bars(40, start=i + 1, price=2011.0, rng=1.0))
        return bars

    def test_event_detected_with_index(self):
        bars = self._series_with_one_impulse()
        fam = next(f for f in PRE_REGISTERED_FAMILIES if f.family_id == "IMP-RE-B")
        evs = detect_events(bars, fam)
        assert (WARMUP_BARS + 10, LONG) in evs

    def test_no_events_before_warmup(self):
        # impulse placed at index 10 (< WARMUP) must never be reported
        bars = quiet_bars(10, rng=1.0)
        bars.append(mkbar(10, 2000.0, 2050.0, 1999.0, 2049.0))
        bars.extend(quiet_bars(WARMUP_BARS + 30, start=11, price=2049.0, rng=1.0))
        fam = next(f for f in PRE_REGISTERED_FAMILIES if f.family_id == "IMP-RE-B")
        evs = detect_events(bars, fam)
        assert all(i > 10 for i, _ in evs)

    def test_overlap_suppression(self):
        """Two impulses within the primary horizon collapse into one event."""
        bars = quiet_bars(WARMUP_BARS + 5, rng=1.0)
        i1 = len(bars)
        bars.append(mkbar(i1, 2000.0, 2012.0, 1999.5, 2011.0))
        for j in range(3, PRIMARY_HORIZON_BARS - 1):  # second impulse inside the window
            i2 = i1 + j
            p = 2011.0 + j
            bars.append(mkbar(i2, p, p + 12.0, p - 0.5, p + 11.0))
        bars.extend(quiet_bars(40, start=len(bars), price=2050.0, rng=1.0))
        fam = next(f for f in PRE_REGISTERED_FAMILIES if f.family_id == "IMP-RE-B")
        evs = detect_events(bars, fam)
        idxs = [i for i, _ in evs]
        assert i1 in idxs
        assert all(i2 - i1 > PRIMARY_HORIZON_BARS or i2 == i1 for i2 in idxs)

    def test_unknown_family_raises(self):
        from qts.research.impulse.definitions import ImpulseFamily

        bad = ImpulseFamily("IMP-XX", "nonexistent_definition", {}, "baseline")
        with pytest.raises(KeyError):
            detect_events(quiet_bars(WARMUP_BARS + 5), bad)
