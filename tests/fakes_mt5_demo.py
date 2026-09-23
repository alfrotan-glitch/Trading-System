"""Shared fake MetaTrader5 terminal for DEMO execution tests.

A stateful stand-in with real order/position/deal semantics: opening an order
creates a position and a deal, closing removes both. It exists so the DEMO
wiring, the autonomous loop and the API can be exercised end to end without a
terminal — never as a way to fake readiness in production code paths.
"""

from __future__ import annotations

import time
from types import SimpleNamespace


class FakeTerminal:
    """A stateful stand-in for MetaTrader5 with real order/position semantics."""

    def __init__(self, *, open_positions: list[SimpleNamespace] | None = None, open_age_s: float = 0.0):
        self.requests: list[dict] = []
        self.positions: list[SimpleNamespace] = list(open_positions or [])
        self.deals: list[SimpleNamespace] = []
        #: How long ago a newly opened position is reported to have been opened.
        self.open_age_s = open_age_s
        self._next_order = 990_001
        self._next_deal = 770_001
        self.account = SimpleNamespace(
            login=123456,
            server="Broker-Demo",
            company="Example Brokers Ltd",
            name="Research Demo",
            trade_mode=0,  # ACCOUNT_TRADE_MODE_DEMO
            trade_allowed=True,
            trade_expert=True,
            currency="USD",
            leverage=100,
            balance=10_000.0,
            equity=10_000.0,
            margin=0.0,
            margin_free=10_000.0,
        )
        self.symbol_spec = SimpleNamespace(
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            digits=2,
            point=0.01,
            tick_size=0.01,
            trade_mode=4,
            filling_mode=1,
            execution_mode=2,
            stops_level=0,
            freeze_level=0,
        )

    # -- market data ---------------------------------------------------------
    def symbol_info_tick(self, name):
        now = time.time()
        return SimpleNamespace(
            time=int(now),
            time_msc=int(now * 1000),
            bid=2000.00,
            ask=2000.20,
            last=2000.00,
            volume=1,
            flags=6,
            volume_real=1.0,
        )

    # -- orders / positions --------------------------------------------------
    def order_send(self, request):
        self.requests.append(dict(request))
        self._next_order += 1
        self._next_deal += 1
        if "position" in request:  # a close
            ticket = int(request["position"])
            self.positions = [p for p in self.positions if p.ticket != ticket]
            self.deals.append(
                SimpleNamespace(
                    ticket=self._next_deal,
                    order=self._next_order,
                    position_id=ticket,
                    symbol=request["symbol"],
                    volume=request["volume"],
                    price=request.get("price", 2000.10),
                    profit=-1.0,
                    # A closing deal mirrors the closing order side (SELL closes a long).
                    type=request["type"],
                    time=time.time(),
                    comment=request.get("comment", ""),
                )
            )
            return SimpleNamespace(
                retcode=10009,
                order=self._next_order,
                deal=self._next_deal,
                price=request.get("price", 2000.0),
                volume=request["volume"],
                comment="Request executed",
            )
        position = SimpleNamespace(
            ticket=self._next_deal,
            symbol=request["symbol"],
            volume=request["volume"],
            type=0 if request["type"] == self.ORDER_TYPE_BUY else 1,
            price_open=2000.20,
            price_current=2000.10,
            sl=request.get("sl", 0.0),
            tp=request.get("tp", 0.0),
            profit=-1.00,
            swap=0.0,
            comment=request.get("comment", ""),
            time=time.time() - self.open_age_s,
            magic=request.get("magic", 0),
        )
        self.positions.append(position)
        self.deals.append(
            SimpleNamespace(
                ticket=self._next_deal,
                order=self._next_order,
                position_id=position.ticket,
                symbol=request["symbol"],
                volume=request["volume"],
                price=2000.20,
                profit=0.0,
                type=request["type"],
                time=time.time(),
                comment=request.get("comment", ""),
            )
        )
        return SimpleNamespace(
            retcode=10009,
            order=self._next_order,
            deal=self._next_deal,
            price=2000.20,
            volume=request["volume"],
            comment="Request executed",
        )

    def positions_get(self, *args, **kwargs):
        ticket = kwargs.get("ticket")
        if ticket is not None:
            return [p for p in self.positions if p.ticket == int(ticket)]
        return list(self.positions)

    def order_check(self, request):
        return SimpleNamespace(retcode=0, comment="Done", balance=10_000.0, equity=10_000.0, margin=17.0)

    # -- plumbing ------------------------------------------------------------
    def initialize(self, **kwargs):
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "No error")

    def terminal_info(self):
        return SimpleNamespace(connected=True, company="Example Brokers Ltd", build=4000)

    def account_info(self):
        return self.account

    def symbol_info(self, name):
        return self.symbol_spec if name == "XAUUSD@" else None

    def symbol_select(self, name, enable):
        return name == "XAUUSD@"

    def copy_rates_from_pos(self, *args, **kwargs):
        return None

    def orders_get(self, **kwargs):
        return ()

    def history_deals_get(self, *args, **kwargs):
        return list(self.deals)

    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 6
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    ORDER_TIME_GTC = 0
    TIMEFRAME_M1 = 1
