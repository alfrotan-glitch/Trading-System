import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from qts.domain.value_objects import Account, Instrument, OrderIntent, OrderType, Side
from qts.risk.engine import RiskContext, RiskEngine, RiskLimits


def _ctx(balance=Decimal("10000"), daily_pnl=Decimal("0"), drawdown=Decimal("0"), open_orders=0, price=Decimal("2000")):
    return RiskContext(
        account=Account(balance=balance, equity=balance, currency="USD", updated_at=datetime.now(UTC)),
        positions={},
        open_orders_count=open_orders,
        daily_pnl=daily_pnl,
        drawdown=drawdown,
        instrument_suspended=set(),
        reference_prices={"XAUUSD": price},
    )


def test_risk_allows_valid():
    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(
            RiskLimits(max_quantity=Decimal("1"), max_notional=Decimal("50000")),
            db_path=Path(tmp) / "db.sqlite",
        )
        instr = Instrument(symbol="XAUUSD")
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET,
            client_order_id="c1",
            strategy_id="s",
        )
        d = eng.pre_trade(intent, _ctx())
        assert d.allowed


def test_risk_veto_quantity():
    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(RiskLimits(max_quantity=Decimal("0.05")), db_path=Path(tmp) / "db.sqlite")
        instr = Instrument(symbol="XAUUSD")
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        d = eng.pre_trade(intent, _ctx())
        assert not d.allowed
        assert d.veto_reason.value == "EXCEEDS_MAX_QUANTITY"


def test_risk_veto_daily_loss():
    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(RiskLimits(daily_loss_limit=Decimal("100")), db_path=Path(tmp) / "db.sqlite")
        instr = Instrument(symbol="XAUUSD")
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        d = eng.pre_trade(intent, _ctx(daily_pnl=Decimal("-150")))
        assert not d.allowed
        assert d.veto_reason.value == "DAILY_LOSS_BREACH"


def test_risk_veto_too_many_orders():
    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(RiskLimits(max_open_orders=1), db_path=Path(tmp) / "db.sqlite")
        instr = Instrument(symbol="XAUUSD")
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        d = eng.pre_trade(intent, _ctx(open_orders=1))
        assert not d.allowed


def test_kill_switch_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        eng.kill_switch("test")
        assert eng.killed
        instr = Instrument(symbol="XAUUSD")
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        d = eng.pre_trade(intent, _ctx())
        assert not d.allowed
        assert d.veto_reason.value == "KILL_SWITCH_ACTIVE"
        eng.reset_kill()
        assert not eng.killed
        d2 = eng.pre_trade(intent, _ctx())
        assert d2.allowed


def test_kill_persists():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "db.sqlite"
        eng = RiskEngine(RiskLimits(), db_path=p)
        eng.kill_switch("persist")
        eng2 = RiskEngine(RiskLimits(), db_path=p)
        assert eng2.killed


def test_exposure_veto():
    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(RiskLimits(max_exposure_lots=Decimal("0.2")), db_path=Path(tmp) / "db.sqlite")
        instr = Instrument(symbol="XAUUSD")
        from qts.domain.value_objects import Position

        pos = Position(instrument=instr, quantity=Decimal("0.15"), avg_price=Decimal("2000"))
        ctx = RiskContext(
            account=Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD", updated_at=datetime.now(UTC)),
            positions={"XAUUSD": pos},
            open_orders_count=0,
            daily_pnl=Decimal("0"),
            drawdown=Decimal("0"),
            instrument_suspended=set(),
            reference_prices={"XAUUSD": Decimal("2000")},
        )
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        d = eng.pre_trade(intent, ctx)
        assert not d.allowed
        assert d.veto_reason.value == "EXCEEDS_EXPOSURE"
