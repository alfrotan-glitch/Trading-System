"""MT5 adapter — external authority with reconciliation.

At import, does not require MetaTrader5 package; fails gracefully to Paper for dev.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from typing import Any

from qts.domain.value_objects import Account, Instrument, Order, OrderIntent, Position, Tick
from qts.execution.engine import BrokerAdapter


class MT5Adapter(BrokerAdapter):
    """Thin wrapper around MetaTrader5. If package missing, raises on connect."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._mt5: Any = None
        self.symbol_map: dict[str, str] = self.config.get("symbol_map", {})

    def _require_mt5(self) -> Any:
        if self._mt5 is not None:
            return self._mt5
        try:
            import MetaTrader5 as mt5

            self._mt5 = mt5
            return mt5
        except ImportError as e:
            raise RuntimeError("MetaTrader5 package not installed — use PaperBroker for dev or install mt5") from e

    def connect(self) -> None:
        mt5 = self._require_mt5()
        # login etc. — config holds path/login/password/server
        # For security, credentials come via SecretsProvider, not config
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        # login handled by caller with secrets

    def disconnect(self) -> None:
        if self._mt5:
            import contextlib

            with contextlib.suppress(Exception):
                self._mt5.shutdown()

    def _map_symbol(self, symbol: str) -> str:
        return self.symbol_map.get(symbol, symbol)

    def submit(self, intent: OrderIntent) -> Order:  # noqa: F841
        self._require_mt5()
        # Simplified — real impl maps OrderIntent to mt5.order_send dict
        # We never assume fill; caller must reconcile
        raise NotImplementedError("MT5 live submit requires terminal + EA bridge — use Paper in backtest")

    def positions(self) -> list[Position]:
        mt5 = self._require_mt5()
        raw = mt5.positions_get()
        if raw is None:
            return []
        out: list[Position] = []
        for p in raw:
            # p.symbol, p.volume, p.price_open, p.profit etc.
            instr = Instrument(symbol=p.symbol, venue="MT5")
            out.append(
                Position(
                    instrument=instr,
                    quantity=Decimal(str(p.volume)),
                    avg_price=Decimal(str(p.price_open)),
                )
            )
        return out

    def account(self) -> Account:
        mt5 = self._require_mt5()
        info = mt5.account_info()
        if info is None:
            return Account(balance=Decimal("0"), equity=Decimal("0"), currency="USD")
        return Account(
            balance=Decimal(str(info.balance)),
            equity=Decimal(str(info.equity)),
            margin=Decimal(str(info.margin)),
            currency=info.currency,
        )

    def ticks(self, instrument: Instrument) -> Tick | None:
        mt5 = self._require_mt5()
        sym = self._map_symbol(instrument.symbol)
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return None
        from datetime import datetime

        return Tick(
            instrument=instrument,
            bid=Decimal(str(tick.bid)),
            ask=Decimal(str(tick.ask)),
            event_time=datetime.fromtimestamp(tick.time, tz=UTC),
        )
