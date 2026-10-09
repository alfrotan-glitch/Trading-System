"""A backtest that stops early must SAY so.

The risk engine's kill switch is terminal: once it fires, every later intent is
vetoed and the engine walks the remaining bars doing nothing. Before this test
existed the result looked like a complete backtest — same field names, same
summary numbers, a plausible equity curve — while only the first 18% of the
series had actually been traded.

That is the most dangerous failure mode in this repository, because it is
silent and it flatters the result. A run that stops at its first drawdown never
records the drawdown that stopped it. It reports the strategy's best stretch
and calls it the strategy.

These tests pin the contract:

* a kill is recorded as ``halted`` with the bar it happened on;
* ``bars_traded`` tells the caller how much of the series is real;
* a strategy evaluated over the whole series actually trades the whole series.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.backtest.engine import BacktestEngine
from qts.domain.value_objects import Bar, Instrument
from qts.risk.engine import RiskEngine

SYMBOL = "XAUUSD"


def _instrument() -> Instrument:
    return Instrument(symbol=SYMBOL)


def _bars(n: int = 60) -> list[Bar]:
    """A sawtooth series: five bars up, five bars down, repeat.

    Needed because a monotone ramp triggers no Donchian breakout at all, and a
    test that trades zero times cannot tell a truncated run from a full one.
    """
    out = []
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    for i in range(n):
        t = start + timedelta(minutes=15 * i)
        phase = i % 10
        leg = phase if phase < 5 else 9 - phase
        px = Decimal("2000") + Decimal(str(leg * 5))
        out.append(
            Bar(
                instrument=_instrument(),
                open=px,
                high=px + Decimal("2"),
                low=px - Decimal("2"),
                close=px + Decimal("1"),
                volume=Decimal("100"),
                open_time=t,
                close_time=t + timedelta(minutes=15),
                data_version="test",
                source="test",
            )
        )
    return out


class _StubManifest:
    checksum = "test-manifest-checksum"
    instrument = SYMBOL
    timeframe = "15m"


class _StubStore:
    """Minimal store: hands back the bars we built and nothing else."""

    def __init__(self, bars: list[Bar], db_path: str = ":memory:") -> None:
        self._bars = bars
        self.db_path = db_path

    def read_bars(self, *args, **kwargs):  # noqa: ARG002 - signature compatibility
        return list(self._bars)

    def manifest(self, *args, **kwargs):  # noqa: ARG002 - signature compatibility
        return _StubManifest()


@pytest.fixture
def kill_at(monkeypatch):
    """Force the kill switch on once the call counter passes a threshold."""

    def install(after: int):
        state = {"n": 0}
        real = RiskEngine.killed.fget

        def fake(self):
            state["n"] += 1
            return state["n"] > after or real(self)

        monkeypatch.setattr(RiskEngine, "killed", property(fake))
        return state

    return install


def _run(store, **kwargs) -> object:
    engine = BacktestEngine(data_store=store)
    return engine.run(
        instrument=_instrument(),
        timeframe="15m",
        data_version="test",
        strategy_id="test",
        strategy_params={"_family": "breakout", "period": 5, "quantity": 0.01},
        **kwargs,
    )


# ------------------------------------------------------------------ contract


def test_an_uninterrupted_run_is_not_marked_halted(tmp_path):
    result = _run(_StubStore(_bars(), str(tmp_path / "t.db")))
    assert result.halted is False
    assert result.halt_reason is None
    assert result.halted_at_bar is None
    assert result.bars_traded == result.bars


def test_a_killed_run_is_recorded_as_halted_with_its_bar(kill_at, tmp_path):
    kill_at(after=10)
    result = _run(_StubStore(_bars(), str(tmp_path / "t.db")))
    assert result.halted is True
    assert result.halted_at_bar is not None
    # The halt is detected on the loop iteration after the kill is observed,
    # so it is well short of the end of a 60-bar series.
    assert result.halted_at_bar < 20
    assert result.halt_reason


def test_a_halted_run_reports_only_the_bars_it_traded(kill_at, tmp_path):
    kill_at(after=10)
    result = _run(_StubStore(_bars(60), str(tmp_path / "t.db")))
    assert result.bars == 60
    assert result.bars_traded is not None
    assert result.bars_traded < 60
    # The whole point: the truncated run must be distinguishable from a full one.
    assert result.bars_traded < result.bars


def test_the_halt_is_reported_before_any_trade_count_is_believed(kill_at, tmp_path):
    """A halted run's trade count describes part of the series, not all of it."""
    store = _StubStore(_bars(60), str(tmp_path / "t.db"))
    # Measure the full series FIRST: the kill patch below is not reversible.
    complete = _run(store)
    kill_at(after=10)
    truncated = _run(store)
    assert complete.halted is False
    assert truncated.halted is True
    # Reporting the truncated count as if it were the strategy's would be the
    # exact bug this module exists to prevent.
    assert truncated.trades < complete.trades
