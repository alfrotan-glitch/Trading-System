from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.domain.value_objects import Bar, Instrument, OrderIntent, OrderType, Side, Tick


def test_bar_invariants():
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    bar = Bar(
        instrument=instr,
        open=Decimal("2000"),
        high=Decimal("2010"),
        low=Decimal("1995"),
        close=Decimal("2005"),
        open_time=now,
        close_time=now + timedelta(minutes=60),
    )
    assert bar.high >= bar.low


def test_bar_rejects_naive_datetime():
    instr = Instrument(symbol="XAUUSD")
    naive = datetime.now()
    with pytest.raises(ValueError):
        Bar(
            instrument=instr,
            open=Decimal("2000"),
            high=Decimal("2010"),
            low=Decimal("1990"),
            close=Decimal("2000"),
            open_time=naive,
            close_time=naive,
        )


def test_bar_rejects_high_low_inversion():
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        Bar(
            instrument=instr,
            open=Decimal("2000"),
            high=Decimal("1990"),
            low=Decimal("2000"),
            close=Decimal("2005"),
            open_time=now,
            close_time=now + timedelta(minutes=60),
        )


def test_tick_spread():
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    tick = Tick(instrument=instr, bid=Decimal("2000"), ask=Decimal("2000.5"), event_time=now)
    assert tick.spread == Decimal("0.5")
    assert tick.mid == Decimal("2000.25")


def test_tick_rejects_crossed():
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        Tick(instrument=instr, bid=Decimal("2001"), ask=Decimal("2000"), event_time=now)


def test_order_intent_requires_price_for_limit():
    instr = Instrument(symbol="XAUUSD")
    with pytest.raises(ValueError):
        OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            order_type=OrderType.LIMIT,
            client_order_id="a",
            strategy_id="s",
        )


def test_instrument_symbol_upper():
    instr = Instrument(symbol="xauusd")
    assert instr.symbol == "XAUUSD"
