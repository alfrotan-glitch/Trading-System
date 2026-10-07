from decimal import Decimal

from qts.domain.value_objects import Account, Instrument, OrderIntent, Position, Side
from qts.risk.engine import RiskEngine, RiskLimits, RiskVetoReason, RiskContext


def _instrument() -> Instrument:
    return Instrument(symbol="XAUUSD", contract_size=Decimal("100"), lot_size=Decimal("0.01"))


def _intent(side: Side, quantity: str) -> OrderIntent:
    return OrderIntent(
        instrument=_instrument(),
        side=side,
        quantity=Decimal(quantity),
        client_order_id=f"risk-{side.value.lower()}-{quantity}",
        strategy_id="test",
    )


def _ctx(position: Position | None, equity: str = "1000") -> RiskContext:
    return RiskContext(
        account=Account(
            balance=Decimal(equity),
            equity=Decimal(equity),
            currency="USD",
            source="PAPER_SIMULATION",
        ),
        positions={position.instrument.symbol: position} if position else {},
        open_orders_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        instrument_suspended=set(),
        reference_prices={"XAUUSD": Decimal("3000")},
    )


def test_leverage_uses_post_trade_gross_exposure_for_reduction(tmp_path):
    instrument = _instrument()
    position = Position(
        instrument=instrument,
        quantity=Decimal("1"),
        avg_price=Decimal("3000"),
    )
    engine = RiskEngine(
        RiskLimits(
            max_quantity=Decimal("2"),
            max_exposure_lots=Decimal("2"),
            max_leverage=Decimal("2"),
        ),
        db_path=tmp_path / "risk.db",
    )

    decision = engine.pre_trade(_intent(Side.SELL, "0.9"), _ctx(position))

    assert decision.allowed is True


def test_existing_position_without_reference_price_blocks_leverage(tmp_path):
    instrument = _instrument()
    other = Instrument(symbol="EURUSD", contract_size=Decimal("100000"), lot_size=Decimal("0.01"))
    position = Position(instrument=other, quantity=Decimal("0.1"), avg_price=Decimal("1.1"))
    engine = RiskEngine(
        RiskLimits(max_leverage=Decimal("100")),
        db_path=tmp_path / "risk.db",
    )
    ctx = _ctx(None)
    ctx = ctx.model_copy(update={"positions": {"EURUSD": position}})

    decision = engine.pre_trade(_intent(Side.BUY, "0.01"), ctx)

    assert decision.allowed is False
    assert decision.veto_reason is RiskVetoReason.MISSING_MARKET_PRICE


def test_market_order_uses_reference_price_not_stop_trigger(tmp_path):
    engine = RiskEngine(
        RiskLimits(max_notional=Decimal("10000")),
        db_path=tmp_path / "risk.db",
    )
    intent = _intent(Side.BUY, "0.01").model_copy(
        update={"stop_price": Decimal("1")}
    )

    decision = engine.pre_trade(intent, _ctx(None))

    assert decision.allowed is True
    assert decision.price == Decimal("3000")
    assert decision.price_source == "reference_prices"
