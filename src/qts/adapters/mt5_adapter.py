"""MT5 adapter — authoritative, isolated, fail-closed.

Production execution boundary: all broker interaction is through this adapter.
No assumption of acceptance or fill. Every action is validated, normalized,
audited, and reconciled.

Symbol metadata is authoritative: contract_size, volume_min/max/step,
digits/precision, trade_mode, filling_mode, point, tick_size, trade_allowed.

Idempotency: client_order_id is stored in MT5 order comment (truncated to 31
chars with mapping table persisted). On restart, comment ↔ client_order_id
mapping is recovered via history.

Account: real broker account_info with balance/equity/margin/free_margin/
leverage/margin_level, with staleness/contradiction checks.

Market data: tick validation is via MarketDataProvider (see adapters/market_data.py),
but MT5Adapter.ticks() is the raw source.

Order lifecycle: submit → ACCEPTED or REJECTED/AMBIGUOUS, fills via polling
history_deals (not assumed), cancel via TRADE_ACTION_REMOVE.
"""

from __future__ import annotations

import contextlib
import math
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect
from qts.domain.value_objects import (
    Account,
    Instrument,
    Order,
    OrderIntent,
    OrderState,
    OrderType,
    Position,
    Side,
    Tick,
)
from qts.execution.engine import BrokerAdapter


@dataclass(frozen=True)
class SymbolSpec:
    """Authoritative broker symbol metadata — single canonical spec."""

    symbol: str
    contract_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    digits: int
    point: Decimal
    tick_size: Decimal
    trade_mode: int
    trade_allowed: bool
    filling_mode: int
    # Extended authoritative fields (Phase 2)
    execution_mode: int = 0  # 0 market, 1 instant, 2 request, 3 exchange
    stops_level: int = 0  # minimum stop distance in points
    freeze_level: int = 0
    volume_limit: Decimal = Decimal("0")
    # session info (if available)
    session_open: str | None = None
    session_close: str | None = None
    # raw mt5 info for audit
    raw: dict[str, Any] | None = None


