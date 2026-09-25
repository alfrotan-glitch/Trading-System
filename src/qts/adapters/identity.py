"""Broker terminal identity probing and fingerprinting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

# MetaTrader5 ACCOUNT_TRADE_MODE_* values
TRADE_MODE_DEMO = 0
TRADE_MODE_CONTEST = 1
TRADE_MODE_REAL = 2

_TRADE_MODE_NAMES = {
    TRADE_MODE_DEMO: "DEMO",
    TRADE_MODE_CONTEST: "CONTEST",
    TRADE_MODE_REAL: "REAL",
}


class BrokerIdentityError(RuntimeError):
    """The terminal could not produce a trustworthy account identity."""


@dataclass(frozen=True)
class BrokerIdentity:
    """Account/broker facts read directly from the MT5 terminal."""

    login: int | None
    server: str | None
    company: str | None
    account_name: str | None
    trade_mode: int | None
    trade_allowed: bool | None
    trade_expert: bool | None
    currency: str | None
    leverage: int | None
    balance: float | None
    equity: float | None
    terminal_connected: bool | None
    terminal_company: str | None
    terminal_build: int | None
    receipt_at: str

    @property
    def trade_mode_name(self) -> str:
        return _TRADE_MODE_NAMES.get(self.trade_mode, "UNKNOWN") if self.trade_mode is not None else "UNKNOWN"

    @property
    def account_type(self) -> str:
        """DEMO | CONTEST | REAL | UNKNOWN."""
        return self.trade_mode_name

    @property
    def is_demo(self) -> bool | None:
        """``True`` only for trade_mode DEMO; ``None`` = UNKNOWN (fail closed)."""
        if self.trade_mode is None:
            return None
        return self.trade_mode == TRADE_MODE_DEMO

    @property
    def is_real(self) -> bool | None:
        if self.trade_mode is None:
            return None
        return self.trade_mode == TRADE_MODE_REAL

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["account_type"] = self.account_type
        d["is_demo"] = self.is_demo
        return d


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(int(value)) if isinstance(value, (int, float)) else None


class _suppress:
    def __enter__(self) -> _suppress:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return True


def probe_broker_identity(mt5_module: Any | None = None, *, initialize: bool = True) -> BrokerIdentity:
    """Read the connected account identity directly from the MT5 terminal."""
    if mt5_module is None:
        try:
            import MetaTrader5 as mt5_module  # type: ignore[no-redef]
        except ImportError as exc:
            raise BrokerIdentityError(
                "MetaTrader5 package not installed — DEMO identity cannot be verified (fail closed)"
            ) from exc
    if mt5_module is None:
        raise BrokerIdentityError("MetaTrader5 module is unavailable")

    if initialize and hasattr(mt5_module, "initialize"):
        import os

        path = os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH")
        kwargs = {"path": path} if path else {}
        try:
            initialized = bool(mt5_module.initialize(**kwargs))
        except Exception as exc:
            raise BrokerIdentityError(f"MT5 initialize failed: {type(exc).__name__}: {exc}") from exc
        if not initialized:
            try:
                last_error = mt5_module.last_error()
            except Exception:
                last_error = "unavailable"
            raise BrokerIdentityError(f"MT5 initialize failed — terminal link not established (last_error={last_error})")

    info = None
    try:
        info = mt5_module.account_info()
    except Exception as exc:
        raise BrokerIdentityError(f"MT5 account_info failed: {type(exc).__name__}: {exc}") from exc
    if info is None:
        try:
            last_error = mt5_module.last_error()
        except Exception:
            last_error = "unavailable"
        raise BrokerIdentityError(f"MT5 account_info unavailable — identity not provable (last_error={last_error})")

    terminal = None
    with _suppress():
        terminal = mt5_module.terminal_info()

    return BrokerIdentity(
        login=_as_int(getattr(info, "login", None)),
        server=_as_str(getattr(info, "server", None)),
        company=_as_str(getattr(info, "company", None)),
        account_name=_as_str(getattr(info, "name", None)),
        trade_mode=_as_int(getattr(info, "trade_mode", None)),
        trade_allowed=_as_bool(getattr(info, "trade_allowed", None)),
        trade_expert=_as_bool(getattr(info, "trade_expert", None)),
        currency=_as_str(getattr(info, "currency", None)),
        leverage=_as_int(getattr(info, "leverage", None)),
        balance=_as_float(getattr(info, "balance", None)),
        equity=_as_float(getattr(info, "equity", None)),
        terminal_connected=_as_bool(getattr(terminal, "connected", None)) if terminal is not None else None,
        terminal_company=_as_str(getattr(terminal, "company", None)) if terminal is not None else None,
        terminal_build=_as_int(getattr(terminal, "build", None)) if terminal is not None else None,
        receipt_at=datetime.now(UTC).isoformat(),
    )


def identity_fingerprint(identity: BrokerIdentity) -> str:
    """Stable SHA-256 fingerprint of the account identity used for pinning."""
    body = {
        "login": identity.login,
        "server": (identity.server or "").upper(),
        "company": (identity.company or "").upper(),
        "trade_mode": identity.trade_mode,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
