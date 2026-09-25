"""Tick-freshness time contract regression (real Windows evidence).

Observed on the user's machine (WMMarkets-Demo ≈ UTC+3 server, XAUUSD@):
``market_data_fresh = true`` with ``age = -10537.1s`` — the gate compared a
SERVER-timezone-based MT5 tick stamp against the local UTC clock and then
accepted any ``age < 60``, i.e. every "future" (negative-age) tick passed no
matter how stale it truly was (up to ~3h on that server). The old code also
fabricated ``age = 0`` (fresh!) for missing/garbage timestamps.

Contract enforced by qts.lifecycle.demo_gate._evaluate_tick_freshness and
pinned here:
1. garbage/missing timestamp -> FAIL (never assumed fresh);
2. raw_age > 60s -> STALE (sound for any server offset >= 0; also kills
   closed-market quotes);
3. with the latest-M1-bar server-clock probe (the only authoritative
   server-time signal the MT5 Python API offers): fresh iff the tick lies
   inside the currently forming bar — provably < 60s old on the server's own
   clock; ticks before the bar open are provably not fresh; ticks stamped
   beyond the bar are corrupt/future and fail;
4. without the probe: same-basis timestamps only, -5s <= raw_age <= 60s;
   future stamps beyond tolerance FAIL — never clamped to zero.
No rule invents an age, clamps a negative, or accepts an unprovable stamp.
"""

from __future__ import annotations

import time
from typing import Any

from qts.lifecycle.demo_gate import (
    FUTURE_TOLERANCE_S,
    MAX_TICK_AGE_S,
    _evaluate_tick_freshness,
    demo_forward_readiness_report,
)

OFFSET_3H = 10800  # WMMarkets-Demo-style server: UTC+3


class Tick:
    def __init__(
        self, time_s: float | None = None, time_msc: int | None = None, bid: float = 2000.0, ask: float = 2000.5
    ):
        if time_s is not None:
            self.time = time_s
        if time_msc is not None:
            self.time_msc = time_msc
        self.bid = bid
        self.ask = ask


class _AccountDemo:
    login = 123
    server = "WMMarkets-Demo"
    company = "WMMarkets"
    balance = 10000
    margin = 0
    trade_mode = 0


class FakeMT5:
    """Real-API-shaped double; ``bar_time=None`` removes the server-clock probe."""

    def __init__(self, tick: Any, bar_time: float | None = None) -> None:
        self._tick = tick
        self._bar_time = bar_time
        self.rates_calls: list[tuple[str, int, int, int]] = []

    def initialize(self, **kwargs: Any) -> bool:
        return True

    def last_error(self) -> tuple[int, str]:
        return (1, "ok")

    def terminal_info(self) -> Any:
        return object()

    def account_info(self) -> Any:
        return _AccountDemo()

    def symbol_select(self, sym: str, flag: bool) -> bool:
        return True

    def symbol_info(self, sym: str) -> Any:
        class SI:
            trade_contract_size = 100.0
            volume_min = 0.01
            volume_max = 500.0
            volume_step = 0.01
            digits = 2
            point = 0.01
            trade_mode = 4

        return SI()

    def symbol_info_tick(self, sym: str) -> Any:
        return self._tick

    # --- server-clock probe ---
    TIMEFRAME_M1 = 1

    def copy_rates_from_pos(self, sym: str, timeframe: int, start: int, count: int) -> Any:
        self.rates_calls.append((sym, timeframe, start, count))
        if self._bar_time is None:
            return None
        return [{"time": int(self._bar_time)}]  # numpy-structured-array shape via item access


def _eval(tick: Any, fake: FakeMT5, now: float, symbol: str = "XAUUSD@") -> tuple[bool, str, str | None]:
    return _evaluate_tick_freshness(tick, fake, symbol, now)


# ------------------------------------------------------------- rule 1: garbage


def test_missing_or_garbage_timestamp_never_assumed_fresh():
    """The old code computed age=0 (FRESH) for these — fabricated freshness."""
    now = time.time()
    fake = FakeMT5(None, bar_time=now + OFFSET_3H)
    for bad in (Tick(time_s=0), Tick(), object(), Tick(time_s=float("nan")), Tick(time_s="abc")):  # type: ignore[arg-type]
        fresh, detail, blocker = _eval(bad, fake, now)
        assert fresh is False, f"garbage timestamp accepted: {detail}"
        assert "invalid" in detail or "missing" in detail
        assert blocker == "Market data not fresh"


# ------------------------------------------------- rule 2: raw stale (any basis)


def test_old_quote_fails_on_raw_age_regardless_of_probe():
    now = time.time()
    # closed-market style: last quote 10h ago on a same-basis clock
    tick = Tick(time_s=now - 36000)
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=None), now)
    assert fresh is False and blocker == "Market data stale"
    assert "36000" in detail

    # server-offset basis, quote genuinely hours old: raw age still > 60
    tick2 = Tick(time_s=now + OFFSET_3H - 36000)
    bar = now + OFFSET_3H - 30  # bar forming NOW on the server clock
    fresh2, detail2, blocker2 = _eval(tick2, FakeMT5(tick2, bar_time=bar), now)
    assert fresh2 is False
    assert blocker2 in ("Market data stale",)


# ------------------------------------- rule 3: server-clock probe (the real case)