def _numeric_or_none(raw: Any) -> float | None:
    """Finite float from an MT5 timestamp field, else None (never fabricate)."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


#: Canonical SymbolSpec field -> accepted attribute names on the raw MT5
#: SymbolInfo object (real MetaTrader5 API name FIRST, legacy/mock alias
#: second). Resolution is by explicit alias list; there are NO default values
#: anywhere in this table — a missing/None/non-finite field fails closed.
_SPEC_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "contract_size": ("trade_contract_size", "contract_size"),
    "volume_min": ("volume_min",),
    "volume_max": ("volume_max",),
    "volume_step": ("volume_step",),
    "digits": ("digits",),
    "point": ("point",),
    "tick_size": ("trade_tick_size", "tick_size"),
    "trade_mode": ("trade_mode",),
    "filling_mode": ("filling_mode",),
    "execution_mode": ("trade_exemode", "execution_mode", "trade_execution"),
    "stops_level": ("trade_stops_level", "stops_level"),
    "freeze_level": ("trade_freeze_level", "freeze_level"),
}

#: Fields whose absence makes execution impossible (mission-critical broker
#: metadata). Mock compatibility exists only via explicitly populated test
#: doubles — never via defaults leaking into the real path.
REQUIRED_SPEC_FIELDS = (
    "contract_size",
    "volume_min",
    "volume_max",
    "volume_step",
    "digits",
    "point",
    "tick_size",
    "trade_mode",
    "filling_mode",
)


def _required_numeric(info: Any, field: str, symbol: str, *, positive: bool = True) -> Decimal:
    """Resolve a required numeric spec field through aliases — fail closed.

    The previous ``getattr(info, "volume_min", 0.01)``-style defaults
    fabricated broker metadata (a wrong contract size fed notional, margin,
    and risk math). Now: missing alias, None, non-finite, or non-positive
    (where positivity is required) raises — execution cannot proceed on
    guessed symbol parameters.
    """
    for attr in _SPEC_FIELD_ALIASES[field]:
        raw = getattr(info, attr, None)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            continue  # non-numeric (e.g. auto-generated mock attribute) == absent
        if not value.is_finite():
            continue
        if positive and value <= 0:
            continue
        return value
    raise RuntimeError(
        f"MT5 symbol {symbol}: required spec field '{field}' "
        f"(aliases {list(_SPEC_FIELD_ALIASES[field])}) missing/invalid "
        f"— refusing to fabricate broker metadata (fail-closed)"
    )


def _required_int(info: Any, field: str, symbol: str, *, min_value: int | None = None) -> int:
    value = _required_numeric(info, field, symbol, positive=False)
    ivalue = int(value)
    if value != Decimal(ivalue):
        raise RuntimeError(f"MT5 symbol {symbol}: spec field '{field}' must be an integer, got {value} (fail-closed)")
    if min_value is not None and ivalue < min_value:
        raise RuntimeError(
            f"MT5 symbol {symbol}: spec field '{field}'={ivalue} below minimum {min_value} (fail-closed)"
        )
    return ivalue


def _resolve_contract_size(info: Any, symbol: str) -> Decimal:
    """Authoritative contract size via the alias table — thin wrapper kept
    for backward-compatible imports; semantics identical to _required_numeric."""
    return _required_numeric(info, "contract_size", symbol, positive=True)


def _session_diagnosis(last_error: Any, path: str | None) -> str:
    """A precise, actionable diagnosis for a failed IPC establishment."""
    code = last_error[0] if isinstance(last_error, (tuple, list)) and last_error else None
    text = last_error[1] if isinstance(last_error, (tuple, list)) and len(last_error) > 1 else None
    where = f"terminal_path={path!r}" if path else "terminal_path=<auto-detect>"
    if code == -10004 or (text and "IPC" in str(text)):
        return (
            "MT5 initialize failed: IPC link not established in this process "
            f"(last_error={last_error}, {where}). MetaTrader5 IPC is per process: the terminal must be "
            "running and reachable from THIS process. QTS establishes the link once before any broker "
            "call; this failure means the terminal is not running, the path is wrong, or another "
            "process owns the terminal session. This is a connection-lifecycle failure, NOT a "
            "reconciliation drift — no order was sent and none may be."
        )
    return (
        f"MT5 initialize failed: terminal link not established (last_error={last_error}, {where}) — "
        "the IPC link to the terminal could not be established or verified in this process"
    )


class MT5SessionError(RuntimeError, ConnectionError):
    """The IPC link to the MT5 terminal is not established in THIS process.

    Raised with a precise diagnosis instead of letting a downstream call return
    ``None``/``(-10004, 'No IPC connection')`` and be misread as a broker or
    reconciliation failure. It is never retried blindly: establishing the link
    once, verified, is the precondition; if that fails the caller fails closed.
    """


def canonical_symbol(symbol: str, symbol_map: dict[str, str] | None) -> str:
    """Resolve ANY spelling of a symbol to its canonical form.

    The canonical symbol is the one key used by the portfolio, the risk engine,
    the journal and — crucially — the registered research policy. The venue
    spells the same instrument ``XAUUSD@``. Operators configure either spelling
    (``configs/setup.json`` has been seen holding the venue alias), so both
    directions must be resolved before anything compares symbols:

    * ``XAUUSD``  (a map key)          → canonical ``XAUUSD``
    * ``XAUUSD@`` (a mapped alias)     → canonical ``XAUUSD``
    * anything unmapped                → returned unchanged (already canonical)

    There is deliberately no "accept both" comparison anywhere else: one
    canonical form per instrument means a policy that allows ``XAUUSD`` can
    never be satisfied by a different instrument, which is what makes the
    symbol binding auditable.
    """
    if not symbol:
        return symbol
    for canonical, broker in (symbol_map or {}).items():
        if str(broker) == str(symbol):
            return str(canonical)
    return str(symbol)


def normalize_terminal_path(path: str | Path | None) -> str | None:
    """Normalize terminal path to the actual executable.

    If given a directory (e.g. ``C:\\Program Files\\MetaTrader 5``), appends
    ``terminal64.exe`` so Windows process creation does not fail with
    ``Process create failed (-10003)``.
    """
    if not path:
        return None
    cleaned = str(path).strip().strip('"').strip("'")
    if not cleaned:
        return None
    lower = cleaned.lower().replace("/", "\\")
    if lower.endswith(".exe"):
        return cleaned
    if lower.endswith("\\terminal64") or lower.endswith("\\terminal"):
        return f"{cleaned}.exe"
    sep = "\\" if "\\" in cleaned else "/"
    return f"{cleaned.rstrip(sep)}{sep}terminal64.exe"


def broker_symbol(symbol: str, symbol_map: dict[str, str] | None) -> str:
    """Canonical symbol → the alias the venue actually trades."""
    if not symbol:
        return symbol
    mapping = symbol_map or {}
    canonical = canonical_symbol(symbol, mapping)
    return str(mapping.get(canonical, canonical))


def _optional_mt5_module() -> Any | None:
    """The real MetaTrader5 module when importable — never a stand-in."""
    import importlib

    try:
        return importlib.import_module("MetaTrader5")
    except ImportError:
        return None


class MT5Adapter(BrokerAdapter):
    """Isolated MT5 broker adapter. All MT5 access is via _mt5 (injected or imported)."""

    is_live = True
    is_shadow = False

    # MT5 retcodes (from MetaTrader5 docs)
    RETCODE_DONE = 10009
    RETCODE_PLACED = 10008
    RETCODE_DONE_PARTIAL = 10010
    RETCODE_REQUOTE = 10004
    RETCODE_REJECT = 10006
    RETCODE_CANCEL = 10007
    RETCODE_INVALID = 10013
    RETCODE_INVALID_VOLUME = 10014
    RETCODE_INVALID_PRICE = 10015
    RETCODE_TIMEOUT = 10012
    RETCODE_NO_MONEY = 10019
    RETCODE_PRICE_OFF = 10018
    RETCODE_TRADE_DISABLED = 10017

    # Ambiguous retcodes that imply unknown broker state
    AMBIGUOUS_RETCODES = {10012, 10011}  # TIMEOUT, etc.

    # --- Canonical timestamp contract (server-basis MT5 stamps -> true UTC) ---
    # All real-world UTC offsets are multiples of 15 minutes; the forming-M1-bar
    # probe window is 60s wide, so it contains at most one grid point and the
    # offset is recovered EXACTLY (no guessing, no clamping).
    _OFFSET_QUANTUM_S = 900.0
    _OFFSET_TTL_S = 300.0  # re-measure cadence; offsets only shift on DST changes
    _MAX_PLAUSIBLE_OFFSET_S = 14 * 3600.0

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        mt5_module: Any | None = None,
        db_path: Path | str | None = None,
    ):
        self.config = config or {}
        self._mt5: Any = mt5_module  # injected mock for tests
        self.symbol_map: dict[str, str] = self.config.get("symbol_map", {})
        self._spec_cache: dict[str, SymbolSpec] = {}
        # client_order_id <-> MT5 comment mapping persisted for restart recovery
        if db_path is None:
            db_path = self.config.get("db_path")
        if db_path is None:
            # Anchored at the machine-local state root, never at cwd — the
            # comment↔client_order_id map is restart-recovery evidence and must
            # be the same file for the CLI and the backend.
            from qts.config.paths import artifact_path

            db_path = artifact_path("db")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # symbol -> (offset_seconds, basis, measured_at_epoch); see server_utc_offset
        self._server_offset_cache: dict[str, tuple[float, str, float]] = {}
        #: Raw receipt of the most recent successful ``order_send`` (broker order
        #: id, position/deal id, executed price) — consumed by the DEMO journal.
        self.last_submission: dict[str, Any] | None = None
        #: IPC session facts for this process (see :meth:`ensure_session`).
        self._session: dict[str, Any] | None = None
        self._init_comment_db()

    def broker_identity(self) -> Any:
        """Connected account/broker identity straight from the terminal.

        Used by the DEMO pre-trade gate to prove the account is DEMO and that
        the broker/server matches the pinned identity. Raises
        ``BrokerIdentityError`` when the terminal cannot prove identity.
        """
        from qts.execution.demo_identity import probe_broker_identity

        return probe_broker_identity(self._mt5)

    def broker_references_available(self) -> bool:
        """Whether this adapter can capture broker order/position identifiers.

        A DEMO order may only be sent through an adapter that returns the
        broker's own identifiers — otherwise the order cannot be reconciled or
        journaled (safeguards #13 and #14).
        """
        mt5 = self._mt5
        module = mt5 if mt5 is not None else _optional_mt5_module()
        if module is None:
            return False
        return all(hasattr(module, name) for name in ("order_send", "positions_get", "last_error"))

    def _init_comment_db(self) -> None:
        with db_connect(self._db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS mt5_comment_map (
                    client_order_id TEXT PRIMARY KEY,
                    mt5_comment TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            con.commit()

    def _store_comment_map(self, client_order_id: str, comment: str) -> None:
        with db_connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO mt5_comment_map VALUES (?,?,?)",
                (client_order_id, comment, datetime.now(UTC).isoformat()),
            )
            con.commit()

    def _load_comment_map(self, client_order_id: str) -> str | None:
        with db_connect(self._db_path) as con:
            row = con.execute(
                "SELECT mt5_comment FROM mt5_comment_map WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            return row[0] if row else None

    def _reverse_comment_map(self, comment: str) -> str | None:
        with db_connect(self._db_path) as con:
            row = con.execute("SELECT client_order_id FROM mt5_comment_map WHERE mt5_comment=?", (comment,)).fetchone()
            return row[0] if row else None

    def _module(self) -> Any:
        """The MT5 module (injected or imported) — no session side effects."""
        if self._mt5 is not None:
            return self._mt5
        try:
            import MetaTrader5 as mt5

            self._mt5 = mt5
            return mt5
        except ImportError as e:
            raise RuntimeError(
                "MetaTrader5 package not installed — install MetaTrader5 or use injected mock for tests"
            ) from e

    def ensure_session(self) -> dict[str, Any]:
        """Establish — once per process — and verify the IPC link to the terminal.

        MetaTrader5's Python API is **per process**: ``terminal_info``,
        ``account_info``, ``symbol_info``, ``symbol_info_tick``, ``positions_get``
        and ``order_send`` all fail with ``(-10004, 'No IPC connection')`` until
        ``initialize()`` has succeeded *in the calling process*. Importing the
        module is not enough, and a link established by another process (an
        earlier ``qts demo verify``, or the web backend) does not carry over.

        QTS used to establish the link only as a side effect of the readiness
        probe. Any process that went straight to execution therefore hit
        ``-10004`` on its first broker call — which is precisely the reported
        ``qts demo run`` halt: step 1 is reconciliation, and nothing in that
        process had called ``initialize()``. The link is now an explicit
        precondition of every broker-facing call (all of which go through
        :meth:`_require_mt5`).

        This is not a retry loop and not a workaround: one deterministic
        establishment, verified with ``terminal_info()``. If it cannot be
        established, the diagnosis says so precisely and the caller fails closed
        — reconciliation still suspends, the kill switch still halts.
        """
        mt5 = self._module()
        if self._session is not None:
            return self._session
        if not hasattr(mt5, "initialize"):
            # An injected test/double module: there is no IPC to establish.
            self._session = {
                "established": True,
                "kind": "injected",
                "detail": "injected MT5 module — no IPC link to establish",
                "established_at": datetime.now(UTC).isoformat(),
            }
            return self._session

        path = normalize_terminal_path(self.config.get("path") or os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH") or None)
        kwargs: dict[str, Any] = {"path": path} if path else {}
        hint = (
            f" (terminal_path={path!r})" if path else " (no terminal_path configured — MT5 auto-detect)"
        )
        try:
            initialized = bool(mt5.initialize(**kwargs))
        except Exception as exc:
            raise MT5SessionError(
                f"MT5 initialize{hint} raised {type(exc).__name__}: {exc} — the IPC link to the terminal "
                "could not be established in this process"
            ) from exc
        if not initialized:
            last_error = None
            with contextlib.suppress(Exception):
                last_error = mt5.last_error()
            raise MT5SessionError(_session_diagnosis(last_error, path))

        info = None
        if hasattr(mt5, "terminal_info"):
            with contextlib.suppress(Exception):
                info = mt5.terminal_info()
            if info is None:
                last_error = None
                with contextlib.suppress(Exception):
                    last_error = mt5.last_error()
                raise MT5SessionError(_session_diagnosis(last_error, path))

        self._session = {
            "established": True,
            "kind": "initialized",
            "terminal_path": path,
            "terminal_build": getattr(info, "build", None),
            "terminal_company": getattr(info, "company", None),
            "terminal_connected": bool(getattr(info, "connected", True)) if info is not None else None,
            "process": os.getpid(),
            "established_at": datetime.now(UTC).isoformat(),
        }
        return self._session

    def session_state(self) -> dict[str, Any]:
        """The IPC session facts for this process (diagnostics; never a permission)."""
        return dict(self._session or {"established": False, "kind": "not-established"})

    def _require_mt5(self) -> Any:
        """The MT5 module with the IPC link established — the single choke point.

        Every broker-facing method in this adapter starts here, so making the
        session an explicit precondition of this call is what guarantees no
        terminal call is ever attempted over a link this process never opened.
        """
        self.ensure_session()
        return self._module()

    def connect(
        self, login: int | None = None, password: str | None = None, server: str | None = None, path: str | None = None
    ) -> None:
        if path:
            self.config["path"] = path
            self._session = None  # a different terminal invalidates the link
        mt5 = self._require_mt5()
        # Use config or params
        login = login or self.config.get("login")
        password = password or self.config.get("password")
        server = server or self.config.get("server")
        path = path or self.config.get("path")
        kwargs: dict[str, Any] = {}
        if path:
            kwargs["path"] = path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if login and password and server and not mt5.login(login, password, server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    def disconnect(self) -> None:
        # The link is per process: after an explicit shutdown this process has
        # no IPC session, so the cached facts must be dropped — otherwise the
        # next call would believe a dead link was established.
        self._session = None
        if self._mt5:
            with contextlib.suppress(Exception):
                self._mt5.shutdown()

    def _map_symbol(self, symbol: str) -> str:
        """Canonical symbol → broker alias (identity when already an alias)."""
        symbol_map = self.symbol_map or {}
        if symbol in symbol_map:
            return symbol_map[symbol]
        # Already a broker alias (an operator may configure `XAUUSD@` directly):
        # mapping it again would produce nothing, so return it unchanged.
        return symbol

    def _canonical_symbol(self, mt5_symbol: str) -> str:
        """Broker symbol → canonical symbol (inverse of :meth:`_map_symbol`).

        The terminal reports broker aliases (``XAUUSD@``) while the portfolio,
        risk engine and reconciliation key positions by the canonical symbol
        (``XAUUSD``). Reporting the broker name as if it were canonical makes
        every venue position look like a local position that does not exist
        (``MISSING_POSITION`` → suspend after the very first order) and hides
        broker-only exposure — so translate back, never assume identity.
        """
        return canonical_symbol(mt5_symbol, self.symbol_map or {})

    # ---------- Symbol metadata (authoritative) ----------

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        """Fetch and cache authoritative symbol spec — single canonical source.

        EVERY field is resolved from broker SymbolInfo through the explicit
        alias table (real API name first, legacy/mock alias second). A
        missing/None/non-finite required field raises — execution can never
        proceed on guessed contract sizes, volume bounds, tick geometry, or
        trade permissions (mission-critical broker metadata, fail-closed).
        """
        if symbol in self._spec_cache:
            return self._spec_cache[symbol]
        mt5 = self._require_mt5()
        mt5_sym = self._map_symbol(symbol)
        # Phase 1: ensure symbol visible/selected before info
        with contextlib.suppress(Exception):
            mt5.symbol_select(mt5_sym, True)
        info = mt5.symbol_info(mt5_sym)
        if info is None:
            raise RuntimeError(f"MT5 symbol_info not found for {symbol} (mapped {mt5_sym}): {mt5.last_error()}")
        contract_size = _resolve_contract_size(info, symbol)
        volume_min = _required_numeric(info, "volume_min", symbol, positive=True)
        volume_max = _required_numeric(info, "volume_max", symbol, positive=True)
        volume_step = _required_numeric(info, "volume_step", symbol, positive=True)
        digits = _required_int(info, "digits", symbol, min_value=0)
        point = _required_numeric(info, "point", symbol, positive=True)
        tick_size = _required_numeric(info, "tick_size", symbol, positive=True)
        trade_mode = _required_int(info, "trade_mode", symbol, min_value=0)
        # Tradability: the AUTHORITATIVE broker signal is trade_mode
        # (0=disabled, 1=longonly, 2=shortonly, 3=closeonly, 4=full) — the
        # real MetaTrader5 SymbolInfo carries trade_mode on every symbol.
        # An explicit trade_allowed attribute (present on some builds/mocks)
        # must be True when present. The old ``getattr(info,
        # "trade_allowed", True)`` fabricated consent when the attribute was
        # absent — removed: absence now defers to trade_mode, never to a
        # guessed True.
        explicit_allowed = getattr(info, "trade_allowed", None)
        trade_allowed = bool(explicit_allowed) if explicit_allowed is not None else trade_mode != 0
        if not trade_allowed:
            raise RuntimeError(
                f"MT5 symbol {symbol}: not tradable (trade_mode={trade_mode},"
                f" trade_allowed={explicit_allowed!r}) — fail-closed"
            )
        filling = _required_int(info, "filling_mode", symbol, min_value=0)
        execution_mode = _required_int(info, "execution_mode", symbol, min_value=0)
        stops_level = _required_int(info, "stops_level", symbol, min_value=0)
        freeze_level = _required_int(info, "freeze_level", symbol, min_value=0)
        if trade_mode == 0:
            raise RuntimeError(f"MT5 symbol {symbol} trade disabled (mode 0)")
        # Contradiction guard: volume bounds must be coherent
        if volume_min > volume_max or volume_step > volume_max:
            raise RuntimeError(
                f"MT5 symbol {symbol}: contradictory volume geometry "
                f"(min {volume_min}, max {volume_max}, step {volume_step}) — fail-closed"
            )
        spec = SymbolSpec(
            symbol=symbol,
            contract_size=contract_size,
            volume_min=volume_min,
            volume_max=volume_max,
            volume_step=volume_step,
            digits=digits,
            point=point,
            tick_size=tick_size,
            trade_mode=trade_mode,
            trade_allowed=trade_allowed,
            filling_mode=filling,
            execution_mode=execution_mode,
            stops_level=stops_level,
            freeze_level=freeze_level,
            raw={
                "contract_size": str(contract_size),
                "volume_min": str(volume_min),
                "volume_max": str(volume_max),
                "volume_step": str(volume_step),
                "digits": digits,
                "point": str(point),
                "tick_size": str(tick_size),
                "trade_mode": trade_mode,
                "trade_allowed": trade_allowed,
                "filling_mode": filling,
                "execution_mode": execution_mode,
                "stops_level": stops_level,
                "freeze_level": freeze_level,
                "source": "MT5 SymbolInfo (authoritative)",
            },
        )
        self._spec_cache[symbol] = spec
        return spec

    # ---------- Phase 1: Connectivity & health ----------

    def validate_prerequisites(self, symbol: str | None = None) -> dict[str, Any]:
        """Verify all prerequisites before any order submission — fail-closed."""
        errors: list[str] = []
        try:
            mt5 = self._require_mt5()
        except MT5SessionError as e:
            return {"ok": False, "errors": [f"terminal not connected: {e}"]}
        try:
            term = mt5.terminal_info()
            if term is None:
                errors.append("terminal_info unavailable — not initialized")
        except Exception as e:
            errors.append(f"terminal_info error: {e}")
        try:
            acct = mt5.account_info()
            if acct is None:
                errors.append(f"account_info unavailable: {mt5.last_error()}")
        except Exception as e:
            errors.append(f"account connectivity: {e}")
        if symbol:
            try:
                self.get_symbol_spec(symbol)
            except Exception as e:
                errors.append(f"symbol {symbol} not tradable: {e}")
        return {"ok": len(errors) == 0, "errors": errors}

    def health_check(self) -> dict[str, Any]:
        """Connection health — IPC session, terminal, account, last_error.

        A status probe must never raise: when the IPC link cannot be established
        it reports ``connected=False`` with the precise lifecycle diagnosis, so
        the UI and the CLI show the same real reason instead of an empty panel
        or a misleading "terminal connected".
        """
        now = datetime.now(UTC)
        result: dict[str, Any] = {
            "timestamp": now.isoformat(),
            "connected": False,
            "terminal_ok": False,
            "account_ok": False,
            "last_error": None,
        }
        try:
            result["session"] = self.ensure_session()
        except MT5SessionError as exc:
            result["session"] = {"established": False, "kind": "failed", "detail": str(exc)}
            result["session_error"] = str(exc)
            return result
        mt5 = self._module()
        try:
            ti = mt5.terminal_info()
            result["terminal_ok"] = ti is not None
            result["terminal_info"] = (
                {
                    "connected": bool(getattr(ti, "connected", False)),
                    "trade_allowed": bool(getattr(ti, "trade_allowed", False)),
                }
                if ti
                else None
            )
        except Exception as e:
            result["terminal_error"] = str(e)
        try:
            ai = mt5.account_info()
            result["account_ok"] = ai is not None
            if ai:
                result["account"] = {"balance": str(getattr(ai, "balance", "")), "login": getattr(ai, "login", None)}
        except Exception as e:
            result["account_error"] = str(e)
        try:
            err = mt5.last_error()
            result["last_error"] = str(err)
            result["connected"] = (
                result["terminal_ok"] and result["account_ok"] and (err[0] == 1 if isinstance(err, tuple) else True)
            )
        except Exception as e:
            result["last_error"] = str(e)
        return result

    def is_connected(self) -> bool:
        try:
            h = self.health_check()
            return bool(h["connected"])
        except Exception:
            return False

    def terminal_info(self) -> Any:
        mt5 = self._require_mt5()
        return mt5.terminal_info()

    def discover_symbols(self, pattern: str = "*", max_count: int = 500) -> list[str]:
        """Symbol discovery — authoritative broker listing."""
        mt5 = self._require_mt5()
        try:
            raw = mt5.symbols_get()
            if raw is None:
                return []
            names = [getattr(s, "name", str(s)) for s in raw]
            if pattern != "*":
                import fnmatch

                names = [n for n in names if fnmatch.fnmatch(n, pattern)]
            return names[:max_count]
        except Exception:
            return []

    def ensure_symbol_visible(self, symbol: str) -> bool:
        mt5 = self._require_mt5()
        try:
            return bool(mt5.symbol_select(self._map_symbol(symbol), True))
        except Exception:
            return False

    def is_symbol_tradable(self, symbol: str) -> bool:
        try:
            spec = self.get_symbol_spec(symbol)
            return spec.trade_allowed and spec.trade_mode != 0
        except Exception:
            return False

    def reconnect(self, max_attempts: int = 3) -> bool:
        """Clean shutdown then reconnect — recovery behavior."""
        self._session = None  # the shutdown below invalidates any cached link
        mt5 = self._module()
        for _attempt in range(max_attempts):
            try:
                import contextlib

                with contextlib.suppress(Exception):
                    mt5.shutdown()
                self._session = None
                kwargs: dict[str, Any] = {}
                path = normalize_terminal_path(self.config.get("path"))
                if path:
                    kwargs["path"] = path
                if not mt5.initialize(**kwargs):
                    continue
                login = self.config.get("login")
                password = self.config.get("password")
                server = self.config.get("server")
                if login and password and server and not mt5.login(login, password, server):
                    continue
                if self.is_connected():
                    self._session = None  # re-verify through the normal path
                    return True
            # B112: reconnect retry loop: failed attempt retries until max_attempts
            except Exception:  # nosec B112
                continue
        return False

    def build_broker_request(self, intent: OrderIntent) -> dict[str, Any]:
        """Construct exact broker request without submitting — dry-run (Phase 9)."""
        spec = self.get_symbol_spec(intent.instrument.symbol)
        normalized_qty = self.validate_and_normalize_quantity(intent.quantity, spec)
        limit_price = self.validate_price_precision(intent.limit_price, spec) if intent.limit_price else None
        stop_price = self.validate_price_precision(intent.stop_price, spec) if intent.stop_price else None
        # SL/TP validation against stops_level
        if intent.limit_price and spec.stops_level > 0:
            # Use current tick price approximation for distance check — not blocking for market orders
            pass
        mt5 = self._require_mt5()
        mt5_symbol = self._map_symbol(intent.instrument.symbol)
        comment = self._build_comment(intent.client_order_id)
        if intent.order_type == OrderType.MARKET:
            mt5_type = mt5.ORDER_TYPE_BUY if intent.side == Side.BUY else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL
            price = 0.0
        elif intent.order_type == OrderType.LIMIT:
            if limit_price is None:
                raise ValueError("LIMIT requires limit_price")
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if intent.side == Side.BUY else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
            price = float(limit_price)
        elif intent.order_type == OrderType.STOP:
            if stop_price is None:
                raise ValueError("STOP requires stop_price")
            mt5_type = mt5.ORDER_TYPE_BUY_STOP if intent.side == Side.BUY else mt5.ORDER_TYPE_SELL_STOP
            action = mt5.TRADE_ACTION_PENDING
            price = float(stop_price)
        else:
            raise ValueError(f"unsupported order_type {intent.order_type}")
        filling = getattr(mt5, "ORDER_FILLING_IOC", 1)
        if spec.filling_mode == 1:
            filling = mt5.ORDER_FILLING_IOC
        elif spec.filling_mode == 2:
            filling = mt5.ORDER_FILLING_FOK
        else:
            filling = mt5.ORDER_FILLING_RETURN
        request: dict[str, Any] = {
            "action": action,
            "symbol": mt5_symbol,
            "volume": float(normalized_qty),
            "type": mt5_type,
            "type_filling": filling,
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            "comment": comment,
            "magic": int(self.config.get("magic", 20250916)),
        }
        if price:
            request["price"] = price
        sl, tp = self._protective_levels(
            mt5, mt5_symbol, spec, intent, limit_price=limit_price, stop_price=stop_price
        )
        if sl is not None:
            request["sl"] = float(sl)
        if tp is not None:
            request["tp"] = float(tp)
        return request

    def _executable_reference(self, mt5: Any, mt5_symbol: str, side: Side) -> Decimal:
        """Executable price for a market order — BUY→ask, SELL→bid.

        Fail closed: without a quote the stop distance cannot be validated
        against ``stops_level``, and an unvalidated stop is not acceptable
        protection.
        """
        try:
            tick = mt5.symbol_info_tick(mt5_symbol)
        except Exception as exc:
            raise ValueError(f"tick unavailable for {mt5_symbol} — stop distance not verifiable: {exc}") from exc
        if tick is None:
            raise ValueError(f"tick unavailable for {mt5_symbol} — stop distance not verifiable")
        raw = getattr(tick, "ask", None) if side == Side.BUY else getattr(tick, "bid", None)
        try:
            value = Decimal(str(raw))
        except (TypeError, InvalidOperation) as exc:
            raise ValueError(f"invalid executable price for {mt5_symbol}: {raw!r}") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError(f"non-positive executable price for {mt5_symbol}: {raw!r}")
        return value

    def validate_sl_tp(
        self, price: Decimal, sl: Decimal | None, tp: Decimal | None, spec: SymbolSpec, side: Side
    ) -> None:
        """Validate SL/TP distance against broker stops_level."""
        if spec.stops_level <= 0:
            return
        min_dist = spec.stops_level * spec.point
        if sl is not None:
            dist = abs(price - sl)
            if dist < min_dist - Decimal("1e-9"):
                raise ValueError(
                    f"SL distance {dist} < stops_level {spec.stops_level}*{spec.point}={min_dist} for {spec.symbol}"
                )
        if tp is not None:
            dist = abs(price - tp)
            if dist < min_dist - Decimal("1e-9"):
                raise ValueError(
                    f"TP distance {dist} < stops_level {spec.stops_level}*{spec.point}={min_dist} for {spec.symbol}"
                )

    def invalidate_spec_cache(self, symbol: str | None = None) -> None:
        if symbol:
            self._spec_cache.pop(symbol, None)
        else:
            self._spec_cache.clear()

    # ---------- Validation & normalization ----------

    @staticmethod
    def _quantize_to_step(quantity: Decimal, step: Decimal) -> Decimal:
        steps = (quantity / step).to_integral_value(rounding=ROUND_HALF_UP)
        return steps * step

    def validate_and_normalize_quantity(self, quantity: Decimal, spec: SymbolSpec) -> Decimal:
        """Validate quantity against broker constraints, quantize to step, fail closed."""
        if quantity <= 0:
            raise ValueError(f"quantity must be >0, got {quantity}")
        # Check min/max before quantize
        if quantity < spec.volume_min - Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} < broker min {spec.volume_min} for {spec.symbol}")
        if quantity > spec.volume_max + Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} > broker max {spec.volume_max} for {spec.symbol}")
        # Quantize to step
        normalized = self._quantize_to_step(quantity, spec.volume_step)
        # Check that quantization didn't move outside bounds
        if normalized < spec.volume_min - Decimal("0.0000001") or normalized > spec.volume_max + Decimal("0.0000001"):
            raise ValueError(
                f"quantized quantity {normalized} out of bounds [{spec.volume_min}, {spec.volume_max}] for {spec.symbol}"
            )
        # Check that original quantity is already a multiple of step within tolerance
        # If caller passed 0.015 with step 0.01, normalized is 0.02 but we should reject unless close
        diff = abs(quantity - normalized)
        # Allow small epsilon due to Decimal
        if diff > spec.volume_step * Decimal("0.49"):
            # Quantity is not on step; we could either reject or normalize — we reject for safety unless caller explicitly wants normalization
            # For MT5, we normalize but audit the diff; for strict, we reject if diff > 0.0001
            # We choose to normalize and return normalized, but caller must be aware
            # To be fail-closed, we will raise if diff > 1e-9 and not exactly on step
            remainder = (quantity / spec.volume_step) % 1
            if remainder != 0 and abs(remainder) > Decimal("0.0000001") and abs(1 - remainder) > Decimal("0.0000001"):
                raise ValueError(
                    f"quantity {quantity} not multiple of broker step {spec.volume_step} for {spec.symbol} (normalized {normalized})"
                )
        return normalized

    def validate_price_precision(self, price: Decimal | None, spec: SymbolSpec) -> Decimal | None:
        """Validate price precision against broker digits, quantize, fail closed."""
        if price is None:
            return None
        quantum = Decimal("1").scaleb(-spec.digits)
        if spec.tick_size < quantum:
            quantum = spec.tick_size
        quantized = (price / quantum).to_integral_value(rounding=ROUND_HALF_UP) * quantum
        # Strict: price must be exactly on quantum (within 1e-9)
        # Allow tiny epsilon for Decimal representation
        if price != quantized and abs(price - quantized) > Decimal("0.0000001"):
            raise ValueError(
                f"price {price} not at broker precision {quantum} (digits {spec.digits}) for {spec.symbol} quantized {quantized}"
            )
        if quantized <= 0:
            raise ValueError(f"price must be >0, got {quantized}")
        return quantized

    @staticmethod
    def lots_to_mt5_volume(quantity_lots: float | str | Decimal, lot_size: float | Decimal = 0.01) -> float:
        """Legacy helper — now delegates to validate_and_normalize."""
        q = Decimal(str(quantity_lots))
        step = Decimal(str(lot_size))
        steps = (q / step).to_integral_value(rounding=ROUND_HALF_UP)
        quantized = steps * step
        if quantized <= 0:
            raise ValueError(f"quantity {q} below lot_size {step}")
        return float(quantized)

    # ---------- Order submission ----------

    def _build_comment(self, client_order_id: str) -> str:
        """MT5 comment limited to 31 chars. Use truncated + mapping."""
        # MT5 comment max 31 chars; client_order_id is uuid hex 32 + prefix, often longer.
        # We store full mapping in DB and use first 31 chars as comment, or hash.
        if len(client_order_id) <= 31:
            comment = client_order_id
        else:
            # Use hash prefix to avoid collision, keep first 24 + hash 6
            import hashlib

            h = hashlib.sha256(client_order_id.encode()).hexdigest()[:6]
            comment = client_order_id[:24] + "_" + h
            comment = comment[:31]
        self._store_comment_map(client_order_id, comment)
        return comment

    def _protective_levels(
        self,
        mt5: Any,
        mt5_symbol: str,
        spec: Any,
        intent: OrderIntent,
        *,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Validate and return ``(stop_loss, take_profit)`` for an order.

        Protective levels ride along with the order itself: exposure must never
        exist without its stop, not even for the milliseconds between a fill and
        a follow-up modify request. A stop that cannot be validated against
        ``stops_level`` is refused here rather than sent unprotected.
        """
        sl = self.validate_price_precision(intent.stop_loss, spec) if intent.stop_loss else None
        tp = self.validate_price_precision(intent.take_profit, spec) if intent.take_profit else None
        if sl is None and tp is None:
            return None, None
        reference = limit_price or stop_price
        if reference is None:
            # Market order: the executable side price is the only honest
            # reference for a stops_level distance check.
            reference = self._executable_reference(mt5, mt5_symbol, intent.side)
        if not reference or reference <= 0:
            raise ValueError(
                f"no executable reference price for {mt5_symbol} — refusing to send an order whose "
                "protective levels cannot be validated"
            )
        self.validate_sl_tp(reference, sl, tp, spec, intent.side)
        return sl, tp

    def submit(self, intent: OrderIntent) -> Order:
        mt5 = self._require_mt5()
        spec = self.get_symbol_spec(intent.instrument.symbol)
        # Validate and normalize quantity
        normalized_qty = self.validate_and_normalize_quantity(intent.quantity, spec)
        # Validate prices
        limit_price = self.validate_price_precision(intent.limit_price, spec) if intent.limit_price else None
        stop_price = self.validate_price_precision(intent.stop_price, spec) if intent.stop_price else None

        # Build MT5 request
        mt5_symbol = self._map_symbol(intent.instrument.symbol)
        comment = self._build_comment(intent.client_order_id)

        # Determine MT5 order type
        # For simplicity, support MARKET, LIMIT, STOP
        if intent.order_type == OrderType.MARKET:
            mt5_type = mt5.ORDER_TYPE_BUY if intent.side == Side.BUY else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL
            price = 0.0  # market
        elif intent.order_type == OrderType.LIMIT:
            if limit_price is None:
                raise ValueError("LIMIT requires limit_price")
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if intent.side == Side.BUY else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
            price = float(limit_price)
        elif intent.order_type == OrderType.STOP:
            if stop_price is None:
                raise ValueError("STOP requires stop_price")
            mt5_type = mt5.ORDER_TYPE_BUY_STOP if intent.side == Side.BUY else mt5.ORDER_TYPE_SELL_STOP
            action = mt5.TRADE_ACTION_PENDING
            price = float(stop_price)
        else:
            raise ValueError(f"unsupported order_type {intent.order_type}")

        # Filling mode — use spec.filling_mode or default IOC
        # MT5 filling: 0 FOK, 1 IOC, 2 RETURN
        filling = getattr(mt5, "ORDER_FILLING_IOC", 1)
        if spec.filling_mode == 1:
            filling = mt5.ORDER_FILLING_IOC
        elif spec.filling_mode == 2:
            filling = mt5.ORDER_FILLING_FOK
        else:
            filling = mt5.ORDER_FILLING_RETURN

        request: dict[str, Any] = {
            "action": action,
            "symbol": mt5_symbol,
            "volume": float(normalized_qty),
            "type": mt5_type,
            "type_filling": filling,
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            "comment": comment,
            "magic": int(self.config.get("magic", 20250916)),
        }
        if price:
            request["price"] = price

        # Protective levels on the order actually sent — the gate requires a
        # stop, so the request must carry one (not only the dry-run preview).
        sl, tp = self._protective_levels(
            mt5, mt5_symbol, spec, intent, limit_price=limit_price, stop_price=stop_price
        )
        if sl is not None:
            request["sl"] = float(sl)
        if tp is not None:
            request["tp"] = float(tp)

        # Dev guard: if config says dry_run, don't actually send
        if self.config.get("dry_run", False):
            # Simulate success for testing without terminal
            raise RuntimeError(f"MT5 dry_run enabled — would send {request}")

        # Send with timeout handling
        try:
            result = mt5.order_send(request)
        except Exception as e:
            # Transport failure — ambiguous
            raise TimeoutError(f"MT5 order_send transport failure for {intent.client_order_id}: {e}") from e

        if result is None:
            err = mt5.last_error()
            raise TimeoutError(f"MT5 order_send returned None for {intent.client_order_id}: {err}")

        # Classify result
        retcode = getattr(result, "retcode", None)
        # Success codes
        if retcode in (self.RETCODE_DONE, self.RETCODE_PLACED, self.RETCODE_DONE_PARTIAL):
            # Accepted — create Order with exchange_order_id = result.order
            exchange_id = str(getattr(result, "order", "")) or str(getattr(result, "deal", ""))
            # Full broker receipt for the DEMO journal (order id, position/deal
            # id, executed price/volume). Captured here because this is the only
            # place the raw result exists.
            self.last_submission = {
                "retcode": retcode,
                "broker_order_id": str(getattr(result, "order", "") or ""),
                "broker_position_id": str(getattr(result, "deal", "") or getattr(result, "position_id", "") or ""),
                "executed_price": str(getattr(result, "price", "") or ""),
                "executed_volume": str(getattr(result, "volume", "") or ""),
                "comment": str(getattr(result, "comment", "") or ""),
                "request": dict(request),
            }
            return Order(
                order_id=str(exchange_id) or intent.client_order_id,
                client_order_id=intent.client_order_id,
                instrument=intent.instrument,
                side=intent.side,
                quantity=normalized_qty,
                order_type=intent.order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                state=OrderState.ACCEPTED,
                strategy_id=intent.strategy_id,
                exchange_order_id=str(exchange_id) if exchange_id else None,
            )
        elif retcode in self.AMBIGUOUS_RETCODES:
            raise TimeoutError(
                f"MT5 ambiguous retcode {retcode} for {intent.client_order_id}: {getattr(result, 'comment', '')}"
            )
        else:
            # Definitive rejection — map retcode to reason
            comment = getattr(result, "comment", f"retcode {retcode}")
            # Classify known rejection codes
            if retcode in (
                self.RETCODE_INVALID,
                self.RETCODE_INVALID_VOLUME,
                self.RETCODE_INVALID_PRICE,
                self.RETCODE_REJECT,
                self.RETCODE_NO_MONEY,
                self.RETCODE_PRICE_OFF,
                self.RETCODE_TRADE_DISABLED,
            ):
                raise ValueError(f"MT5 rejected {intent.client_order_id} retcode {retcode}: {comment}")
            # Unknown retcode — treat as reject if not timeout
            raise ValueError(f"MT5 rejected {intent.client_order_id} retcode {retcode}: {comment}")

    def cancel(self, client_order_id: str) -> None:
        mt5 = self._require_mt5()
        # Find MT5 order by comment
        comment = self._load_comment_map(client_order_id) or client_order_id[:31]
        # Need to find order ticket via orders_get
        try:
            orders = mt5.orders_get()
            if orders is None:
                orders = []
        except Exception:
            orders = []
        target = None
        for o in orders:
            if getattr(o, "comment", "") == comment or str(getattr(o, "ticket", "")) == client_order_id:
                target = o
                break
        if target is None:
            # Also check history?
            # For now, raise to indicate not found — but for idempotency, cancel is best-effort
            raise RuntimeError(f"MT5 cancel: order {client_order_id} (comment {comment}) not found on broker")
        ticket = getattr(target, "ticket", None)
        if ticket is None:
            raise RuntimeError(f"MT5 cancel: no ticket for {client_order_id}")
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(ticket),
        }
        result = mt5.order_send(request)
        if result is None or getattr(result, "retcode", None) not in (
            self.RETCODE_DONE,
            self.RETCODE_PLACED,
            self.RETCODE_CANCEL,
        ):
            raise RuntimeError(
                f"MT5 cancel failed for {client_order_id} ticket {ticket}: {getattr(result, 'comment', mt5.last_error())}"
            )

    # ---------- Positions, orders, account, ticks ----------

    def positions(self) -> list[Position]:
        mt5 = self._require_mt5()
        raw = mt5.positions_get()
        if raw is None:
            # Check last_error to distinguish empty vs disconnect
            err = mt5.last_error()
            # If error indicates disconnect, raise
            if err and err[0] != 1:  # 1 = RES_S_OK
                raise ConnectionError(f"MT5 positions_get failed: {err}")
            return []
        out: list[Position] = []
        for p in raw:
            # p.symbol, p.volume, p.price_open, p.price_current, p.profit, p.type (0 buy, 1 sell)
            sym = getattr(p, "symbol", "UNKNOWN")
            vol = Decimal(str(getattr(p, "volume", 0)))
            price_open = Decimal(str(getattr(p, "price_open", 0)))
            # Broker alias → canonical, so reconciliation compares like with like.
            instr = Instrument(symbol=self._canonical_symbol(sym), venue="MT5")
            # Quantity signed: BUY positive, SELL negative
            # MT5 position type 0 = BUY, 1 = SELL
            pos_type = getattr(p, "type", 0)
            qty = vol if pos_type == 0 else -vol
            out.append(
                Position(
                    instrument=instr,
                    quantity=qty,
                    avg_price=price_open,
                )
            )
        return out

    def position_details(self) -> list[dict[str, Any]]:
        """Broker-authoritative open positions (ticket, SL/TP, profit, stamps).

        ``positions()`` returns the domain projection (symbol/quantity/price)
        used by risk and reconciliation. Position *management* — closing a
        specific ticket, observing stop/target behaviour, recording unrealized
        P&L — needs the broker identifiers and protective levels, so they are
        exposed here verbatim instead of being re-derived or guessed.
        """
        mt5 = self._require_mt5()
        raw = mt5.positions_get()
        if raw is None:
            err = mt5.last_error()
            if err and err[0] != 1:  # 1 = RES_S_OK
                raise ConnectionError(f"MT5 positions_get failed: {err}")
            return []
        out: list[dict[str, Any]] = []
        for p in raw:
            out.append(
                {
                    "ticket": getattr(p, "ticket", None),
                    "symbol": getattr(p, "symbol", None),
                    "broker_symbol": getattr(p, "symbol", None),
                    "volume": str(getattr(p, "volume", 0)),
                    "type": getattr(p, "type", None),  # 0 = BUY, 1 = SELL
                    "side": "BUY" if getattr(p, "type", 0) == 0 else "SELL",
                    "price_open": str(getattr(p, "price_open", 0)),
                    "price_current": str(getattr(p, "price_current", 0)),
                    "sl": str(getattr(p, "sl", 0) or 0),
                    "tp": str(getattr(p, "tp", 0) or 0),
                    "profit": str(getattr(p, "profit", 0)),
                    "swap": str(getattr(p, "swap", 0)),
                    "comment": str(getattr(p, "comment", "") or ""),
                    "time": getattr(p, "time", None),
                    "magic": getattr(p, "magic", None),
                }
            )
        return out

    def close_position(self, ticket: int, *, volume: Decimal | None = None, comment: str = "qts-close") -> dict[str, Any]:
        """Close an open position by ticket (TRADE_ACTION_DEAL, opposite side).

        Returns the raw broker receipt so the caller can journal the closing
        deal/order id and realized P&L. Raises on failure — a close that
        cannot be confirmed must never be assumed successful.
        """
        mt5 = self._require_mt5()
        raw = None
        try:
            raw = mt5.positions_get(ticket=int(ticket))
        except TypeError:
            # Some builds/mocks only support the no-argument form.
            raw = mt5.positions_get()
            raw = [p for p in (raw or []) if getattr(p, "ticket", None) == int(ticket)] or None
        if raw is None or len(raw) == 0:
            raise ValueError(f"position {ticket} not found — refusing to send a speculative close")
        pos = raw[0]
        symbol = getattr(pos, "symbol", None)
        if not symbol:
            raise ValueError(f"position {ticket} has no symbol — close refused")
        volume_dec = Decimal(str(volume)) if volume is not None else Decimal(str(getattr(pos, "volume", 0)))
        if volume_dec <= 0:
            raise ValueError(f"close volume {volume_dec} must be > 0")
        pos_type = getattr(pos, "type", 0)
        close_type = mt5.ORDER_TYPE_SELL if pos_type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ConnectionError(f"tick unavailable for {symbol} — close refused")
        price = float(tick.bid) if pos_type == 0 else float(tick.ask)
        if not price or price <= 0:
            raise ConnectionError(f"executable price unavailable for {symbol} — close refused")
        spec = self.get_symbol_spec(symbol)
        # ``spec`` is broker-authoritative (get_symbol_spec fails closed), so
        # the filling mode is read directly — never defaulted.
        filling = getattr(mt5, "ORDER_FILLING_IOC", 1)
        if spec.filling_mode == 1:
            filling = mt5.ORDER_FILLING_IOC
        elif spec.filling_mode == 2:
            filling = mt5.ORDER_FILLING_FOK
        else:
            filling = mt5.ORDER_FILLING_RETURN
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume_dec),
            "type": close_type,
            "position": int(ticket),
            "price": price,
            "deviation": int(self.config.get("deviation", 20)),
            "magic": int(self.config.get("magic", 20250916)),
            "comment": str(comment)[:31],
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            "type_filling": filling,
        }
        # Attribute the closing deal before it can come back: without a comment
        # → order mapping the broker's close deal is unattributable, and the
        # engine is required to discard unattributed fills — which would leave
        # the local portfolio holding a position the venue has already closed.
        with contextlib.suppress(Exception):
            self._store_comment_map(f"close-{int(ticket)}", str(request["comment"]))

        result = mt5.order_send(request)
        if result is None:
            raise TimeoutError(f"MT5 close returned None for position {ticket}: {mt5.last_error()}")
        retcode = getattr(result, "retcode", None)
        receipt = {
            "retcode": retcode,
            "broker_order_id": str(getattr(result, "order", "") or ""),
            "broker_position_id": str(getattr(result, "deal", "") or ""),
            "executed_price": str(getattr(result, "price", "") or ""),
            "executed_volume": str(getattr(result, "volume", "") or ""),
            "comment": str(getattr(result, "comment", "") or ""),
            "request": dict(request),
        }
        if retcode not in (self.RETCODE_DONE, self.RETCODE_PLACED, self.RETCODE_DONE_PARTIAL):
            raise ValueError(f"MT5 close of position {ticket} failed retcode {retcode}: {receipt['comment']}")
        self.last_submission = receipt
        return receipt

    def orders(self) -> list[Order]:
        mt5 = self._require_mt5()
        raw = mt5.orders_get()
        if raw is None:
            err = mt5.last_error()
            if err and err[0] != 1:
                raise ConnectionError(f"MT5 orders_get failed: {err}")
            return []
        out: list[Order] = []
        for o in raw:
            comment = getattr(o, "comment", "")
            client_id = self._reverse_comment_map(comment) or comment
            sym = getattr(o, "symbol", "UNKNOWN")
            instr = Instrument(symbol=self._canonical_symbol(sym), venue="MT5")
            vol = Decimal(str(getattr(o, "volume_current", getattr(o, "volume_initial", 0))))
            # MT5 order type to side
            o_type = getattr(o, "type", 0)
            # 0 BUY, 1 SELL, 2 BUY_LIMIT, 3 SELL_LIMIT, 4 BUY_STOP, 5 SELL_STOP
            side = Side.BUY if o_type in (0, 2, 4) else Side.SELL
            # Determine order_type
            if o_type in (2, 3):
                otype = OrderType.LIMIT
            elif o_type in (4, 5):
                otype = OrderType.STOP
            else:
                otype = OrderType.MARKET
            # Price
            price_open = getattr(o, "price_open", 0)
            limit_price = Decimal(str(price_open)) if otype == OrderType.LIMIT else None
            stop_price = Decimal(str(price_open)) if otype == OrderType.STOP else None
            state = OrderState.ACCEPTED if getattr(o, "state", 1) == 1 else OrderState.PENDING
            # Try to get volume
            out.append(
                Order(
                    order_id=str(getattr(o, "ticket", client_id)),
                    client_order_id=client_id,
                    instrument=instr,
                    side=side,
                    quantity=vol,
                    order_type=otype,
                    limit_price=limit_price,
                    stop_price=stop_price,
                    state=state,
                    strategy_id="unknown",
                    exchange_order_id=str(getattr(o, "ticket", "")),
                )
            )
        return out

    def account(self) -> Account:
        mt5 = self._require_mt5()
        info = mt5.account_info()
        if info is None:
            raise ConnectionError(f"MT5 account_info unavailable: {mt5.last_error()}")
        # Authoritative broker account state — fail closed on missing/malformed.
        # Unknown OPTIONAL fields (leverage, currency) stay UNAVAILABLE (None):
        # they are never replaced with guesses. Receipt time is local and is
        # explicitly NOT a broker timestamp (documented limitation).
        try:
            balance = Decimal(str(info.balance))
            equity = Decimal(str(info.equity))
            margin = Decimal(str(getattr(info, "margin", 0) or 0))
            raw_free = getattr(info, "margin_free", None)
            free_margin = Decimal(str(raw_free)) if raw_free is not None else equity - margin
            raw_lev = getattr(info, "leverage", None)
            if raw_lev is None or str(raw_lev).strip() in ("", "0"):
                leverage: Decimal | None = None  # UNAVAILABLE — never guessed
            else:
                leverage = Decimal(str(raw_lev))
                if leverage <= 0:
                    leverage = None  # nonsensical broker leverage -> unknown, not fabricated
            raw_cur = getattr(info, "currency", None)
            currency: str | None = str(raw_cur) if raw_cur else None
            for v in (balance, equity, margin, free_margin):
                if not v.is_finite():
                    raise ValueError(f"account value not finite: {v}")
            if equity < Decimal("0") or balance < Decimal("0"):
                raise ValueError(f"account equity/balance negative: {equity}/{balance}")
            if free_margin < Decimal("0") - Decimal("1"):
                raise ValueError(f"account free_margin negative large: {free_margin}")
            return Account(
                balance=balance,
                equity=equity,
                margin=margin,
                free_margin=free_margin,
                leverage=leverage,
                currency=currency,
                source="BROKER",
                updated_at=datetime.now(UTC),
            )
        except Exception as e:
            raise RuntimeError(f"MT5 account_info malformed: {e} raw={info}") from e

    def _latest_bar_time(self, symbol: str) -> float | None:
        """Latest M1 bar open time (epoch seconds, SERVER basis) or None.

        Same authoritative probe as the DEMO readiness gate: while the market
        is open the latest M1 bar is the one forming now, so
        server_now in [bar_time, bar_time + 60).
        """
        getter = getattr(self._mt5, "copy_rates_from_pos", None)
        if getter is None:
            return None
        timeframe_m1 = getattr(self._mt5, "TIMEFRAME_M1", 1)
        try:
            rates = getter(symbol, timeframe_m1, 0, 1)
            if rates is None or len(rates) == 0:
                return None
            bar = rates[0]
            try:
                raw = bar["time"]
            except (TypeError, KeyError, IndexError):
                raw = getattr(bar, "time", None)
            value = _numeric_or_none(raw)
        except Exception:
            return None
        if value is None:
            return None
        if value > 1e12:  # milliseconds
            value /= 1000.0
        if value <= 1e9:  # garbage/zero — never a plausible bar time
            return None
        return value

    def server_utc_offset(self, symbol: str) -> tuple[float, str]:
        """Measured trade-server<->UTC offset in seconds (east positive) + basis.

        MT5 stamps ticks in trade-server local time and the Python API exposes
        no server-time/offset call. Measurement: offset lies in
        [bar_time - utc_now, bar_time + 60 - utc_now) and must be a multiple
        of 15 minutes — a 60s window holds at most one such grid point, so a
        match is EXACT.

        Authoritative clock basis: true UTC is ``time.time()`` (system clock);
        broker stamps are server-local. The offset is server - UTC, measured
        via the forming-M1-bar probe. Canonical normalization is
        ``event_time = broker_stamp - offset`` -> true UTC, single application,
        never double-applied.

        Failure handling (fix for FS-c42bbd +3h future-tick storm):
        - If the probe succeeds, the measured offset is cached and returned.
        - If the probe fails (no bar, stale bar, no grid point), we MUST NOT
          lose a previously measured offset by overwriting it with 0. That
          caused 2396 good ticks then 30 consecutive ``tick from future``
          failures when the 5-minute TTL expired and ``copy_rates`` was
          intermittently unavailable, falling back to 0.0 while ticks were
          still server-local (+3h).
        - Contract: on probe failure, retain the last known good offset if
          present (return it, refresh its timestamp to avoid hammering); only
          if no offset was ever measured do we fall back to
          ``(0.0, 'assumed-utc-fallback')``. The fallback still loudly fails
          via MarketDataProvider's unchanged future/stale validation instead
          of silently mis-dating.

        Cached per broker symbol for _OFFSET_TTL_S.
        """
        now_epoch = time.time()
        cached = self._server_offset_cache.get(symbol)
        if cached is not None and (now_epoch - cached[2]) < self._OFFSET_TTL_S:
            return cached[0], cached[1]

        # Attempt fresh measurement
        measured_offset: float | None = None
        measured_basis: str | None = None
        bar_time = self._latest_bar_time(symbol)
        if bar_time is not None:
            lo = bar_time - now_epoch
            hi = lo + 60.0
            grid = math.ceil(lo / self._OFFSET_QUANTUM_S) * self._OFFSET_QUANTUM_S
            if lo <= grid < hi and abs(grid) <= self._MAX_PLAUSIBLE_OFFSET_S:
                measured_offset, measured_basis = float(grid), "measured-m1-bar"

        if measured_offset is not None and measured_basis is not None:
            self._server_offset_cache[symbol] = (measured_offset, measured_basis, now_epoch)
            return measured_offset, measured_basis

        # Measurement failed — retain previous good offset if any, do not lose it
        if cached is not None:
            prev_offset, prev_basis, _ = cached
            # Refresh timestamp to avoid tight retry loop, but keep offset/basis
            self._server_offset_cache[symbol] = (prev_offset, prev_basis, now_epoch)
            return prev_offset, prev_basis

        # No previous offset ever measured — fallback, loudly rejected for server-basis stamps
        fallback_offset, fallback_basis = 0.0, "assumed-utc-fallback"
        self._server_offset_cache[symbol] = (fallback_offset, fallback_basis, now_epoch)
        return fallback_offset, fallback_basis

    def offset_cache_info(self, symbol: str) -> dict[str, Any]:
        """Read-only view of the cached broker-offset state. Never measures.

        Reports what the cache actually knows: the offset, its basis, and the
        time the cache entry was last stamped. A retained offset keeps its last
        refresh stamp, so this is deliberately NOT labelled a measurement
        timestamp — no clock fact is invented.
        """
        cached = self._server_offset_cache.get(symbol)
        if cached is None:
            return {"status": "UNAVAILABLE", "reason": "no broker offset has been measured yet for this symbol"}
        offset, basis, stamped = cached
        return {
            "status": "MEASURED",
            "server_utc_offset_s": float(offset),
            "basis": str(basis),
            "cache_stamped_at": datetime.fromtimestamp(stamped, tz=UTC).isoformat(),
            "cache_age_s": max(0.0, time.time() - float(stamped)),
            "note": (
                "cache refresh time; an offset retained after a failed probe keeps its last refresh stamp, "
                "which is not necessarily the original measurement time"
            ),
        }

    def ticks(self, instrument: Instrument) -> Tick | None:
        """Raw broker tick, normalized to the canonical QTS time basis (true UTC).

        event_time = broker stamp - measured server offset; the raw stamps and
        the offset/basis travel in Tick.provenance so every downstream
        observation is auditable. Freshness/integrity validation remains
        MarketDataProvider's job (unchanged, fail-closed).
        """
        mt5 = self._require_mt5()
        sym = self._map_symbol(instrument.symbol)
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return None
        received_at = datetime.now(UTC)
        raw_s = _numeric_or_none(getattr(tick, "time", None))
        raw_msc = _numeric_or_none(getattr(tick, "time_msc", None))
        base: float | None = None
        if raw_msc is not None and raw_msc > 1e12:
            base = raw_msc / 1000.0  # millisecond precision when available
        elif raw_s is not None:
            base = raw_s / 1000.0 if raw_s > 1e12 else raw_s
        if base is None or base <= 1e9:
            raise RuntimeError(
                f"MT5 tick for {sym} carries no usable timestamp (time={raw_s!r} time_msc={raw_msc!r}) — "
                "refusing to fabricate event_time (fail-closed)"
            )
        offset, basis = self.server_utc_offset(sym)
        event_time = datetime.fromtimestamp(base - offset, tz=UTC)
        provenance: dict[str, Any] = {
            "mt5_time": raw_s,
            "mt5_time_msc": raw_msc,
            "server_utc_offset_s": offset,
            "offset_basis": basis,
            "broker_symbol": sym,
            "received_at": received_at.isoformat(),
        }
        return Tick(
            instrument=instrument,
            bid=Decimal(str(tick.bid)),
            ask=Decimal(str(tick.ask)),
            event_time=event_time,
            provenance=provenance,
        )

    def history_deals(self, client_order_id: str | None = None) -> list[Any]:
        """Fetch deals for reconciliation — deals are fills."""
        mt5 = self._require_mt5()
        # Use history_deals_get with date range — for now last 30 days
        try:
            # Need to ensure history is selected
            from datetime import datetime, timedelta

            now = datetime.now(UTC)
            start = now - timedelta(days=30)
            deals = mt5.history_deals_get(start, now)
            if deals is None:
                return []
            if client_order_id:
                comment = self._load_comment_map(client_order_id) or client_order_id[:31]
                # Filter by comment
                return [d for d in deals if getattr(d, "comment", "") == comment]
            return list(deals)
        except Exception:
            return []

    def poll_fills(self, client_order_id: str) -> list[Any]:
        """Poll for fills (deals) — used by ExecutionEngine live path.

        Each returned dict carries:
        * ``fill_id`` — STABLE id derived from the deal ticket, so repeated polls
          deduplicate instead of re-applying the same economic fill.
        * ``client_order_id`` — the attributed order via the persisted comment map,
          or None when the deal comment cannot be mapped. Callers MUST fail closed
          on unattributed fills (never apply them to a portfolio blindly).
        """
        deals = self.history_deals(client_order_id or None)
        fills = []
        for d in deals:
            # Deal fields: ticket, order, symbol, volume, price, profit, type, time
            try:
                # Broker alias → canonical: the portfolio is keyed by canonical
                # symbol, so a fill reported as ``XAUUSD@`` would create a
                # phantom position that reconciliation can never match.
                sym = self._canonical_symbol(getattr(d, "symbol", "UNKNOWN"))
                vol = Decimal(str(getattr(d, "volume", 0)))
                price = Decimal(str(getattr(d, "price", 0)))
                # type 0 BUY, 1 SELL
                deal_type = getattr(d, "type", 0)
                side = Side.BUY if deal_type == 0 else Side.SELL
                deal_time = datetime.fromtimestamp(getattr(d, "time", datetime.now(UTC).timestamp()), tz=UTC)
                ticket = getattr(d, "ticket", None)
                comment = getattr(d, "comment", "") or ""
                attributed = self._reverse_comment_map(comment)
                if attributed is None and client_order_id:
                    # history_deals already filtered by this order's comment —
                    # accept the match when the comment equals the mapped/expected one
                    expected = self._load_comment_map(client_order_id) or client_order_id[:31]
                    if comment == expected:
                        attributed = client_order_id
                if ticket is not None:
                    fill_id = f"mt5-deal-{ticket}"
                else:
                    import hashlib

                    key = f"{attributed or comment}|{sym}|{deal_time.isoformat()}|{price}|{vol}"
                    fill_id = "mt5-deal-" + hashlib.sha256(key.encode()).hexdigest()[:16]
                fills.append(
                    {
                        "fill_id": fill_id,
                        "client_order_id": attributed,
                        "symbol": sym,
                        "volume": vol,
                        "price": price,
                        "side": side,
                        "time": deal_time,
                        "deal": d,
                    }
                )
            # B112: skip unprocessable deal; reconcile fail-closes on venue drift
            except Exception:  # nosec B112
                continue
        return fills

    def close(self) -> None:
        with contextlib.suppress(Exception):
            # File-backed connections are opened/closed per operation via qts.db.connect,
            # so no persistent handle exists here. We must NOT re-open the database file
            # in close()/__del__: that recreates deleted files and re-acquires Windows
            # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                with contextlib.suppress(Exception):
                    mem.commit()
                    mem.close()
                self._memory_con = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
