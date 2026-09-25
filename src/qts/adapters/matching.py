"""Matching engine for simulated broker execution — spread, slippage, latency, partial fills."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qts.domain.value_objects import Bar, Fill, OrderIntent, Side, Tick, uuid7


@dataclass
class MatchingConfig:
    spread_bps: float = 3.0
    slippage_bps: float = 2.0
    execution_delay_ms: int = 500
    commission_per_lot: float = 0.0
    partial_fill_model: str = "none"  # or volume_based


class MatchingEngine:
    def __init__(self, config: MatchingConfig | None = None):
        self.config = config or MatchingConfig()

    def price_for(
        self,
        side: Side,
        bar: Bar | None,
        tick: Tick | None = None,
        spread_override_bps: float | None = None,
    ) -> Decimal:
        """Return execution price including spread and slippage, adverse to side."""
        if tick:
            base = tick.ask if side == Side.BUY else tick.bid
            # slippage adverse
            slip = Decimal(str(self.config.slippage_bps)) / Decimal("10000") * base
            if side == Side.BUY:
                return base + slip
            else:
                return base - slip
        if bar is None:
            raise ValueError("need bar or tick")
        # bar.close is mid estimate; apply spread half
        spread_bps = spread_override_bps if spread_override_bps is not None else self.config.spread_bps
        spread = Decimal(str(spread_bps)) / Decimal("10000") * bar.close
        slip = Decimal(str(self.config.slippage_bps)) / Decimal("10000") * bar.close
        if side == Side.BUY:
            return bar.close + spread / Decimal("2") + slip
        else:
            return bar.close - spread / Decimal("2") - slip

    def match(
        self,
        intent: OrderIntent,
        bar: Bar,
        tick: Tick | None = None,
        event_time: datetime | None = None,
        spread_override_bps: float | None = None,
    ) -> list[Fill]:
        """Produce fills for intent at bar (or tick). Single fill unless partial."""
        event_time = event_time or bar.close_time or datetime.now(UTC)
        # latency
        fill_time = event_time + timedelta(milliseconds=self.config.execution_delay_ms)
        price = self.price_for(intent.side, bar, tick, spread_override_bps=spread_override_bps)
        # commission
        fee = Decimal(str(self.config.commission_per_lot)) * intent.quantity
        # partial fill logic
        qty = intent.quantity
        if self.config.partial_fill_model == "volume_based" and bar.volume > 0:
            # if quantity > 30% of volume, split into 2 fills
            vol = bar.volume
            if qty > vol * Decimal("0.3"):
                q1 = (qty * Decimal("0.6")).quantize(Decimal("0.01"))
                q2 = qty - q1
                return [
                    Fill(
                        fill_id=uuid7(),
                        order_id=intent.client_order_id,
                        client_order_id=intent.client_order_id,
                        instrument=intent.instrument,
                        side=intent.side,
                        quantity=q1,
                        price=price,
                        fee=fee * Decimal("0.6"),
                        event_time=fill_time,
                    ),
                    Fill(
                        fill_id=uuid7(),
                        order_id=intent.client_order_id,
                        client_order_id=intent.client_order_id,
                        instrument=intent.instrument,
                        side=intent.side,
                        quantity=q2,
                        price=price,
                        fee=fee * Decimal("0.4"),
                        event_time=fill_time + timedelta(milliseconds=100),
                    ),
                ]
        return [
            Fill(
                fill_id=uuid7(),
                order_id=intent.client_order_id,
                client_order_id=intent.client_order_id,
                instrument=intent.instrument,
                side=intent.side,
                quantity=qty,
                price=price,
                fee=fee,
                event_time=fill_time,
            )
        ]
