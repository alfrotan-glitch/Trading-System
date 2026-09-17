"""Canonical QTS tick-timestamp contract regression (real Windows evidence).

Scenario reproduced from the user's machine: WMMarkets-Demo server stamps
ticks in SERVER local time (~UTC+3). MT5Adapter.ticks() previously did
``datetime.fromtimestamp(tick.time, tz=UTC)`` — treating the server-basis
stamp as true UTC — so every live tick looked ~3h "from the future" and
MarketDataProvider.validate_tick() rejected it ("tick from future"),
blocking DEMO_FORWARD observations on any non-UTC broker.

Contract pinned here (readiness gate untouched):
- canonical QTS time is true UTC; broker stamps are normalized via the
  MEASURED server offset (forming-M1-bar probe + 15-minute offset grid =>
  exact recovery, never guessed, never clamped);
- provenance (raw stamps, offset, basis, broker symbol, receipt time) rides
  on Tick.provenance and into persisted ObservationTick rows — auditable;
- validate_tick is NOT weakened: corrupt future stamps and stale quotes
  still fail; garbage timestamps fail closed (never fabricated);
- no-probe modules (mocks/legacy) keep the old same-basis behavior with the
  fallback basis recorded, and server-basis stamps then fail LOUDLY.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qts.adapters.market_data import MarketDataError, MarketDataProvider
from qts.adapters.mt5_adapter import MT5Adapter
from qts.db import connect as db_connect
from qts.domain.value_objects import Instrument, Tick
from qts.observability.forward_observatory import ForwardObservatory, ObservationTick

OFFSET_3H = 10800


class RawTick:
    def __init__(
        self, time_s: float | None = None, time_msc: int | None = None, bid: float = 2000.0, ask: float = 2000.5
    ):
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
    """Real-API-shaped double. ``bar_time=None`` => empty series (no measurement)."""

    TIMEFRAME_M1 = 1

    def __init__(self, tick: Any, bar_time: float | None = None) -> None:
        self._tick = tick
        self._bar_time = bar_time
        self.rates_calls: list[tuple[str, int, int, int]] = []

    def symbol_info_tick(self, sym: str) -> Any:
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
    """Server-basis tick + forming-bar probe for a live quote ``quote_age_s`` old."""
    tick_stamp = int(now + offset_s - quote_age_s)
    bar_time = int(now + offset_s - bar_phase_s)
    return RawTick(time_s=tick_stamp), FakeMT5(RawTick(time_s=tick_stamp), bar_time=bar_time)


# ------------------------------------------------------- the proven Windows bug


def test_utc3_broker_tick_now_passes_provider_validation(tmp_path: Path):
    """End-to-end repro: quote 2s old on a UTC+3 server. Old conversion made
    it 3h 'from the future'; the contract normalizes it to true UTC and the
    UNCHANGED provider validation accepts it."""
    now = float(int(time.time()))
    raw_tick, fake = _scenario(now, quote_age_s=2)
    adapter = _adapter(fake, tmp_path)

    tick = adapter.ticks(INSTR)
    assert tick is not None
    assert tick.event_time == datetime.fromtimestamp(now - 2, tz=UTC)

    provider = MarketDataProvider(broker=adapter)
    got = provider.get_tick(INSTR)  # raises MarketDataError on any contract violation
    assert got.event_time == tick.event_time

    # prove the OLD naive conversion is exactly what validation rejects
    naive = Tick(
        instrument=INSTR,
        bid=Decimal("2000.0"),
        ask=Decimal("2000.5"),
        event_time=datetime.fromtimestamp(raw_tick.time, tz=UTC),
    )
    with pytest.raises(MarketDataError, match="tick from future"):
        provider._validate_tick(naive, "XAUUSD")


def test_offset_recovered_exactly_across_bar_phases_and_zones(tmp_path: Path):
    now = float(int(time.time()))
    for offset in (OFFSET_3H, 7200, 0, 19800, -18000):  # +3h, +2h, UTC, +5:30, -5h
        for bar_phase in (0, 15, 30, 59):  # anywhere inside the forming bar
            fake = FakeMT5(RawTick(time_s=now), bar_time=now + offset - bar_phase)
            adapter = _adapter(fake, tmp_path)
            measured, basis = adapter.server_utc_offset("XAUUSD@")
            assert measured == float(offset), (offset, bar_phase, measured)
            assert basis == "measured-m1-bar"


def test_provenance_is_attached_and_auditable(tmp_path: Path):
    now = float(int(time.time()))
    tick_raw, fake = _scenario(now, quote_age_s=3)
    adapter = _adapter(fake, tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None and tick.provenance is not None
    prov = tick.provenance
    assert prov["mt5_time"] == tick_raw.time  # raw server-basis stamp preserved
    assert prov["server_utc_offset_s"] == float(OFFSET_3H)
    assert prov["offset_basis"] == "measured-m1-bar"
    assert prov["broker_symbol"] == "XAUUSD@"
    datetime.fromisoformat(prov["received_at"])  # parseable receipt time
    assert fake.rates_calls and fake.rates_calls[0] == ("XAUUSD@", 1, 0, 1)


# ------------------------------------------------- validation NOT weakened


def test_corrupt_future_tick_still_rejected(tmp_path: Path):
    now = float(int(time.time()))
    tick_stamp = int(now + OFFSET_3H + 3600)  # 1h beyond even the server clock
    fake = FakeMT5(RawTick(time_s=tick_stamp), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    provider = MarketDataProvider(broker=adapter)
    with pytest.raises(MarketDataError, match="tick from future"):
        provider.get_tick(INSTR)


def test_stale_quote_still_rejected(tmp_path: Path):
    now = float(int(time.time()))
    tick_stamp = int(now + OFFSET_3H - 120)  # genuinely 2 minutes old
    fake = FakeMT5(RawTick(time_s=tick_stamp), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    provider = MarketDataProvider(broker=adapter)
    with pytest.raises(MarketDataError, match="tick stale"):
        provider.get_tick(INSTR)


def test_garbage_timestamp_fails_closed_never_fabricated(tmp_path: Path):
    fake = FakeMT5(RawTick(), bar_time=int(time.time()) + OFFSET_3H)  # no time fields at all
    adapter = _adapter(fake, tmp_path)
    with pytest.raises(RuntimeError, match="refusing to fabricate"):
        adapter.ticks(INSTR)
    provider = MarketDataProvider(broker=adapter)
    with pytest.raises(MarketDataError):  # wrapped, still fail-closed
        provider.get_tick(INSTR)


def test_validation_thresholds_unchanged():
    """The provider's future/stale contract is byte-for-byte as strict as before."""
    provider = MarketDataProvider(broker=object())
    assert provider.max_tick_age_s == 5.0
    now = datetime.now(UTC)
    base = {"instrument": INSTR, "bid": Decimal("2000.0"), "ask": Decimal("2000.5")}
    future = Tick(event_time=now + timedelta(seconds=2), **base)
    with pytest.raises(MarketDataError, match="tick from future"):
        provider._validate_tick(future, "XAUUSD")
    past = Tick(event_time=now - timedelta(seconds=120), **base)
    with pytest.raises(MarketDataError, match="tick stale"):
        provider._validate_tick(past, "XAUUSD")


