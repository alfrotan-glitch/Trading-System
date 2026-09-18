"""Property-based tests with hypothesis."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from qts.data.quality import validate_bars
from qts.domain.value_objects import Bar, Instrument


@st.composite
def bar_strategy(draw):
    price = draw(st.decimals(min_value=Decimal("1000"), max_value=Decimal("3000"), places=2))
    spread = draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("20"), places=2))
    high = price + spread
    low = price - spread
    # ensure high >= low
    if high < price:
        high = price
    if low > price:
        low = price
    base = datetime(2024, 1, 1, tzinfo=UTC)
    offset = draw(st.integers(min_value=0, max_value=10000))
    ot = base + timedelta(minutes=offset)
    ct = ot + timedelta(minutes=60)
    instr = Instrument(symbol="XAUUSD")
    return Bar(
        instrument=instr,
        open=price,
        high=high,
        low=low,
        close=price,
        volume=Decimal(str(draw(st.integers(min_value=0, max_value=5000)))),
        open_time=ot,
        close_time=ct,
    )


@settings(max_examples=50)
@given(bar_strategy())
def test_bar_high_low_invariant(bar):
    assert bar.high >= bar.low
    assert bar.high >= bar.open
    assert bar.low <= bar.open


@settings(max_examples=30)
@given(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("10"), places=2))
def test_risk_never_exceeds_after_veto(qty):
    import tempfile
    from pathlib import Path

    from qts.domain.value_objects import Account, Instrument, OrderIntent, Side
    from qts.risk.engine import RiskContext, RiskEngine, RiskLimits

    with tempfile.TemporaryDirectory() as tmp:
        eng = RiskEngine(
            RiskLimits(max_quantity=Decimal("1.0"), max_notional=Decimal("100000")),
            db_path=Path(tmp) / "db.sqlite",
        )
        instr = Instrument(symbol="XAUUSD")
        intent = OrderIntent(instrument=instr, side=Side.BUY, quantity=qty, client_order_id="c1", strategy_id="s")
        ctx = RiskContext(
            account=Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD"),
            positions={},
            open_orders_count=0,
            daily_pnl=Decimal("0"),
            drawdown=Decimal("0"),
            instrument_suspended=set(),
            reference_prices={"XAUUSD": Decimal("2000")},
        )
        d = eng.pre_trade(intent, ctx)
        if d.allowed:
            final_qty = d.resized_quantity or qty
            assert final_qty <= Decimal("1.0")


@settings(max_examples=20)
@given(st.lists(bar_strategy(), min_size=2, max_size=20))
def test_bars_sorted_monotonic_after_sort(bars):
    # deduplicate open_time for test
    unique = {}
    for b in bars:
        unique[b.open_time] = b
    dedup = sorted(unique.values(), key=lambda b: b.open_time)
    report = validate_bars(dedup)
    # should pass monotonic if deduped and sorted
    assert any(c.name == "monotonic_time" and c.passed for c in report.checks)
