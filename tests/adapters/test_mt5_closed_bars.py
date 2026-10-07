"""Bounded completed-bar loader used for restart warmup (``recent_closed_bars``).

Contract under test:

* only bars that are already complete are returned — the currently forming bar
  is always excluded, and a future-dated bar is never trusted;
* boundaries are normalized with the *measured* server→UTC offset;
* an unmeasured clock (``assumed-utc-fallback``) refuses the whole window,
  because mislabelled bar history would corrupt every later signal;
* duplicates are dropped, the window is ascending, and it is bounded by the
  caller's ``count`` (and by the adapter's hard cap);
* unreadable/empty/malformed input produces no bars at all — nothing is
  fabricated or interpolated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import qts.adapters.mt5_adapter as mt5_adapter
from qts.adapters.mt5_adapter import MT5Adapter

NOW = 1_800_000_123.4
OFFSET = 3 * 3600
SPAN_S = 900


class FakeTerminal:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M15 = 15

    def __init__(
        self,
        *,
        now: float,
        offset: float = OFFSET,
        bars: list[tuple[float, float]] | None = None,
        m1_bar: float | None = None,
        tick: bool = True,
        rates_missing: bool = False,
        rates_error: bool = False,
    ) -> None:
        self._now = now
        self._offset = offset
        self._bars = list(bars or [])
        self._m1_bar = floor_to(m1_bar if m1_bar is not None else (now + offset), 60) if m1_bar is not False else None
        self._tick = tick
        self._rates_missing = rates_missing
        self._rates_error = rates_error

    def symbol_info_tick(self, symbol):
        if not self._tick:
            return None
        epoch = self._now + self._offset
        return SimpleNamespace(time=epoch, time_msc=epoch * 1000, bid=2000.0, ask=2000.2)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        # The M1 probe calibrates the server clock and stays available; the
        # failure modes below describe the *warmup* request only.
        if timeframe == self.TIMEFRAME_M1:
            return [] if self._m1_bar is None else [{"time": self._m1_bar, "close": 2000.0}]
        if self._rates_error:
            raise RuntimeError("terminal busy")
        if self._rates_missing:
            return None
        rows = [{"time": t, "close": c} for t, c in self._bars]
        return rows[-count:] if count else rows

    def last_error(self):
        return (1, "no rates")


def floor_to(value: float, span: float) -> float:
    return (int(value) // int(span)) * int(span)


def _completed_and_forming(now: float, offset: float, completed: int, start_close: float = 4000.0):
    """`completed` finished M15 bars in *server* time, plus the forming one.

    Closes ascend with time, so the newest completed bar has the highest close.
    """
    forming = floor_to(now + offset, SPAN_S)
    bars = [(forming - SPAN_S * (completed - i), start_close + i) for i in range(completed)]
    bars.append((forming, start_close + completed))  # the bar still forming
    return bars, forming


def _adapter(tmp_path, monkeypatch, terminal) -> MT5Adapter:
    monkeypatch.setattr(mt5_adapter.time, "time", lambda: NOW)
    return MT5Adapter(mt5_module=terminal, db_path=tmp_path / "qts.db")


def test_returns_only_completed_bars_and_excludes_the_forming_bar(tmp_path, monkeypatch):
    bars, forming = _completed_and_forming(NOW, OFFSET, completed=6)
    terminal = FakeTerminal(now=NOW, bars=bars)
    adapter = _adapter(tmp_path, monkeypatch, terminal)

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10)

    assert window["ok"] is True, window
    assert window["basis"] in {"measured-fresh-tick", "measured-m1-bar"}
    assert window["server_utc_offset_s"] == OFFSET
    assert window["forming_bar_excluded"] is True
    assert window["dropped_uncompleted"] == 1
    returned = [boundary for boundary, _close in window["bars"]]
    assert returned == sorted(returned)
    assert returned[-1] == datetime.fromtimestamp(forming - OFFSET - SPAN_S, tz=UTC)
    assert datetime.fromtimestamp(forming - OFFSET, tz=UTC) not in returned
    # Ascending closes for the six completed bars, newest last.
    assert window["bars"][-1][1] == Decimal("4005")


def test_window_is_bounded_by_the_requested_count(tmp_path, monkeypatch):
    bars, _forming = _completed_and_forming(NOW, OFFSET, completed=40)
    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, bars=bars))

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=5)

    assert window["ok"] is True
    assert len(window["bars"]) == 5
    assert window["requested_bars"] == 5


def test_hard_cap_bounds_a_hostile_request(tmp_path, monkeypatch):
    bars, _forming = _completed_and_forming(NOW, OFFSET, completed=3)
    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, bars=bars))

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10_000_000)

    assert window["ok"] is True
    assert window["requested_bars"] == adapter.MAX_WARMUP_BARS


def test_duplicates_and_malformed_bars_are_dropped_not_trusted(tmp_path, monkeypatch):
    bars, forming = _completed_and_forming(NOW, OFFSET, completed=4)
    duplicate = bars[0]
    bars = [duplicate, *bars, (forming - SPAN_S * 5, 0.0), (forming - SPAN_S * 6, None)]
    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, bars=bars))

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10)

    assert window["ok"] is True
    boundaries = [boundary for boundary, _close in window["bars"]]
    assert len(boundaries) == len(set(boundaries)) == 4
    assert window["dropped_malformed"] == 2


def test_unmeasured_server_clock_refuses_the_window(tmp_path, monkeypatch):
    bars, _forming = _completed_and_forming(NOW, OFFSET, completed=4)
    # No tick and no M1 bar: the adapter cannot measure the broker clock, so the
    # normalized boundary cannot be trusted.
    terminal = FakeTerminal(now=NOW, bars=bars, tick=False, m1_bar=False)
    adapter = _adapter(tmp_path, monkeypatch, terminal)

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10)

    assert window["ok"] is False
    assert "not measured" in window["error"]


def test_unavailable_rates_never_become_bars(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, rates_missing=True))
    missing = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10)
    assert missing["ok"] is False
    assert "no M15 rates" in missing["error"]

    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, rates_error=True))
    error = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10)
    assert error["ok"] is False
    assert "rate request failed" in error["error"]


def test_a_window_with_no_completed_bars_is_not_a_window(tmp_path, monkeypatch):
    forming = floor_to(NOW + OFFSET, SPAN_S)
    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, bars=[(forming, 4000.0)]))

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=15, count=10)

    assert window["ok"] is False
    assert "no completed M15 bars" in window["error"]


@pytest.mark.parametrize(
    "timeframe,count",
    [(15, 0), (15, -3), (7, 10), (0, 10), ("x", 10)],
)
def test_invalid_warmup_requests_are_refused(tmp_path, monkeypatch, timeframe, count):
    bars, _forming = _completed_and_forming(NOW, OFFSET, completed=2)
    adapter = _adapter(tmp_path, monkeypatch, FakeTerminal(now=NOW, bars=bars))

    window = adapter.recent_closed_bars("XAUUSD", timeframe_minutes=timeframe, count=count)

    assert window["ok"] is False
    assert "invalid warmup request" in window["error"]
