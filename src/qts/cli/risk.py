"""QTS CLI — risk."""

from __future__ import annotations

from datetime import UTC, datetime

import click

from qts.domain.value_objects import Instrument


@click.group()
def risk() -> None:
    pass


@risk.command("kill")
@click.option("--reason", default="manual")
def risk_kill(reason: str) -> None:
    from qts.risk.engine import RiskEngine, RiskLimits

    eng = RiskEngine(RiskLimits())
    eng.kill_switch(reason)
    click.echo(f"kill active: {reason}")


@risk.command("reset")
@click.option("--confirm", required=True, help="must be 'yes' to reset")
def risk_reset(confirm: str) -> None:
    from qts.risk.engine import RiskEngine, RiskLimits

    if confirm != "yes":
        click.echo("reset requires --confirm yes", err=True)
        raise SystemExit(2)
    eng = RiskEngine(RiskLimits())
    eng.reset_kill()
    click.echo("kill reset")


@risk.command("check")
@click.option("--instrument", default="XAUUSD")
@click.option("--quantity", default=0.1, type=float)
@click.option(
    "--reference-price",
    required=True,
    help="Authoritative current reference price for notional/exposure checks. "
    "REQUIRED — the CLI never assumes a hardcoded market price. Obtain it from your "
    "market data source (e.g. MT5 terminal) and pass it explicitly.",
)
def risk_check(instrument: str, quantity: float, reference_price: str) -> None:
    from decimal import Decimal, InvalidOperation

    from qts.domain.value_objects import Account, OrderIntent
    from qts.risk.engine import RiskContext, RiskEngine, RiskLimits

    try:
        price = Decimal(reference_price)
    except InvalidOperation:
        click.echo(f"invalid --reference-price: {reference_price!r}", err=True)
        raise SystemExit(2) from None
    if price <= 0:
        click.echo("--reference-price must be > 0 (no hardcoded or placeholder prices)", err=True)
        raise SystemExit(2)

    from qts.domain.value_objects import Side

    instr = Instrument(symbol=instrument)
    intent = OrderIntent(
        instrument=instr, side=Side.BUY, quantity=Decimal(str(quantity)), client_order_id="check", strategy_id="check"
    )
    # Reference price is caller-supplied and auditable — never hardcoded here.
    # The account is an explicit LABELED synthetic state for offline checks
    # (this command never reaches a broker).
    ctx = RiskContext(
        account=Account(
            balance=Decimal("10000"),
            equity=Decimal("10000"),
            currency="OFFLINE_CHECK",
            source="CLI_SYNTHETIC",
            updated_at=datetime.now(UTC),
        ),
        positions={},
        open_orders_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        instrument_suspended=set(),
        reference_prices={instrument: price},
    )
    eng = RiskEngine(RiskLimits())
    dec = eng.pre_trade(intent, ctx)
    eng.close()
    click.echo(f"allowed={dec.allowed} veto={dec.veto_reason} detail={dec.reason_detail} notional={dec.reason_detail}")


