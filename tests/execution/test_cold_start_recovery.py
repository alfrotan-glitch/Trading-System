"""Cold-start portfolio recovery tests."""

from decimal import Decimal

import pytest

from qts.domain.value_objects import Instrument, Position
from qts.portfolio.portfolio import Portfolio


def _position(symbol: str = "XAUUSD", quantity: str = "0.10", price: str = "2000") -> Position:
    return Position(
        instrument=Instrument(symbol=symbol),
        quantity=Decimal(quantity),
        avg_price=Decimal(price),
    )


def test_restore_open_positions_uses_broker_position_without_history():
    portfolio = Portfolio(initial_balance=Decimal("0"))

    portfolio.restore_open_positions([_position()])

    position = portfolio.get_position("XAUUSD")
    assert position is not None
    assert position.quantity == Decimal("0.10")
    assert position.avg_price == Decimal("2000")


def test_restore_open_positions_rejects_multiple_positions_for_one_symbol():
    portfolio = Portfolio(initial_balance=Decimal("0"))

    with pytest.raises(RuntimeError, match="multiple broker positions"):
        portfolio.restore_open_positions([_position(), _position(price="2001")])


def test_restore_open_positions_cannot_overwrite_local_exposure():
    portfolio = Portfolio(initial_balance=Decimal("0"))
    portfolio.positions["XAUUSD"] = _position()

    with pytest.raises(RuntimeError, match="non-empty local portfolio"):
        portfolio.restore_open_positions([_position(price="2001")])
