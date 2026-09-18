"""Regression for FS-c42bbd: +3h timestamp normalization mismatch.

Session FS-c42bbd stopped after 30 consecutive failures:
  ticks_recorded 2396, duplicates_skipped 233, orders_submitted 0,
  last_tick_time 2026-09-18T05:49:59.206000+00:00,
  timestamp_basis broker-normalized(measured-m1-bar),
  failure MarketDataError: tick from future 2026-09-18 08:50:29.367 vs now 05:50:29 age -10800.28s

Root cause: server_utc_offset cache TTL expiry + intermittent copy_rates failure
caused fallback to 0.0 offset while ticks remained server-local (+3h), producing
future ticks. Fix: retain last measured offset on probe failure, only fallback
to 0 when never measured. No weakening of future-tick protection.

Tests required:
- +3h broker offset
- UTC/no offset
- repeated normalization (idempotency, no double-apply)
- offset re-measurement (TTL, retain on failure, DST shift)
- future-tick rejection (unchanged validation)
- DST/offset boundary
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qts.adapters.market_data import MarketDataError, MarketDataProvider
from qts.adapters.mt5_adapter import MT5Adapter
from qts.domain.value_objects import Instrument, Tick

OFFSET_3H = 10800
OFFSET_2H = 7200
OFFSET_0 = 0


class RawTick:
    def __init__(self, time_s: float | None = None, time_msc: int | None = None, bid: float = 2000.0, ask: float = 2000.5):
        if time_s is not None:
            self.time = time_s
        if time_msc is not None:
            self.time_msc = time_msc
        self.bid = bid
        self.ask = ask


class _SI:
    trade_contract_size = 100.0
    volume_min = 0.01
    volume_max = 500.0
    volume_step = 0.01
    digits = 2
    point = 0.01
    trade_tick_size = 0.01
    trade_mode = 4
    filling_mode = 1
    trade_exemode = 0
    trade_stops_level = 0
    trade_freeze_level = 0


class FakeMT5:
    TIMEFRAME_M1 = 1

    def __init__(self, tick: Any, bar_time: float | None = None):
        self._tick = tick
        self._bar_time = bar_time
        self.rates_calls: list[tuple[str, int, int, int]] = []
        self.tick_calls = 0

    def symbol_info_tick(self, sym: str) -> Any:
        self.tick_calls += 1
        return self._tick

    def symbol_info(self, sym: str) -> Any:
        return _SI()

    def symbol_select(self, sym: str, flag: bool) -> bool:
        return True

    def last_error(self) -> tuple[int, str]:
        return (1, "ok")

    def copy_rates_from_pos(self, sym: str, timeframe: int, start: int, count: int) -> Any:
        self.rates_calls.append((sym, timeframe, start, count))
        if self._bar_time is None:
            return None
        return [{"time": int(self._bar_time)}]


def _adapter(fake: Any, tmp_path: Path) -> MT5Adapter:
    return MT5Adapter(
        config={"symbol_map": {"XAUUSD": "XAUUSD@"}},
        mt5_module=fake,
        db_path=tmp_path / "adapter.db",
    )


INSTR = Instrument(symbol="XAUUSD", venue="MT5")


def _scenario(now: float, quote_age_s: float, offset_s: int = OFFSET_3H, bar_phase_s: float = 30.0):
    tick_stamp = int(now + offset_s - quote_age_s)
    bar_time = int(now + offset_s - bar_phase_s)
    return RawTick(time_s=tick_stamp), FakeMT5(RawTick(time_s=tick_stamp), bar_time=bar_time)


# ---------------------------------------------------------------- +3h offset


def test_plus_3h_broker_offset_normalizes_to_utc(tmp_path: Path):
    """FS-c42bbd core: +3h server must be subtracted to true UTC."""
    now = float(int(time.time()))
    raw_tick, fake = _scenario(now, quote_age_s=1, offset_s=OFFSET_3H)
    adapter = _adapter(fake, tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None
    assert tick.event_time == datetime.fromtimestamp(now - 1, tz=UTC)
    assert tick.provenance["server_utc_offset_s"] == float(OFFSET_3H)
    assert tick.provenance["offset_basis"] == "measured-m1-bar"
    # Provider validation must accept
    provider = MarketDataProvider(broker=adapter)
    got = provider.get_tick(INSTR)
    assert got.event_time == tick.event_time


# ---------------------------------------------------------------- UTC/no offset


def test_utc_no_offset_normalizes_identity(tmp_path: Path):
    now = float(int(time.time()))
    raw_tick, fake = _scenario(now, quote_age_s=1, offset_s=OFFSET_0)
    adapter = _adapter(fake, tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None
    assert tick.event_time == datetime.fromtimestamp(now - 1, tz=UTC)
    assert tick.provenance["server_utc_offset_s"] == 0.0
    assert tick.provenance["offset_basis"] == "measured-m1-bar"
    MarketDataProvider(broker=adapter).get_tick(INSTR)


# ---------------------------------------------------------------- repeated normalization (no double-apply)


def test_repeated_normalization_is_idempotent_no_double_apply(tmp_path: Path):
    """Calling ticks() twice on same raw stamp must not double-subtract offset."""
    now = float(int(time.time()))
    raw_tick, fake = _scenario(now, quote_age_s=2, offset_s=OFFSET_3H)
    adapter = _adapter(fake, tmp_path)

    t1 = adapter.ticks(INSTR)
    t2 = adapter.ticks(INSTR)
    assert t1 is not None and t2 is not None
    # Same raw stamp, same offset, same UTC — not UTC-3h on second call
    assert t1.event_time == t2.event_time
    assert t1.event_time == datetime.fromtimestamp(now - 2, tz=UTC)
    assert t2.provenance["server_utc_offset_s"] == float(OFFSET_3H)

    # Simulate 2396 ticks like FS-c42bbd: all must stay at now-2, not drift
    for _ in range(10):
        ti = adapter.ticks(INSTR)
        assert ti.event_time == datetime.fromtimestamp(now - 2, tz=UTC)


def test_from_domain_tick_does_not_renormalize(tmp_path: Path):
    """ObservationTick.from_domain_tick must not re-apply offset."""
    now = float(int(time.time()))
    raw_tick, fake = _scenario(now, quote_age_s=2, offset_s=OFFSET_3H)
    adapter = _adapter(fake, tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None

    from qts.observability.forward_observatory import ObservationTick

    obs = ObservationTick.from_domain_tick(tick, symbol="XAUUSD@")
    # broker_event_time is already normalized UTC, not double-subtracted
    assert obs.broker_event_time == tick.event_time
    assert obs.broker_event_time == datetime.fromtimestamp(now - 2, tz=UTC)
    assert obs.server_utc_offset_s == float(OFFSET_3H)


# ---------------------------------------------------------------- offset re-measurement


def test_offset_remeasurement_retains_on_probe_failure_fs_c42bbd(tmp_path: Path):
    """Core FS-c42bbd fix: when copy_rates fails after TTL, retain last offset.

    Previously: TTL expiry + None bar -> fallback 0.0 -> server-local tick
    appears +3h in future -> 30 consecutive MarketDataError -> STOPPED_ON_ERRORS.
    Now: retain previous +3h offset, ticks continue to normalize correctly.
    """
    now = float(int(time.time()))
    tick_stamp = int(now + OFFSET_3H - 1)
    fake = FakeMT5(RawTick(time_s=tick_stamp), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)

    # First measurement succeeds, caches +3h
    t1 = adapter.ticks(INSTR)
    assert t1.provenance["server_utc_offset_s"] == float(OFFSET_3H)
    assert len(fake.rates_calls) == 1

    # Expire cache
    sym = "XAUUSD@"
    cached = adapter._server_offset_cache[sym]
    adapter._server_offset_cache[sym] = (cached[0], cached[1], time.time() - 10_000)

    # Now make probe fail (None)
    fake._bar_time = None
    fake._tick = RawTick(time_s=tick_stamp)  # still server-local stamp

    t2 = adapter.ticks(INSTR)
    # Must RETAIN +3h, not fallback to 0
    assert t2 is not None
    assert t2.provenance["server_utc_offset_s"] == float(OFFSET_3H), "lost measured offset on probe failure"
    assert t2.provenance["offset_basis"] == "measured-m1-bar", "basis should be retained, not fallback"
    assert t2.event_time == datetime.fromtimestamp(now - 1, tz=UTC), "tick should still normalize to UTC, not future"

    # Provider must accept, not raise future
    provider = MarketDataProvider(broker=adapter)
    got = provider.get_tick(INSTR)
    assert got.event_time == datetime.fromtimestamp(now - 1, tz=UTC)

    # Second call within new TTL should use cached retained offset, no extra probe
    calls_before = len(fake.rates_calls)
    adapter.ticks(INSTR)
    assert len(fake.rates_calls) == calls_before, "should use cached retained offset within TTL"


def test_offset_remeasurement_updates_on_success(tmp_path: Path):
    """When probe succeeds after TTL, offset updates (DST shift)."""
    now = float(int(time.time()))
    fake = FakeMT5(RawTick(time_s=int(now + OFFSET_3H - 1)), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    adapter.ticks(INSTR)
    assert len(fake.rates_calls) == 1

    sym = "XAUUSD@"
    cached = adapter._server_offset_cache[sym]
    adapter._server_offset_cache[sym] = (cached[0], cached[1], time.time() - 10_000)

    # DST: server moves to +2h
    fake._bar_time = int(now + OFFSET_2H - 30)
    fake._tick = RawTick(time_s=int(now + OFFSET_2H - 1))

    t2 = adapter.ticks(INSTR)
    assert t2.provenance["server_utc_offset_s"] == float(OFFSET_2H)
    assert t2.event_time == datetime.fromtimestamp(now - 1, tz=UTC)
    assert len(fake.rates_calls) == 2


def test_no_prior_offset_fallback_still_loudly_rejects_server_basis(tmp_path: Path):
    """If never measured, fallback 0 must still cause future rejection for server-basis stamps."""
    now = float(int(time.time()))

    class NoProbeMT5:
        def symbol_info_tick(self, sym):
            return RawTick(time_s=now + OFFSET_3H - 1)

        def symbol_info(self, sym):
            return _SI()

        def last_error(self):
            return (1, "ok")

    adapter = _adapter(NoProbeMT5(), tmp_path)
    # No bar probe, no cache -> fallback 0, server stamp appears future
    with pytest.raises(MarketDataError, match="tick from future"):
        MarketDataProvider(broker=adapter).get_tick(INSTR)


# ---------------------------------------------------------------- future-tick rejection (not weakened)


def test_future_tick_rejection_not_weakened(tmp_path: Path):
    """Future protection must remain strict: >1s in future fails."""
    now = float(int(time.time()))
    # Genuinely future: even after correct +3h normalization, it's 1h beyond server clock
    tick_stamp = int(now + OFFSET_3H + 3600)
    fake = FakeMT5(RawTick(time_s=tick_stamp), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    provider = MarketDataProvider(broker=adapter)
    with pytest.raises(MarketDataError, match="tick from future"):
        provider.get_tick(INSTR)

    # Also test raw UTC future without offset
    fake2 = FakeMT5(RawTick(time_s=int(now + 10)), bar_time=int(now - 30))
    adapter2 = _adapter(fake2, tmp_path)
    with pytest.raises(MarketDataError, match="tick from future"):
        MarketDataProvider(broker=adapter2).get_tick(INSTR)


def test_future_tolerance_unchanged(tmp_path: Path):
    provider = MarketDataProvider(broker=object())
    assert provider.max_tick_age_s == 5.0
    now = datetime.now(UTC)
    base = {"instrument": INSTR, "bid": Decimal("2000.0"), "ask": Decimal("2000.5")}
    future = Tick(event_time=now + timedelta(seconds=2), **base)
    with pytest.raises(MarketDataError, match="tick from future"):
        provider._validate_tick(future, "XAUUSD")


# ---------------------------------------------------------------- DST/offset boundary


def test_dst_boundary_2h_to_3h_shift(tmp_path: Path):
    """DST boundary: server shifts +2h <-> +3h, measurement must track exactly."""
    now = float(int(time.time()))
    for offset in (OFFSET_2H, OFFSET_3H):
        fake = FakeMT5(RawTick(time_s=int(now + offset - 1)), bar_time=int(now + offset - 30))
        adapter = _adapter(fake, tmp_path)
        measured, basis = adapter.server_utc_offset("XAUUSD@")
        assert measured == float(offset)
        assert basis == "measured-m1-bar"
        tick = adapter.ticks(INSTR)
        assert tick.event_time == datetime.fromtimestamp(now - 1, tz=UTC)


def test_offset_grid_exactness_across_zones(tmp_path: Path):
    """All real-world offsets are multiples of 15min; grid recovers exactly."""
    now = float(int(time.time()))
    for offset in (0, 900, 1800, 3600, 7200, 10800, 19800, -18000, -14400, 50400):  # includes +14h max
        for bar_phase in (0, 15, 30, 59):
            fake = FakeMT5(RawTick(time_s=now), bar_time=now + offset - bar_phase)
            adapter = _adapter(fake, tmp_path)
            measured, basis = adapter.server_utc_offset("XAUUSD@")
            assert measured == float(offset), f"offset {offset} phase {bar_phase} got {measured}"
            assert basis == "measured-m1-bar"


def test_fs_c42bbd_repro_2396_ticks_then_probe_failure_should_not_future(tmp_path: Path):
    """Repro FS-c42bbd: 2396 good ticks, then probe fails, next tick must NOT be future."""
    now = float(int(time.time()))
    fake = FakeMT5(RawTick(time_s=int(now + OFFSET_3H - 1)), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    provider = MarketDataProvider(broker=adapter)

    # Simulate 2396 ticks (we do 10 for speed, but logic same)
    for _ in range(10):
        tick = provider.get_tick(INSTR)
        assert tick.event_time == datetime.fromtimestamp(now - 1, tz=UTC)

    # Expire and fail probe like in production
    sym = "XAUUSD@"
    cached = adapter._server_offset_cache[sym]
    adapter._server_offset_cache[sym] = (cached[0], cached[1], time.time() - 10_000)
    fake._bar_time = None  # probe failure
    fake._tick = RawTick(time_s=int(now + OFFSET_3H - 1))

    # With fix, this must still pass, not raise future
    tick_after = provider.get_tick(INSTR)
    assert tick_after.event_time == datetime.fromtimestamp(now - 1, tz=UTC)
    assert tick_after.provenance["server_utc_offset_s"] == float(OFFSET_3H)
