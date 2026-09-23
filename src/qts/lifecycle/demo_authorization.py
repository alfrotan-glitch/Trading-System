"""Explicit, revocable OWNER authorization for DEMO execution.

Why this module exists
----------------------
QTS shipped with ``DEMO_EXECUTION = DISABLED BY POLICY``: a product policy
constant (:data:`qts.lifecycle.demo_authority.DEMO_EXECUTION_DISABLED`), not a
missing capability. Every other part of the broker path (MT5 adapter
``order_send``, execution engine, risk authority, reconciliation, kill switch)
was already implemented — the policy switch was the *only* thing standing
between DEMO_FORWARD (observation) and DEMO_EXECUTION (orders).

This module replaces "a boolean in source" with a **recorded, hashed,
revocable, scope-limited authorization artifact**:

* no artifact (or an invalid/tampered/expired/revoked one) → the resolved
  policy is still ``DISABLED BY POLICY`` — the shipped default is unchanged on
  a clean clone;
* a valid artifact → ``ENABLED_AUTHORIZED``, and even then only for the scope
  written into it (DEMO account only, ``LIVE = LOCKED``, zero real capital
  exposure, no funds transfer, no broker switching).

The artifact is deliberately **not** an override switch:

* it cannot widen the canonical DEMO risk limits (``risk_ceiling`` may only
  tighten — loosening invalidates the artifact);
* it cannot enable LIVE (an artifact mentioning LIVE, or one with
  ``live_locked=false``, is rejected outright);
* it cannot be created by a readiness pass, a request payload, an environment
  variable, or a direct authority call. Only committing an artifact to the
  repository (or to ``QTS_DEMO_AUTHORIZATION``) changes policy, and every
  resolution is recorded with reasons.

This keeps the property the old constant protected — DEMO execution is never
enabled implicitly — while making the authorization explicit, auditable and
reversible, which is exactly what a controlled DEMO order path requires.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qts.domain.modes import ExecutionMode

AUTHORIZATION_SCHEMA = "qts.demo_execution_authorization.v1"
REVOCATION_SCHEMA = "qts.demo_execution_revocation.v1"

#: Environment override for the artifact location (selection only — the file
#: itself must still validate; pointing at another path is not a bypass).
ENV_AUTHORIZATION_PATH = "QTS_DEMO_AUTHORIZATION"

DEFAULT_AUTHORIZATION_PATH = Path("data/evidence/demo_execution_authorization_2026-09-23.json")
REVOCATION_SUFFIX = ".revocation.json"

#: Shipped default policy strings. ``DISABLED BY POLICY`` is what a checkout
#: with no recorded authorization resolves to; it is never silently replaced.
DEMO_EXECUTION_POLICY = "DISABLED BY POLICY"
POLICY_ENABLED_AUTHORIZED = "ENABLED_AUTHORIZED"

#: Fields of the canonical risk authority that an artifact may TIGHTEN.
_RISK_CEILING_FIELDS: frozenset[str] = frozenset(
    {
        "max_quantity",  # lots per order
        "max_exposure_lots",
        "max_open_orders",
        "max_orders_per_minute",
        "daily_loss_limit",
        "max_drawdown",
        "max_drawdown_pct",
        "max_spread_bps",
        "max_slippage_bps",
    }
)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON used for every fingerprint in this module."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def document_fingerprint(doc: dict[str, Any]) -> str:
    """SHA-256 of the artifact with its own ``integrity`` block removed."""
    body = {k: v for k, v in doc.items() if k != "integrity"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


class AuthorizationScope(BaseModel):
    """The boundaries written into the artifact — none of them negotiable."""

    model_config = ConfigDict(extra="ignore")

    account_type: str
    modes_allowed: list[str] = Field(default_factory=list)
    symbols_allowed: list[str] = Field(default_factory=list)
    live_locked: bool = False
    real_capital_exposure_usd: float | int | str = 0
    funds_transfer_permitted: bool = False
    broker_switch_permitted: bool = False
    autonomous_order_management: bool = False


class DemoAuthorization(BaseModel):
    """Parsed authorization artifact (structure only — see :func:`_validate`)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_name: str = Field(alias="schema")
    authorization_id: str
    authorized_at: str
    authorized_by: str
    scope: AuthorizationScope
    expires_at: str | None = None
    statement: str = ""
    risk_ceiling: dict[str, Any] = Field(default_factory=dict)
    research_integrity: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class LoadedAuthorization:
    """An authorization artifact that passed every validation rule."""

    document: DemoAuthorization
    raw: dict[str, Any]
    path: Path
    fingerprint: str

    @property
    def authorization_id(self) -> str:
        return self.document.authorization_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.document.authorization_id,
            "authorized_at": self.document.authorized_at,
            "authorized_by": self.document.authorized_by,
            "expires_at": self.document.expires_at,
            "schema": self.document.schema_name,
            "path": str(self.path),
            "fingerprint": self.fingerprint,
            "scope": self.document.scope.model_dump(),
            "risk_ceiling": dict(self.document.risk_ceiling),
            "research_integrity": dict(self.document.research_integrity),
            "statement": self.document.statement,
        }


