from types import SimpleNamespace

import qts.adapters.mt5_adapter as mt5_adapter
from qts.adapters.mt5_adapter import MT5Adapter


class FakeMT5:
    TIMEFRAME_M1 = 1

    def __init__(self, tick, bar_time):
        self._tick = tick
        self._bar_time = bar_time

    def symbol_info_tick(self, symbol):
        return self._tick

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        return [{"time": self._bar_time}]


def test_server_offset_prefers_fresh_tick_with_non_quarter_hour_offset(tmp_path, monkeypatch):
    now = 1_800_000_123.4
    offset = 2 * 3600 + 59 * 60
    tick = SimpleNamespace(time=now + offset)
    mt5 = FakeMT5(tick, now + offset - 30.0)

    monkeypatch.setattr(mt5_adapter.time, "time", lambda: now)
    adapter = MT5Adapter(mt5_module=mt5, db_path=tmp_path / "qts.db")

    measured, basis = adapter.server_utc_offset("XAUUSD")

    assert measured == offset
    assert basis == "measured-m1-bar"


def test_server_offset_rejects_stale_tick_and_uses_m1_bar(tmp_path, monkeypatch):
    now = 1_800_000_123.4
    tick = SimpleNamespace(time=now + 3 * 3600 - 300)
    bar_time = (int(now + 3 * 3600) // 60) * 60
    mt5 = FakeMT5(tick, bar_time)

    monkeypatch.setattr(mt5_adapter.time, "time", lambda: now)
    adapter = MT5Adapter(mt5_module=mt5, db_path=tmp_path / "qts.db")

    measured, basis = adapter.server_utc_offset("XAUUSD")

    assert measured == 3 * 3600
    assert basis == "measured-m1-bar"


def test_server_offset_does_not_cache_unmeasured_zero(tmp_path, monkeypatch):
    now = 1_800_000_123.4
    mt5 = FakeMT5(None, None)

    monkeypatch.setattr(mt5_adapter.time, "time", lambda: now)
    adapter = MT5Adapter(mt5_module=mt5, db_path=tmp_path / "qts.db")

    measured, basis = adapter.server_utc_offset("XAUUSD")

    assert measured == 0.0
    assert basis == "assumed-utc-fallback"
    assert adapter.offset_cache_info("XAUUSD")["status"] == "UNAVAILABLE"
