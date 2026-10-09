"""The MT5 history-depth probe — the question that decides the 15m blocker.

The blocker rests on a number that was never measured: "the broker gives 30
days". That came from one oversized request per window. An oversized request
failing is what a REQUEST-SIZE limit looks like; it is not a RETENTION limit,
and the acquisition layer already banks on the difference by chunking at 24h
and halving on failure.

These tests pin that the probe asks the two questions separately, reports
"unavailable" instead of throwing, and never calls an order API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from qts.data.mt5_depth import (
    BAR_PROBE_COUNTS,
    DEFAULT_TICK_PROBE_AGES_DAYS,
    markdown,
    probe,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class Terminal:
    """A simulated terminal whose bar and tick depth are configurable."""

    def __init__(
        self,
        *,
        bars_available: int = 0,
        tick_rows_by_age: dict[int, int] | None = None,
        bars_raise: bool = False,
        no_bar_api: bool = False,
        no_tick_api: bool = False,
    ) -> None:
        # Every attribute must be set before __getattr__ can be reached, or
        # the lookup for one of these recurses.
        self.bars_available = bars_available
        self.tick_rows_by_age = tick_rows_by_age or {}
        self.bars_raise = bars_raise
        self._no_bar_api = no_bar_api
        self._no_tick_api = no_tick_api
        self.calls: list[tuple[str, tuple]] = []
        self.TIMEFRAME_M15 = 15
        self.COPY_TICKS_ALL = 1

    def __getattr__(self, name: str):
        """Expose the read APIs conditionally, so "absent" means AttributeError.

        The probe uses ``getattr(mt5, name, None)``, so a genuinely missing
        function must raise AttributeError -- which is exactly what a terminal
        that does not expose one does.
        """
        if name == "copy_rates_from_pos" and not self._no_bar_api:
            return self._bars
        if name == "copy_ticks_range" and not self._no_tick_api:
            return self._ticks
        raise AttributeError(name)

    def _bars(self, symbol, timeframe, start, count):
        self.calls.append(("bars", (symbol, timeframe, start, count)))
        if self.bars_raise:
            raise RuntimeError("Terminal: Call failed")
        n = max(0, min(count, self.bars_available))
        return [SimpleNamespace(time=0)] * n

    def _ticks(self, symbol, start, end, flags):
        self.calls.append(("ticks", (symbol, start, end, flags)))
        age = round((NOW - end).total_seconds() / 86400)
        return [SimpleNamespace(bid=1.0, ask=1.1)] * self.tick_rows_by_age.get(age, 0)


# --------------------------------------------------------------------------- #
# bar depth
# --------------------------------------------------------------------------- #


def test_a_terminal_with_deep_bar_history_meets_the_minimum() -> None:
    """The finding that would unblock the benchmark, if the terminal has it."""
    report = probe(Terminal(bars_available=60_000), "XAUUSD@", now=NOW)
    assert report.max_bar_rows is not None and report.max_bar_rows >= 5000
    assert report.bar_depth_sufficient is True
    assert any("sufficient" in n for n in report.notes)


def test_a_terminal_with_shallow_bar_history_says_so() -> None:
    report = probe(Terminal(bars_available=1_200), "XAUUSD@", now=NOW)
    assert report.max_bar_rows == 1200
    assert report.bar_depth_sufficient is False
    assert any("below the 5,000-bar minimum" in n for n in report.notes)


def test_bar_probing_stops_ascending_once_the_terminal_cannot_fill() -> None:
    """No point asking for 100k bars once 5k already came back short."""
    terminal = Terminal(bars_available=1_200)
    probe(terminal, "XAUUSD@", now=NOW)
    bar_calls = [c for c in terminal.calls if c[0] == "bars"]
    assert len(bar_calls) == 1, "should stop after the first short response"
    assert bar_calls[0][1][3] == BAR_PROBE_COUNTS[0]


def test_bar_probing_keeps_ascending_while_the_terminal_keeps_filling() -> None:
    terminal = Terminal(bars_available=500_000)
    probe(terminal, "XAUUSD@", now=NOW)
    assert len([c for c in terminal.calls if c[0] == "bars"]) == len(BAR_PROBE_COUNTS)


def test_a_failing_bar_query_is_reported_not_raised() -> None:
    report = probe(Terminal(bars_raise=True), "XAUUSD@", now=NOW)
    bar = [o for o in report.observations if o.probe == "bars"][0]
    assert bar.status == "QUERY_ERROR"
    assert "Terminal: Call failed" in bar.detail


def test_a_missing_bar_api_is_unavailable_not_zero() -> None:
    report = probe(Terminal(no_bar_api=True), "XAUUSD@", now=NOW)
    bar = [o for o in report.observations if o.probe == "bars"][0]
    assert bar.status == "UNAVAILABLE"
    assert report.max_bar_rows is None


# --------------------------------------------------------------------------- #
# tick depth — small windows, not one huge request
# --------------------------------------------------------------------------- #


def test_tick_probing_uses_small_windows_at_increasing_age() -> None:
    """The whole design point: never conflate request size with retention."""
    terminal = Terminal(tick_rows_by_age={7: 500, 30: 400, 365: 300})
    probe(terminal, "XAUUSD@", now=NOW)
    tick_calls = [c for c in terminal.calls if c[0] == "ticks"]
    assert len(tick_calls) == len(DEFAULT_TICK_PROBE_AGES_DAYS)
    for _name, (_, start, end, _flags) in tick_calls:
        assert (end - start).total_seconds() == 3600, "each probe is a 1h window"


def test_oldest_age_with_tick_data_is_reported() -> None:
    terminal = Terminal(tick_rows_by_age={7: 100, 30: 100, 90: 100, 180: 0, 365: 0, 730: 0})
    report = probe(terminal, "XAUUSD@", now=NOW)
    assert report.oldest_tick_age_days == 90


def test_history_older_than_the_suspected_ceiling_would_be_found() -> None:
    """If data exists at 730 days, the '30-day retention' reading was wrong."""
    terminal = Terminal(tick_rows_by_age=dict.fromkeys(DEFAULT_TICK_PROBE_AGES_DAYS, 50))
    report = probe(terminal, "XAUUSD@", now=NOW)
    assert report.oldest_tick_age_days == max(DEFAULT_TICK_PROBE_AGES_DAYS)


def test_a_missing_tick_api_is_unavailable_not_zero() -> None:
    report = probe(Terminal(no_tick_api=True), "XAUUSD@", now=NOW)
    tick = [o for o in report.observations if o.probe == "ticks"][0]
    assert tick.status == "UNAVAILABLE"


# --------------------------------------------------------------------------- #
# safety and reporting
# --------------------------------------------------------------------------- #


def test_no_module_yields_a_report_that_explains_itself() -> None:
    report = probe(None, "XAUUSD@", now=NOW)
    assert report.observations == []
    assert any("Windows machine" in n for n in report.notes)
    assert report.bar_depth_sufficient is False


def test_the_probe_never_calls_an_order_api() -> None:
    terminal = Terminal(bars_available=10_000, tick_rows_by_age={7: 10})
    probe(terminal, "XAUUSD@", now=NOW)
    assert report_calls_only_reads(terminal.calls)
    assert not hasattr(terminal, "order_send")


def report_calls_only_reads(calls: list) -> bool:
    return all(name in ("bars", "ticks") for name, _ in calls)


def test_the_report_declares_zero_orders() -> None:
    report = probe(Terminal(bars_available=10_000), "XAUUSD@", now=NOW)
    payload = report.as_dict()
    assert payload["orders_submitted"] == 0
    assert payload["order_apis_called"] == []


def test_the_report_is_json_serialisable() -> None:
    import json

    report = probe(Terminal(bars_available=10_000, tick_rows_by_age={7: 5}), "XAUUSD@", now=NOW)
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["schema"] == "qts.mt5_depth_probe.v1"


def test_the_markdown_states_the_verdict() -> None:
    text = markdown(probe(Terminal(bars_available=60_000), "XAUUSD@", now=NOW))
    assert "Bar depth sufficient" in text
    assert "YES" in text
    assert "Orders submitted:** 0" in text


def test_the_markdown_reports_no_when_shallow() -> None:
    text = markdown(probe(Terminal(bars_available=100), "XAUUSD@", now=NOW))
    assert "NO" in text


@pytest.mark.parametrize("bars", [0, 4999, 5000, 5001])
def test_the_sufficiency_boundary_is_exact(bars: int) -> None:
    report = probe(Terminal(bars_available=bars), "XAUUSD@", now=NOW)
    assert report.bar_depth_sufficient is (bars >= 5000)
