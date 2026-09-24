"""Forward-validation strategy registry for DEMO execution.

DEMO execution being *authorized* is not the same as a strategy being
*eligible*. This registry is the boundary between the two:

* the owner authorization (``demo_authorization``) answers **may QTS send DEMO
  orders at all?**;
* the registry answers **which registered research/execution policy may
  generate those orders, with which frozen parameters?**.

The registry exists to keep the research covenant executable:

* **no invented strategies** — an entry must name a preregistered hypothesis
  (``hypothesis_id``) and its preregistration artifact; an empty registry means
  the honest state ``NO_TRADE`` even while ``DEMO_EXECUTION = ENABLED``;
* **no forward fitting** — parameters are hashed (``params_hash``). Any change
  breaks the hash and the entry is refused (``PARAMETER_DRIFT``). Changing a
  registered policy therefore requires a *new* registry version plus a new
  preregistration, not an edit after a losing trade;
* **no optimization against forward results** — ``optimization_allowed`` is
  required to be false, and the autopilot refuses providers that expose an
  ``optimize``/``fit`` hook.

Every load is fail-closed: malformed, tampered, or unregistered input resolves
to "no eligible strategy", never to a permissive default.

Schema v2 adds the mandatory research/execution policy
(:mod:`qts.lifecycle.demo_policy`) — the full specification of the forward
experiment: signal/exit/stop logic, sizing, exposure, loss, drawdown, order
frequency, symbols, hours, cost limits, data requirements, kill conditions,
reconciliation requirements, and the code/config/data hashes that let the
runtime prove the experiment was not respecified mid-flight. A v2 entry
without a complete, valid policy is refused, so "registered" always means
"fully specified before the first order".
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA = "qts.demo_forward_registry.v1"
#: v2 entries carry a complete, validated research/execution policy.
REGISTRY_SCHEMA_V2 = "qts.demo_forward_registry.v2"
REGISTRY_SCHEMAS = (REGISTRY_SCHEMA, REGISTRY_SCHEMA_V2)
ENV_REGISTRY_PATH = "QTS_DEMO_REGISTRY"
DEFAULT_REGISTRY_PATH = Path("data/evidence/demo_forward_validation_registry_2026-09-23.json")

#: Statuses that allow DEMO order generation. ``ELIGIBLE`` means a strategy
#: with a recorded validation artifact; ``ELIGIBLE_DIAGNOSTIC`` means an
#: explicitly registered, non-validated forward *measurement* policy. Both may
#: trade; they must never be confused with one another, because only the first
#: implies an edge claim.
ELIGIBLE_STATUSES = frozenset({"ELIGIBLE"})
DIAGNOSTIC_STATUSES = frozenset({"ELIGIBLE_DIAGNOSTIC"})
#: Statuses that explicitly mean "do not trade".
BLOCKED_STATUSES = frozenset({"NO_TRADE", "HALTED", "REJECTED", "SUSPENDED", "RESEARCH"})


def params_fingerprint(params: dict[str, Any]) -> str:
    """Deterministic hash of a registered parameter set (freeze control)."""
    body = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _registry_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.getenv(ENV_REGISTRY_PATH)
    return Path(env) if env else DEFAULT_REGISTRY_PATH


@dataclass(frozen=True)
class StrategyRegistration:
    """One registered forward-validation policy."""

    strategy_id: str
    status: str
    hypothesis_id: str | None = None
    preregistration_artifact: str | None = None
    signal_provider: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    params_hash: str = ""
    size_policy: dict[str, Any] = field(default_factory=dict)
    stop_policy: dict[str, Any] = field(default_factory=dict)
    exit_policy: dict[str, Any] = field(default_factory=dict)
    allowed_symbols: list[str] = field(default_factory=list)
    max_orders_per_day: int = 0
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    #: The complete research/execution policy (v2 entries; None for v1).
    policy: Any | None = None  # qts.lifecycle.demo_policy.ResearchPolicy

    @property
    def eligible(self) -> bool:
        if self.status in ELIGIBLE_STATUSES:
            return True
        # A diagnostic policy may trade, but ONLY as a non-validated DEMO
        # forward research policy: no other status is allowed to trade without
        # a recorded validation artifact.
        if self.status in DIAGNOSTIC_STATUSES:
            from qts.lifecycle.demo_policy import POLICY_CLASS

            return (
                self.policy is not None
                and self.policy.policy_class == POLICY_CLASS
                and self.policy.validated_edge is False
            )
        return False

    @property
    def policy_class(self) -> str | None:
        return self.policy.policy_class if self.policy is not None else None

    @property
    def validated_edge(self) -> bool:
        return bool(self.policy.validated_edge) if self.policy is not None else False

    @property
    def policy_id(self) -> str | None:
        return self.policy.policy_id if self.policy is not None else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "status": self.status,
            "hypothesis_id": self.hypothesis_id,
            "preregistration_artifact": self.preregistration_artifact,
            "signal_provider": self.signal_provider,
            "params": dict(self.params),
            "params_hash": self.params_hash,
            "size_policy": dict(self.size_policy),
            "stop_policy": dict(self.stop_policy),
            "exit_policy": dict(self.exit_policy),
            "allowed_symbols": list(self.allowed_symbols),
            "max_orders_per_day": self.max_orders_per_day,
            "notes": self.notes,
            "policy_class": self.policy_class,
            "policy_id": self.policy_id,
            "validated_edge": self.validated_edge,
        }


@dataclass(frozen=True)
class RegistrySnapshot:
    """Parsed registry plus the reasons it can/cannot authorize trading."""

    path: Path
    valid: bool
    entries: tuple[StrategyRegistration, ...] = ()
    research_integrity: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def eligible_entries(self) -> tuple[StrategyRegistration, ...]:
        return tuple(e for e in self.entries if e.eligible)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "valid": self.valid,
            "entry_count": len(self.entries),
            "eligible": [e.as_dict() for e in self.eligible_entries],
            "statuses": {e.strategy_id: e.status for e in self.entries},
            "research_integrity": dict(self.research_integrity),
            "reasons": list(self.reasons),
        }


def _entry_from(doc: dict[str, Any]) -> tuple[StrategyRegistration | None, list[str]]:
    problems: list[str] = []
    strategy_id = str(doc.get("strategy_id") or "").strip()
    if not strategy_id:
        return None, ["registry entry without strategy_id — refused"]
    params = dict(doc.get("params") or {})
    declared_hash = str(doc.get("params_hash") or "")
    actual_hash = params_fingerprint(params)
    if declared_hash and declared_hash != actual_hash:
        problems.append(
            f"entry {strategy_id}: params_hash mismatch (declared {declared_hash[:12]}…, computed "
            f"{actual_hash[:12]}…) — parameters were edited after registration (PARAMETER_DRIFT)"
        )
    try:
        max_orders = int(doc.get("max_orders_per_day") or 0)
    except (TypeError, ValueError):
        problems.append(f"entry {strategy_id}: max_orders_per_day is not an integer — fail closed")
        max_orders = 0
    status = str(doc.get("status") or "NO_TRADE").upper()

    # ---- research/execution policy (v2: mandatory) -------------------------
    policy = None
    policy_doc = doc.get("policy")
    if policy_doc is not None:
        from qts.lifecycle.demo_policy import validate_policy

        policy, policy_problems = validate_policy(policy_doc, params)
        problems.extend(f"policy {strategy_id}: {r}" for r in policy_problems)
    elif status in ELIGIBLE_STATUSES | DIAGNOSTIC_STATUSES:
        problems.append(
            f"entry {strategy_id}: status {status} requires a complete research/execution policy block "
            "(qts.lifecycle.demo_policy) — an un-specified experiment may not trade"
        )
    if policy is not None:
        # The policy and the entry must describe the same strategy, and the
        # policy's own allowed symbols must include the entry's.
        if policy.strategy_id and policy.strategy_id != strategy_id:
            problems.append(
                f"entry {strategy_id}: policy.strategy_id {policy.strategy_id!r} does not match the entry"
            )
        if policy.allowed_symbols and [str(x) for x in (doc.get("allowed_symbols") or [])]:
            extra = [s for s in (doc.get("allowed_symbols") or []) if not policy.allows_symbol(s)]
            if extra:
                problems.append(
                    f"entry {strategy_id}: allowed_symbols {extra} are not permitted by the policy "
                    f"({list(policy.allowed_symbols)})"
                )
        if policy.max_orders_per_day and int(doc.get("max_orders_per_day") or 0) not in (0, policy.max_orders_per_day):
            problems.append(
                f"entry {strategy_id}: max_orders_per_day {doc.get('max_orders_per_day')} disagrees with the "
                f"policy ({policy.max_orders_per_day})"
            )

    entry = StrategyRegistration(
        strategy_id=strategy_id,
        status=status,
        hypothesis_id=(str(doc["hypothesis_id"]) if doc.get("hypothesis_id") else None),
        preregistration_artifact=(
            str(doc["preregistration_artifact"]) if doc.get("preregistration_artifact") else None
        ),
        signal_provider=(str(doc["signal_provider"]) if doc.get("signal_provider") else None),
        params=params,
        params_hash=declared_hash or actual_hash,
        size_policy=dict(doc.get("size_policy") or {}),
        stop_policy=dict(doc.get("stop_policy") or {}),
        exit_policy=dict(doc.get("exit_policy") or {}),
        allowed_symbols=[str(s) for s in (doc.get("allowed_symbols") or [])],
        max_orders_per_day=max_orders,
        notes=str(doc.get("notes") or ""),
        raw=doc,
        policy=policy,
    )
    return entry, problems


def load_registry(path: str | Path | None = None) -> RegistrySnapshot:
    """Load the forward-validation registry (fail closed)."""
    target = _registry_path(path)
    if not target.exists():
        return RegistrySnapshot(
            path=target,
            valid=False,
            reasons=[f"no forward-validation registry at {target} — no strategy is eligible (NO_TRADE)"],
        )
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return RegistrySnapshot(
            path=target,
            valid=False,
            reasons=[f"forward-validation registry unreadable — fail closed ({type(exc).__name__}: {exc})"],
        )
    if not isinstance(doc, dict) or doc.get("schema") not in REGISTRY_SCHEMAS:
        return RegistrySnapshot(
            path=target,
            valid=False,
            reasons=[f"unsupported registry schema {doc.get('schema')!r} — fail closed (no eligible strategy)"],
        )

    reasons: list[str] = []
    integrity = dict(doc.get("research_integrity") or {})
    if integrity.get("optimization_allowed") is not False:
        reasons.append("research_integrity.optimization_allowed must be false — no optimization against forward DEMO results")
    if integrity.get("no_forward_fitting") is not True:
        reasons.append("research_integrity.no_forward_fitting must be true — parameters stay frozen for the window")

    entries: list[StrategyRegistration] = []
    for raw_entry in list(doc.get("entries") or []):
        entry, problems = _entry_from(raw_entry if isinstance(raw_entry, dict) else {})
        reasons.extend(problems)
        if entry is not None:
            entries.append(entry)

    return RegistrySnapshot(
        path=target,
        valid=not reasons,
        entries=tuple(entries),
        research_integrity=integrity,
        reasons=reasons,
        raw=doc,
    )


def resolve_entry(
    registry: RegistrySnapshot,
    strategy_id: str | None = None,
) -> tuple[StrategyRegistration | None, list[str]]:
    """Resolve the ONE strategy allowed to generate DEMO orders (fail closed).

    ``strategy_id=None`` means "whatever the single eligible entry is"; with
    zero or several eligible entries the resolution refuses, because an
    ambiguous trading mandate is not an auditable one.
    """
    reasons: list[str] = list(registry.reasons)
    if not registry.entries:
        reasons.append("forward-validation registry has no entries — NO_TRADE")
        return None, reasons
    if registry.reasons:
        return None, reasons

    if strategy_id:
        matches = [e for e in registry.entries if e.strategy_id == strategy_id]
        if not matches:
            reasons.append(f"strategy {strategy_id!r} is not registered for DEMO forward validation — NO_TRADE")
            return None, reasons
        entry = matches[0]
        if not entry.eligible:
            reasons.append(
                f"strategy {strategy_id!r} status is {entry.status} — not eligible for DEMO execution (NO_TRADE)"
                + (
                    ""
                    if entry.policy is not None
                    else " (no complete research/execution policy attached to the entry)"
                )
            )
            return None, reasons
    else:
        eligible = registry.eligible_entries
        if not eligible:
            reasons.append(
                "no strategy is eligible in the forward-validation registry — NO_TRADE "
                "(DEMO_EXECUTION may be ENABLED while no strategy is validated; an eligible entry needs "
                "status ELIGIBLE with a validation artifact, or ELIGIBLE_DIAGNOSTIC with a complete, "
                "non-validated DEMO_FORWARD_RESEARCH_POLICY)"
            )
            return None, reasons
        if len(eligible) > 1:
            reasons.append(
                "multiple eligible strategies in the registry — an explicit --strategy selection is required "
                f"({', '.join(e.strategy_id for e in eligible)})"
            )
            return None, reasons
        entry = eligible[0]

    # Per-entry covenants.
    if not entry.hypothesis_id:
        reasons.append(f"strategy {entry.strategy_id}: no hypothesis_id — unpreregistered strategies may not trade")
    if not entry.preregistration_artifact:
        reasons.append(f"strategy {entry.strategy_id}: no preregistration_artifact — research mandate missing")
    if not entry.signal_provider:
        reasons.append(f"strategy {entry.strategy_id}: no signal_provider — cannot generate orders")
    stop_required = bool(entry.stop_policy.get("required", True))
    if not stop_required and not str(entry.stop_policy.get("justification") or "").strip():
        reasons.append(
            f"strategy {entry.strategy_id}: stop_policy.required=false without justification — fail closed"
        )
    if entry.max_orders_per_day <= 0:
        reasons.append(f"strategy {entry.strategy_id}: max_orders_per_day must be > 0 — fail closed")
    if entry.policy is None:
        reasons.append(
            f"strategy {entry.strategy_id}: no complete research/execution policy — un-specified experiments "
            "may not generate orders (NO_TRADE)"
        )
    elif entry.status in DIAGNOSTIC_STATUSES and entry.policy.validated_edge:
        reasons.append(
            f"strategy {entry.strategy_id}: status ELIGIBLE_DIAGNOSTIC with validated_edge=true is contradictory "
            "— a validated strategy must be registered as ELIGIBLE"
        )

    if reasons:
        return None, reasons
    return entry, []


def registry_status(path: str | Path | None = None) -> dict[str, Any]:
    """Operator-facing registry state (used by CLI/API)."""
    registry = load_registry(path)
    entry, reasons = resolve_entry(registry)
    return {
        "registry": registry.as_dict(),
        "resolved_strategy": entry.as_dict() if entry else None,
        "trading_state": _trading_state(entry),
        "validated_edge": bool(entry.validated_edge) if entry else False,
        "policy_class": entry.policy_class if entry else None,
        "reasons": reasons,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def _trading_state(entry: StrategyRegistration | None) -> str:
    """Operator-facing trading state, distinguishing validated from diagnostic.

    ``TRADING_ELIGIBLE``        — a strategy with a validated edge may trade.
    ``TRADING_ELIGIBLE_DIAGNOSTIC`` — a registered, non-validated DEMO forward
    research policy may trade to *measure*; no edge is claimed.
    ``NO_TRADE``                — nothing eligible.
    """
    if entry is None:
        return "NO_TRADE"
    if entry.status in ELIGIBLE_STATUSES:
        return "TRADING_ELIGIBLE"
    return "TRADING_ELIGIBLE_DIAGNOSTIC"
