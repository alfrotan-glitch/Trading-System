import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from qts.adapters.base import BrokerAdapter
from qts.adapters.matching import MatchingEngine
from qts.adapters.paper_adapter import RealisticPaperBroker
from qts.domain.value_objects import Account, Bar, Instrument, OrderIntent, Position, Side
from qts.execution.engine import ExecutionEngine, OrderManager
from qts.portfolio.portfolio import Portfolio
from qts.risk.engine import RiskEngine, RiskLimits


class FakeVenueAdapter(BrokerAdapter):
    def __init__(self):
        self._positions: dict[str, Position] = {}

    def submit(self, intent):  # type: ignore[no-untyped-def]
        from qts.domain.value_objects import Order, OrderState, uuid7

        return Order(
            order_id=uuid7(),
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            state=OrderState.ACCEPTED,
            strategy_id=intent.strategy_id,
        )

    def positions(self):  # type: ignore[no-untyped-def]
        return list(self._positions.values())

    def account(self):  # type: ignore[no-untyped-def]
        return Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD")

    def set_position(self, pos: Position):
        self._positions[pos.instrument.symbol] = pos


def _bar():
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    return Bar(
        instrument=instr,
        open=Decimal("2000"),
        high=Decimal("2010"),
        low=Decimal("1990"),
        close=Decimal("2005"),
        volume=Decimal("1000"),
        open_time=now,
        close_time=now + timedelta(minutes=60),
    )


def test_reconcile_none():
    with tempfile.TemporaryDirectory() as tmp:
        om = OrderManager()
        matching = MatchingEngine()
        risk = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        broker = RealisticPaperBroker(matching=matching)
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        eng = ExecutionEngine(om, risk, broker, matching, portfolio)
        bar = _bar()
        intent = OrderIntent(
            instrument=bar.instrument,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        eng.submit_intent(intent, bar=bar)
        report = eng.reconcile()
        assert report.drift == "NONE"
        assert not report.requires_suspend


def test_reconcile_mismatch_detected():
    with tempfile.TemporaryDirectory() as tmp:
        om = OrderManager()
        matching = MatchingEngine()
        risk = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        venue = FakeVenueAdapter()
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        eng = ExecutionEngine(om, risk, venue, matching, portfolio)
        bar = _bar()
        intent = OrderIntent(
            instrument=bar.instrument,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        eng.submit_intent(intent, bar=bar)
        # For FakeVenue, fills are not auto-applied (only PaperBroker), so portfolio stays flat unless we manually apply.
        # Inject mismatch: set venue position to 0.5, local to 0.1 via portfolio
        instr = bar.instrument
        venue.set_position(Position(instrument=instr, quantity=Decimal("0.5"), avg_price=Decimal("2000")))
        portfolio.positions["XAUUSD"] = Position(instrument=instr, quantity=Decimal("0.1"), avg_price=Decimal("2000"))
        # portfolio also needs mark price for notional, but reconcile only checks qty
        report = eng.reconcile()
        assert report.drift == "QUANTITY_MISMATCH"
        assert report.requires_suspend


def test_reconcile_unknown_position():
    with tempfile.TemporaryDirectory() as tmp:
        om = OrderManager()
        matching = MatchingEngine()
        risk = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        venue = FakeVenueAdapter()
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        eng = ExecutionEngine(om, risk, venue, matching, portfolio)
        instr = Instrument(symbol="XAUUSD")
        venue.set_position(Position(instrument=instr, quantity=Decimal("0.3"), avg_price=Decimal("2000")))
        report = eng.reconcile()
        assert report.drift == "UNKNOWN_POSITION"
        assert report.requires_suspend
