"""One freshness contract for broker quotes — regression for the UI starvation bug.

Symptom on the operator's machine: startup health, readiness and
reconciliation all green (WMMarkets-Demo connected, XAUUSD -> XAUUSD@
mapped, live prices), yet the Market card stayed "waiting for a fresh
price" and the guide stayed "Almost ready" — because two freshness
contracts disagreed about the SAME live quote:

* the readiness gate judged the RAW broker stamp on the server clock
  (proven correct on WMMarkets-Demo) and passed;
* the product quote probes judged the NORMALIZED ``event_time`` — and one
  transient ``copy_rates`` failure cached the assumed-UTC fallback offset
  for the whole TTL, fabricating hours-future event times, so every quote
  was rejected as "from the future" until the cache expired (and again on
  every later failure).

Pinned here:
* the assumed-UTC fallback is NEVER cached — every tick re-attempts the
  server-offset measurement (a measured offset is still retained, FS-c42bbd
  contract unchanged);
* under the fallback basis, time validation routes through the SAME
  server-clock contract the readiness gate uses: fresh when the server
  clock proves it, loud and fail-closed when it does not;
* stale and corrupt stamps still fail closed. No gate is weakened.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from qts.adapters.market_data import MarketDataError, MarketDataProvider
from qts.adapters.mt5_adapter import MT5Adapter
from qts.domain.value_objects import Instrument
from qts.execution.demo_session import DemoSession, DemoSessionConfig
from qts.lifecycle.demo_gate import MAX_TICK_AGE_S

OFFSET_3H = 10800
INSTR = Instrument(symbol="XAUUSD", venue="MT5")


class RawTick:
    def __init__(self, time_s: float, bid: float = 2000.0, ask: float = 2000.5) -> None:
        self.time = time_s
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


class FlakyMT5:
    """Real-API-shaped double whose bar probe fails ``fail_times`` calls first.

    Models the documented intermittent ``copy_rates`` failures: the first
    offset measurement sees no bar (fallback), later calls do.
    """

    TIMEFRAME_M1 = 1

    def __init__(self, tick_stamp: float, bar_time: float, fail_times: int = 0) -> None:
        self._tick = RawTick(time_s=tick_stamp)
        self._bar_time = bar_time
        self._fail_left = fail_times
        self.rates_calls = 0

    def symbol_info_tick(self, sym: str) -> Any:
        return self._tick

    def symbol_info(self, sym: str) -> Any:
        return _SI()

    def symbol_select(self, sym: str, flag: bool) -> bool:
        return True

    def last_error(self) -> tuple[int, str]:
        return (1, "ok")

    def copy_rates_from_pos(self, sym: str, timeframe: int, start: int, count: int) -> Any:
        self.rates_calls += 1
        if self._fail_left > 0:
            self._fail_left -= 1
            return None
        return [{"time": int(self._bar_time)}]


def _adapter(fake: Any, tmp_path: Path) -> MT5Adapter:
    return MT5Adapter(
        config={"symbol_map": {"XAUUSD": "XAUUSD@"}},
        mt5_module=fake,
        db_path=tmp_path / "adapter.db",
    )


def _session(fake: Any, tmp_path: Path) -> DemoSession:
    return DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=tmp_path / "qts.db",
            actor="freshness-contract-test",
            mt5_module=fake,
        )
    )


def _live_scenario(quote_age_s: float = 2.0, fail_times: int = 0, stale_s: float = 0.0):
    now = float(int(time.time()))
    tick_stamp = now + OFFSET_3H - quote_age_s - stale_s
    bar_time = now + OFFSET_3H - 30.0  # tick sits inside the forming M1 bar
    return FlakyMT5(tick_stamp, bar_time, fail_times=fail_times)


def test_fallback_offset_is_never_cached(tmp_path: Path) -> None:
    """A transient probe failure must not poison the offset for the TTL window."""
    fake = _live_scenario()
    fake._tick = RawTick(None)
    fake._fail_left = 1  # first bar probe fails, second succeeds
    adapter = _adapter(fake, tmp_path)

    offset, basis = adapter.server_utc_offset("XAUUSD@")
    assert basis == "assumed-utc-fallback"
    assert offset == 0.0

    # Next tick re-measures instead of replaying the cached fallback.
    offset, basis = adapter.server_utc_offset("XAUUSD@")
    assert basis == "measured-m1-bar"
    assert offset == float(OFFSET_3H)


def test_quote_probe_is_fresh_despite_transient_probe_failure(tmp_path: Path) -> None:
    """THE regression: readiness-green machine, one flaky copy_rates call.

    Old behaviour: the fallback offset was cached, the normalized event_time
    landed ~3h in the future, and every quote probe said not-fresh until the
    TTL expired — Market starved and the guide could not be prepared while
    readiness passed. New behaviour: the shared server-clock contract proves
    the quote fresh on the very next probe.
    """
    fake = _live_scenario(quote_age_s=2.0, fail_times=1)
    session = _session(fake, tmp_path)

    quote = session._quote_probe()
    assert quote["ok"] is True, quote
    assert quote["fresh"] is True, quote
    assert quote["offset_basis"] == "measured-m1-bar"
    assert float(quote["bid"]) > 0 and float(quote["ask"]) > 0

    # The provider certification under the fallback basis went through the
    # readiness gate's contract — not through the poisoned event_time. The
    # NEXT probe re-measures the offset (fallback is not cached) and recovers.
    got = session.market_data.get_tick(INSTR)
    assert got.provenance["offset_basis"] == "measured-m1-bar"


def test_quote_probe_starves_closed_when_quote_is_stale(tmp_path: Path) -> None:
    """Fallback basis never fabricates freshness: a stale quote stays rejected."""
    fake = _live_scenario(quote_age_s=2.0, fail_times=1, stale_s=MAX_TICK_AGE_S + 240.0)
    session = _session(fake, tmp_path)

    quote = session._quote_probe()
    assert quote["ok"] is False or quote["fresh"] is False
    if not quote["ok"]:
        assert "not fresh on server clock" in quote["error"]


def test_quote_probe_fails_closed_on_corrupt_future_stamp(tmp_path: Path) -> None:
    """A stamp beyond the forming bar is corrupt — loud rejection, fallback or not."""
    now = float(int(time.time()))
    tick_stamp = now + OFFSET_3H + 600.0  # far beyond bar_time + 60 + tolerance
    fake = FlakyMT5(tick_stamp, now + OFFSET_3H - 30.0, fail_times=1)
    adapter = _adapter(fake, tmp_path)

    with pytest.raises(MarketDataError, match="not fresh on server clock"):
        MarketDataProvider(broker=adapter).get_tick(INSTR)


def test_connectivity_quote_and_readiness_share_one_contract(tmp_path: Path) -> None:
    """With a healthy measured offset the quote probe and the gate agree the
    quote is fresh — and the connectivity report's quote reflects it."""
    fake = _live_scenario(quote_age_s=2.0)
    session = _session(fake, tmp_path)

    quote = session._quote_probe()
    assert quote["fresh"] is True
    assert quote["offset_basis"] == "measured-m1-bar"

    report = session.connectivity_report()
    assert report["quote"]["fresh"] is True
    # The readiness gate's own freshness check agrees on the same quote —
    # one contract, one answer (the minimal double does not satisfy the
    # full 14-check probe, so only the freshness check is compared).
    checks = report["readiness"].get("checks") or {}
    assert checks.get("market_data_fresh") is True