def test_user_scenario_future_raw_age_with_fresh_inbar_tick_passes_transparently():
    """Server UTC+3, quote arrived 20s ago: raw local age is ~-3h (the
    reported -10537s pattern) but the tick lies inside the forming M1 bar —
    provably <60s old on the server's own clock."""
    now = float(int(time.time()))  # whole seconds: real MT5 bar times are integer epochs
    bar = now + OFFSET_3H - 30  # current bar opened 30s ago (server basis)
    tick = Tick(time_s=now + OFFSET_3H - 20)  # quote 20s ago (server basis)
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=bar), now)
    assert fresh is True
    assert blocker is None
    assert "current M1 bar" in detail
    assert "+3h00m" in detail  # implied server offset surfaced for audit
    assert "-10" in detail or "raw local age" in detail  # raw age still reported


def test_user_scenario_stale_quote_is_no_longer_accepted():
    """The exact field report: raw age -10537.1s ≈ UTC+3 server with a quote
    ~263s old. The old gate said fresh; the contract says provably stale."""
    now = float(int(time.time()))  # whole seconds: real MT5 bar times are integer epochs
    bar = now + OFFSET_3H - 30
    tick = Tick(time_s=now + OFFSET_3H - 263)  # quote 263s ago -> 4+ bars back
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=bar), now)
    assert fresh is False
    assert blocker == "Market data stale"
    assert "precedes the current M1 bar" in detail
    assert "233" in detail  # server-clock lower bound on the true age


def test_corrupt_future_tick_beyond_current_bar_fails():
    now = time.time()
    bar = now + OFFSET_3H - 30
    tick = Tick(time_s=bar + 3600)  # stamped an hour past the forming bar
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=bar), now)
    assert fresh is False
    assert blocker == "Market data not fresh"
    assert "beyond the current M1 bar" in detail


def test_minute_boundary_is_conservative_not_permissive():
    """A tick 1s before the bar open MIGHT be <60s old but cannot be proven
    so — the contract rejects (fail-closed direction); re-checking passes."""
    now = time.time()
    bar = now + OFFSET_3H
    tick = Tick(time_s=bar - 1)
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=bar), now)
    assert fresh is False
    assert blocker == "Market data stale"


def test_probe_reads_latest_m1_bar_for_the_broker_symbol():
    now = time.time()
    tick = Tick(time_s=now - 5)
    fake = FakeMT5(tick, bar_time=now - 30)
    _eval(tick, fake, now, symbol="XAUUSD@")
    assert fake.rates_calls == [("XAUUSD@", 1, 0, 1)]


# ------------------------------------------------- rule 4: no probe (mocks/legacy)


def test_future_tick_without_probe_fails_closed_never_clamped():
    now = time.time()
    tick = Tick(time_s=now + 3600)
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=None), now)
    assert fresh is False
    assert blocker == "Market data not fresh"
    assert "future" in detail and "fail-closed" in detail
    # explicitly NOT clamped to zero and NOT accepted
    assert "age 0.0s" not in detail


def test_small_same_basis_skew_within_tolerance_passes():
    now = time.time()
    tick = Tick(time_s=now + FUTURE_TOLERANCE_S - 2)  # +3s skew
    fresh, detail, _ = _eval(tick, FakeMT5(tick, bar_time=None), now)
    assert fresh is True
    assert "age" in detail


def test_same_basis_mock_ticks_still_pass():
    """Existing mocks stamp time.time() with no probe — unchanged behavior."""
    now = time.time()
    tick = Tick(time_s=now - 10)
    fresh, detail, blocker = _eval(tick, FakeMT5(tick, bar_time=None), now)
    assert fresh is True and blocker is None
    assert "age 10.0s" in detail


def test_time_msc_millisecond_fallback_paths():
    now = time.time()
    # only time_msc present (ms)
    tick_ms = Tick(time_msc=int((now - 10) * 1000))
    fresh, _, blocker = _eval(tick_ms, FakeMT5(tick_ms, bar_time=None), now)
    assert fresh is True and blocker is None
    # `time` field carrying milliseconds (>1e12 heuristic preserved)
    tick_t_ms = Tick(time_s=(now - 5) * 1000)
    fresh2, _, blocker2 = _eval(tick_t_ms, FakeMT5(tick_t_ms, bar_time=None), now)
    assert fresh2 is True and blocker2 is None


# ------------------------------------------------------- full-gate integration


def test_full_report_future_raw_age_fresh_quote_enables_check():
    now = time.time()
    bar = now + OFFSET_3H - 30
    tick = Tick(time_s=now + OFFSET_3H - 20)
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(tick, bar_time=bar), symbol="XAUUSD@")
    assert rpt["checks"]["market_data_fresh"] is True
    assert "current M1 bar" in rpt["details"]["market_data_fresh"]
    assert not any("fresh" in b.lower() for b in rpt["blocked_reasons"])


def test_full_report_stale_server_quote_blocks_demo():
    now = time.time()
    bar = now + OFFSET_3H - 30
    tick = Tick(time_s=now + OFFSET_3H - 263)
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(tick, bar_time=bar), symbol="XAUUSD@")
    assert rpt["checks"]["market_data_fresh"] is False
    assert any("Market data stale" in b for b in rpt["blocked_reasons"])
    assert rpt["passed"] is False
    assert rpt["demo_enabled"] is False


def test_full_report_garbage_tick_blocks_demo():
    now = time.time()
    tick = Tick(time_s=0)
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(tick, bar_time=now), symbol="XAUUSD@")
    assert rpt["checks"]["market_data_fresh"] is False
    assert any("Market data not fresh" in b for b in rpt["blocked_reasons"])
    assert rpt["demo_enabled"] is False


def test_contract_constants_unchanged():
    """The fix must not weaken the published freshness window."""
    assert MAX_TICK_AGE_S == 60.0
    assert FUTURE_TOLERANCE_S == 5.0
