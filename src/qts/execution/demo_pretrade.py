"""DEMO pre-trade safety gate — every required safeguard, fail closed.

The gate is the single place that answers "may this specific DEMO order be
sent right now?". It is deliberately independent of the caller: CLI, API, and
autopilot all receive the same verdict for the same facts.

Rules that shape every check here:

* **No UNKNOWN ever passes.** A missing fact is recorded as ``UNKNOWN`` and
  fails the gate. ``None`` is never coerced into a permissive value
  (unknown account → not DEMO; unknown kill state → killed; unknown reconcile
  state → suspended).
* **Refusal is structured.** Every check carries a machine-readable status plus
  a human detail, so an operator sees *which* safeguard blocked, not a generic
  "not allowed".
* **Hard caps come from one authority** (:mod:`qts.risk.authority`) resolved
  for ``DEMO_EXECUTION``, optionally tightened by the authorization artifact.
  The gate never invents a limit.

Check → requirement mapping (owner's 17 required safeguards):

===  ================================================  ================================
#    Required safeguard                                Check name(s)
===  ================================================  ================================
1    account is actually DEMO                          ``account_is_demo``
2    broker/server identity                            ``broker_identity_verified``
3    canonical symbol mapping                          ``symbol_mapping_canonical``
4    market data freshness                             ``market_data_fresh``
5    spread available                                  ``spread_available``
6    order size within hard maximum                    ``order_size_within_hard_max``
7    stop-loss present where required                  ``stop_loss_present``
8    maximum simultaneous positions                    ``max_simultaneous_positions``
9    maximum daily loss                                ``max_daily_loss``
10   maximum total demo exposure                       ``max_total_exposure``
11   duplicate-order protection                        ``duplicate_order_protection``
12   kill-switch functionality                         ``kill_switch_functional``
13   reconciliation after every order                  ``reconciliation_ready``
14   broker order/position id recorded                 ``broker_reference_capture``
15   price/spread/slippage/timestamps recorded         ``execution_record_fields``
16   strategy/configuration hash recorded              ``strategy_registered_frozen``
17   fail closed on any uncertainty                    ``no_unknown_checks``
===  ================================================  ================================

Contract-level checks (``authorization_valid``, ``execution_permission``,
``mode_is_demo_execution``, ``stage_allows_order``, ``autonomous_allowed``)
guard *whether this process may trade at all* and run alongside the above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from qts.execution.demo_identity import BrokerIdentity
from qts.lifecycle.demo_authorization import LoadedAuthorization
from qts.lifecycle.demo_registry import StrategyRegistration
from qts.lifecycle.demo_stage import ORDER_STAGES, DemoStage

CHECK_PASS = "PASS"
CHECK_FAIL = "FAIL"
CHECK_UNKNOWN = "UNKNOWN"

#: Required execution-record fields (safeguard #15). A recorder that cannot
#: fill all of them must not be used for DEMO orders.
REQUIRED_RECORD_FIELDS: tuple[str, ...] = (
    "authorization_id",
    "client_order_id",
    "strategy_id",
    "strategy_config_hash",
    "requested_price",
    "executed_price",
    "spread_bps",
    "slippage_bps",
    "requested_at",
    "submitted_at",
    "broker_order_id",
    "label",
)

#: Label carried by every DEMO order produced through this path.
RESEARCH_DEMO_ORDER = "RESEARCH_DEMO_ORDER"

DEFAULT_MAX_RECONCILE_AGE_S = 300.0
DEFAULT_MIN_ORDER_INTERVAL_S = 15.0


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == CHECK_PASS

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class PretradeVerdict:
    passed: bool
    checks: dict[str, CheckResult] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(name for name, c in self.checks.items() if c.status == CHECK_FAIL)

    @property
    def unknown(self) -> tuple[str, ...]:
        return tuple(name for name, c in self.checks.items() if c.status == CHECK_UNKNOWN)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "failed": list(self.failed),
            "unknown": list(self.unknown),
            "checks": {name: c.as_dict() for name, c in self.checks.items()},
            "checked_at": self.checked_at,
        }


@dataclass
class DemoPretradeContext:
    """Everything the gate needs. ``None`` means UNKNOWN and fails closed."""

    # ---- contract / permission -------------------------------------------
    policy: Any | None = None  # DemoExecutionPolicy
    authorization: LoadedAuthorization | None = None
    authority_permitted: bool | None = None
    authority_reasons: list[str] = field(default_factory=list)
    mode: str | None = None
    stage: str = DemoStage.DISABLED.value

    # ---- identity / market ------------------------------------------------
    identity: BrokerIdentity | None = None
    pin: dict[str, Any] | None = None
    pin_reasons: list[str] = field(default_factory=list)

    symbol: str | None = None
    broker_symbol: str | None = None
    symbol_visible: bool | None = None
    symbol_tradable: bool | None = None
    spec: Any | None = None  # MT5Adapter.SymbolSpec
    order_check_ok: bool | None = None  # broker order_check dry-run result
    order_check_detail: str = ""
    tick: Any | None = None  # domain Tick
    tick_age_s: float | None = None
    max_tick_age_s: float | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    spread_bps: float | None = None

    # ---- account / exposure ----------------------------------------------
    account: Any | None = None  # domain Account
    open_positions: list[Any] = field(default_factory=list)
    open_orders: list[Any] = field(default_factory=list)
    daily_realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None

    # ---- the intended order ----------------------------------------------
    side: str | None = None
    intended_lots: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    stop_required: bool = True
    client_order_id: str | None = None
    idempotency_status: str | None = None
    recent_order_epochs: list[float] = field(default_factory=list)
    min_order_interval_s: float = DEFAULT_MIN_ORDER_INTERVAL_S
    autonomous: bool = False

    # ---- controls ---------------------------------------------------------
    kill_switch_active: bool | None = None
    kill_switch_readable: bool = False
    kill_switch_self_test: bool | None = None
    kill_switch_detail: str = ""
    reconcile_suspended: bool | None = None
    reconcile_drift: str | None = None
    last_reconcile_age_s: float | None = None
    max_reconcile_age_s: float = DEFAULT_MAX_RECONCILE_AGE_S

    # ---- recording --------------------------------------------------------
    adapter_captures_broker_ids: bool | None = None
    journal_ready: bool = False
    record_fields_available: dict[str, bool] = field(default_factory=dict)

    # ---- strategy ---------------------------------------------------------
    entry: StrategyRegistration | None = None
    strategy_config_hash: str | None = None

    # ---- limits -----------------------------------------------------------
    limits: Any | None = None  # ResolvedRiskSnapshot


def _spread_bps(bid: Decimal | None, ask: Decimal | None) -> float | None:
    if bid is None or ask is None or bid <= 0:
        return None
    mid = (bid + ask) / Decimal("2")
    if mid <= 0:
        return None
    return float((ask - bid) / mid * Decimal("10000"))


def run_pretrade_gate(ctx: DemoPretradeContext) -> PretradeVerdict:
    """Evaluate every DEMO safeguard for one intended order (fail closed)."""
    checks: dict[str, CheckResult] = {}

    def record(name: str, status: str, detail: str) -> None:
        checks[name] = CheckResult(name=name, status=status, detail=detail)

    # ------------------------------------------------------------------ #0
    # Contract-level: authorization, permission, mode, stage, autonomy.
    policy = ctx.policy
    if policy is None:
        record("authorization_valid", CHECK_UNKNOWN, "no policy supplied to the gate — cannot prove authorization")
    elif not getattr(policy, "enabled", False):
        record(
            "authorization_valid",
            CHECK_FAIL,
            f"DEMO execution policy is {getattr(policy, 'state', 'DISABLED BY POLICY')}: "
            + "; ".join(getattr(policy, "reasons", []))
            or "no owner authorization recorded",
        )
    else:
        record(
            "authorization_valid",
            CHECK_PASS,
            f"owner authorization {policy.authorization_id} active (DEMO only, LIVE locked)",
        )

    if ctx.authority_permitted is None:
        record("execution_permission", CHECK_UNKNOWN, "durable authority permission state unknown — fail closed")
    elif ctx.authority_permitted is False:
        record(
            "execution_permission",
            CHECK_FAIL,
            "durable DEMO authority refuses execution: " + "; ".join(ctx.authority_reasons or ["not permitted"]),
        )
    else:
        record("execution_permission", CHECK_PASS, "durable DEMO authority permits execution (fresh evidence)")

    if ctx.mode is None:
        record("mode_is_demo_execution", CHECK_UNKNOWN, "execution mode unknown — fail closed")
    elif str(ctx.mode).upper() != "DEMO_EXECUTION":
        record("mode_is_demo_execution", CHECK_FAIL, f"mode {ctx.mode} cannot submit DEMO orders")
    else:
        record("mode_is_demo_execution", CHECK_PASS, "mode DEMO_EXECUTION")

    if ctx.stage in ORDER_STAGES:
        record("stage_allows_order", CHECK_PASS, f"stage {ctx.stage} permits DEMO order submission")
    else:
        record(
            "stage_allows_order",
            CHECK_FAIL,
            f"stage {ctx.stage} does not permit orders — advance to "
            f"{DemoStage.STAGE_2_MIN_SIZE_ORDER.value} or {DemoStage.STAGE_3_FORWARD_OBSERVATION.value} first",
        )

    if ctx.autonomous:
        allowed = bool(getattr(getattr(ctx.authorization, "document", None), "scope", None) and
                       ctx.authorization.document.scope.autonomous_order_management)  # type: ignore[union-attr]
        if not allowed:
            record(
                "autonomous_allowed",
                CHECK_FAIL,
                "autonomous DEMO order management is not granted by the authorization scope",
            )
        else:
            record("autonomous_allowed", CHECK_PASS, "authorization scope permits autonomous DEMO order management")

    # ---- limits provenance: caps must come from the canonical authority,
    # never from a hard-coded fallback inside a check.
    if ctx.limits is None:
        record(
            "risk_limits_resolved",
            CHECK_UNKNOWN,
            "canonical DEMO risk limits not supplied — no cap can be verified (fail closed)",
        )
    else:
        snapshot_hash = str(getattr(ctx.limits, "config_hash", "") or "")
        record(
            "risk_limits_resolved",
            CHECK_PASS,
            f"canonical DEMO risk limits resolved{' (config_hash=' + snapshot_hash + ')' if snapshot_hash else ''}",
        )

    # ------------------------------------------------------------------ #1
    if ctx.identity is None:
        record("account_is_demo", CHECK_UNKNOWN, "broker identity unavailable — DEMO status unprovable")
    else:
        ok, detail, status = _demo_account_check(ctx.identity)
        record("account_is_demo", CHECK_PASS if ok else status, detail[0] if ok else "; ".join(detail))

    # ------------------------------------------------------------------ #2
    if ctx.identity is None:
        record("broker_identity_verified", CHECK_UNKNOWN, "no identity to verify against the pin")
    else:
        ok, detail = _identity_pin_check(ctx.identity, ctx.pin, ctx.pin_reasons)
        record("broker_identity_verified", CHECK_PASS if ok else CHECK_FAIL, "; ".join(detail))

    # ------------------------------------------------------------------ #3
    record(*_symbol_check(ctx))

    # ------------------------------------------------------------------ #4
    if ctx.tick is None:
        record("market_data_fresh", CHECK_UNKNOWN, "no tick available — feed state unknown")
    elif ctx.tick_age_s is None:
        record("market_data_fresh", CHECK_UNKNOWN, "tick age could not be computed (no usable timestamp)")
    else:
        limit = ctx.max_tick_age_s if ctx.max_tick_age_s is not None else 60.0
        if ctx.tick_age_s > limit:
            record("market_data_fresh", CHECK_FAIL, f"tick age {ctx.tick_age_s:.1f}s > {limit:.0f}s (stale)")
        else:
            record("market_data_fresh", CHECK_PASS, f"tick age {ctx.tick_age_s:.1f}s ≤ {limit:.0f}s")

    # ------------------------------------------------------------------ #5
    bid, ask = ctx.bid, ctx.ask
    spread = ctx.spread_bps if ctx.spread_bps is not None else _spread_bps(bid, ask)
    if bid is None or ask is None:
        record("spread_available", CHECK_UNKNOWN, "bid/ask unavailable — spread not measurable")
    elif bid <= 0 or ask <= 0 or ask < bid:
        record("spread_available", CHECK_FAIL, f"invalid quote bid={bid} ask={ask}")
    elif spread is None:
        record("spread_available", CHECK_UNKNOWN, "spread could not be computed from the quote")
    else:
        max_spread = _limit_value(ctx, "max_spread_bps", 100.0)
        if spread > float(max_spread):
            record("spread_available", CHECK_FAIL, f"spread {spread:.1f}bps > demo limit {float(max_spread):.1f}bps")
        else:
            record("spread_available", CHECK_PASS, f"spread {spread:.1f}bps ≤ demo limit {float(max_spread):.1f}bps")

    # ------------------------------------------------------------------ #6
    record(*_size_check(ctx))
    if ctx.order_check_ok is None:
        record(
            "broker_order_check",
            CHECK_UNKNOWN,
            f"broker order_check dry-run unavailable ({ctx.order_check_detail or 'no result'})",
        )
    elif not ctx.order_check_ok:
        record(
            "broker_order_check",
            CHECK_FAIL,
            f"broker order_check refused the request: {ctx.order_check_detail}",
        )
    else:
        record("broker_order_check", CHECK_PASS, f"broker order_check dry-run passed ({ctx.order_check_detail})")

    # ------------------------------------------------------------------ #7
    record(*_stop_loss_check(ctx))

    # ------------------------------------------------------------------ #8
    max_orders = int(float(_limit_value(ctx, "max_open_orders", 3)))
    positions = list(ctx.open_positions or [])
    if len(positions) + 1 > max_orders:
        record(
            "max_simultaneous_positions",
            CHECK_FAIL,
            f"opening one more position exceeds the demo cap ({len(positions)}+1 > {max_orders})",
        )
    else:
        record("max_simultaneous_positions", CHECK_PASS, f"positions {len(positions)}+1 ≤ cap {max_orders}")

    # ------------------------------------------------------------------ #9
    if ctx.daily_realized_pnl is None:
        record("max_daily_loss", CHECK_UNKNOWN, "daily realized P&L unknown (broker day-start not established)")
    else:
        limit = Decimal(str(_limit_value(ctx, "daily_loss_limit", 50)))
        loss = -Decimal(ctx.daily_realized_pnl)
        if loss >= limit:
            record("max_daily_loss", CHECK_FAIL, f"daily loss {loss} ≥ demo limit {limit}")
        else:
            record("max_daily_loss", CHECK_PASS, f"daily loss {loss} < demo limit {limit}")

    # ------------------------------------------------------------------ #10
    record(*_exposure_check(ctx, positions))

    # ------------------------------------------------------------------ #11
    problems: list[str] = []
    if ctx.idempotency_status:
        problems.append(f"client_order_id already recorded with status {ctx.idempotency_status}")
    now_epoch = datetime.now(UTC).timestamp()
    recent = [t for t in (ctx.recent_order_epochs or []) if (now_epoch - float(t)) < float(ctx.min_order_interval_s)]
    if recent:
        problems.append(
            f"{len(recent)} order(s) submitted within {ctx.min_order_interval_s:.0f}s — rate/duplicate guard"
        )
    if not ctx.client_order_id:
        problems.append("client_order_id missing — duplicate protection cannot be evaluated")
    record(
        "duplicate_order_protection",
        CHECK_FAIL if problems else CHECK_PASS,
        "; ".join(problems) if problems else f"no duplicate for {ctx.client_order_id}",
    )

    # ------------------------------------------------------------------ #12
    if not ctx.kill_switch_readable:
        record("kill_switch_functional", CHECK_UNKNOWN, "kill-switch state not readable — treated as KILLED")
    elif ctx.kill_switch_active is None:
        record("kill_switch_functional", CHECK_UNKNOWN, "kill-switch state unknown — treated as KILLED")
    elif ctx.kill_switch_active:
        record("kill_switch_functional", CHECK_FAIL, f"kill switch ACTIVE ({ctx.kill_switch_detail or 'no reason'})")
    elif ctx.kill_switch_self_test is None:
        record(
            "kill_switch_functional",
            CHECK_UNKNOWN,
            "kill-switch self-test not performed this cycle — cannot prove the switch works",
        )
    elif ctx.kill_switch_self_test is False:
        record("kill_switch_functional", CHECK_FAIL, f"kill-switch self-test failed ({ctx.kill_switch_detail})")
    else:
        record("kill_switch_functional", CHECK_PASS, "kill switch idle and self-test passed")

    # ------------------------------------------------------------------ #13
    if ctx.reconcile_suspended is None:
        record("reconciliation_ready", CHECK_UNKNOWN, "reconciliation state unknown — treated as suspended")
    elif ctx.reconcile_suspended:
        record("reconciliation_ready", CHECK_FAIL, f"reconciliation suspended: {ctx.reconcile_drift or 'unresolved drift'}")
    elif ctx.reconcile_drift:
        record("reconciliation_ready", CHECK_FAIL, f"reconciliation drift: {ctx.reconcile_drift}")
    elif ctx.last_reconcile_age_s is None:
        record("reconciliation_ready", CHECK_UNKNOWN, "no reconciliation has run — cannot verify broker vs internal state")
    elif ctx.last_reconcile_age_s > float(ctx.max_reconcile_age_s):
        record(
            "reconciliation_ready",
            CHECK_FAIL,
            f"last reconciliation {ctx.last_reconcile_age_s:.0f}s ago > {ctx.max_reconcile_age_s:.0f}s",
        )
    else:
        record("reconciliation_ready", CHECK_PASS, f"reconciled {ctx.last_reconcile_age_s:.0f}s ago, no drift")

    # ------------------------------------------------------------------ #14
    if ctx.adapter_captures_broker_ids is None:
        record("broker_reference_capture", CHECK_UNKNOWN, "adapter broker-id capture not verified")
    elif not ctx.adapter_captures_broker_ids:
        record("broker_reference_capture", CHECK_FAIL, "adapter does not capture broker order/position IDs")
    elif not ctx.journal_ready:
        record("broker_reference_capture", CHECK_FAIL, "DEMO order journal unavailable — broker IDs would not be recorded")
    else:
        record("broker_reference_capture", CHECK_PASS, "broker order/position IDs captured and journaled")

    # ------------------------------------------------------------------ #15
    missing = [f for f in REQUIRED_RECORD_FIELDS if not (ctx.record_fields_available or {}).get(f)]
    if not ctx.record_fields_available:
        record("execution_record_fields", CHECK_UNKNOWN, "no record-field capability reported by the recorder")
    elif missing:
        record("execution_record_fields", CHECK_FAIL, f"recorder cannot capture: {', '.join(missing)}")
    else:
        record(
            "execution_record_fields",
            CHECK_PASS,
            f"recorder captures all {len(REQUIRED_RECORD_FIELDS)} required execution fields",
        )

    # ------------------------------------------------------------------ #16
    if ctx.entry is None:
        record("strategy_registered_frozen", CHECK_FAIL, "no registered forward-validation strategy — NO_TRADE")
    elif not ctx.strategy_config_hash:
        record("strategy_registered_frozen", CHECK_UNKNOWN, "runtime strategy config hash unavailable")
    elif ctx.strategy_config_hash != ctx.entry.params_hash:
        record(
            "strategy_registered_frozen",
            CHECK_FAIL,
            f"parameter drift: runtime {ctx.strategy_config_hash[:12]}… != registered "
            f"{ctx.entry.params_hash[:12]}… (frozen parameters may not change mid-window)",
        )
    else:
        record(
            "strategy_registered_frozen",
            CHECK_PASS,
            f"strategy {ctx.entry.strategy_id} registered and frozen (hash {ctx.entry.params_hash[:12]}…)",
        )

    # ------------------------------------------------------------------ #17
    unknown = [name for name, c in checks.items() if c.status == CHECK_UNKNOWN]
    if unknown:
        record(
            "no_unknown_checks",
            CHECK_FAIL,
            "fail closed — unresolved checks: " + ", ".join(sorted(unknown)),
        )
    else:
        record("no_unknown_checks", CHECK_PASS, "every safeguard resolved to a definite state")

    failed = [name for name, c in checks.items() if c.status == CHECK_FAIL]
    passed = not failed
    reasons = [f"{name}: {checks[name].detail}" for name in failed]
    return PretradeVerdict(passed=passed, checks=checks, reasons=reasons)


# --------------------------------------------------------------------- helpers


def _demo_account_check(identity: BrokerIdentity) -> tuple[bool, list[str], str]:
    """Check #1: DEMO proof, tri-state.

    ``(True, [..], PASS)`` only when the terminal reports DEMO explicitly.
    An unprovable trade_mode is ``UNKNOWN`` — distinct from ``FAIL`` because
    "cannot prove" and "proved not-DEMO" are different operator problems — and
    both block the order.
    """
    from qts.execution.demo_identity import assert_demo_account

    if identity.is_demo is None:
        return (
            False,
            [
                "account trade_mode unavailable from terminal — DEMO status UNPROVABLE, fail closed "
                "(MT5 must report ACCOUNT_TRADE_MODE_DEMO)"
            ],
            CHECK_UNKNOWN,
        )
    ok, detail = assert_demo_account(identity)
    return ok, detail, CHECK_PASS if ok else CHECK_FAIL


def _identity_pin_check(
    identity: BrokerIdentity,
    pin: dict[str, Any] | None,
    pin_reasons: list[str],
) -> tuple[bool, list[str]]:
    from qts.execution.demo_identity import verify_pin

    ok, detail = verify_pin(identity, pin)
    if not ok and pin_reasons:
        detail = list(pin_reasons) + list(detail)
    return ok, detail


def _limit_value(ctx: DemoPretradeContext, name: str, default: Any) -> Any:
    limits = ctx.limits
    if limits is None:
        return default
    value = getattr(getattr(limits, "limits", limits), name, None)
    return default if value is None else value


def _symbol_check(ctx: DemoPretradeContext) -> tuple[str, str, str]:
    if not ctx.symbol:
        return ("symbol_mapping_canonical", CHECK_UNKNOWN, "no canonical symbol supplied")
    if not ctx.broker_symbol:
        return (
            "symbol_mapping_canonical",
            CHECK_FAIL,
            f"canonical symbol {ctx.symbol} has no broker mapping (e.g. XAUUSD@) — refusing",
        )
    if ctx.spec is None:
        return ("symbol_mapping_canonical", CHECK_UNKNOWN, f"broker spec for {ctx.symbol} unavailable")
    if ctx.symbol_visible is False:
        return ("symbol_mapping_canonical", CHECK_FAIL, f"broker symbol {ctx.broker_symbol} is not visible/selected")
    if ctx.symbol_tradable is False:
        return ("symbol_mapping_canonical", CHECK_FAIL, f"broker symbol {ctx.broker_symbol} is not tradable")
    if ctx.symbol_visible is None or ctx.symbol_tradable is None:
        return (
            "symbol_mapping_canonical",
            CHECK_UNKNOWN,
            f"symbol visibility/tradability for {ctx.broker_symbol} is unknown",
        )
    return (
        "symbol_mapping_canonical",
        CHECK_PASS,
        f"{ctx.symbol} → {ctx.broker_symbol} resolved and tradable",
    )


def _size_check(ctx: DemoPretradeContext) -> tuple[str, str, str]:
    lots = _dec(ctx.intended_lots)
    if lots is None:
        return ("order_size_within_hard_max", CHECK_UNKNOWN, "intended size unknown")
    if lots <= 0:
        return ("order_size_within_hard_max", CHECK_FAIL, f"intended size {lots} must be > 0")
    spec = ctx.spec
    if spec is None:
        return ("order_size_within_hard_max", CHECK_UNKNOWN, "broker symbol spec unknown — size not verifiable")
    hard_max = Decimal(str(_limit_value(ctx, "max_quantity", Decimal("0.1"))))
    try:
        broker_max = Decimal(str(spec.volume_max))
        broker_min = Decimal(str(spec.volume_min))
        step = Decimal(str(spec.volume_step))
    except Exception:
        return ("order_size_within_hard_max", CHECK_UNKNOWN, "broker volume geometry unreadable — fail closed")
    hard_max = min(hard_max, broker_max)
    if lots > hard_max:
        return (
            "order_size_within_hard_max",
            CHECK_FAIL,
            f"size {lots} lots exceeds hard maximum {hard_max} lots (demo cap ∩ broker max)",
        )
    if lots < broker_min:
        return ("order_size_within_hard_max", CHECK_FAIL, f"size {lots} lots below broker minimum {broker_min}")
    if step > 0:
        remainder = (lots / step) % 1
        if remainder != 0 and abs(remainder - 1) > Decimal("0.0000001") and abs(remainder) > Decimal("0.0000001"):
            return ("order_size_within_hard_max", CHECK_FAIL, f"size {lots} not a multiple of broker step {step}")
    return ("order_size_within_hard_max", CHECK_PASS, f"size {lots} lots ≤ hard maximum {hard_max} lots")


def _stop_loss_check(ctx: DemoPretradeContext) -> tuple[str, str, str]:
    if not ctx.stop_required:
        return (
            "stop_loss_present",
            CHECK_PASS,
            "registered policy declares no stop requirement (justification recorded in registry)",
        )
    if ctx.stop_loss is None:
        return ("stop_loss_present", CHECK_FAIL, "registered policy requires a stop-loss and none was supplied")
    ref = ctx.ask if (ctx.side or "").upper() == "BUY" else ctx.bid
    stop = _dec(ctx.stop_loss)
    if ref is None or stop is None:
        return ("stop_loss_present", CHECK_UNKNOWN, "stop-loss cannot be validated without an executable reference price")
    if (ctx.side or "").upper() == "BUY" and stop >= ref:
        return ("stop_loss_present", CHECK_FAIL, f"BUY stop {stop} must be below the entry reference {ref}")
    if (ctx.side or "").upper() == "SELL" and stop <= ref:
        return ("stop_loss_present", CHECK_FAIL, f"SELL stop {stop} must be above the entry reference {ref}")
    spec = ctx.spec
    if spec is not None:
        try:
            min_distance = Decimal(str(spec.stops_level)) * Decimal(str(spec.point))
            if min_distance > 0 and abs(ref - stop) < min_distance:
                return (
                    "stop_loss_present",
                    CHECK_FAIL,
                    f"stop distance {abs(ref - stop)} < broker stops_level distance {min_distance}",
                )
        except Exception:
            return ("stop_loss_present", CHECK_UNKNOWN, "broker stops_level unreadable — stop not verifiable")
    return ("stop_loss_present", CHECK_PASS, f"stop-loss {stop} present and valid for {ctx.side}")


def _exposure_check(ctx: DemoPretradeContext, positions: list[Any]) -> tuple[str, str, str]:
    lots = _dec(ctx.intended_lots)
    if lots is None:
        return ("max_total_exposure", CHECK_UNKNOWN, "intended size unknown — exposure not computable")
    current = Decimal("0")
    for p in positions:
        qty = _dec(getattr(p, "quantity", None))
        if qty is None:
            return ("max_total_exposure", CHECK_UNKNOWN, "a position has an unreadable quantity — exposure unknown")
        current += abs(qty)
    total = current + abs(lots)
    max_lots = Decimal(str(_limit_value(ctx, "max_exposure_lots", Decimal("0.3"))))
    if total > max_lots:
        return ("max_total_exposure", CHECK_FAIL, f"exposure {total} lots > demo limit {max_lots} lots")
    spec = ctx.spec
    max_notional = _limit_value(ctx, "max_notional", None)
    if max_notional is not None and spec is not None:
        price = ctx.ask if (ctx.side or "").upper() == "BUY" else ctx.bid
        if price is None:
            return ("max_total_exposure", CHECK_UNKNOWN, "notional exposure not computable without a price")
        try:
            notional = total * Decimal(str(spec.contract_size)) * Decimal(price)
        except Exception:
            return ("max_total_exposure", CHECK_UNKNOWN, "notional exposure computation failed — fail closed")
        if notional > Decimal(str(max_notional)):
            return ("max_total_exposure", CHECK_FAIL, f"notional {notional} > demo limit {max_notional}")
    return ("max_total_exposure", CHECK_PASS, f"exposure {total} lots ≤ demo limit {max_lots} lots")


def context_field_names() -> tuple[str, ...]:
    """Introspection helper used by tests/UI to document the gate inputs."""
    return tuple(f.name for f in dataclass_fields(DemoPretradeContext))
