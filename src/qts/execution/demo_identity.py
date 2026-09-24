"""Broker/account identity verification for DEMO execution.

Two of the required pre-trade safeguards are identity questions:

1. **Is the connected account actually a DEMO account?**
2. **Is this the expected broker/server?**

Both are answered from the MT5 terminal itself (``account_info`` /
``terminal_info``), never from configuration. The rules are deliberately
fail-closed:

* ``account_info()`` returning ``None`` (terminal not initialized in this
  process) is an error, not an empty identity;
* an absent ``trade_mode`` is **UNKNOWN**, not DEMO — ``is_demo`` stays
  ``None`` and every consumer must refuse;
* ``ACCOUNT_TRADE_MODE_DEMO`` (0) is accepted; ``CONTEST`` (1) and ``REAL`` (2)
  are refused; anything else is UNKNOWN;
* identity is pinned: the first successful probe can be written to a pin file
  (``PENDING_REVIEW``), and the DEMO order path requires a pin the owner has
  reviewed (``CONFIRMED``) that matches the live terminal exactly.

The pin is the anti-account-switch control: even if the terminal is later
pointed at a different broker/server/login, the fingerprint no longer matches
and the order path refuses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PIN_SCHEMA = "qts.demo_broker_identity_pin.v1"
ENV_PIN_PATH = "QTS_DEMO_IDENTITY_PIN"
DEFAULT_PIN_PATH = Path("data/evidence/demo_broker_identity_pin.json")

# MetaTrader5 ACCOUNT_TRADE_MODE_* values (documented by MetaQuotes).
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
    """Account/broker facts read from the terminal — no configuration."""

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


def probe_broker_identity(mt5_module: Any | None = None, *, initialize: bool = True) -> BrokerIdentity:
    """Read the connected account identity from the MT5 terminal.

    ``mt5_module`` may be injected (tests) or is imported. When the module
    exposes ``initialize`` it is called first: the MetaTrader5 package returns
    ``None`` from ``account_info()`` until ``initialize()`` succeeds *in this
    process* — importing it is not enough (documented root cause in
    ``qts.lifecycle.demo_gate``).
    """
    if mt5_module is None:
        try:
            import MetaTrader5 as mt5_module  # type: ignore[no-redef]
        except ImportError as exc:
            raise BrokerIdentityError(
                "MetaTrader5 package not installed — DEMO identity cannot be verified (fail closed)"
            ) from exc

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
            except Exception:  # pragma: no cover - diagnostic only
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
        except Exception:  # pragma: no cover - diagnostic only
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


class _suppress:
    """``contextlib.suppress(Exception)`` without the import cycle noise."""

    def __enter__(self) -> _suppress:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return True


def identity_fingerprint(identity: BrokerIdentity) -> str:
    """Stable fingerprint of the account identity used for pinning."""
    body = {
        "login": identity.login,
        "server": (identity.server or "").upper(),
        "company": (identity.company or "").upper(),
        "trade_mode": identity.trade_mode,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def pin_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = _env(ENV_PIN_PATH)
    return Path(env) if env else DEFAULT_PIN_PATH


def _env(name: str) -> str | None:
    import os

    value = os.getenv(name)
    return value or None


def write_pin(
    identity: BrokerIdentity,
    *,
    actor: str = "cli",
    path: str | Path | None = None,
    status: str = "PENDING_REVIEW",
    symbol: dict[str, Any] | None = None,
) -> Path:
    """Record the observed identity as a pin (default: pending owner review).

    The pin is written ``PENDING_REVIEW`` on purpose: arming the DEMO order
    path requires the owner to confirm it (``qts demo identity --confirm``),
    so a first-run probe can never silently authorize the account it happened
    to find.
    """
    target = pin_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": PIN_SCHEMA,
        "pinned_at": datetime.now(UTC).isoformat(),
        "pinned_by": actor,
        "status": status,
        "identity": identity.as_dict(),
        "fingerprint": identity_fingerprint(identity),
    }
    if symbol:
        # Symbol provenance: which canonical/venue pair was verified on THIS
        # account. A registered policy is bound to the canonical symbol, so the
        # pin — the one artefact the owner reviews and confirms — is the right
        # place to record what the venue actually calls it.
        doc["symbol"] = {
            "canonical": str(symbol.get("canonical") or ""),
            "broker": str(symbol.get("broker") or symbol.get("broker_symbol") or ""),
            "digits": symbol.get("digits"),
            "contract_size": (str(symbol.get("contract_size")) if symbol.get("contract_size") is not None else None),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    target.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return target


def load_pin(path: str | Path | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    target = pin_path(path)
    if not target.exists():
        return None, [f"no broker identity pin at {target} — run `qts demo connectivity --pin` then confirm it"]
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"broker identity pin unreadable — fail closed ({type(exc).__name__}: {exc})"]
    if not isinstance(doc, dict) or doc.get("schema") != PIN_SCHEMA:
        return None, [f"unsupported broker identity pin schema {doc.get('schema')!r} — fail closed"]
    return doc, []


def confirm_pin(
    path: str | Path | None = None,
    *,
    actor: str = "owner",
    expected_fingerprint: str | None = None,
) -> tuple[bool, str]:
    """Owner confirmation of a previously recorded pin (review step)."""
    doc, reasons = load_pin(path)
    if doc is None:
        return False, "; ".join(reasons)
    target = pin_path(path)
    if expected_fingerprint and doc.get("fingerprint") != expected_fingerprint:
        return False, (
            f"pin fingerprint {str(doc.get('fingerprint'))[:12]}… does not match the reviewed fingerprint "
            f"{expected_fingerprint[:12]}… — confirmation refused"
        )
    doc["status"] = "CONFIRMED"
    doc["confirmed_at"] = datetime.now(UTC).isoformat()
    doc["confirmed_by"] = actor
    target.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return True, f"broker identity pin confirmed for login={doc.get('identity', {}).get('login')}"


def verify_pin(
    identity: BrokerIdentity,
    pin: dict[str, Any] | None,
    *,
    require_confirmed: bool = True,
) -> tuple[bool, list[str]]:
    """Compare a live identity against the pinned identity (fail closed)."""
    if pin is None:
        return False, ["broker identity is not pinned — DEMO order path refused"]

    status = str(pin.get("status") or "")
    if require_confirmed and status != "CONFIRMED":
        return False, [f"broker identity pin status is {status or 'MISSING'} — owner confirmation required"]

    pinned_identity = pin.get("identity") or {}
    problems: list[str] = []

    def _cmp(field: str, live: Any, pinned: Any, *, upper: bool = False) -> None:
        if pinned is None and live is None:
            return
        a = str(live or "").upper() if upper else live
        b = str(pinned or "").upper() if upper else pinned
        if a != b:
            problems.append(f"{field} mismatch — pinned {pinned!r} vs connected {live!r}")

    _cmp("login", identity.login, pinned_identity.get("login"))
    _cmp("server", identity.server, pinned_identity.get("server"), upper=True)
    _cmp("company", identity.company, pinned_identity.get("company"), upper=True)
    _cmp("trade_mode", identity.trade_mode, pinned_identity.get("trade_mode"))

    expected_fp = pin.get("fingerprint")
    actual_fp = identity_fingerprint(identity)
    if expected_fp and expected_fp != actual_fp:
        problems.append(
            f"identity fingerprint mismatch — pinned {str(expected_fp)[:12]}… vs connected {actual_fp[:12]}…"
        )

    if problems:
        return False, problems
    return True, [f"identity verified: login={identity.login} server={identity.server} type={identity.account_type}"]


def assert_demo_account(identity: BrokerIdentity) -> tuple[bool, list[str]]:
    """Check #1 — the connected account must be provably DEMO."""
    if identity.is_demo is None:
        return False, [
            "account trade_mode unavailable from terminal — DEMO status UNPROVABLE, fail closed "
            "(MT5 must report ACCOUNT_TRADE_MODE_DEMO)"
        ]
    if not identity.is_demo:
        return False, [
            f"connected account is {identity.account_type} (trade_mode={identity.trade_mode}) — "
            "DEMO execution refuses any non-DEMO account"
        ]
    if identity.trade_allowed is False:
        return False, ["terminal reports trade_allowed=false — account cannot trade"]
    if identity.trade_expert is False:
        return False, ["terminal reports trade_expert=false — automated trading disabled on this account"]
    return True, [f"account is DEMO (login={identity.login}, server={identity.server}, company={identity.company})"]
