"""One resolution of the MT5 connection — terminal path, symbol, alias table.

Several places need an :class:`~qts.adapters.mt5_adapter.MT5Adapter`: the
dashboard account probe, the ``/api/mt5`` status panel, the DEMO session, the
observation runtime. Each used to build its own ``config`` dict, and two of them
passed only ``{"path": ...}`` — no ``symbol_map``. An adapter with an empty alias
table maps ``XAUUSD`` to ``XAUUSD``, so those calls asked the broker for a symbol
that does not exist on this venue (the real one is ``XAUUSD@``) and reported
``symbol_info exists=False`` / ``tick=None`` while the DEMO session, which did
have the table, resolved the same instrument correctly. Same machine, same
terminal, two different answers — because there were five sources of truth.

:func:`resolve_connection` is now the single one: terminal path, canonical
symbol, the alias table, and the venue symbol that canonical name resolves to.
:func:`adapter_from_setup` builds an adapter from it, so no call site can forget
the mapping again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qts.adapters.mt5_adapter import MT5Adapter, broker_symbol, canonical_symbol
from qts.config.wizard import load_setup, setup_file

DEFAULT_CANONICAL_SYMBOL = "XAUUSD"


def resolve_connection(symbol: str | None = None) -> dict[str, Any]:
    """Terminal path + canonical symbol + alias table, from the machine-local setup.

    The canonical symbol stays canonical (``XAUUSD``) no matter which spelling
    the operator saved, and ``broker_symbol`` is what the venue actually trades
    (``XAUUSD@``). Callers must never send the canonical name to the broker or
    compare the venue name against a policy.
    """
    saved = load_setup()
    raw_map = saved.get("symbol_map")
    symbol_map = {str(k): str(v) for k, v in raw_map.items()} if isinstance(raw_map, dict) else {}
    requested = str(symbol or saved.get("symbol") or DEFAULT_CANONICAL_SYMBOL)
    if not symbol_map and requested.endswith("@"):
        canonical_fallback = requested[:-1]
        symbol_map = {canonical_fallback: requested}
        requested = canonical_fallback
    canonical = canonical_symbol(requested, symbol_map)
    broker = broker_symbol(requested, symbol_map)
    return {
        "terminal_path": saved.get("terminal_path") or None,
        "symbol": canonical,
        "canonical_symbol": canonical,
        "broker_symbol": broker,
        "symbol_map": symbol_map,
        "requested_symbol": requested,
        "alias_declared": bool(symbol_map),
        "setup_file": str(setup_file()),
        "setup_exists": setup_file().exists(),
    }


def adapter_from_setup(
    symbol: str | None = None,
    *,
    db_path: Path | str | None = None,
    mt5_module: Any | None = None,
) -> tuple[MT5Adapter, dict[str, Any]]:
    """An adapter whose alias table always matches the resolved connection.

    Returns ``(adapter, connection)`` so callers can report exactly which
    canonical → venue pair they probed, instead of implying one and testing
    another.
    """
    connection = resolve_connection(symbol)
    adapter = MT5Adapter(
        config={
            "path": connection["terminal_path"] or "",
            "symbol_map": dict(connection["symbol_map"]),
            "symbol": connection["canonical_symbol"],
        },
        mt5_module=mt5_module,
        db_path=db_path,
    )
    return adapter, connection
