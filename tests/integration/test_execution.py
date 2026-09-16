import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from qts.domain.value_objects import Bar, Instrument, OrderIntent, Side
from qts.execution.engine import ExecutionEngine, OrderManager, PaperBrokerAdapter
from qts.execution.matching import MatchingConfig, MatchingEngine
from qts.observability.audit import InMemoryAuditLog
from qts.risk.engine import RiskEngine, RiskLimits


def _bar(close=Decimal("2005")):
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    return Bar(
        instrument=instr,
        open=close,
        high=close + Decimal("5"),
        low=close - Decimal("5"),
        close=close,
        volume=Decimal("1000"),
        open_time=now,
        close_time=now + timedelta(minutes=60),
    )


def test_execution_full_flow():
    with tempfile.TemporaryDirectory() as tmp:
        audit = InMemoryAuditLog()
        om = OrderManager(audit=audit)
        matching = MatchingEngine(MatchingConfig(spread_bps=3, slippage_bps=2))
        risk = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        broker = PaperBrokerAdapter(matching=matching)
        eng = ExecutionEngine(om, risk, broker, matching, audit=audit)
        bar = _bar()
        intent = OrderIntent(
            instrument=bar.instrument,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        order, fills = eng.submit_intent(intent, bar=bar)
        assert order is not None
        assert len(fills) == 1
        assert order.client_order_id == "c1"
        # idempotency
        order2, fills2 = eng.submit_intent(intent, bar=bar)
        assert order2.client_order_id == order.client_order_id
        # risk veto
        risk2 = RiskEngine(RiskLimits(max_quantity=Decimal("0.01")), db_path=Path(tmp) / "db2.sqlite")
        eng2 = ExecutionEngine(OrderManager(), risk2, broker, matching)
        intent_big = OrderIntent(
            instrument=bar.instrument,
            side=Side.BUY,
            quantity=Decimal("0.5"),
            client_order_id="c2",
            strategy_id="s",
        )
        order3, fills3 = eng2.submit_intent(intent_big, bar=bar)
        assert order3 is None
        assert fills3 == []


def test_fill_at_ask_not_mid():
    with tempfile.TemporaryDirectory():  # noqa: SIM115
        matching = MatchingEngine(MatchingConfig(spread_bps=10, slippage_bps=0))
        bar = _bar(close=Decimal("2000"))
        instr = bar.instrument
        intent = OrderIntent(
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="c1",
            strategy_id="s",
        )
        fills = matching.match(intent, bar)
        # BUY should be above close (ask = mid + spread/2)
        assert fills[0].price > bar.close
        intent2 = OrderIntent(
            instrument=instr,
            side=Side.SELL,
            quantity=Decimal("0.1"),
            client_order_id="c2",
            strategy_id="s",
        )
        fills2 = matching.match(intent2, bar)
        assert fills2[0].price < bar.close


def test_latency():
    matching = MatchingEngine(MatchingConfig(execution_delay_ms=2000))
    bar = _bar()
    instr = bar.instrument
    intent = OrderIntent(
        instrument=instr,
        side=Side.BUY,
        quantity=Decimal("0.1"),
        client_order_id="c1",
        strategy_id="s",
    )
    fills = matching.match(intent, bar, event_time=bar.close_time)
    assert fills[0].event_time == bar.close_time + timedelta(milliseconds=2000)
