from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.domain.value_objects import Bar, Instrument, Order, OrderIntent, OrderState, OrderType, Side, Tick


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


def _order() -> Order:
    now = datetime.now(UTC)
    return Order(
        order_id="order-1",
        client_order_id="client-1",
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity=Decimal("0.1"),
        order_type=OrderType.MARKET,
        strategy_id="test",
        created_at=now,
        updated_at=now,
    )


def test_order_state_machine_allows_valid_execution_lifecycle():
    order = _order()
    order = order.with_state(OrderState.ACCEPTED)
    order = order.with_state(OrderState.PARTIALLY_FILLED, filled_quantity=Decimal("0.05"))
    order = order.with_state(OrderState.FILLED, filled_quantity=Decimal("0.1"))
    assert order.state is OrderState.FILLED


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (OrderState.PENDING, OrderState.FILLED),
        (OrderState.FILLED, OrderState.PENDING),
        (OrderState.CANCELLED, OrderState.ACCEPTED),
        (OrderState.AMBIGUOUS, OrderState.ACCEPTED),
    ],
)
def test_order_state_machine_rejects_invalid_transition(start: OrderState, target: OrderState):
    order = _order().with_state(start) if start is not OrderState.PENDING else _order()
    with pytest.raises(ValueError, match="invalid order state transition"):
        order.with_state(target)
