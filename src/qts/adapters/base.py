"""Canonical broker adapter interfaces and reconciliation contracts."""

from __future__ import annotations

from typing import Any

from qts.domain.value_objects import Account, Instrument, Order, OrderIntent, Position, Tick


class ReconcileReport:
    """Outcome of a broker-vs-portfolio reconciliation check."""

    def __init__(self, drift: str, details: str = "", requires_suspend: bool = False):
        self.drift = drift
        self.details = details
        self.requires_suspend = requires_suspend

    def is_ok(self) -> bool:
        return self.drift == "NONE"


class BrokerAdapter:
    """Canonical abstract base protocol for all broker adapters."""

    is_live: bool = False
    is_shadow: bool = False

    def submit(self, intent: OrderIntent) -> Order:
        raise NotImplementedError

    def positions(self) -> list[Position]:
        return []

    def account(self) -> Account:
        """NO fabricated account. Adapters that cannot provide authoritative
        broker state must override and either return a labeled simulation
        account or raise — a silent ``balance=10000`` default is a fabricated
        fallback in a safety-critical path (removed, fail-closed)."""
        raise NotImplementedError(
            f"{type(self).__name__} does not provide authoritative account state — "
            "refusing to fabricate one (fail-closed)"
        )

    def orders(self) -> list[Order]:
        return []

    def cancel(self, client_order_id: str) -> None:  # noqa: B027
        pass

    def get_symbol_spec(self, symbol: str) -> Any:
        return None

    def ticks(self, instrument: Instrument) -> Tick | None:
        return None
