import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from qts.domain.value_objects import Account, Bar, Instrument, OrderIntent, Position, Side
from qts.execution.engine import BrokerAdapter, ExecutionEngine, OrderManager, PaperBrokerAdapter
from qts.execution.matching import MatchingEngine
from qts.risk.engine import RiskEngine, RiskLimits


class FakeVenueAdapter(BrokerAdapter):
    def __init__(self):
        self._positions = {}

    def submit(self, intent):
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

    def positions(self):
        return list(self._positions.values())

    def account(self):
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
        broker = PaperBrokerAdapter(matching=matching)
        eng = ExecutionEngine(om, risk, broker, matching)
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


def test_reconcile_mismatch_detected():
    with tempfile.TemporaryDirectory() as tmp:
        om = OrderManager()
        matching = MatchingEngine()
        risk = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        venue = FakeVenueAdapter()
        eng = ExecutionEngine(om, risk, venue, matching)
        bar = _bar()
        intent = OrderIntent(
            instrument=bar.instrument,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        eng.submit_intent(intent, bar=bar)
        # locally we have position via Paper? But FakeVenue doesn't auto-apply fills, so eng.positions has 0.1, venue has 0
        # Actually ExecutionEngine only fills for PaperBrokerAdapter, not FakeVenue. So eng.positions stays 0 for FakeVenue.
        # Inject mismatch: set venue position to different qty
        instr = bar.instrument
        venue.set_position(Position(instrument=instr, quantity=Decimal("0.5"), avg_price=Decimal("2000")))
        # force local to have 0.1

        eng.positions["XAUUSD"] = Position(instrument=instr, quantity=Decimal("0.1"), avg_price=Decimal("2000"))
        report = eng.reconcile()
        assert report.drift == "QUANTITY_MISMATCH"
