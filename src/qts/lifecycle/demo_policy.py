"""The DEMO forward research/execution policy — schema, validation, enforcement.

Why a policy object and not a config dict
-----------------------------------------
``DEMO_EXECUTION = ENABLED_AUTHORIZED`` answers *"may QTS send DEMO orders at
all?"*. It deliberately does not answer *"what may QTS do with them?"*. That
second question is this module: a registered **research/execution policy** —
the frozen, hashed, auditable description of one forward experiment.

A policy is a *measurement* instrument, not an alpha claim. Every field is
required (a policy missing one is refused, never defaulted) so that the
experiment is fully specified before the first order and cannot be re-specified
afterwards because a trade lost:

* **identity** — ``policy_id``/``strategy_id``/``policy_class``/``version``/
  ``created_at``;
* **logic** — ``signal_logic``, ``entry_conditions``, ``exit_conditions``,
  ``stop_loss_logic``, ``position_sizing``;
* **limits** — ``max_simultaneous_exposure_lots``, ``max_daily_loss``,
  ``max_drawdown``, ``max_orders_per_day``, ``min_order_interval_s``;
* **market** — ``allowed_symbols``, ``allowed_trading_hours``,
  ``max_spread_bps``, ``max_slippage_bps``;
* **execution** — ``execution_delay_assumption_ms``, ``min_data_requirements``,
  ``stale_data_protection``, ``duplicate_order_protection``;
* **controls** — ``kill_conditions``, ``reconciliation_requirements``;
* **provenance** — ``code_hash``, ``config_hash``, ``data_hash``;
* **research integrity** — ``validated_edge`` and ``edge_statement``.

Two rules matter more than the rest:

1. **Nothing is inferred.** A missing or unparseable field fails closed with a
   named reason, because a policy that is half-specified is a policy that will
   be finished later — after seeing the first result.
2. **The policy is small.** These caps may only *tighten* the canonical DEMO
   risk limits. Registration is not a route to a bigger position.

``validated_edge`` is the honesty bit: it is ``false`` for every diagnostic
policy (the normal case for a system with no validated strategy). A policy may
only set it ``true`` together with a ``validation_artifact`` that exists — an
assertion of edge without an artifact behind it is refused.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from qts.lifecycle.demo_registry import params_fingerprint

POLICY_SCHEMA = "qts.demo_forward_research_policy.v1"

#: The only class of policy this module registers. Naming it explicitly keeps
#: "a registered research experiment" distinguishable from "a validated
#: trading strategy" everywhere the policy is surfaced (CLI, API, journal).
POLICY_CLASS = "DEMO_FORWARD_RESEARCH_POLICY"

#: Fields that must be present and non-empty. Order is documentation order.
REQUIRED_POLICY_FIELDS: tuple[str, ...] = (
    # identity
    "policy_id",
    "strategy_id",
    "policy_class",
    "version",
    "created_at",
    # logic
    "signal_logic",
    "entry_conditions",
    "exit_conditions",
    "stop_loss_logic",
    "position_sizing",
    # limits
    "max_simultaneous_exposure_lots",
    "max_daily_loss",
    "max_drawdown",
    "max_orders_per_day",
    "min_order_interval_s",
    # market
    "allowed_symbols",
    "allowed_trading_hours",
    "max_spread_bps",
    "max_slippage_bps",
    # execution
    "execution_delay_assumption_ms",
    "min_data_requirements",
    "stale_data_protection",
    "duplicate_order_protection",
    # controls
    "kill_conditions",
    "reconciliation_requirements",
    # provenance
    "code_hash",
    "config_hash",
    "policy_hash",
    "data_hash",
    # research integrity
    "validated_edge",
    "edge_statement",
)

#: Kill-condition vocabulary. An unrecognised condition is REFUSED rather than
#: ignored: a typo must never silently remove a kill condition.
KILL_CONDITION_VOCABULARY: frozenset[str] = frozenset(
    {
        "daily_loss_limit",
        "max_drawdown",
        "kill_switch",
        "reconciliation_suspension",
        "reconciliation_drift",
        "parameter_drift",
        "code_drift",
        "identity_mismatch",
        "authorization_revoked",
        "stage_not_order_permitted",
        "market_data_stale",
        "provider_error",
    }
)

#: Gate-check names a kill condition maps onto. When the gate fails one of
#: these checks AND the policy lists the condition, the system must raise the
#: kill switch (not merely refuse the order) — that is what makes "kill
#: conditions" a control instead of a comment.
KILL_CONDITION_CHECKS: dict[str, tuple[str, ...]] = {
    "daily_loss_limit": ("max_daily_loss",),
    "max_drawdown": ("max_drawdown_within_policy",),
    "reconciliation_suspension": ("reconciliation_ready",),
    "reconciliation_drift": ("reconciliation_ready",),
    "parameter_drift": ("strategy_registered_frozen",),
    "identity_mismatch": ("broker_identity_verified", "account_is_demo"),
    "authorization_revoked": ("authorization_valid",),
    "stage_not_order_permitted": ("stage_allows_order",),
    "market_data_stale": ("market_data_fresh",),
}

_WEEKDAYS = frozenset({"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"})
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

#: Phrases that make an edge statement a disclaimer rather than a claim. A
#: policy's ``edge_statement`` must contain one of them, so a future policy
#: cannot register an honest-sounding field that actually claims an edge.
_EDGE_DISCLAIMER_MARKERS: tuple[str, ...] = (
    "does not establish",
    "does not constitute",
    "does not demonstrate",
    "not proof",
    "not evidence",
    "no validated edge",
)


def _freeze(value: Any) -> Any:
    """Deep-freeze a parsed policy document.

    A frozen dataclass wrapping a mutable dict is not immutable: a caller
    holding the policy could retune ``max_daily_loss`` after registration and
    the hash would still match, because the hash covers what was *registered*,
    not what the object now says. Read-only views remove that gap.
    """
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def policy_fingerprint(doc: dict[str, Any]) -> str:
    """SHA-256 of a policy document, excluding its own ``policy_hash`` field.

    ``config_hash`` pins the *parameters*; this pins the *policy* — the limits,
    hours, kill conditions and symbol binding themselves. Without it, a policy
    document could be edited after registration (``max_daily_loss`` 5 → 500)
    while every existing hash still matched, and nothing would notice.
    """
    body = {k: v for k, v in (doc or {}).items() if k != "policy_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return isinstance(value, (list, tuple, dict)) and len(value) == 0


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_weekday(moment: datetime) -> str:
    return ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[moment.weekday()]


@dataclass(frozen=True)
class ResearchPolicy:
    """One validated DEMO forward research/execution policy (immutable)."""

    raw: dict[str, Any]
    params: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ identity
    @property
    def policy_id(self) -> str:
        return str(self.raw.get("policy_id") or "")

    @property
    def strategy_id(self) -> str:
        return str(self.raw.get("strategy_id") or "")

    @property
    def policy_class(self) -> str:
        return str(self.raw.get("policy_class") or "")

    @property
    def version(self) -> str:
        return str(self.raw.get("version") or "")

    @property
    def created_at(self) -> str:
        return str(self.raw.get("created_at") or "")

    @property
    def purpose(self) -> str:
        return str(self.raw.get("purpose") or "")

    @property
    def hypothesis_id(self) -> str | None:
        value = self.raw.get("hypothesis_id")
        return str(value) if value else None

    @property
    def validated_edge(self) -> bool:
        return bool(self.raw.get("validated_edge"))

    @property
    def edge_statement(self) -> str:
        return str(self.raw.get("edge_statement") or "")

    @property
    def validation_artifact(self) -> str | None:
        value = self.raw.get("validation_artifact")
        return str(value) if value else None

    # ------------------------------------------------------------- hashes
    @property
    def code_hash(self) -> str:
        return str(self.raw.get("code_hash") or "")

    @property
    def config_hash(self) -> str:
        return str(self.raw.get("config_hash") or "")

    @property
    def policy_hash(self) -> str:
        return str(self.raw.get("policy_hash") or "")

    @property
    def data_hash(self) -> str | None:
        value = self.raw.get("data_hash")
        return str(value) if value else None

    # ------------------------------------------------------------- limits
    @property
    def max_orders_per_day(self) -> int:
        return int(_as_float(self.raw.get("max_orders_per_day")) or 0)

    @property
    def min_order_interval_s(self) -> float:
        return float(_as_float(self.raw.get("min_order_interval_s")) or 0.0)

    @property
    def max_daily_loss(self) -> float:
        return float(_as_float(self.raw.get("max_daily_loss")) or 0.0)

    @property
    def max_drawdown(self) -> float:
        return float(_as_float(self.raw.get("max_drawdown")) or 0.0)

    @property
    def max_simultaneous_exposure_lots(self) -> float:
        return float(_as_float(self.raw.get("max_simultaneous_exposure_lots")) or 0.0)

    @property
    def max_spread_bps(self) -> float:
        return float(_as_float(self.raw.get("max_spread_bps")) or 0.0)

    @property
    def max_slippage_bps(self) -> float:
        return float(_as_float(self.raw.get("max_slippage_bps")) or 0.0)

    @property
    def execution_delay_assumption_ms(self) -> float:
        return float(_as_float(self.raw.get("execution_delay_assumption_ms")) or 0.0)

    @property
    def allowed_symbols(self) -> tuple[str, ...]:
        return tuple(str(s) for s in (self.raw.get("allowed_symbols") or []))

    @property
    def kill_conditions(self) -> tuple[str, ...]:
        return tuple(str(c) for c in (self.raw.get("kill_conditions") or []))

    # ------------------------------------------------------------- helpers
    def allows_symbol(self, symbol: str | None) -> bool:
        if not symbol or not self.allowed_symbols:
            return False
        return str(symbol).upper() in {s.upper() for s in self.allowed_symbols}

    def within_trading_hours(self, moment: datetime | None = None) -> bool:
        """Whether ``moment`` (UTC) falls inside a declared session.

        An undeclared or malformed schedule refuses — trading hours are a
        limit, and an unreadable limit is not an open one.
        """
        now = moment or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        now = now.astimezone(UTC)
        sessions = (self.raw.get("allowed_trading_hours") or {}).get("sessions") or []
        day = _utc_weekday(now)
        minutes = now.hour * 60 + now.minute
        for session in sessions:
            days = {str(d).upper() for d in (session.get("days") or [])}
            if day not in days:
                continue
            start = _hhmm_to_minutes(session.get("start"))
            end = _hhmm_to_minutes(session.get("end"))
            if start is None or end is None or start >= end:
                continue
            if start <= minutes < end:
                return True
        return False

    def spread_cap_bps(self) -> float:
        return self.max_spread_bps

    def tick_age_cap_s(self) -> float | None:
        value = _as_float((self.raw.get("stale_data_protection") or {}).get("max_tick_age_s"))
        return value if value and value > 0 else None

    def stop_distance_price(self) -> float | None:
        value = _as_float((self.raw.get("stop_loss_logic") or {}).get("distance_price"))
        return value if value and value > 0 else None

    def stop_required(self) -> bool:
        return bool((self.raw.get("stop_loss_logic") or {}).get("required", True))

    def max_hold_seconds(self) -> float:
        return float(_as_float((self.raw.get("exit_conditions") or {}).get("max_hold_seconds")) or 0.0)

    def reconcile_max_age_s(self) -> float | None:
        value = _as_float((self.raw.get("reconciliation_requirements") or {}).get("max_age_s"))
        return value if value and value > 0 else None

    def reconcile_after_every_order(self) -> bool:
        return bool((self.raw.get("reconciliation_requirements") or {}).get("after_every_order", False))

    def required_gate_checks(self) -> tuple[str, ...]:
        """Gate checks this policy declares as mandatory (may only add)."""
        return tuple(str(c) for c in ((self.raw.get("min_data_requirements") or {}).get("required_checks") or []))

    def must_kill_on(self, failed_checks: Any) -> tuple[str, ...]:
        """Which of this policy's kill conditions are triggered by ``failed_checks``."""
        failed = {str(c) for c in (failed_checks or [])}
        triggered: list[str] = []
        for condition in self.kill_conditions:
            for check in KILL_CONDITION_CHECKS.get(condition, (condition,)):
                if check in failed:
                    triggered.append(condition)
                    break
        return tuple(triggered)

    def verify_code_hash(self, source_path: str | Path) -> tuple[bool, str]:
        """Compare the policy's ``code_hash`` against a source file on disk.

        A signal provider that no longer matches the registered code is a
        different experiment wearing the same ``strategy_id``: it must halt,
        not trade.
        """
        try:
            body = Path(source_path).read_bytes()
        except Exception as exc:
            return False, f"code source unreadable — fail closed ({type(exc).__name__}: {exc})"
        actual = hashlib.sha256(body).hexdigest()
        if not self.code_hash:
            return False, "policy declares no code_hash — fail closed"
        if actual.lower() != self.code_hash.lower():
            return False, f"code drift: registered {self.code_hash[:12]}… != on-disk {actual[:12]}…"
        return True, f"code hash matches ({actual[:12]}…)"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": POLICY_SCHEMA,
            "policy_id": self.policy_id,
            "strategy_id": self.strategy_id,
            "policy_class": self.policy_class,
            "version": self.version,
            "created_at": self.created_at,
            "purpose": self.purpose,
            "hypothesis_id": self.hypothesis_id,
            "validated_edge": self.validated_edge,
            "edge_statement": self.edge_statement,
            "validation_artifact": self.validation_artifact,
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "policy_hash": self.policy_hash,
            "data_hash": self.data_hash,
            "limits": {
                "max_simultaneous_exposure_lots": self.max_simultaneous_exposure_lots,
                "max_daily_loss": self.max_daily_loss,
                "max_drawdown": self.max_drawdown,
                "max_orders_per_day": self.max_orders_per_day,
                "min_order_interval_s": self.min_order_interval_s,
                "max_spread_bps": self.max_spread_bps,
                "max_slippage_bps": self.max_slippage_bps,
            },
            "allowed_symbols": list(self.allowed_symbols),
            "allowed_trading_hours": dict(self.raw.get("allowed_trading_hours") or {}),
            "execution_delay_assumption_ms": self.execution_delay_assumption_ms,
            "kill_conditions": list(self.kill_conditions),
            "reconciliation_requirements": dict(self.raw.get("reconciliation_requirements") or {}),
            "stale_data_protection": dict(self.raw.get("stale_data_protection") or {}),
            "duplicate_order_protection": dict(self.raw.get("duplicate_order_protection") or {}),
            "min_data_requirements": dict(self.raw.get("min_data_requirements") or {}),
            "signal_logic": dict(self.raw.get("signal_logic") or {}),
            "entry_conditions": dict(self.raw.get("entry_conditions") or {}),
            "exit_conditions": dict(self.raw.get("exit_conditions") or {}),
            "stop_loss_logic": dict(self.raw.get("stop_loss_logic") or {}),
            "position_sizing": dict(self.raw.get("position_sizing") or {}),
        }