@dataclass(frozen=True)
class DemoExecutionPolicy:
    """The resolved DEMO execution policy for this process.

    ``state`` is either :data:`POLICY_ENABLED_AUTHORIZED` or
    :data:`DEMO_EXECUTION_POLICY` (``DISABLED BY POLICY``). ``reasons`` is
    never empty when ``enabled`` is False — a refusal must always be legible.
    """

    state: str
    enabled: bool
    reasons: tuple[str, ...] = ()
    authorization: LoadedAuthorization | None = None

    @property
    def authorization_id(self) -> str | None:
        return self.authorization.authorization_id if self.authorization else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy": self.state,
            "enabled": self.enabled,
            "reasons": list(self.reasons),
            "authorization_id": self.authorization_id,
            "authorization": self.authorization.as_dict() if self.authorization else None,
            "live_locked": True,  # invariant — never derived from an artifact
            "real_capital_exposure_usd": 0,
        }


def _authorization_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.getenv(ENV_AUTHORIZATION_PATH)
    return Path(env) if env else DEFAULT_AUTHORIZATION_PATH


def _revocation_path(auth_path: Path) -> Path:
    return auth_path.with_name(auth_path.name + REVOCATION_SUFFIX)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def is_revoked(auth_path: str | Path | None = None) -> tuple[bool, str | None]:
    """Whether a revocation record exists for this authorization."""
    path = _revocation_path(_authorization_path(auth_path))
    if not path.exists():
        return False, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        reason = str(doc.get("reason") or "revoked")
        actor = doc.get("actor")
        at = doc.get("revoked_at")
        detail = f"revoked at {at} by {actor}: {reason}" if actor else f"revoked at {at}: {reason}"
    except Exception as exc:  # an unreadable revocation still blocks (fail closed)
        return True, f"revocation record unreadable — fail closed ({type(exc).__name__}: {exc})"
    return True, detail