# ------------------------------------------- no-probe fallback (mocks/legacy)


def test_no_probe_same_basis_ticks_keep_working(tmp_path: Path):
    now = float(int(time.time()))

    class LegacyMT5:
        def symbol_info_tick(self, sym):
            return RawTick(time_s=now - 1)

        def symbol_info(self, sym):
            return _SI()

        def last_error(self):
            return (1, "ok")

    adapter = _adapter(LegacyMT5(), tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None
    assert tick.event_time == datetime.fromtimestamp(now - 1, tz=UTC)  # identical to legacy behavior
    assert tick.provenance is not None
    assert tick.provenance["offset_basis"] == "assumed-utc-fallback"
    assert tick.provenance["server_utc_offset_s"] == 0.0
    MarketDataProvider(broker=adapter).get_tick(INSTR)  # still validates clean


def test_no_probe_server_basis_stamp_fails_loudly(tmp_path: Path):
    """With no probe, a server-basis stamp is NOT silently mis-dated into
    acceptance — the unchanged future check rejects it."""
    now = float(int(time.time()))

    class LegacyMT5:
        def symbol_info_tick(self, sym):
            return RawTick(time_s=now + OFFSET_3H - 2)

        def symbol_info(self, sym):
            return _SI()

        def last_error(self):
            return (1, "ok")

    adapter = _adapter(LegacyMT5(), tmp_path)
    with pytest.raises(MarketDataError, match="tick from future"):
        MarketDataProvider(broker=adapter).get_tick(INSTR)


# ------------------------------------------------------- offset cache / DST


def test_offset_cache_ttl_and_dst_shift(tmp_path: Path):
    now = float(int(time.time()))
    tick_stamp = int(now + OFFSET_3H - 2)
    fake = FakeMT5(RawTick(time_s=tick_stamp), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)

    adapter.ticks(INSTR)
    adapter.ticks(INSTR)
    assert len(fake.rates_calls) == 1  # cached within TTL

    # DST shift: server moves to UTC+2; expire the cache entry
    fake._bar_time = int(now + 7200 - 30)
    fake._tick = RawTick(time_s=int(now + 7200 - 2))
    sym = "XAUUSD@"
    cached = adapter._server_offset_cache[sym]
    adapter._server_offset_cache[sym] = (cached[0], cached[1], time.time() - 10_000)

    tick2 = adapter.ticks(INSTR)
    assert len(fake.rates_calls) == 2  # re-measured after TTL
    assert tick2 is not None and tick2.provenance is not None
    assert tick2.provenance["server_utc_offset_s"] == 7200.0
    assert tick2.event_time == datetime.fromtimestamp(now - 2, tz=UTC)


# ------------------------------------------------------------ sub-second path


def test_time_msc_subsecond_precision(tmp_path: Path):
    now = float(int(time.time()))
    msc = int((now + OFFSET_3H - 2.65) * 1000)
    fake = FakeMT5(RawTick(time_s=int(now + OFFSET_3H - 2), time_msc=msc), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None
    expected = datetime.fromtimestamp(now - 2.65, tz=UTC)
    assert abs((tick.event_time - expected).total_seconds()) < 0.01
    assert tick.provenance is not None and tick.provenance["mt5_time_msc"] == msc


# ------------------------------------------------- observation persistence


def test_observation_persistence_carries_auditable_basis(tmp_path: Path):
    now = float(int(time.time()))
    tick_stamp = int(now + OFFSET_3H - 2)
    fake = FakeMT5(RawTick(time_s=tick_stamp), bar_time=int(now + OFFSET_3H - 30))
    adapter = _adapter(fake, tmp_path)
    tick = adapter.ticks(INSTR)
    assert tick is not None

    obs = ObservationTick.from_domain_tick(tick)
    assert obs.timestamp_basis == "broker-normalized(measured-m1-bar)"
    assert obs.broker_time_raw == float(tick_stamp)
    assert obs.server_utc_offset_s == float(OFFSET_3H)
    assert obs.broker_event_time == tick.event_time
    assert obs.spread_bps is not None and abs(obs.spread_bps - 2.5) < 0.01

    store = ForwardObservatory(db_path=tmp_path / "obs.db")
    store.record_tick(obs)
    assert store.summary()["ticks_recorded"] == 1

    with db_connect(tmp_path / "obs.db") as con:  # sanctioned opener (qts.db)
        row = con.execute("SELECT payload FROM observation_ticks WHERE id=?", (obs.id,)).fetchone()
    payload = json.loads(row[0])
    assert payload["timestamp_basis"] == "broker-normalized(measured-m1-bar)"
    assert payload["broker_time_raw"] == float(tick_stamp)
    assert payload["server_utc_offset_s"] == float(OFFSET_3H)
    stored_event = datetime.fromisoformat(str(payload["broker_event_time"]).replace("Z", "+00:00"))
    assert stored_event == tick.event_time


def test_observation_tick_defaults_remain_backward_compatible():
    obs = ObservationTick(symbol="XAUUSD")
    assert obs.timestamp_basis == "ingest-utc"
    assert obs.broker_event_time is None and obs.broker_time_raw is None and obs.server_utc_offset_s is None