def _hhmm_to_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _TIME_RE.match(value.strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def validate_policy(doc: Any, params: dict[str, Any] | None = None) -> tuple[ResearchPolicy | None, list[str]]:
    """Validate a policy block (fail closed, every problem reported)."""
    reasons: list[str] = []

    if not isinstance(doc, dict):
        return None, ["policy block is not an object — fail closed"]
    if doc.get("schema") not in (None, POLICY_SCHEMA):
        reasons.append(f"unsupported policy schema {doc.get('schema')!r} — expected {POLICY_SCHEMA}")
    label = str(doc.get("policy_id") or doc.get("strategy_id") or "policy")

    missing = [name for name in REQUIRED_POLICY_FIELDS if _is_blank(doc.get(name))]
    # `data_hash` may legitimately be absent when no historical dataset is used
    # (declared explicitly), so it is validated separately below.
    if "data_hash" in missing:
        missing.remove("data_hash")
    if missing:
        reasons.append(f"policy {label}: missing required field(s) {', '.join(missing)} — fail closed")

    if doc.get("policy_class") and str(doc["policy_class"]) != POLICY_CLASS:
        reasons.append(
            f"policy {label}: policy_class {doc['policy_class']!r} != {POLICY_CLASS} — "
            "only DEMO forward research policies may be registered for DEMO execution"
        )
    if doc.get("version") and not _VERSION_RE.match(str(doc["version"])):
        reasons.append(f"policy {label}: version {doc['version']!r} is not MAJOR.MINOR.PATCH")
    if doc.get("created_at"):
        try:
            datetime.fromisoformat(str(doc["created_at"]))
        except (TypeError, ValueError):
            reasons.append(f"policy {label}: created_at {doc['created_at']!r} is not an ISO-8601 timestamp")

    # ---- research integrity ------------------------------------------------
    if doc.get("validated_edge") is True:
        artifact = str(doc.get("validation_artifact") or "").strip()
        if not artifact:
            reasons.append(
                f"policy {label}: validated_edge=true without a validation_artifact — an edge claim needs evidence"
            )
        elif not Path(artifact).exists():
            reasons.append(f"policy {label}: validation_artifact {artifact!r} does not exist — fail closed")
    statement = str(doc.get("edge_statement") or "").strip()
    if statement:
        lowered = statement.lower()
        if len(statement) < 40:
            reasons.append(f"policy {label}: edge_statement is too short to be an explicit statement")
        if not any(marker in lowered for marker in _EDGE_DISCLAIMER_MARKERS):
            reasons.append(
                f"policy {label}: edge_statement lacks an explicit disclaimer that DEMO performance does not "
                f"establish a validated edge (one of: {', '.join(_EDGE_DISCLAIMER_MARKERS)})"
            )

    # ---- numeric limits (must be positive and small) ------------------------
    for name in ("max_daily_loss", "max_drawdown", "max_simultaneous_exposure_lots", "max_spread_bps"):
        value = _as_float(doc.get(name))
        if value is None or value <= 0:
            reasons.append(f"policy {label}: {name} must be a positive number (got {doc.get(name)!r})")
    orders = _as_float(doc.get("max_orders_per_day"))
    if orders is None or orders < 1:
        reasons.append(f"policy {label}: max_orders_per_day must be >= 1 (got {doc.get('max_orders_per_day')!r})")
    interval = _as_float(doc.get("min_order_interval_s"))
    if interval is None or interval < 0:
        reasons.append(f"policy {label}: min_order_interval_s must be >= 0 (got {doc.get('min_order_interval_s')!r})")
    delay = _as_float(doc.get("execution_delay_assumption_ms"))
    if delay is None or delay <= 0:
        reasons.append(
            f"policy {label}: execution_delay_assumption_ms must be positive (got {doc.get('execution_delay_assumption_ms')!r})"
        )

    # ---- symbols ------------------------------------------------------------
    symbols = [str(s) for s in (doc.get("allowed_symbols") or [])]
    if not symbols:
        reasons.append(f"policy {label}: allowed_symbols must name at least one symbol")

    # ---- trading hours ------------------------------------------------------
    hours = doc.get("allowed_trading_hours") or {}
    if not isinstance(hours, dict) or not hours.get("sessions"):
        reasons.append(f"policy {label}: allowed_trading_hours must declare at least one session")
    else:
        if str(hours.get("timezone") or "UTC").upper() != "UTC":
            reasons.append(f"policy {label}: allowed_trading_hours.timezone must be UTC (got {hours.get('timezone')!r})")
        for index, session in enumerate(hours["sessions"]):
            if not isinstance(session, dict):
                reasons.append(f"policy {label}: session {index} is not an object")
                continue
            days = {str(d).upper() for d in (session.get("days") or [])}
            if not days or not days <= _WEEKDAYS:
                reasons.append(f"policy {label}: session {index} declares invalid days {sorted(days)}")
            start = _hhmm_to_minutes(session.get("start"))
            end = _hhmm_to_minutes(session.get("end"))
            if start is None or end is None:
                reasons.append(
                    f"policy {label}: session {index} has unparseable start/end "
                    f"({session.get('start')!r}/{session.get('end')!r}) — expected HH:MM"
                )
            elif start >= end:
                reasons.append(f"policy {label}: session {index} start must be before end")

    # ---- stop, sizing, exits -------------------------------------------------
    stop = doc.get("stop_loss_logic") or {}
    if isinstance(stop, dict) and stop.get("required") is not False:
        distance = _as_float(stop.get("distance_price"))
        if distance is None or distance <= 0:
            reasons.append(
                f"policy {label}: stop_loss_logic.required without a positive distance_price — "
                "a stop that cannot be computed is not a stop"
            )
    elif isinstance(stop, dict) and not str(stop.get("justification") or "").strip():
        reasons.append(f"policy {label}: stop_loss_logic.required=false requires a justification")

    sizing = doc.get("position_sizing") or {}
    if isinstance(sizing, dict):
        lots = _as_float(sizing.get("lots"))
        cap = _as_float(doc.get("max_simultaneous_exposure_lots"))
        if lots is None or lots <= 0:
            reasons.append(f"policy {label}: position_sizing.lots must be positive")
        elif cap is not None and lots > cap:
            reasons.append(
                f"policy {label}: position_sizing.lots {lots} exceeds max_simultaneous_exposure_lots {cap}"
            )
        if str(sizing.get("mode") or "") not in ("broker_minimum", "fixed"):
            reasons.append(f"policy {label}: position_sizing.mode must be 'broker_minimum' or 'fixed'")

    exits = doc.get("exit_conditions") or {}
    if isinstance(exits, dict):
        hold = _as_float(exits.get("max_hold_seconds"))
        if hold is None or hold <= 0:
            reasons.append(
                f"policy {label}: exit_conditions.max_hold_seconds must be positive — "
                "every position needs a deterministic time exit"
            )

    # ---- data requirements / hashes -----------------------------------------
    min_data = doc.get("min_data_requirements") or {}
    if isinstance(min_data, dict):
        if not [str(c) for c in (min_data.get("required_checks") or [])]:
            reasons.append(f"policy {label}: min_data_requirements.required_checks must name the mandatory gate checks")
        if bool(min_data.get("requires_historical_dataset")) and not str(doc.get("data_hash") or "").strip():
            reasons.append(
                f"policy {label}: requires_historical_dataset=true but no data_hash — the dataset must be pinned"
            )
    data_hash = str(doc.get("data_hash") or "").strip()
    if data_hash and not _HEX64_RE.match(data_hash):
        reasons.append(f"policy {label}: data_hash is not a sha256 hex digest")

    declared_policy_hash = str(doc.get("policy_hash") or "").strip()
    if not declared_policy_hash:
        reasons.append(f"policy {label}: policy_hash missing — the policy document itself must be pinned")
    elif not _HEX64_RE.match(declared_policy_hash):
        reasons.append(f"policy {label}: policy_hash is not a sha256 hex digest")
    elif declared_policy_hash != policy_fingerprint(doc):
        reasons.append(
            f"policy {label}: policy_hash mismatch (declared {declared_policy_hash[:12]}…, computed "
            f"{policy_fingerprint(doc)[:12]}…) — the policy was edited after registration"
        )

    for hash_field in ("code_hash", "config_hash"):
        value = str(doc.get(hash_field) or "").strip()
        if value and not _HEX64_RE.match(value):
            reasons.append(f"policy {label}: {hash_field} is not a sha256 hex digest")

    declared_config = str(doc.get("config_hash") or "").strip()
    if declared_config and declared_config != params_fingerprint(params or {}):
        reasons.append(
            f"policy {label}: config_hash does not match the registered params "
            f"(declared {declared_config[:12]}…, computed {params_fingerprint(params or {})[:12]}…)"
        )

    # ---- controls -------------------------------------------------------------
    stale = doc.get("stale_data_protection") or {}
    if isinstance(stale, dict):
        age = _as_float(stale.get("max_tick_age_s"))
        if age is None or age <= 0:
            reasons.append(f"policy {label}: stale_data_protection.max_tick_age_s must be positive")
        if str(stale.get("on_stale") or "").upper() not in ("NO_TRADE", "HALT"):
            reasons.append(f"policy {label}: stale_data_protection.on_stale must be NO_TRADE or HALT")

    duplicates = doc.get("duplicate_order_protection") or {}
    if isinstance(duplicates, dict):
        if duplicates.get("idempotency_required") is not True:
            reasons.append(
                f"policy {label}: duplicate_order_protection.idempotency_required must be true — "
                "client_order_id idempotency is mandatory for DEMO orders"
            )
        gap = _as_float(duplicates.get("min_order_interval_s"))
        if gap is None or gap < 0:
            reasons.append(f"policy {label}: duplicate_order_protection.min_order_interval_s must be >= 0")

    kills = [str(c) for c in (doc.get("kill_conditions") or [])]
    if not kills:
        reasons.append(f"policy {label}: kill_conditions must name at least one condition")
    unknown = [c for c in kills if c not in KILL_CONDITION_VOCABULARY]
    if unknown:
        reasons.append(
            f"policy {label}: unknown kill condition(s) {unknown} — refused so a typo cannot silently "
            f"drop a control (vocabulary: {', '.join(sorted(KILL_CONDITION_VOCABULARY))})"
        )

    recon = doc.get("reconciliation_requirements") or {}
    if isinstance(recon, dict):
        if recon.get("after_every_order") is not True:
            reasons.append(f"policy {label}: reconciliation_requirements.after_every_order must be true")
        age = _as_float(recon.get("max_age_s"))
        if age is None or age <= 0:
            reasons.append(f"policy {label}: reconciliation_requirements.max_age_s must be positive")
        if str(recon.get("on_drift") or "").upper() not in ("HALT", "NO_TRADE"):
            reasons.append(f"policy {label}: reconciliation_requirements.on_drift must be HALT or NO_TRADE")

    if reasons:
        return None, reasons
    return ResearchPolicy(raw=_freeze(doc), params=_freeze(dict(params or {}))), []
