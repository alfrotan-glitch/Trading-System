from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.domain.value_objects import Bar, Instrument, OrderIntent, Side, Tick
from qts.execution.matching import MatchingConfig, MatchingEngine


def _bar(close=Decimal("2000")):
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


def test_buy_at_ask_plus_slippage():
    eng = MatchingEngine(MatchingConfig(spread_bps=3, slippage_bps=2))
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    tick = Tick(instrument=instr, bid=Decimal("2000"), ask=Decimal("2000.6"), event_time=now)
    price = eng.price_for(Side.BUY, bar=None, tick=tick)
    assert price > tick.ask


def test_sell_at_bid_minus_slippage():
    eng = MatchingEngine(MatchingConfig(spread_bps=3, slippage_bps=2))
    instr = Instrument(symbol="XAUUSD")
    now = datetime.now(UTC)
    tick = Tick(instrument=instr, bid=Decimal("2000"), ask=Decimal("2000.6"), event_time=now)
    price = eng.price_for(Side.SELL, bar=None, tick=tick)
    assert price < tick.bid


def test_spread_override():
    eng = MatchingEngine(MatchingConfig(spread_bps=3))
    bar = _bar()
    p1 = eng.price_for(Side.BUY, bar=bar, spread_override_bps=3)
    p2 = eng.price_for(Side.BUY, bar=bar, spread_override_bps=6)
    assert p2 > p1


def test_match_produces_fill():
    eng = MatchingEngine(MatchingConfig(execution_delay_ms=100))
    bar = _bar()
    instr = Instrument(symbol="XAUUSD")
    intent = OrderIntent(
        instrument=instr,
        side=Side.BUY,
        quantity=Decimal("0.1"),
        client_order_id="c1",
        strategy_id="s",
    )
    fills = eng.match(intent, bar)
    assert len(fills) == 1
    assert fills[0].quantity == Decimal("0.1")


def test_partial_fill_volume_based():
    eng = MatchingEngine(MatchingConfig(partial_fill_model="volume_based"))
    bar = _bar()
    bar = bar.model_copy(update={"volume": Decimal("0.2")})
    instr = Instrument(symbol="XAUUSD")
    intent = OrderIntent(
        instrument=instr,
        side=Side.BUY,
        quantity=Decimal("0.1"),
        client_order_id="c1",
        strategy_id="s",
    )
    fills = eng.match(intent, bar)
    assert len(fills) == 2
    assert sum(f.quantity for f in fills) == Decimal("0.1")
