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

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.adapters.identity import (
    _TRADE_MODE_NAMES,
    TRADE_MODE_CONTEST,
    TRADE_MODE_DEMO,
    TRADE_MODE_REAL,
    BrokerIdentity,
    BrokerIdentityError,
    identity_fingerprint,
    probe_broker_identity,
)

__all__ = [
    "TRADE_MODE_CONTEST",
    "TRADE_MODE_DEMO",
    "TRADE_MODE_REAL",
    "_TRADE_MODE_NAMES",
    "BrokerIdentity",
    "BrokerIdentityError",
    "identity_fingerprint",
    "probe_broker_identity",
    "PIN_SCHEMA",
    "ENV_PIN_PATH",
    "DEFAULT_PIN_PATH",
    "pin_path",
    "write_pin",
    "load_pin",
    "confirm_pin",
    "verify_pin",
]

PIN_SCHEMA = "qts.demo_broker_identity_pin.v1"
ENV_PIN_PATH = "QTS_DEMO_IDENTITY_PIN"
DEFAULT_PIN_PATH = Path("data/evidence/demo_broker_identity_pin.json")


def pin_path(path: str | Path | None = None) -> Path:
    """The identity pin location — anchored, never cwd-relative.

    The pin is confirmed evidence about ONE broker account. If its path
    depended on the working directory, a CLI invocation from another directory
    would read (or write) a *different* pin than the backend, and the two could
    disagree about which account is confirmed.
    """
    from qts.config.paths import artifact_path

    return artifact_path("identity_pin", path)


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
