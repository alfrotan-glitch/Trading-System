"""MT5 adapter — authoritative, isolated, fail-closed.

Production execution boundary: all broker interaction is through this adapter.
No assumption of acceptance or fill. Every action is validated, normalized,
audited, and reconciled.

Symbol metadata is authoritative: contract_size, volume_min/max/step,
digits/precision, trade_mode, filling_mode, point, tick_size, trade_allowed.

Idempotency: client_order_id is stored in MT5 order comment (a short,
deterministic, ASCII-safe digest — see MT5_COMMENT_MAX — with the full
client_order_id ↔ comment mapping table persisted). On restart,
comment ↔ client_order_id mapping is recovered via history.

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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qts.adapters.base import MEASURED_SERVER_OFFSET_BASES, BrokerAdapter
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

#: Hard cap on the MT5 order ``comment`` field. The terminal documentation
#: allows 31 characters, but the MetaTrader5 Python library rejects comments
#: shorter than that — ``order_send`` returns ``None`` with
#: ``last_error() == (-2, 'Invalid "comment" argument')`` once a comment
#: reaches roughly 29-31 chars (real failure: journal_id=1,
#: ``demo-20260928T140630-884971d1e6``, 31 chars, refused on
#: WMMarkets-Demo). Some brokers also retain only the first 16 characters of
#: a stored comment, so QTS never sends more than 16: the library accepts it,
#: the broker stores it unchanged, and fill attribution by comment stays
#: exact. The full client_order_id lives in the persisted comment map —
#: the comment only has to be accepted by the broker, not carry identity.
MT5_COMMENT_MAX = 16


def mt5_comment_for(client_order_id: str) -> str:
    """Deterministic MT5-safe comment for a client_order_id (pure function).

    Exactly :data:`MT5_COMMENT_MAX` ASCII characters: a short ``qts`` marker
    plus a sha256 prefix of the client_order_id. The same id always yields
    the same comment (idempotent retries and restart recovery send/match the
    identical string), and 13 hex chars of sha256 make accidental collisions
    irrelevant at DEMO order volumes. Callers that persist attribution must
    store the mapping — see :meth:`MT5Adapter._store_comment_map`.
    """
    import hashlib

    digest = hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()
    comment = ("qts" + digest)[:MT5_COMMENT_MAX]
    if not comment.isascii() or not (0 < len(comment) <= MT5_COMMENT_MAX):  # pragma: no cover - guard
        raise ValueError(f"constructed an invalid MT5 comment for {client_order_id!r}: {comment!r}")
    return comment


def mt5_safe_comment_text(text: str) -> str:
    """Free-form comment (e.g. a position close marker) made MT5-safe.

    Keeps only printable ASCII and caps at :data:`MT5_COMMENT_MAX` — the same
    constraint that protects order submission. Pure truncation: nothing is
    invented, and an empty result stays empty so callers decide the default.
    """
    cleaned = "".join(ch for ch in str(text) if ch.isascii() and ch.isprintable())
    return cleaned[:MT5_COMMENT_MAX]


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


def _bar_field(bar: Any, name: str) -> Any:
    """Read one field from an MT5 rate entry (structured array or object)."""
    try:
        return bar[name]
    except (TypeError, KeyError, IndexError, ValueError):
        return getattr(bar, name, None)


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
    RETCODE_INVALID_STOPS = 10016
    RETCODE_TIMEOUT = 10012
    RETCODE_ERROR = 10011
    RETCODE_CANCEL = 10007
    RETCODE_MARKET_CLOSED = 10018
    RETCODE_PRICE_CHANGED = 10020
    RETCODE_PRICE_OFF = 10021
    RETCODE_INVALID_EXPIRATION = 10022
    RETCODE_TOO_MANY_REQUESTS = 10024
    RETCODE_NO_CHANGES = 10025
    RETCODE_SERVER_DISABLES = 10026
    RETCODE_CLIENT_DISABLES = 10027
    RETCODE_FROZEN = 10029
    RETCODE_INVALID_FILL = 10030
    RETCODE_ONLY_REAL = 10032
    RETCODE_LIMIT_ORDERS = 10033
    RETCODE_LIMIT_VOLUME = 10034
    RETCODE_INVALID_ORDER = 10035
    RETCODE_POSITION_CLOSED = 10036
    RETCODE_INVALID_CLOSE_VOLUME = 10038
    RETCODE_CLOSE_ORDER_EXIST = 10039
    RETCODE_LIMIT_POSITIONS = 10040
    RETCODE_REJECT_CANCEL = 10041
    RETCODE_LONG_ONLY = 10042
    RETCODE_SHORT_ONLY = 10043
    RETCODE_CLOSE_ONLY = 10044
    RETCODE_FIFO_CLOSE = 10045
    RETCODE_HEDGE_PROHIBITED = 10046
    RETCODE_CONNECTION = 10031
    RETCODE_LOCKED = 10028
    RETCODE_NO_MONEY = 10019
    RETCODE_TRADE_DISABLED = 10017

    # Ambiguous retcodes that imply unknown broker state
    AMBIGUOUS_RETCODES = {10011, 10012, 10028, 10031}

    # --- Canonical timestamp contract (server-basis MT5 stamps -> true UTC) ---
    # Prefer a fresh raw tick for calibration: its server timestamp carries
    # second/millisecond precision, so broker offsets such as UTC+2:59 are not
    # rounded to a false UTC+3. The forming-M1 bar remains the conservative
    # fallback and is only used as a minute-resolution calibration.
    _OFFSET_QUANTUM_S = 60.0
    _OFFSET_TTL_S = 300.0  # re-measure cadence; offsets only shift on DST changes
    _OFFSET_TICK_MAX_AGE_S = 120.0
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
        from qts.adapters.identity import probe_broker_identity

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
            existing = con.execute(
                "SELECT client_order_id FROM mt5_comment_map WHERE mt5_comment=?",
                (comment,),
            ).fetchone()
            if existing is not None and existing[0] != client_order_id:
                raise RuntimeError(
                    f"MT5 comment collision: {comment!r} already belongs to {existing[0]!r}"
                )
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

    def _load_comment_created_at(self, client_order_id: str) -> datetime | None:
        """Return the persisted broker-attribution start time for one client order."""
        with db_connect(self._db_path) as con:
            row = con.execute(
                "SELECT created_at FROM mt5_comment_map WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
        if not row or not row[0]:
            return None
        try:
            value = datetime.fromisoformat(str(row[0]))
        except ValueError as exc:
            raise RuntimeError(
                f"invalid persisted MT5 comment timestamp for {client_order_id}: {row[0]!r}"
            ) from exc
        if value.tzinfo is None:
            raise RuntimeError(
                f"persisted MT5 comment timestamp is naive for {client_order_id}: {row[0]!r}"
            )
        return value.astimezone(UTC)

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
        """Establish the terminal session once, then authenticate if configured."""
        if path:
            self.config["path"] = path
            self._session = None
        mt5 = self._module()
        login = login or self.config.get("login")
        password = password or self.config.get("password")
        server = server or self.config.get("server")
        path = path or self.config.get("path")
        kwargs: dict[str, Any] = {}
        normalized_path = normalize_terminal_path(path)
        if normalized_path:
            kwargs["path"] = normalized_path
        if not mt5.initialize(**kwargs):
            raise MT5SessionError(_session_diagnosis(mt5.last_error(), normalized_path))
        if login and password and server and not mt5.login(login, password, server):
            with contextlib.suppress(Exception):
                mt5.shutdown()
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        self._session = None
        self.ensure_session()

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

    # ------------------------------------------------------------------
    # Actual execution cost evidence (phase 3)
    #
    # ``last_submission`` used to carry only ids and the executed price. The
    # broker's own commission/swap/fee/spread — the whole point of measuring
    # real costs — was fetched and thrown away. These helpers preserve it.
    # ------------------------------------------------------------------

    @staticmethod
    def _deal_rows_as_dicts(rows: Any) -> list[dict[str, Any]]:
        """Freeze MT5 deal rows into plain dicts before they go out of scope.

        MT5 returns a numpy structured array whose rows are views; holding the
        live objects across a reconnect is not safe. Absent attributes stay
        ABSENT (never defaulted to 0) — a missing field must remain
        distinguishable from a genuine zero charge.
        """
        out: list[dict[str, Any]] = []
        for row in rows or ():
            record: dict[str, Any] = {}
            for name in (
                "ticket", "order", "position_id", "symbol", "type", "entry",
                "volume", "price", "profit", "commission", "swap", "fee",
                "time", "time_msc", "comment", "magic", "reason", "external_id",
            ):
                value = getattr(row, name, None)
                if value is not None:
                    record[name] = value
            out.append(record)
        return out

    @staticmethod
    def _account_currency(mt5: Any) -> str | None:
        """Deposit currency of the account, or None when unavailable.

        MT5 reports money amounts in the account deposit currency, not in USD.
        Returning None rather than assuming "USD" is what keeps a currency
        conversion assumption from being smuggled in silently.
        """
        if mt5 is None:
            return None
        try:
            info = mt5.account_info()
        except Exception:
            return None
        currency = getattr(info, "currency", None)
        return str(currency) if currency else None

    @staticmethod
    def _quote_snapshot(mt5: Any, symbol: str) -> dict[str, Any]:
        """Pre-trade bid/ask/spread, the reference slippage is measured against.

        Slippage is only meaningful against the quote that existed when the
        order was sent. Captured BEFORE the send so a post-fill re-quote cannot
        make the fill look better than it was. Unavailable quotes are recorded
        as UNAVAILABLE, never as 0 spread.
        """
        snapshot: dict[str, Any] = {
            "schema": "qts.broker_quote_snapshot.v1",
            "symbol": symbol,
            "observed_at": datetime.now(UTC).isoformat(),
            "bid": None,
            "ask": None,
            "spread_points": None,
            "unavailable": True,
        }
        if mt5 is None:
            return snapshot
        try:
            tick = mt5.symbol_info_tick(symbol)
        except Exception:
            return snapshot
        if tick is None:
            return snapshot
        bid = getattr(tick, "bid", None)
        ask = getattr(tick, "ask", None)
        snapshot["bid"] = str(bid) if bid else None
        snapshot["ask"] = str(ask) if ask else None
        try:
            info = mt5.symbol_info(symbol)
        except Exception:
            info = None
        point = getattr(info, "point", None) if info is not None else None
        digits = getattr(info, "digits", None) if info is not None else None
        spread = getattr(tick, "spread", None)
        if spread is not None:
            snapshot["spread_points"] = str(spread)
        elif point not in (None, 0) and bid and ask:
            try:
                decimals = int(digits) if digits is not None else 8
                spread_price = Decimal(str(ask)) - Decimal(str(bid))
                snapshot["spread_points"] = str(
                    int((spread_price / Decimal(str(point))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                )
                snapshot["spread_price_units"] = str(spread_price.quantize(Decimal(f"1e-{decimals}")))
            except (TypeError, ValueError, InvalidOperation, ArithmeticError):
                pass
        snapshot["unavailable"] = snapshot["bid"] is None and snapshot["ask"] is None
        return snapshot

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

    def _order_send(self, mt5: Any, request: dict[str, Any], *, operation: str) -> Any:
        """Single broker-send primitive for every MT5 trade operation.

        Keeping the raw MT5 call here makes broker submission auditable: entry,
        cancel, and close may build different requests, but none may bypass the
        adapter's one send authority.
        """
        try:
            result = mt5.order_send(request)
        except Exception as exc:
            raise TimeoutError(f"MT5 {operation} transport failure: {exc}") from exc
        if result is None:
            raise TimeoutError(f"MT5 {operation} returned None: {mt5.last_error()}")
        return result

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

    def reconnect(self) -> bool:
        """Perform one explicit reconnect attempt and verify the session."""
        mt5 = self._module()
        with contextlib.suppress(Exception):
            mt5.shutdown()
        self._session = None
        kwargs: dict[str, Any] = {}
        path = normalize_terminal_path(self.config.get("path"))
        if path:
            kwargs["path"] = path
        try:
            if not mt5.initialize(**kwargs):
                return False
            login = self.config.get("login")
            password = self.config.get("password")
            server = self.config.get("server")
            if login and password and server and not mt5.login(login, password, server):
                return False
            self._session = None
            self.ensure_session()
            return self.is_connected()
        except Exception:
            self._session = None
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

    def validate_and_normalize_quantity(self, quantity: Decimal, spec: SymbolSpec) -> Decimal:
        """Validate quantity against broker constraints without implicit rounding."""
        if quantity <= 0:
            raise ValueError(f"quantity must be >0, got {quantity}")
        if quantity < spec.volume_min - Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} < broker min {spec.volume_min} for {spec.symbol}")
        if quantity > spec.volume_max + Decimal("0.0000001"):
            raise ValueError(f"quantity {quantity} > broker max {spec.volume_max} for {spec.symbol}")
        remainder = quantity % spec.volume_step
        if remainder != 0 and abs(remainder) > Decimal("0.0000001") and abs(spec.volume_step - remainder) > Decimal("0.0000001"):
            raise ValueError(
                f"quantity {quantity} is not a multiple of broker step {spec.volume_step} for {spec.symbol}"
            )
        normalized = quantity.quantize(spec.volume_step)
        if normalized < spec.volume_min - Decimal("0.0000001") or normalized > spec.volume_max + Decimal("0.0000001"):
            raise ValueError(
                f"quantity {normalized} out of bounds [{spec.volume_min}, {spec.volume_max}] for {spec.symbol}"
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
        """MT5-safe order comment — deterministic, short, ASCII-only.

        Regression (journal_id=1, ``demo-20260928T140630-884971d1e6``): the
        31-char client_order_id used to be sent verbatim, and the MetaTrader5
        library refused the whole request — ``order_send`` returned ``None``
        with ``last_error() == (-2, 'Invalid "comment" argument')`` — even
        though the terminal documentation allows 31 characters. The pre-trade
        dry-run did not catch it because it never validates the comment field.

        Every comment is now built by :func:`mt5_comment_for` (exactly
        :data:`MT5_COMMENT_MAX` ASCII chars, well below every observed
        limit), and the full client_order_id ↔ comment mapping is persisted
        so restart recovery and fill attribution keep working. An invalid
        comment is raised, never sent: fail closed.
        """
        comment = mt5_comment_for(client_order_id)
        if not comment.isascii() or not (0 < len(comment) <= MT5_COMMENT_MAX):  # pragma: no cover - guard
            raise ValueError(f"refusing to send an invalid MT5 comment for {client_order_id!r}: {comment!r}")
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

        # Pre-trade quote: the reference slippage is measured against. Taken
        # BEFORE the send so the fill can never be judged against a later,
        # more favourable quote.
        pre_trade_quote = self._quote_snapshot(mt5, mt5_symbol)

        # All broker sends pass through the single MT5 send authority.
        result = self._order_send(mt5, request, operation=f"order {intent.client_order_id}")

        # Classify result
        retcode = getattr(result, "retcode", None)
        # Success codes
        if retcode in (self.RETCODE_DONE, self.RETCODE_PLACED, self.RETCODE_DONE_PARTIAL):
            # Accepted — create Order with exchange_order_id = result.order
            exchange_id = str(getattr(result, "order", "")) or str(getattr(result, "deal", ""))
            # Full broker receipt for the DEMO journal (order id, position/deal
            # id, executed price/volume). Captured here because this is the only
            # place the raw result exists.
            position_identifier = ""
            if intent.order_type == OrderType.MARKET:
                deal_ticket = int(getattr(result, "deal", 0) or 0)
                if deal_ticket <= 0:
                    raise TimeoutError(
                        f"MT5 market order {intent.client_order_id} completed without a broker deal ticket"
                    )
                try:
                    deal_rows = mt5.history_deals_get(ticket=deal_ticket)
                except Exception as exc:
                    raise TimeoutError(
                        f"MT5 market order {intent.client_order_id} position identity lookup failed: {exc}"
                    ) from exc
                if not deal_rows:
                    raise TimeoutError(
                        f"MT5 market order {intent.client_order_id} completed but its deal is not readable"
                    )
                expected_order = int(getattr(result, "order", 0) or 0)
                if expected_order > 0:
                    deal_rows = [
                        deal for deal in deal_rows
                        if int(getattr(deal, "order", 0) or 0) == expected_order
                    ]
                if not deal_rows:
                    raise TimeoutError(
                        f"MT5 market order {intent.client_order_id} deal ticket is not attributable to the submitted order"
                    )
                position_ids = {
                    int(getattr(deal, "position_id", 0) or 0)
                    for deal in deal_rows
                    if int(getattr(deal, "position_id", 0) or 0) > 0
                }
                if len(position_ids) != 1:
                    raise TimeoutError(
                        f"MT5 market order {intent.client_order_id} has no unique position identifier: {position_ids}"
                    )
                position_identifier = str(next(iter(position_ids)))

            # The deal rows here are the broker's own record of what it
            # actually charged. They are preserved verbatim: commission, swap
            # and fee are what cost measurement exists to observe, and they
            # cannot be re-derived from anywhere else.
            self.last_submission = {
                "retcode": retcode,
                "broker_order_id": str(getattr(result, "order", "") or ""),
                "broker_position_id": position_identifier,
                "executed_price": str(getattr(result, "price", "") or ""),
                "executed_volume": str(getattr(result, "volume", "") or ""),
                "comment": str(getattr(result, "comment", "") or ""),
                "request": dict(request),
                "deal_rows": self._deal_rows_as_dicts(deal_rows)
                if intent.order_type == OrderType.MARKET
                else [],
                "pre_trade_quote": pre_trade_quote,
                "account_currency": self._account_currency(mt5),
                "partial_fill": retcode == self.RETCODE_DONE_PARTIAL,
                "captured_at": datetime.now(UTC).isoformat(),
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
            if retcode in {
                self.RETCODE_REQUOTE,
                self.RETCODE_REJECT,
                self.RETCODE_CANCEL,
                self.RETCODE_INVALID,
                self.RETCODE_INVALID_VOLUME,
                self.RETCODE_INVALID_PRICE,
                self.RETCODE_INVALID_STOPS,
                self.RETCODE_TRADE_DISABLED,
                self.RETCODE_MARKET_CLOSED,
                self.RETCODE_NO_MONEY,
                self.RETCODE_PRICE_CHANGED,
                self.RETCODE_PRICE_OFF,
                self.RETCODE_INVALID_EXPIRATION,
                self.RETCODE_TOO_MANY_REQUESTS,
                self.RETCODE_NO_CHANGES,
                self.RETCODE_SERVER_DISABLES,
                self.RETCODE_CLIENT_DISABLES,
                self.RETCODE_FROZEN,
                self.RETCODE_INVALID_FILL,
                self.RETCODE_ONLY_REAL,
                self.RETCODE_LIMIT_ORDERS,
                self.RETCODE_LIMIT_VOLUME,
                self.RETCODE_INVALID_ORDER,
                self.RETCODE_POSITION_CLOSED,
                self.RETCODE_INVALID_CLOSE_VOLUME,
                self.RETCODE_CLOSE_ORDER_EXIST,
                self.RETCODE_LIMIT_POSITIONS,
                self.RETCODE_REJECT_CANCEL,
                self.RETCODE_LONG_ONLY,
                self.RETCODE_SHORT_ONLY,
                self.RETCODE_CLOSE_ONLY,
                self.RETCODE_FIFO_CLOSE,
                self.RETCODE_HEDGE_PROHIBITED,
            }:
                raise ValueError(f"MT5 rejected {intent.client_order_id} retcode {retcode}: {comment}")
            # An unrecognized server code is not safe to interpret as a
            # definitive rejection. MT5 can add return codes, and some codes
            # indicate processing/connection uncertainty. Reconcile before any
            # retry so an unknown outcome can never become a duplicate trade.
            raise TimeoutError(
                f"MT5 unknown/uncertain retcode {retcode} for {intent.client_order_id}: {comment}"
            )

    def cancel(self, client_order_id: str) -> None:
        mt5 = self._require_mt5()
        # Find MT5 order by comment
        comment = self._load_comment_map(client_order_id) or mt5_comment_for(client_order_id)
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
        result = self._order_send(mt5, request, operation=f"cancel {client_order_id}")
        if getattr(result, "retcode", None) not in (
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
        seen_symbols: set[str] = set()
        for p in raw:
            # This execution model is net-position based: one broker position
            # per canonical symbol. Never collapse multiple MT5 positions into
            # one dict entry, because that would hide real exposure.
            sym = getattr(p, "symbol", "UNKNOWN")
            canonical = self._canonical_symbol(sym)
            if canonical in seen_symbols:
                raise RuntimeError(
                    f"multiple broker positions for canonical symbol {canonical} "
                    "are unsupported by the net-position execution model"
                )
            seen_symbols.add(canonical)
            vol = Decimal(str(getattr(p, "volume", 0)))
            price_open = Decimal(str(getattr(p, "price_open", 0)))
            # Broker metadata is authoritative for risk/notional math;
            # never project an open position with the domain default contract size.
            spec = self.get_symbol_spec(canonical)
            instr = Instrument(
                symbol=canonical,
                venue="MT5",
                contract_size=spec.contract_size,
                lot_size=spec.volume_step,
                tick_size=spec.tick_size,
            )
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
                    "position_id": getattr(p, "identifier", getattr(p, "position_id", None)),
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
        broker_volume = Decimal(str(getattr(pos, "volume", 0)))
        volume_dec = broker_volume if volume is None else Decimal(str(volume))
        if broker_volume <= 0 or volume_dec <= 0:
            raise ValueError(f"close volume {volume_dec} must be > 0")
        if volume_dec != broker_volume:
            raise ValueError(
                f"partial closes are unsupported: requested {volume_dec}, broker position is {broker_volume}"
            )
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
        close_client_id = f"close-{int(ticket)}-{uuid.uuid4().hex[:10]}"
        close_comment = mt5_comment_for(close_client_id)
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume_dec),
            "type": close_type,
            "position": int(ticket),
            "price": price,
            "deviation": int(self.config.get("deviation", 20)),
            "magic": int(self.config.get("magic", 20250916)),
            # Use the same deterministic, short comment mapping as entries.
            # A unique close id prevents an old partial-close deal from being
            # replayed into a later close of the same position ticket.
            "comment": close_comment,
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            "type_filling": filling,
        }
        self._store_comment_map(close_client_id, close_comment)

        result = self._order_send(mt5, request, operation=f"close position {ticket}")
        retcode = getattr(result, "retcode", None)
        position_identifier = getattr(pos, "identifier", getattr(pos, "position_id", None))
        if position_identifier is None or int(position_identifier) <= 0:
            raise RuntimeError(
                f"MT5 position {ticket} has no valid POSITION_IDENTIFIER — refusing a close "
                "whose realized P&L cannot be correlated"
            )
        receipt = {
            "retcode": retcode,
            "broker_order_id": str(getattr(result, "order", "") or ""),
            "broker_position_id": str(int(position_identifier)),
            "client_order_id": close_client_id,
            "executed_price": str(getattr(result, "price", "") or ""),
            "executed_volume": str(getattr(result, "volume", "") or ""),
            "comment": str(getattr(result, "comment", "") or ""),
            "request": dict(request),
        }
        if retcode in self.AMBIGUOUS_RETCODES:
            raise TimeoutError(
                f"MT5 close of position {ticket} has ambiguous retcode {retcode}: {receipt['comment']}"
            )
        if retcode not in (self.RETCODE_DONE, self.RETCODE_PLACED, self.RETCODE_DONE_PARTIAL):
            raise ValueError(f"MT5 close of position {ticket} failed retcode {retcode}: {receipt['comment']}")
        # Same cost evidence as submit(): the close carries the swap accrued
        # over the life of the position, which is exactly the charge that
        # arrives late and is easiest to miss.
        receipt["deal_rows"] = self._deal_rows_as_dicts(
            self._deals_for_order(mt5, int(str(receipt.get("broker_order_id") or 0) or 0))
        )
        receipt["account_currency"] = self._account_currency(mt5)
        receipt["captured_at"] = datetime.now(UTC).isoformat()
        self.last_submission = receipt
        return receipt

    @staticmethod
    def _deals_for_order(mt5: Any, broker_order_id: int) -> list[Any]:
        """Deal rows attributed to one broker order, or [] when unreadable.

        A failure here must not fail a close that already succeeded: the
        position is flat either way. But an unreadable deal is recorded as
        MISSING evidence, never as a zero-cost close.
        """
        if mt5 is None or broker_order_id <= 0:
            return []
        try:
            deals = mt5.history_deals_get(order=broker_order_id)
        except Exception:
            return []
        if deals is None:
            return []
        return [deal for deal in deals if int(getattr(deal, "order", 0) or 0) == broker_order_id]

    def position_realized_result(self, ticket: int, *, client_order_id: str | None = None) -> dict[str, Any]:
        """Return broker-authoritative realized P&L and charges for one MT5 position.

        MT5 exposes the economic result on deals. The Python API can query all
        deals for a specific position directly, so there is no arbitrary
        time-window or whole-history scan.
        """
        mt5 = self._require_mt5()
        try:
            raw = mt5.history_deals_get(position=int(ticket))
        except Exception as exc:
            raise ConnectionError(f"MT5 deal history unavailable for position {ticket}: {exc}") from exc
        if raw is None:
            raise ConnectionError(f"MT5 deal history unavailable for position {ticket}: {mt5.last_error()}")
        matched = list(raw)
        if client_order_id:
            comment = self._load_comment_map(client_order_id)
            if not comment:
                raise RuntimeError(
                    f"no persisted MT5 comment mapping for close client order {client_order_id}"
                )
            matched = [deal for deal in matched if str(getattr(deal, "comment", "") or "") == comment]
        if not matched:
            raise RuntimeError(f"no MT5 deals found for closed position {ticket}; realized P&L is unproven")

        def dec(deal: Any, name: str) -> Decimal:
            raw_value = getattr(deal, name, 0) or 0
            value = Decimal(str(raw_value))
            if not value.is_finite():
                raise ValueError(f"non-finite MT5 deal {name} for position {ticket}: {raw_value}")
            return value

        profit = sum((dec(d, "profit") for d in matched), Decimal("0"))
        commission = sum((dec(d, "commission") for d in matched), Decimal("0"))
        swap = sum((dec(d, "swap") for d in matched), Decimal("0"))
        fee = sum((dec(d, "fee") for d in matched), Decimal("0"))
        net = profit + commission + swap + fee
        return {
            "position_ticket": int(ticket),
            "deal_count": len(matched),
            "profit": profit,
            "commission": commission,
            "swap": swap,
            "fee": fee,
            "net_realized_pnl": net,
            "deal_tickets": [
                str(getattr(d, "ticket", ""))
                for d in matched
                if getattr(d, "ticket", None) is not None
            ],
        }

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
            canonical = self._canonical_symbol(sym)
            spec = self.get_symbol_spec(canonical)
            instr = Instrument(
                symbol=canonical,
                venue="MT5",
                contract_size=spec.contract_size,
                lot_size=spec.volume_step,
                tick_size=spec.tick_size,
            )
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
        """Measure the broker-server -> UTC offset without inventing precision.

        A fresh tick is the primary calibration source because its timestamp is
        close to the current server clock and can resolve offsets such as +02:59.
        If no fresh tick is available, the forming M1 bar provides a conservative
        minute-resolution fallback. Failed probes never replace a known-good
        offset with zero.
        """
        now_epoch = time.time()
        cached = self._server_offset_cache.get(symbol)
        if cached is not None and (now_epoch - cached[2]) < self._OFFSET_TTL_S:
            return cached[0], cached[1]

        measured_offset: float | None = None
        measured_basis: str | None = None

        # Primary calibration: a fresh broker tick, but only after it is
        # cross-checked against the forming M1 bar. A tick alone cannot reveal
        # the server offset: subtracting an arbitrary tick from UTC simply
        # turns an old tick into a plausible-looking "offset" (e.g. +02:55
        # for a tick five minutes stale). The bar and tick share the broker
        # clock, so their same-basis relationship is the authoritative guard.
        mt5 = self._mt5
        bar_time = self._latest_bar_time(symbol)
        try:
            tick = mt5.symbol_info_tick(symbol) if mt5 is not None else None
        except Exception:
            tick = None
        if tick is not None:
            raw_msc = _numeric_or_none(getattr(tick, "time_msc", None))
            raw_s = _numeric_or_none(getattr(tick, "time", None))
            if raw_msc is not None and raw_msc > 1e12:
                tick_epoch = raw_msc / 1000.0
            elif raw_s is not None:
                tick_epoch = raw_s / 1000.0 if raw_s > 1e12 else raw_s
            else:
                tick_epoch = None
            if tick_epoch is not None and tick_epoch > 1e9:
                tick_is_current_bar = (
                    bar_time is not None
                    and bar_time <= tick_epoch <= bar_time + 60.0 + 5.0
                )
                if tick_is_current_bar:
                    candidate = round((tick_epoch - now_epoch) / 60.0) * 60.0
                    if abs(candidate) <= self._MAX_PLAUSIBLE_OFFSET_S:
                        measured_offset = float(candidate)
                        # If the tick agrees with the forming M1 bar's minute
                        # offset, the bar is already sufficient evidence. Use
                        # the tick basis only when it resolves a finer/different
                        # offset such as a broker's +02:59 clock.
                        bar_basis_offset: float | None = None
                        if bar_time is not None:
                            bar_lo = bar_time - now_epoch
                            bar_grid = math.ceil(bar_lo / self._OFFSET_QUANTUM_S) * self._OFFSET_QUANTUM_S
                            if bar_lo <= bar_grid < bar_lo + 60.0 and abs(bar_grid) <= self._MAX_PLAUSIBLE_OFFSET_S:
                                bar_basis_offset = float(bar_grid)
                        measured_basis = (
                            "measured-m1-bar"
                            if bar_basis_offset is not None and candidate == bar_basis_offset
                            else "measured-fresh-tick"
                        )

        # Conservative fallback: forming M1 bar. The bar is minute-aligned, so
        # minute resolution is the honest precision available from this probe.
        if measured_offset is None and bar_time is not None:
                lo = bar_time - now_epoch
                hi = lo + 60.0
                grid = math.ceil(lo / self._OFFSET_QUANTUM_S) * self._OFFSET_QUANTUM_S
                if lo <= grid < hi and abs(grid) <= self._MAX_PLAUSIBLE_OFFSET_S:
                    measured_offset, measured_basis = float(grid), "measured-m1-bar"

        if measured_offset is not None and measured_basis is not None:
            self._server_offset_cache[symbol] = (measured_offset, measured_basis, now_epoch)
            return measured_offset, measured_basis

        # Measurement failed — retain the last good offset, but mark the cache
        # refresh time so repeated failures do not hammer the terminal.
        if cached is not None:
            prev_offset, prev_basis, _ = cached
            self._server_offset_cache[symbol] = (prev_offset, prev_basis, now_epoch)
            return prev_offset, prev_basis

        # No measurement exists. Do not cache a fabricated UTC basis.
        return 0.0, "assumed-utc-fallback"

    #: Hard bound on a startup warmup window. Enough for any registered EMA
    #: period, small enough that a DEMO restart costs one bounded M15 read.
    MAX_WARMUP_BARS = 512

    def recent_closed_bars(
        self,
        symbol: str,
        *,
        timeframe_minutes: int,
        count: int,
    ) -> dict[str, Any]:
        """Bounded window of **completed** bars from the terminal (fail closed).

        This is the restart-warmup source for a bar-based strategy: a DEMO
        process may be restarted at any time, and rebuilding bar history from
        live quotes alone would cost hours of ``NO_TRADE``.

        Contract:
        * only bars whose normalized boundary plus the timeframe is already in
          the past are returned — the forming bar is always excluded;
        * timestamps are normalized with the measured server→UTC offset, and an
          unmeasured clock refuses the whole window (a mislabelled bar boundary
          would silently corrupt every later signal);
        * duplicates are removed, the result is ascending by boundary and capped
          at ``count`` bars;
        * nothing is fabricated: an unreadable/empty/late rate window returns a
          failure record, never synthesized bars.

        Returns ``{"ok": True, "bars": [(utc_boundary, close), ...], "basis",
        "server_utc_offset_s", "symbol", "forming_bar_excluded"}`` or
        ``{"ok": False, "error": ...}``.
        """
        try:
            want = int(count)
            minutes = int(timeframe_minutes)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": f"invalid warmup request: {exc}"}
        if want < 1 or minutes < 1 or 60 % minutes != 0:
            return {"ok": False, "error": f"invalid warmup request: count={count} timeframe={timeframe_minutes}"}
        want = min(want, self.MAX_WARMUP_BARS)

        mt5 = self._mt5 or _optional_mt5_module()
        if mt5 is None:
            return {"ok": False, "error": "MetaTrader5 module is unavailable"}
        broker_sym = self._map_symbol(symbol)
        tf_const = getattr(mt5, f"TIMEFRAME_M{minutes}", None)
        if tf_const is None:
            return {"ok": False, "error": f"terminal exposes no M{minutes} timeframe constant"}

        offset, basis = self.server_utc_offset(symbol)
        if basis not in MEASURED_SERVER_OFFSET_BASES:
            return {
                "ok": False,
                "error": (
                    f"server clock offset for {broker_sym} is not measured (basis={basis}) — "
                    "refusing to label bar history"
                ),
            }
        try:
            rates = mt5.copy_rates_from_pos(broker_sym, tf_const, 0, want + 2)
        except Exception as exc:
            return {"ok": False, "error": f"terminal rate request failed: {type(exc).__name__}: {exc}"}
        if rates is None or len(rates) == 0:
            detail = ""
            with contextlib.suppress(Exception):
                detail = f" ({mt5.last_error()})"
            return {"ok": False, "error": f"terminal returned no M{minutes} rates for {broker_sym}{detail}"}

        # Same clock the offset measurement uses: a bar is complete when its
        # end is not later than "now" on this UTC basis.
        now_epoch = time.time()
        span_s = minutes * 60.0
        bars: list[tuple[datetime, Decimal]] = []
        seen: set[datetime] = set()
        future_dated = 0
        malformed = 0
        for bar in rates:
            raw_time = _numeric_or_none(_bar_field(bar, "time"))
            raw_close = _numeric_or_none(_bar_field(bar, "close"))
            if raw_time is None or raw_close is None or raw_close <= 0:
                malformed += 1
                continue
            if raw_time > 1e12:  # milliseconds
                raw_time /= 1000.0
            if raw_time <= 1e9:
                malformed += 1
                continue
            boundary = datetime.fromtimestamp(raw_time - offset, tz=UTC).replace(second=0, microsecond=0)
            if raw_time - offset + span_s > now_epoch:
                future_dated += 1  # includes the currently forming bar
                continue
            if boundary in seen:
                continue
            seen.add(boundary)
            bars.append((boundary, Decimal(str(raw_close))))

        bars.sort(key=lambda item: item[0])
        bars = bars[-want:]
        if not bars:
            return {
                "ok": False,
                "error": (
                    f"no completed M{minutes} bars for {broker_sym} "
                    f"(dropped {future_dated} uncompleted/future, {malformed} malformed)"
                ),
            }
        return {
            "ok": True,
            "symbol": broker_sym,
            "timeframe_minutes": minutes,
            "bars": bars,
            "basis": basis,
            "server_utc_offset_s": float(offset),
            "forming_bar_excluded": True,
            "dropped_uncompleted": future_dated,
            "dropped_malformed": malformed,
            "requested_bars": want,
        }

    def raw_tick_freshness(self, symbol: str, epoch_seconds: float | None) -> tuple[bool, str]:
        """Judge a RAW broker stamp with the readiness gate's server-clock contract.

        The single shared answer to "is this broker quote fresh?" — the same
        contract the DEMO readiness gate applies, evaluated on the raw
        server-basis stamp (never on a normalized ``event_time``, which is
        unusable while the server-UTC offset is unmeasured). ``symbol`` may be
        canonical; it is mapped before the bar probe.
        """
        from qts.lifecycle.demo_gate import evaluate_tick_epoch_freshness

        mt5 = self._require_mt5()
        broker_sym = self._map_symbol(symbol)
        fresh, detail, _blocker = evaluate_tick_epoch_freshness(epoch_seconds, mt5, broker_sym, time.time())
        return fresh, detail

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
        """Fetch recent broker deals; history errors are execution-unsafe."""
        mt5 = self._require_mt5()
        try:
            now = datetime.now(UTC)
            if client_order_id:
                start = self._load_comment_created_at(client_order_id)
                if start is None:
                    raise RuntimeError(
                        f"no persisted creation time for correlated client order {client_order_id}"
                    )
            else:
                # Uncorrelated history is intentionally bounded. Execution paths
                # must always provide a client_order_id; this branch is retained
                # only for diagnostics/legacy callers and must never drive fill
                # attribution.
                from datetime import timedelta

                start = now - timedelta(days=30)
            deals = mt5.history_deals_get(start, now)
        except Exception as exc:
            raise ConnectionError(f"MT5 deal history unavailable: {exc}") from exc
        if deals is None:
            raise ConnectionError(f"MT5 deal history unavailable: {mt5.last_error()}")
        if client_order_id:
            comment = self._load_comment_map(client_order_id) or mt5_comment_for(client_order_id)
            return [d for d in deals if getattr(d, "comment", "") == comment]
        return list(deals)

    def poll_fills(self, client_order_id: str) -> list[Any]:
        """Return only fully attributable, stable broker deals for one client order.

        A malformed or unattributable deal is an execution safety failure, not a
        deal to skip. The caller must suspend and reconcile rather than silently
        pretending the broker history was empty.
        """
        if not client_order_id:
            raise ValueError("client_order_id is required for correlated fill polling")
        deals = self.history_deals(client_order_id)
        fills = []
        expected_comment = self._load_comment_map(client_order_id) or mt5_comment_for(client_order_id)

        for d in deals:
            sym = self._canonical_symbol(getattr(d, "symbol", ""))
            if not sym or sym == "UNKNOWN":
                raise RuntimeError(f"MT5 deal for {client_order_id} has no valid symbol")
            ticket = getattr(d, "ticket", None)
            if ticket is None:
                raise RuntimeError(f"MT5 deal for {client_order_id} has no stable ticket")
            try:
                ticket_int = int(ticket)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"MT5 deal for {client_order_id} has invalid ticket {ticket!r}"
                ) from exc
            if ticket_int <= 0:
                raise RuntimeError(f"MT5 deal for {client_order_id} has invalid ticket {ticket_int}")
            comment = getattr(d, "comment", "") or ""
            attributed = self._reverse_comment_map(comment)
            if attributed != client_order_id:
                if comment != expected_comment:
                    raise RuntimeError(
                        f"MT5 deal {ticket_int} for {client_order_id} has unexpected comment {comment!r}"
                    )
                attributed = client_order_id

            vol = Decimal(str(getattr(d, "volume", 0)))
            price = Decimal(str(getattr(d, "price", 0)))
            if not vol.is_finite() or vol <= 0:
                raise RuntimeError(f"MT5 deal {ticket_int} has invalid volume {vol!r}")
            if not price.is_finite() or price <= 0:
                raise RuntimeError(f"MT5 deal {ticket_int} has invalid price {price!r}")

            deal_type = getattr(d, "type", None)
            if deal_type == 0:
                side = Side.BUY
            elif deal_type == 1:
                side = Side.SELL
            else:
                raise RuntimeError(f"MT5 deal {ticket_int} has unsupported deal type {deal_type!r}")

            raw_time = getattr(d, "time", None)
            if raw_time is None:
                raise RuntimeError(f"MT5 deal {ticket_int} has no timestamp")
            deal_time = datetime.fromtimestamp(float(raw_time), tz=UTC)

            fee = (
                Decimal(str(getattr(d, "commission", 0) or 0))
                + Decimal(str(getattr(d, "swap", 0) or 0))
                + Decimal(str(getattr(d, "fee", 0) or 0))
            )
            if not fee.is_finite():
                raise RuntimeError(f"MT5 deal {ticket_int} has non-finite charges")

            fills.append(
                {
                    "fill_id": f"mt5-deal-{ticket_int}",
                    "client_order_id": attributed,
                    "symbol": sym,
                    "volume": vol,
                    "price": price,
                    "fee": fee,
                    "side": side,
                    "time": deal_time,
                    "deal": d,
                }
            )
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
