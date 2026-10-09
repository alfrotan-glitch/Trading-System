"""Exit rules: a stop-loss strategy must be backtested as a stop-loss strategy.

Without declared exits, the only thing that closes a position is an opposite
signal. That turns every stop-loss strategy into a naked always-in reversal
system — a different strategy wearing the same name, producing confident
evidence about the wrong thing.

These tests pin the exit conventions:

* time exits fill at the bar's open, and are considered FIRST;
* stop exits fill at the stop level, or at the open when the bar gapped
  through it — a stop is an order, not a guarantee;
* exits are priced by the matching engine, so an exit pays costs like an entry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.backtest.engine import BacktestEngine, _parse_exit_rules
from qts.domain.value_objects import Bar, Instrument, Position, Side

SYMBOL = "XAUUSD"


def _instrument() -> Instrument:
    return Instrument(symbol=SYMBOL)


def _bar(open: str, high: str, low: str, close: str, minute: int = 0) -> Bar:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return Bar(
        instrument=_instrument(),
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
        open_time=start,
        close_time=start + timedelta(minutes=1),
        data_version="test",
        source="test",
    )


def _position(quantity: str, avg_price: str) -> Position:
    return Position(instrument=_instrument(), quantity=Decimal(quantity), avg_price=Decimal(avg_price))


class _StubPortfolio:
    def __init__(self, positions: dict[str, Position]):
        self.positions = positions


def _exits(
    *,
    bar: Bar,
    idx: int,
    position: Position | None,
    entry_index: dict | None = None,
    stop_distance: float | None = None,
    max_hold: int | None = None,
    seq: int = 0,
) -> list[tuple]:
    engine = BacktestEngine.__new__(BacktestEngine)
    portfolio = _StubPortfolio({SYMBOL: position} if position is not None else {})
    return engine._exit_intents(
        bar=bar,
        idx=idx,
        portfolio=portfolio,
        entry_index=entry_index if entry_index is not None else {SYMBOL: (0, 1 if position.quantity > 0 else -1)},
        stop_distance=stop_distance,
        max_hold=max_hold,
        strategy_id="test",
        seq=seq,
    )


# --------------------------------------------------------------------- stop


def test_a_long_is_stopped_out_when_the_bar_trades_through_the_level():
    # entered at 2000, 3.00 stop -> 1997
    position = _position("0.1", "2000")
    bar = _bar("1999", "1999.5", "1996", "1996.5")
    exits = _exits(bar=bar, idx=1, position=position, stop_distance=3.0)
    assert len(exits) == 1
    intent, reason, exit_bar = exits[0]
    assert reason == "exit_stop"
    assert intent.side is Side.SELL
    assert intent.quantity == Decimal("0.1")
    # Fill reference is the stop level itself: the bar opened above it.
    assert exit_bar.close == Decimal("1997")


def test_a_short_is_stopped_out_when_the_bar_trades_through_the_level():
    position = _position("-0.1", "2000")
    bar = _bar("2001", "2003.5", "2000.5", "2003")
    exits = _exits(bar=bar, idx=1, position=position, stop_distance=3.0)
    assert len(exits) == 1
    intent, reason, exit_bar = exits[0]
    assert reason == "exit_stop"
    assert intent.side is Side.BUY  # buying back a short
    assert exit_bar.close == Decimal("2003")


def test_a_gap_through_the_stop_fills_at_the_open_not_the_level():
    """A stop is not a guarantee. You get the first price that trades."""
    position = _position("0.1", "2000")
    # Opens at 1990, already 10 below the 1997 stop.
    bar = _bar("1990", "1992", "1988", "1991")
    exits = _exits(bar=bar, idx=1, position=position, stop_distance=3.0)
    assert len(exits) == 1
    _, _, exit_bar = exits[0]
    assert exit_bar.close == Decimal("1990")  # the open, not the stop level


def test_a_short_gap_through_the_stop_fills_at_the_open():
    position = _position("-0.1", "2000")
    bar = _bar("2010", "2012", "2008", "2011")
    exits = _exits(bar=bar, idx=1, position=position, stop_distance=3.0)
    _, _, exit_bar = exits[0]
    assert exit_bar.close == Decimal("2010")


def test_no_exit_when_the_bar_never_reaches_the_stop():
    position = _position("0.1", "2000")
    bar = _bar("2001", "2002", "1999", "2001.5")  # low 1999 > stop 1997
    assert _exits(bar=bar, idx=1, position=position, stop_distance=3.0) == []


# --------------------------------------------------------------------- time


def test_a_time_exit_fills_at_this_bars_open():
    position = _position("0.1", "2000")
    bar = _bar("2010", "2011", "2009", "2010.5")
    exits = _exits(bar=bar, idx=4, position=position, max_hold=4, entry_index={SYMBOL: (0, 1)})
    assert len(exits) == 1
    intent, reason, exit_bar = exits[0]
    assert reason == "exit_time"
    assert exit_bar.close == Decimal("2010")  # the open


def test_the_clock_is_measured_from_the_entry_bar():
    position = _position("0.1", "2000")
    bar = _bar("2010", "2011", "2009", "2010.5")
    # Held 2 bars with a 4-bar limit -> no exit.
    assert _exits(bar=bar, idx=2, position=position, max_hold=4, entry_index={SYMBOL: (0, 1)}) == []
    # Held 4 bars -> exit.
    assert len(_exits(bar=bar, idx=4, position=position, max_hold=4, entry_index={SYMBOL: (0, 1)})) == 1


def test_time_wins_when_both_rules_trigger_on_the_same_bar():
    """Deterministic ordering: the clock settles the bar, not the stop."""
    position = _position("0.1", "2000")
    bar = _bar("1990", "1992", "1980", "1991")  # gaps through the stop too
    exits = _exits(
        bar=bar,
        idx=4,
        position=position,
        entry_index={SYMBOL: (0, 1)},
        stop_distance=3.0,
        max_hold=4,
    )
    assert len(exits) == 1
    _, reason, _ = exits[0]
    assert reason == "exit_time"


# ------------------------------------------------------------------ general


def test_a_flat_position_produces_no_exit():
    position = _position("0", "2000")
    bar = _bar("1990", "1992", "1980", "1991")
    assert _exits(bar=bar, idx=5, position=position, stop_distance=3.0, max_hold=1) == []


def test_no_rules_declared_means_no_exits():
    position = _position("0.1", "2000")
    bar = _bar("1990", "1992", "1980", "1991")
    assert _exits(bar=bar, idx=1, position=position) == []


def test_the_exit_quantity_closes_the_whole_position():
    position = _position("-0.25", "2000")
    bar = _bar("2010", "2011", "2009", "2010.5")
    (intent, _, _) = _exits(bar=bar, idx=9, position=position, max_hold=2, entry_index={SYMBOL: (0, -1)})[0]
    assert intent.quantity == Decimal("0.25")


def test_exit_client_order_ids_are_unique_per_bar_and_reason():
    """Idempotency depends on it: two exits must never share an id."""
    position = _position("0.1", "2000")
    bar = _bar("1996", "1997", "1990", "1992")
    a = _exits(bar=bar, idx=1, position=position, stop_distance=3.0, seq=0)[0][0]
    b = _exits(bar=bar, idx=1, position=position, stop_distance=3.0, seq=1)[0][0]
    assert a.client_order_id != b.client_order_id


# ---------------------------------------------------------- entry bookkeeping


def test_the_entry_clock_restarts_when_a_position_flips():
    index: dict = {}
    portfolio = _StubPortfolio({SYMBOL: _position("0.1", "2000")})
    BacktestEngine._sync_entry_index(portfolio, index, 5)
    assert index[SYMBOL] == (5, 1)

    # Same direction, later bar -> the clock is NOT restarted.
    BacktestEngine._sync_entry_index(portfolio, index, 9)
    assert index[SYMBOL] == (5, 1)

    # Flip to short -> new position, new clock.
    portfolio.positions[SYMBOL] = _position("-0.1", "2010")
    BacktestEngine._sync_entry_index(portfolio, index, 12)
    assert index[SYMBOL] == (12, -1)


def test_going_flat_clears_the_clock():
    index: dict = {}
    portfolio = _StubPortfolio({SYMBOL: _position("0.1", "2000")})
    BacktestEngine._sync_entry_index(portfolio, index, 5)
    portfolio.positions[SYMBOL] = _position("0", "2000")
    BacktestEngine._sync_entry_index(portfolio, index, 8)
    assert SYMBOL not in index


# --------------------------------------------------------------- parsing


def test_exit_rules_are_included_in_the_run_configuration_hash():
    """A run with a stop and a run without one are different experiments."""
    import inspect

    source = inspect.getsource(BacktestEngine.run)
    assert '"exit_rules": exit_rules or {}' in source


@pytest.mark.parametrize(
    "rules,expected",
    [
        (None, (None, None)),
        ({}, (None, None)),
        ({"stop_distance_usd": "3.0"}, (3.0, None)),
        ({"max_hold_bars": 16}, (None, 16)),
    ],
)
def test_exit_rule_parsing(rules, expected):
    assert _parse_exit_rules(rules) == expected


def test_non_finite_stop_is_refused():
    with pytest.raises(ValueError):
        _parse_exit_rules({"stop_distance_usd": float("nan")})
    with pytest.raises(ValueError):
        _parse_exit_rules({"stop_distance_usd": float("inf")})