def revoke_authorization(
    auth_path: str | Path | None = None,
    *,
    reason: str,
    actor: str = "cli",
    now: datetime | None = None,
) -> Path:
    """Write a revocation record — the reversible half of the authorization.

    Revocation is additive: the artifact is never edited or deleted, so the
    audit trail keeps both the authorization and its withdrawal.
    """
    path = _revocation_path(_authorization_path(auth_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": REVOCATION_SCHEMA,
        "revoked_at": (now or datetime.now(UTC)).isoformat(),
        "actor": actor,
        "reason": reason,
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _validate_risk_ceiling(ceiling: dict[str, Any]) -> list[str]:
    """An artifact may only TIGHTEN the canonical DEMO risk limits."""
    if not ceiling:
        return []
    try:
        from qts.risk.authority import resolve_risk_limits

        resolved = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    except Exception as exc:
        return [f"risk ceiling unverifiable — canonical risk authority unavailable ({exc})"]

    problems: list[str] = []
    for key, value in ceiling.items():
        if key not in _RISK_CEILING_FIELDS:
            problems.append(f"risk_ceiling contains unknown key {key!r} — fail closed")
            continue
        base = getattr(resolved.limits, key)
        try:
            if float(value) > float(base):
                problems.append(f"risk_ceiling {key}={value} exceeds canonical DEMO limit {base} — loosening refused")
        except (TypeError, ValueError):
            problems.append(f"risk_ceiling {key}={value!r} is not comparable to canonical limit {base} — fail closed")
    return problems


def _validate(doc: dict[str, Any], path: Path, now: datetime) -> tuple[LoadedAuthorization | None, list[str]]:
    """Every rule here fails CLOSED: any problem ⇒ no authorization."""
    reasons: list[str] = []

    if not isinstance(doc, dict):
        return None, [f"authorization artifact is not a JSON object ({path})"]

    schema = doc.get("schema")
    if schema != AUTHORIZATION_SCHEMA:
        return None, [f"unsupported authorization schema {schema!r} — expected {AUTHORIZATION_SCHEMA}"]

    revoked, detail = is_revoked(path)
    if revoked:
        return None, [f"authorization revoked — {detail}"]

    # Integrity first: a document whose hash does not match its own contents
    # has been edited after the fact and cannot be trusted for ANY purpose.
    integrity = doc.get("integrity") or {}
    declared = str(integrity.get("content_sha256") or "")
    actual = document_fingerprint(doc)
    if not declared:
        reasons.append("authorization has no integrity.content_sha256 — fail closed")
    elif declared.lower() != actual:
        reasons.append(
            f"authorization content hash mismatch (declared {declared[:12]}…, computed {actual[:12]}…) — "
            "artifact was modified after signing; treated as not authorized"
        )
    if reasons:
        return None, reasons

    try:
        parsed = DemoAuthorization.model_validate(doc)
    except Exception as exc:
        return None, [f"authorization artifact is malformed — fail closed ({type(exc).__name__}: {exc})"]

    scope = parsed.scope

    # ---------------- absolute boundaries (never negotiable) ----------------
    if str(scope.account_type).lower() != "demo":
        reasons.append(f"scope.account_type={scope.account_type!r} — DEMO authorization only")
    if not scope.live_locked:
        reasons.append("scope.live_locked is not true — LIVE must remain locked")
    if "LIVE" in {str(m).upper() for m in scope.modes_allowed}:
        reasons.append("scope.modes_allowed contains LIVE — refused (LIVE = LOCKED)")
    if "DEMO_EXECUTION" not in {str(m).upper() for m in scope.modes_allowed}:
        reasons.append("scope.modes_allowed does not include DEMO_EXECUTION — no order path authorized")
    try:
        if float(scope.real_capital_exposure_usd) != 0.0:
            reasons.append(
                f"scope.real_capital_exposure_usd={scope.real_capital_exposure_usd} — must be 0 for DEMO research"
            )
    except (TypeError, ValueError):
        reasons.append("scope.real_capital_exposure_usd is not numeric — fail closed")
    if scope.funds_transfer_permitted:
        reasons.append("scope.funds_transfer_permitted is true — no funds transfer may ever be authorized")
    if scope.broker_switch_permitted:
        reasons.append("scope.broker_switch_permitted is true — only the pinned DEMO account may be used")

    # ---------------- expiry ----------------
    expires = _parse_iso(parsed.expires_at)
    if expires is not None and expires <= now:
        reasons.append(f"authorization expired at {parsed.expires_at}")

    # ---------------- research-integrity covenants ----------------
    ri = dict(parsed.research_integrity or {})
    if ri and ri.get("no_forward_optimization") is not True:
        reasons.append("research_integrity.no_forward_optimization must be true — no fitting to forward DEMO results")
    if ri and ri.get("strategy_registry_required") is not True:
        reasons.append("research_integrity.strategy_registry_required must be true — unregistered strategies may not trade")

    # ---------------- risk ceiling may only tighten ----------------
    reasons.extend(_validate_risk_ceiling(dict(parsed.risk_ceiling or {})))

    if reasons:
        return None, reasons

    return LoadedAuthorization(document=parsed, raw=doc, path=Path(path), fingerprint=actual), []


def load_authorization(
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> tuple[LoadedAuthorization | None, list[str]]:
    """Load and validate the owner authorization artifact (fail closed).

    Returns ``(None, reasons)`` when no artifact exists — that is the normal,
    shipped state and **not** an error.
    """
    auth_path = _authorization_path(path)
    moment = now or datetime.now(UTC)
    if not auth_path.exists():
        return None, [
            f"no owner authorization artifact at {auth_path} — DEMO_EXECUTION remains {DEMO_EXECUTION_POLICY}"
        ]
    try:
        doc = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [
            f"owner authorization artifact unreadable — fail closed ({type(exc).__name__}: {exc})"
        ]
    return _validate(doc, auth_path, moment)


_UNSET = object()


def resolve_demo_execution_policy(
    authorization: LoadedAuthorization | None = _UNSET,  # type: ignore[assignment]
    *,
    mode: str | None = None,
    path: str | Path | None = None,
    load: bool = True,
    now: datetime | None = None,
) -> DemoExecutionPolicy:
    """Resolve the DEMO execution policy for this process.

    ``authorization`` may be:

    * omitted → load from the artifact path (the normal runtime case);
    * a :class:`LoadedAuthorization` (caller already validated it);
    * ``None`` explicitly → no authorization (used by tests and by callers
      that must prove the un-authorized behaviour).

    ``mode`` is the canonical execution mode of the *requesting process*. LIVE
    is refused even with a valid artifact: ``LIVE = LOCKED`` is an invariant of
    the system, not a clause in the artifact.
    """
    moment = now or datetime.now(UTC)
    reasons: list[str] = []

    if authorization is _UNSET:
        if not load:
            return DemoExecutionPolicy(
                state=DEMO_EXECUTION_POLICY,
                enabled=False,
                reasons=(f"authorization loading disabled — DEMO_EXECUTION remains {DEMO_EXECUTION_POLICY}",),
            )
        authorization, reasons = load_authorization(path, now=moment)
    elif authorization is not None:
        # Re-check time-dependent rules (expiry, revocation) at use time.
        authorization, fresh_reasons = _validate(authorization.raw, authorization.path, moment)
        reasons.extend(fresh_reasons)

    if mode is not None:
        try:
            resolved_mode = ExecutionMode(str(mode).upper())
        except ValueError:
            return DemoExecutionPolicy(
                state=DEMO_EXECUTION_POLICY,
                enabled=False,
                reasons=(f"mode {mode!r} is not a canonical execution mode — fail closed", *reasons),
            )
        if resolved_mode is ExecutionMode.LIVE:
            return DemoExecutionPolicy(
                state=DEMO_EXECUTION_POLICY,
                enabled=False,
                reasons=("LIVE = LOCKED — no authorization artifact can permit real-capital trading", *reasons),
            )
        if not resolved_mode.can_submit_broker_orders:
            # DEMO_FORWARD/PAPER/SHADOW/DEVELOPMENT: observation or simulation,
            # never broker orders. Refused here rather than only downstream, so
            # no caller can read ``enabled=True`` in a mode that cannot trade.
            return DemoExecutionPolicy(
                state=DEMO_EXECUTION_POLICY,
                enabled=False,
                reasons=(
                    f"mode {resolved_mode.value} cannot submit broker orders — DEMO_EXECUTION requires "
                    "QTS_MODE=demo_execution",
                    *reasons,
                ),
                authorization=authorization,
            )

    if authorization is None:
        return DemoExecutionPolicy(
            state=DEMO_EXECUTION_POLICY,
            enabled=False,
            reasons=tuple(reasons) or (f"no valid owner authorization — {DEMO_EXECUTION_POLICY}",),
        )

    return DemoExecutionPolicy(
        state=POLICY_ENABLED_AUTHORIZED,
        enabled=True,
        reasons=tuple(reasons),
        authorization=authorization,
    )


@dataclass(frozen=True)
class AuthorizationStatus:
    """Everything an operator surface needs to show, with no inference."""

    path: Path
    exists: bool
    revoked: bool
    revocation_detail: str | None
    valid: bool
    reasons: list[str] = field(default_factory=list)
    authorization: LoadedAuthorization | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "revoked": self.revoked,
            "revocation_detail": self.revocation_detail,
            "valid": self.valid,
            "reasons": list(self.reasons),
            "authorization": self.authorization.as_dict() if self.authorization else None,
        }


def authorization_status(path: str | Path | None = None) -> AuthorizationStatus:
    auth_path = _authorization_path(path)
    revoked, detail = is_revoked(auth_path)
    auth, reasons = load_authorization(auth_path)
    return AuthorizationStatus(
        path=auth_path,
        exists=auth_path.exists(),
        revoked=revoked,
        revocation_detail=detail,
        valid=auth is not None,
        reasons=list(reasons),
        authorization=auth,
    )
