"""Controlled DEMO execution session — the one wired path from policy to order.

This module assembles the pieces that already existed (MT5 adapter, execution
engine, risk authority, idempotency, reconciliation, kill switch, readiness
gate) with the new authorization, identity, registry, pre-trade gate, stage
machine and journal. It is the *only* place where a DEMO order request is
turned into a broker order, so every caller (CLI, API, autopilot) inherits the
same safeguards.

Flow for a single order:

1. resolve the owner authorization and the durable authority permission;
2. Stage 1 probes: terminal, DEMO account, pinned broker identity, canonical
   symbol, live quote, order-check dry-run;
3. run the 21-check pre-trade gate (:mod:`qts.execution.demo_pretrade`);
4. on PASS → submit through :class:`~qts.execution.engine.ExecutionEngine`
   (risk veto + idempotency + kill switch + market-data safety still apply),
   then **reconcile immediately** and journal the receipt;
5. on any FAIL/UNKNOWN → record a NO_TRADE signal and refuse. There is no
   "retry with relaxed checks" path anywhere in this module.

Nothing here can reach a LIVE account: the authorization scope forbids it, the
mode gate forbids it, and the identity check refuses any non-DEMO trade_mode.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qts.domain.modes import ExecutionMode
from qts.execution.demo_journal import DemoOrderJournal
from qts.execution.demo_pretrade import (
    CHECK_PASS,
    DEFAULT_MIN_ORDER_INTERVAL_S,
    MUTATION_AUTHORITY_PREDICATES,
    DemoPretradeContext,
    run_pretrade_gate,
)
from qts.execution.demo_refusal import explain_refusal
from qts.execution.order_truth import open_demo_journal
from qts.lifecycle.demo_authorization import resolve_demo_execution_policy
from qts.lifecycle.demo_stage import ORDER_STAGES, DemoStageMachine

DEFAULT_DB_PATH = Path("data/sqlite/qts.db")
SELF_TEST_DB = Path("data/sqlite/demo_killswitch_selftest.db")


def new_client_order_id(prefix: str = "demo") -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:10]}"


@dataclass
class DemoSessionConfig:
    """Operator-supplied connection/selection inputs (no secrets here)."""

    symbol: str = "XAUUSD"
    terminal_path: str | None = None
    symbol_map: dict[str, str] = field(default_factory=dict)
    db_path: Path = DEFAULT_DB_PATH
    actor: str = "cli"
    mt5_module: Any | None = None
    max_tick_age_s: float = 60.0
    max_spread_bps: float = 30.0
    #: Minimum seconds between two orders of the same strategy/symbol/side.
    min_order_interval_s: float = DEFAULT_MIN_ORDER_INTERVAL_S
    #: Canonical execution mode of the REQUESTING process. ``None`` → resolve
    #: from the environment (``QTS_MODE``). The DEMO path is only reachable
    #: when that resolves to ``DEMO_EXECUTION``; a process running in any other
    #: mode (including LIVE) is refused here rather than at the broker.
    mode: str | None = None


@dataclass
class SubmissionResult:
    allowed: bool
    client_order_id: str | None = None
    journal_id: int | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    state: str = "NO_TRADE"
    reasons: list[str] = field(default_factory=list)
    verdict: dict[str, Any] | None = None
    #: Predicate id for a refusal raised OUTSIDE the pre-trade gate. The gate's
    #: own verdict names its failures; these paths must name theirs too, in the
    #: same vocabulary, or the user gets "a safety check refused the order".
    blocked_by: str | None = None
    executed_price: str | None = None
    spread_bps: float | None = None
    slippage_bps: float | None = None
    latency_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "allowed": self.allowed,
            "client_order_id": self.client_order_id,
            "journal_id": self.journal_id,
            "broker_order_id": self.broker_order_id,
            "broker_position_id": self.broker_position_id,
            "state": self.state,
            "reasons": list(self.reasons),
            "verdict": self.verdict,
            "executed_price": self.executed_price,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "latency_ms": self.latency_ms,
        }
        if not self.allowed:
            # Every refusal — from the gate or from any guard around it —
            # leaves with an explanation attached. This is the single
            # chokepoint, so no refusal path can forget to explain itself.
            from qts.execution.demo_refusal import explain_refusal

            payload["refusal"] = explain_refusal(
                verdict=self.verdict,
                reasons=list(self.reasons),
                blocked_by=self.blocked_by,
                state=self.state,
            )
        return payload


class DemoSession:
    """A wired DEMO execution session. Every method fails closed."""

    def __init__(self, config: DemoSessionConfig) -> None:
        from qts.config.paths import artifact_path, resolve_state_path

        self.config = config
        # Anchor the durable store exactly the way RiskEngine does. The session
        # owns the journal, the stage machine and the durable reconciliation
        # row, and it CONSTRUCTS the RiskEngine that owns the durable kill
        # switch — but it used its configured path verbatim while RiskEngine
        # resolved the same value through qts.config.paths. Launched from any
        # directory other than the state root, that split the two halves of the
        # durable suspension set across two SQLite files, and startup health
        # (which reads artifact_path("db")) agreed with neither. A relative
        # ``--db data/sqlite/qts.db`` — the documented operator form — hit the
        # same split. One session, one store, whatever the working directory.
        configured = config.db_path
        if configured is None or Path(configured) == DEFAULT_DB_PATH:
            self.db_path = artifact_path("db")
        else:
            self.db_path = resolve_state_path(configured)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal = open_demo_journal(self.db_path)
        # Recovery: a submission that never recorded an outcome (this process
        # or another died between the broker call and the journal update) is an
        # unknown state, not a completed one. Fail it instead of letting the
        # in-flight guard block every future order.
        with contextlib.suppress(Exception):
            self.journal.expire_inflight_rows()
        self.stage = DemoStageMachine(db_path=self.db_path)
        self._mt5: Any = config.mt5_module
        self._adapter: Any = None
        self._engine: Any = None
        self._risk: Any = None
        self._idempotency: Any = None
        self._market_data: Any = None
        self._last_reconcile_at: datetime | None = None
        self._last_reconcile: Any = None
        self._reconcile_attempted: bool = False
        self._authority: Any = None
        self._authority_mode: Any = None

    # ------------------------------------------------------------- properties
    @property
    def canonical_symbol(self) -> str:
        """The ONE symbol spelling used for policy, journal and portfolio.

        Operators configure either the canonical symbol or the venue alias
        (``XAUUSD@``) in the machine-local setup (``data/setup/mt5_setup.json``,
        override ``QTS_SETUP_FILE``), and the two have been mixed there.
        Everything that compares a symbol — the registered policy, the journal,
        reconciliation — must therefore read this property, never
        ``config.symbol``, or a policy allowing ``XAUUSD`` silently stops
        matching an ``XAUUSD@`` session (the defect seen on the Windows host).
        """
        from qts.adapters.mt5_adapter import canonical_symbol

        return canonical_symbol(self.config.symbol, self.config.symbol_map or {})

    @property
    def broker_symbol(self) -> str:
        """The alias the venue actually trades (``XAUUSD@``)."""
        from qts.adapters.mt5_adapter import broker_symbol

        return broker_symbol(self.config.symbol, self.config.symbol_map or {})

    @property
    def mode(self) -> ExecutionMode:
        """The canonical mode this process is running in (fail closed).

        The DEMO session must never assert a mode: reporting ``DEMO_EXECUTION``
        because a DEMO session exists would let a LIVE-mode process walk the
        DEMO path with a gate that claims the right thing. The mode is either
        explicitly requested (audited call site) or resolved from the
        environment, and anything other than ``DEMO_EXECUTION`` is refused by
        the policy resolver and by the ``mode_is_demo_execution`` gate check.
        """
        if self.config.mode:
            try:
                return ExecutionMode(str(self.config.mode).upper())
            except ValueError:
                return ExecutionMode.DEVELOPMENT  # unresolvable → least capable
        try:
            from qts.domain.modes import resolve_mode

            return resolve_mode()
        except Exception:
            return ExecutionMode.DEVELOPMENT

    @property
    def policy(self):
        return resolve_demo_execution_policy(mode=self.mode.value)

    @property
    def authorization(self):
        return self.policy.authorization

    @property
    def adapter(self) -> Any:
        if self._adapter is None:
            from qts.adapters.mt5_adapter import MT5Adapter

            self._adapter = MT5Adapter(
                config={
                    "path": self.config.terminal_path or "",
                    "symbol_map": dict(self.config.symbol_map or {}),
                    "db_path": str(self.db_path),
                },
                mt5_module=self._mt5,
                db_path=self.db_path,
            )
        return self._adapter

    @property
    def authority(self) -> Any:
        # The mode is resolved per access, not cached: a process whose mode
        # changes (or was resolved differently) must not keep an authority that
        # was built for the previous mode.
        if self._authority is None or self._authority_mode != self.mode:
            from qts.lifecycle.demo_authority import DemoExecutionAuthority
            from qts.observability.audit import SqliteAuditLog

            try:
                audit: Any = SqliteAuditLog()
            except Exception:
                audit = None
            # Bound to the canonical mode: a DEMO_FORWARD process can never
            # hold DEMO_EXECUTION permission, even with a valid authorization.
            self._authority = DemoExecutionAuthority(
                db_path=self.db_path,
                audit=audit,
                mode=self.mode.value,
            )
            self._authority_mode = self.mode
        return self._authority

    # ------------------------------------------------------------ Stage 1
    def connectivity_report(self) -> dict[str, Any]:
        """Stage 1 — prove the environment, take no action.

        Reports: terminal link, DEMO account + broker identity (pinned or not),
        canonical symbol mapping, live quote freshness/spread, account state
        and an order-check dry-run. Never submits anything.
        """
        from qts.lifecycle.demo_gate import demo_forward_readiness_report

        report: dict[str, Any] = {
            "checked_at": datetime.now(UTC).isoformat(),
            "stage": self.stage.current().stage,
            "policy": self.policy.as_dict(),
            "symbol": self.canonical_symbol,
        }

        try:
            readiness = demo_forward_readiness_report(
                mt5_module=self._mt5,
                terminal_path=self.config.terminal_path,
                symbol=self.canonical_symbol,
                symbol_map=dict(self.config.symbol_map or {}) or None,
            )
        except Exception as exc:
            readiness = {"passed": False, "blocked_reasons": [f"readiness probe failed: {exc}"], "checks": {}}
        report["readiness"] = readiness

        report["identity"] = self._identity_probe()
        report["identity_pin"] = self._pin_probe()
        report["symbol_mapping"] = self._symbol_probe()
        report["quote"] = self._quote_probe()
        report["account"] = self._account_probe()
        report["order_check"] = self._order_check_probe()
        report["ready_for_stage_1"] = bool(
            readiness.get("passed")
            and report["identity"].get("is_demo") is True
            and report["symbol_mapping"].get("ok")
            and report["quote"].get("fresh")
        )
        return report

    def _identity_probe(self) -> dict[str, Any]:
        try:
            identity = self.adapter.broker_identity()
        except Exception as exc:
            return {"ok": False, "is_demo": None, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, **identity.as_dict()}

    def _pin_probe(self) -> dict[str, Any]:
        from qts.execution.demo_identity import load_pin, verify_pin

        pin, reasons = load_pin()
        identity = None
        with contextlib.suppress(Exception):
            identity = self.adapter.broker_identity()
        verified: bool | None = None
        detail: list[str] = []
        if identity is not None and pin is not None:
            verified, detail = verify_pin(identity, pin)
        return {
            "pinned": pin is not None,
            "status": (pin or {}).get("status"),
            "fingerprint": (pin or {}).get("fingerprint"),
            "verified": verified,
            "detail": detail or reasons,
            "identity": (pin or {}).get("identity"),
        }

    def _symbol_probe(self) -> dict[str, Any]:
        canonical = self.canonical_symbol
        broker_symbol = self.broker_symbol
        try:
            spec = self.adapter.get_symbol_spec(canonical)
            visible = bool(self.adapter.ensure_symbol_visible(broker_symbol))
            return {
                "ok": True,
                "canonical": canonical,
                "broker_symbol": broker_symbol,
                "visible": visible,
                "tradable": bool(spec.trade_allowed),
                "volume_min": str(spec.volume_min),
                "volume_max": str(spec.volume_max),
                "volume_step": str(spec.volume_step),
                "contract_size": str(spec.contract_size),
                "digits": spec.digits,
                "stops_level": spec.stops_level,
            }
        except Exception as exc:
            return {
                "ok": False,
                "canonical": canonical,
                "broker_symbol": broker_symbol,
                "visible": False,
                "tradable": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _quote_probe(self) -> dict[str, Any]:
        from qts.domain.value_objects import Instrument

        instrument = Instrument(symbol=self.canonical_symbol, venue="MT5")
        try:
            provider = self.market_data
            tick = provider.get_tick(instrument)
        except Exception as exc:
            return {"ok": False, "fresh": False, "error": f"{type(exc).__name__}: {exc}"}
        provenance = getattr(tick, "provenance", None) or {}
        basis = provenance.get("offset_basis")
        if basis == "assumed-utc-fallback":
            # The normalized event_time is unusable while the server-UTC offset is
            # unmeasured. get_tick already certified this tick on the raw stamp via
            # the SAME server-clock contract the readiness gate applies, so the
            # quote is fresh by that contract. The reported age is the RAW
            # server-basis age — the exact quantity that contract bounded
            # ("raw_age > 60s is stale on any clock basis"), so age-cap checks
            # consume a real measured fact, never an invention.
            import time as _time

            raw_msc = provenance.get("mt5_time_msc")
            raw_s = provenance.get("mt5_time")
            raw_epoch = float(raw_msc) / 1000.0 if raw_msc is not None and float(raw_msc) > 1e12 else raw_s
            age = (_time.time() - float(raw_epoch)) if raw_epoch is not None else None
            fresh = age is not None
        else:
            age = self._tick_age(tick)
            fresh = bool(age is not None and age <= self.config.max_tick_age_s)
        spread = self._spread_bps(tick.bid, tick.ask)
        return {
            "ok": True,
            "fresh": fresh,
            "age_s": age,
            "offset_basis": basis,
            "age_basis": "server-local-raw (offset unmeasured)" if basis == "assumed-utc-fallback" else "normalized-utc",
            "bid": str(tick.bid),
            "ask": str(tick.ask),
            "spread_bps": spread,
            "event_time": tick.event_time.isoformat(),
        }

    def _account_probe(self) -> dict[str, Any]:
        try:
            account = self.adapter.account()
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "ok": True,
            "balance": str(account.balance),
            "equity": str(account.equity),
            "free_margin": str(account.free_margin),
            "leverage": None if account.leverage is None else str(account.leverage),
            "currency": account.currency,
            "source": account.source,
        }

    def _order_check_probe(self, lots: Decimal | None = None) -> dict[str, Any]:
        """Dry-run of an order request — proves the plumbing without sending."""
        try:
            from qts.adapters.order_check import mt5_order_check
            from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

            spec = self.adapter.get_symbol_spec(self.canonical_symbol)
            size = lots if lots is not None else Decimal(str(spec.volume_min))
            quote = self._quote_probe()
            if not quote.get("ok"):
                return {"ok": False, "error": quote.get("error", "quote unavailable")}
            price = Decimal(quote["ask"])
            intent = OrderIntent(
                instrument=Instrument(symbol=self.canonical_symbol, venue="MT5"),
                side=Side.BUY,
                quantity=size,
                order_type=OrderType.MARKET,
                client_order_id=new_client_order_id("check"),
                strategy_id="connectivity-probe",
            )
            result = mt5_order_check(self.adapter, intent, market_price=price)
            return {
                "ok": bool(result.ok),
                "retcode": result.retcode,
                "comment": result.comment,
                "probe_size_lots": str(size),
                "reference_price": str(price),
            }
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @property
    def market_data(self) -> Any:
        if self._market_data is None:
            from qts.adapters.market_data import MarketDataProvider

            self._market_data = MarketDataProvider(
                broker=self.adapter,
                max_tick_age_s=self.config.max_tick_age_s,
                max_spread_bps=self.config.max_spread_bps,
            )
        return self._market_data

    def _tick_age(self, tick: Any) -> float | None:
        """Age of a normalized tick (``MT5Adapter.ticks`` maps server stamps
        to true UTC using the measured offset and keeps the raw stamps in
        ``Tick.provenance``).

        A tick stamped in the future is reported as ``inf`` so no caller can
        mistake clock skew for freshness.
        """
        try:
            age = (datetime.now(UTC) - tick.event_time).total_seconds()
        except Exception:
            return None
        if age < 0:
            return float("inf")
        return age

    @staticmethod
    def _spread_bps(bid: Decimal, ask: Decimal) -> float | None:
        if bid is None or ask is None or bid <= 0:
            return None
        mid = (bid + ask) / Decimal("2")
        return float((ask - bid) / mid * Decimal("10000")) if mid > 0 else None

    # ------------------------------------------------------------- controls
    def kill_switch_self_test(self) -> tuple[bool, str]:
        """Prove the durable kill switch works — on a scratch database.

        Raising the production kill flag as a test would halt every other
        process, so the test uses its own SQLite file and leaves the real flag
        untouched.
        """
        try:
            from qts.config.paths import resolve_state_path
            from qts.risk.engine import RiskEngine, RiskLimits

            scratch = resolve_state_path(SELF_TEST_DB)
            scratch.parent.mkdir(parents=True, exist_ok=True)
            engine = RiskEngine(RiskLimits(), db_path=scratch, persist_kill=True)
            if engine.is_killed():
                engine.reset_kill()
            engine.kill_switch("demo pre-trade self-test")
            armed = engine.is_killed()
            engine.reset_kill()
            cleared = not engine.is_killed()
            ok = bool(armed and cleared)
            return ok, ("kill switch armed and cleared on scratch DB" if ok else
                        f"kill switch self-test failed (armed={armed}, cleared={cleared})")
        except Exception as exc:
            return False, f"kill switch self-test error: {type(exc).__name__}: {exc}"

    def kill_switch_state(self) -> dict[str, Any]:
        try:
            from qts.risk.engine import RiskEngine, RiskLimits

            engine = RiskEngine(RiskLimits(), db_path=self.db_path, persist_kill=True)
            return {"readable": True, **engine.kill_state()}
        except Exception as exc:
            return {"readable": False, "killed": None, "reason": f"{type(exc).__name__}: {exc}"}

    def raise_kill_switch(self, reason: str) -> dict[str, Any]:
        """Operator halt: durable kill + stage HALTED."""
        from qts.risk.engine import RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(), db_path=self.db_path, persist_kill=True)
        engine.kill_switch(reason)
        record = self.stage.halt(reason=reason, actor=self.config.actor)
        return {"killed": True, "reason": reason, "stage": record.as_dict()}

    # ------------------------------------------------- durable suspension set
    #: Every DURABLE record that can suspend trading, and the canonical
    #: predicate that alone is allowed to recover it. There is exactly one
    #: authority per record; nothing here introduces a second state machine.
    SUSPENSION_RECORDS: tuple[str, ...] = ("kill_switch", "reconciliation_suspension")

    def durable_suspension_state(self) -> dict[str, Any]:
        """The complete DURABLE suspension set, read from its own authorities.

        Two independent rows can each block trading and they are written by
        different components:

        * ``risk_state.killed`` — :class:`~qts.risk.engine.RiskEngine`, the flag
          ``pre_trade`` enforces and the startup ``restore_suspension`` check
          reports;
        * ``reconcile_state.suspended`` — :class:`~qts.execution.engine.
          ExecutionEngine`, the flag the pre-trade check ``reconciliation_ready``
          enforces.

        Reporting only one of them is what allowed "the stop was cleared" and
        "orders are refused because reconciliation is suspended" to be true at
        the same time. This method is the single read every surface uses, so
        the two can no longer be described separately.

        Unreadable is SUSPENDED (fail closed), never "healthy".
        """
        from qts.execution.engine import load_reconcile_suspension

        kill = self.kill_switch_state()
        kill_readable = bool(kill.get("readable"))
        kill_active = bool(kill.get("killed")) or not kill_readable
        recon = load_reconcile_suspension(self.db_path)

        active: list[dict[str, Any]] = []
        if kill_active:
            active.append(
                {
                    "id": "kill_switch",
                    "detail": (
                        str(kill.get("reason") or "no reason recorded")
                        if kill_readable
                        else f"kill-switch state unreadable — treated as ACTIVE ({kill.get('reason')})"
                    ),
                    "recoverable_by": "operator decision recorded with a reason (resume)",
                }
            )
        if recon.suspended:
            active.append(
                {
                    "id": "reconciliation_suspension",
                    "detail": str(recon.reason or "unresolved drift"),
                    "recoverable_by": "a fresh broker-authoritative reconciliation reporting no drift",
                }
            )
        stage = self.stage.current()
        return {
            "kill_switch": dict(kill),
            "reconciliation": recon.as_dict(),
            "stage": stage.as_dict(),
            "active_blockers": active,
            "active_ids": [b["id"] for b in active],
            "suspended": bool(active),
            "orders_permitted": (not active) and stage.stage in ORDER_STAGES,
        }

    def _emit_recovery_event(self, event_type: Any, payload: dict[str, Any]) -> None:
        """Best-effort audit of a recovery decision. Never erases history."""
        with contextlib.suppress(Exception):
            from qts.observability.audit import SqliteAuditLog

            SqliteAuditLog().emit(event_type(payload))

    # ------------------------------------------------ unresolved executions
    UNRESOLVED_STATES = ("AMBIGUOUS", "NEW", "SUBMITTED")

    def unresolved_executions(self) -> list[dict[str, Any]]:
        """Durable rows whose broker outcome is not known. Read-only."""
        return [r for r in self.journal.list_orders(limit=500) if r.get("state") in self.UNRESOLVED_STATES]

    def resolve_unresolved_executions(self, *, actor: str | None = None) -> dict[str, Any]:
        """Resolve every unresolved execution against BROKER evidence.

        The missing exit from the dead end. An order whose outcome was unknown
        durably suspended trading, and nothing in the product could ever
        resolve it: :meth:`reconcile` compares the in-memory order manager with
        the venue, and after a restart that map is empty, so the unresolved
        order was invisible to the only check that could have cleared it. The
        suspension therefore outlived the condition it described, with no
        evidence-based way back.

        For each unresolved row we ask the broker the only question that
        matters — *did this order execute?* — and accept only a definite
        answer:

        ``EXECUTED``
            a deal, position or live order carries this order's comment. The
            broker's record is adopted onto the journal row. Nothing is
            cleared: real exposure needs an operator, and reconciliation will
            keep the system suspended until local and venue state agree.
        ``NO_EXECUTION``
            the broker link answered, and its positions, orders and deal
            history contain no trace of this order. It provably never
            executed, so the row is closed as REJECTED with the evidence
            recorded.
        ``UNVERIFIABLE``
            the broker could not be asked (disconnected, history unreadable).
            Nothing is decided and nothing is cleared — fail closed.

        Absence of evidence is only accepted as evidence of absence when the
        broker positively answered all three queries; a swallowed error can
        never masquerade as "nothing executed".
        """
        actor = actor or f"{self.config.actor}:resolve"
        unresolved = self.unresolved_executions()
        report: dict[str, Any] = {
            "checked": len(unresolved),
            "resolved": [],
            "executed": [],
            "unverifiable": [],
            "all_resolved": True,
            "detail": "no unresolved executions",
        }
        if not unresolved:
            return report

        from qts.domain.events import DomainEvent, EventType

        # Broker liveness must be PROVEN before absence means anything. These
        # calls raise on a dead link, which is what makes "no trace" evidence.
        try:
            adapter = self.adapter
            venue_positions = list(adapter.positions() or [])
            venue_orders = list(adapter.orders() or [])
            broker_reachable = True
            link_error = ""
        except Exception as exc:
            venue_positions, venue_orders = [], []
            broker_reachable = False
            link_error = f"{type(exc).__name__}: {exc}"

        for row in unresolved:
            cid = str(row.get("client_order_id") or "")
            journal_id = row.get("journal_id")
            entry = {"client_order_id": cid, "journal_id": journal_id, "state": row.get("state")}
            if journal_id is None:
                # An unresolved row with no journal id cannot be marked, so it
                # cannot be reported resolved. Previously `int(None)` threw
                # inside the write's own try/except and was reported as a
                # "journal write failed" — fail closed either way, but naming
                # the wrong cause. Say what is actually wrong.
                report["unverifiable"].append(
                    {**entry, "detail": "journal row carries no journal_id — cannot record an outcome against it"}
                )
                report["all_resolved"] = False
                continue
            if not broker_reachable:
                report["unverifiable"].append(
                    {**entry, "detail": f"broker link unavailable — fail closed ({link_error})"}
                )
                report["all_resolved"] = False
                continue
            try:
                comment = adapter._load_comment_map(cid) or ""
                deals = adapter.history_deals(cid, strict=True)
            except Exception as exc:
                report["unverifiable"].append(
                    {**entry, "detail": f"broker deal history unreadable — fail closed ({type(exc).__name__}: {exc})"}
                )
                report["all_resolved"] = False
                continue

            def _matches(obj: Any, _comment: str = comment, _cid: str = cid) -> bool:
                text = str(getattr(obj, "comment", "") or "")
                return bool(_comment) and text == _comment

            matching_positions = [p for p in venue_positions if _matches(p)]
            matching_orders = [
                o
                for o in venue_orders
                if _matches(o) or str(getattr(o, "client_order_id", "") or "") == cid
            ]
            if deals or matching_positions or matching_orders:
                evidence = {
                    "deals": [str(getattr(d, "ticket", "")) for d in deals],
                    "positions": [str(getattr(p, "ticket", "") or getattr(p, "symbol", "")) for p in matching_positions],
                    "orders": [str(getattr(o, "client_order_id", "") or getattr(o, "order_id", "")) for o in matching_orders],
                }
                adopted_state = "FILLED" if deals or matching_positions else "ACCEPTED"
                try:
                    self.journal.mark_outcome(
                        int(journal_id),
                        state=adopted_state,
                        exit_reason=(
                            "broker evidence: this order DID reach the broker — adopted from "
                            f"deals={evidence['deals']} positions={evidence['positions']} orders={evidence['orders']}"
                        ),
                    )
                except Exception as exc:  # the durable record MUST reflect the finding
                    report["unverifiable"].append(
                        {**entry, "detail": f"broker evidence found but the journal write failed: {exc}"}
                    )
                    report["all_resolved"] = False
                    continue
                self._record_idempotency_status(cid, adopted_state)
                report["executed"].append({**entry, "evidence": evidence})
                report["all_resolved"] = False
                self._emit_recovery_event(
                    lambda payload: DomainEvent(event_type=EventType.RECONCILE, payload=payload),
                    {
                        "action": "unresolved_execution_adopted",
                        "client_order_id": cid,
                        "evidence": evidence,
                        "actor": actor,
                    },
                )
                continue

            detail = (
                "broker evidence: no position, no working order and no deal carries this order's "
                f"comment {comment!r} — it never executed"
            )
            try:
                self.journal.mark_outcome(int(journal_id), state="REJECTED", exit_reason=detail)
            except Exception as exc:
                # Never report an order resolved unless the durable row says so.
                report["unverifiable"].append(
                    {**entry, "detail": f"broker proved no execution but the journal write failed: {exc}"}
                )
                report["all_resolved"] = False
                continue
            self._record_idempotency_status(cid, "REJECTED")
            report["resolved"].append({**entry, "detail": detail})
            self._emit_recovery_event(
                lambda payload: DomainEvent(event_type=EventType.RECONCILE, payload=payload),
                {
                    "action": "unresolved_execution_resolved",
                    "client_order_id": cid,
                    "resolution": "NO_EXECUTION",
                    "detail": detail,
                    "actor": actor,
                },
            )

        parts = []
        if report["resolved"]:
            parts.append(f"{len(report['resolved'])} proven not executed")
        if report["executed"]:
            parts.append(f"{len(report['executed'])} DID execute and were adopted from broker evidence")
        if report["unverifiable"]:
            parts.append(f"{len(report['unverifiable'])} could not be verified")
        report["detail"] = "; ".join(parts) if parts else "no unresolved executions"
        return report

    def _record_idempotency_status(self, client_order_id: str, status: str) -> None:
        """Keep the duplicate guard in step with the journal's resolution.

        The idempotency ledger answers a different question ("has this id been
        used?") but stores the same outcome vocabulary. If a resolution updated
        only the journal the two stores would disagree about whether an order
        is still ambiguous — the split-brain this work exists to remove.
        """
        if not client_order_id:
            return
        with contextlib.suppress(Exception):
            from qts.execution.idempotency import IdempotencyStore

            store = self._idempotency or IdempotencyStore(db_path=self.db_path)
            store.update(client_order_id, status)

    def resume_from_suspension(self, *, reason: str, actor: str | None = None) -> dict[str, Any]:
        """The ONE canonical recovery transition out of a durable suspension.

        ``SUSPENDED`` → ``RECOVERY IN PROGRESS`` → ``RECOVERY VERIFIED`` →
        ``RECOVERED`` (stage still ``HALTED``), or back to ``SUSPENDED`` when a
        recovery predicate is not satisfied.

        Every durable record is recovered through its OWN authority and only
        when its own predicate holds:

        * ``reconciliation_suspension`` → a fresh, broker-authoritative
          :meth:`reconcile` reporting ``requires_suspend=False``, cleared with
          :meth:`~qts.execution.engine.ExecutionEngine.heal_reconcile`;
        * ``kill_switch`` → an explicit operator decision with a recorded
          reason, cleared with :meth:`~qts.risk.engine.RiskEngine.reset_kill`.

        The operation is **all-or-nothing**: if any active record cannot be
        recovered, nothing is cleared and the refusal is recorded. It is
        **idempotent** (already-recovered is a success with ``changed=False``)
        and **verified after the write** (the durable set is re-read, so an
        in-memory "cleared" can never disagree with the store).

        Recovery clears the *active blocking conditions* only. It grants no
        permission: the stage machine stays ``HALTED``, the authority is
        untouched, and every pre-trade gate still runs before any order. The
        original fault stays in the audit log as evidence.
        """
        actor = actor or f"{self.config.actor}:resume"
        reason = str(reason or "").strip()
        from qts.domain.events import DomainEvent, EventType

        def _event(event_type: Any):
            return lambda payload: DomainEvent(event_type=event_type, payload=payload)

        before = self.durable_suspension_state()
        result: dict[str, Any] = {
            "recovered": False,
            "changed": False,
            "reason": reason,
            "actor": actor,
            "before": before,
            "after": before,
            "cleared": [],
            "active_blockers": list(before["active_blockers"]),
            "recovery_checks": {},
            "failed_predicates": [],
            "stage": before["stage"],
            "orders_permitted": False,
            "next": "prepare",
        }
        if not reason:
            result["active_blockers"] = [
                {"id": "invalid_request", "detail": "a recovery decision requires a recorded reason"}
            ]
            result["failed_predicates"] = ["recorded_reason_supplied"]
            return result

        if not before["active_blockers"]:
            # Already recovered — idempotent success, still recorded.
            result.update(recovered=True, changed=False, active_blockers=[])
            result["recovery_checks"]["no_active_suspension"] = {
                "satisfied": True,
                "detail": "no durable suspension record is active",
            }
            result["orders_permitted"] = before["orders_permitted"]
            result["next"] = None if before["orders_permitted"] else "prepare"
            self._emit_recovery_event(
                _event(EventType.KILL_SWITCH),
                {
                    "action": "resume_noop",
                    "recovered": True,
                    "changed": False,
                    "reason": reason,
                    "actor": actor,
                    "stage": before["stage"]["stage"],
                },
            )
            return result

        active_ids = set(before["active_ids"])
        checks: dict[str, Any] = result["recovery_checks"]

        # --- predicate: the kill-switch row must be readable to act on it ----
        if "kill_switch" in active_ids:
            readable = bool(before["kill_switch"].get("readable"))
            checks["kill_switch_state_readable"] = {
                "satisfied": readable,
                "detail": (
                    "durable kill-switch row readable; an explicit operator decision may clear it"
                    if readable
                    else "durable kill-switch row unreadable — cannot clear a state that cannot be read"
                ),
            }

        # --- predicate: no execution is left in an unknown state ------------
        # Resolved against BROKER evidence first, because reconciliation
        # compares state the resolution may correct. Skipped entirely when the
        # journal holds nothing unresolved, so a clean recovery never needs a
        # terminal.
        if "reconciliation_suspension" in active_ids and self.unresolved_executions():
            resolution = self.resolve_unresolved_executions(actor=actor)
            result["unresolved_executions"] = resolution
            checks["unresolved_executions_resolved"] = {
                "satisfied": bool(resolution["all_resolved"]),
                "detail": resolution["detail"],
            }

        # --- predicate: broker-authoritative reconciliation reports no drift -
        fresh_reconcile: dict[str, Any] | None = None
        if "reconciliation_suspension" in active_ids:
            try:
                fresh_reconcile = self.reconcile()
                clean = not bool(fresh_reconcile.get("requires_suspend"))
                detail = (
                    f"fresh reconciliation drift={fresh_reconcile.get('drift')} "
                    f"details={fresh_reconcile.get('details')}"
                )
            except Exception as exc:
                fresh_reconcile = {
                    "drift": "UNAVAILABLE",
                    "details": f"{type(exc).__name__}: {exc}",
                    "requires_suspend": True,
                }
                clean = False
                detail = f"reconciliation could not be run — fail closed ({type(exc).__name__}: {exc})"
            checks["reconciliation_verified_clean"] = {"satisfied": clean, "detail": detail}
            result["reconciliation"] = fresh_reconcile

        unsatisfied = [name for name, c in checks.items() if not c["satisfied"]]
        result["failed_predicates"] = list(unsatisfied)
        if unsatisfied:
            after = self.durable_suspension_state()
            result.update(
                recovered=False,
                changed=False,
                after=after,
                active_blockers=list(after["active_blockers"]),
                stage=after["stage"],
            )
            self._emit_recovery_event(
                _event(EventType.KILL_SWITCH),
                {
                    "action": "resume_refused",
                    "reason": reason,
                    "actor": actor,
                    "unsatisfied_recovery_checks": unsatisfied,
                    "active_blockers": [b["id"] for b in after["active_blockers"]],
                    "evidence": {name: c["detail"] for name, c in checks.items()},
                    "stage": after["stage"]["stage"],
                },
            )
            return result

        # ---------------------------------------------------------- recover
        # Every predicate holds. Clear each active record through its OWN
        # canonical API, recording the ORIGINAL fault reason as evidence.
        if "reconciliation_suspension" in active_ids:
            original = before["reconciliation"].get("reason")
            self.engine.heal_reconcile(
                f"recovery verified via canonical reconciliation: {reason} "
                f"(original suspension: {original or 'unrecorded'})"
            )
            result["cleared"].append("reconciliation_suspension")

        if "kill_switch" in active_ids:
            from qts.risk.engine import RiskEngine, RiskLimits

            original_kill = before["kill_switch"].get("reason")
            RiskEngine(RiskLimits(), db_path=self.db_path, persist_kill=True).reset_kill()
            result["cleared"].append("kill_switch")
            self._emit_recovery_event(
                _event(EventType.KILL_SWITCH),
                {
                    "action": "cleared",
                    "was_killed": True,
                    "reason": reason,
                    "previous_reason": original_kill,
                    "actor": actor,
                    "stage": before["stage"]["stage"],
                },
            )

        # ------------------------------------------------- verify the write
        # Re-read the durable set: an in-memory "cleared" that the store does
        # not agree with must never be reported as recovered.
        after = self.durable_suspension_state()
        recovered = not after["active_blockers"]
        result.update(
            recovered=recovered,
            changed=bool(result["cleared"]),
            after=after,
            active_blockers=list(after["active_blockers"]),
            stage=after["stage"],
            orders_permitted=after["orders_permitted"],
        )
        result["next"] = None if after["orders_permitted"] else "prepare"
        self._emit_recovery_event(
            _event(EventType.RECONCILE if "reconciliation_suspension" in active_ids else EventType.KILL_SWITCH),
            {
                "action": "resume_completed" if recovered else "resume_incomplete",
                "drift": "RECOVERED" if recovered else "STILL_SUSPENDED",
                "recovered": recovered,
                "cleared": list(result["cleared"]),
                "reason": reason,
                "actor": actor,
                "previous_blockers": before["active_ids"],
                "remaining_blockers": [b["id"] for b in after["active_blockers"]],
                "stage": after["stage"]["stage"],
                "orders_permitted": after["orders_permitted"],
            },
        )
        return result

    def positions(self) -> list[dict[str, Any]]:
        """List open broker positions enriched with canonical symbol and journal correlation."""
        try:
            raw_positions = self.adapter.position_details()
        except Exception:
            return []

        open_journal_orders: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            open_journal_orders = list(self.journal.open_orders())

        from qts.adapters.mt5_adapter import canonical_symbol

        out: list[dict[str, Any]] = []
        for pos in raw_positions:
            ticket = pos.get("ticket")
            raw_sym = str(pos.get("symbol") or pos.get("broker_symbol") or "")
            canonical = canonical_symbol(raw_sym, self.config.symbol_map or {})

            matched_row = None
            for row in open_journal_orders:
                if ticket is not None and row.get("broker_position_id") and str(row["broker_position_id"]) == str(ticket):
                    matched_row = row
                    break
                if row.get("broker_symbol") == raw_sym and row.get("side") == pos.get("side"):
                    matched_row = row
                    break

            item = dict(pos)
            item["canonical_symbol"] = canonical
            if matched_row is not None:
                item["journal_id"] = matched_row.get("journal_id")
                item["client_order_id"] = matched_row.get("client_order_id")
                item["strategy_id"] = matched_row.get("strategy_id")
                item["hypothesis_id"] = matched_row.get("hypothesis_id")
            out.append(item)
        return out

    #: Predicates that authorize ANY trading mutation, including a close.
    #:
    #: A close is *risk reducing*, so the entry-quality predicates (spread,
    #: market-data freshness, stop-loss presence, exposure/frequency ceilings,
    #: stage, kill switch) are deliberately NOT applied to it: those controls
    #: exist to stop NEW risk, and letting them block a close would trap an
    #: operator in a live position — the opposite of safety.
    #:
    #: What may never be skipped is *authority*: which account, which broker,
    #: which symbol, and whether this actor is permitted to trade at all.
    #: Closing the wrong ticket on the wrong account is unrecoverable, so these
    #: predicates are enforced on the close path exactly as they are on the
    #: order path, from the same gate and the same registry.
    #: Closes answer to the gate's MUTATION AUTHORITY subset, defined once
    #: beside the gate itself. This used to be a hand-copied tuple here, which
    #: meant a new authority predicate added to the gate would silently not
    #: apply to closes — the duplicate could only ever drift toward permitting
    #: more. See MUTATION_AUTHORITY_PREDICATES for why entry-quality checks are
    #: deliberately excluded from closes.
    CLOSE_AUTHORITY_PREDICATES: tuple[str, ...] = MUTATION_AUTHORITY_PREDICATES

    def authorize_close(self, *, symbol: str | None = None) -> tuple[bool, list[str], list[str]]:
        """Evaluate the mutation-authority subset of the canonical gate.

        Reuses :func:`run_pretrade_gate` rather than re-deriving authority, so
        manual closes, autopilot closes and order submission all answer to one
        execution-policy authority. Returns ``(ok, reasons, blocked_by)``.
        """
        ctx = self.build_context(
            side="SELL",
            lots=Decimal("0"),
            stop_loss=None,
            take_profit=None,
            client_order_id=f"close-authority-{int(time.time() * 1000)}",
            entry=None,
            autonomous=False,
        )
        verdict = run_pretrade_gate(ctx)
        reasons: list[str] = []
        blocked_by: list[str] = []
        for name in self.CLOSE_AUTHORITY_PREDICATES:
            check = verdict.checks.get(name)
            if check is None:
                # Fail closed: an authority predicate the gate did not evaluate
                # is an unproven fact, not a pass.
                blocked_by.append(name)
                reasons.append(f"{name}: not evaluated — cannot prove authority to close")
                continue
            if check.status != CHECK_PASS:
                blocked_by.append(name)
                reasons.append(f"{name}: {check.detail}")
        return (not blocked_by), reasons, blocked_by

    @staticmethod
    def _close_refused(ticket: int, blocked_by: str, message: str) -> dict[str, Any]:
        """One shape for every close refusal: named predicate + explanation."""
        reason = f"close refused: {message}"
        return {
            "success": False,
            "ticket": ticket,
            "error": reason,
            "blocked_by": [blocked_by],
            "refusal": explain_refusal(reasons=[reason], blocked_by=blocked_by, state="CLOSE_REFUSED"),
        }

    def close_position(
        self,
        ticket: int,
        *,
        volume: Decimal | None = None,
        reason: str = "operator-close",
        comment: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Close an open DEMO position by ticket, journal the outcome, and reconcile.

        Fail-closed and broker-authoritative throughout: the broker's position
        list decides whether the ticket exists and how large it is, the broker's
        deal history decides the realized P&L, and any failure to establish
        those facts refuses the close instead of guessing.
        """
        ticket_int = int(ticket)

        # ---------------------------------------------------------- authority
        # Same execution-policy authority as the order path (see
        # CLOSE_AUTHORITY_PREDICATES for why the subset is the subset).
        authorized, auth_reasons, auth_blocked = self.authorize_close()
        if not authorized:
            return {
                "success": False,
                "ticket": ticket_int,
                "error": "close refused: " + "; ".join(auth_reasons),
                "blocked_by": auth_blocked,
                "refusal": explain_refusal(
                    reasons=auth_reasons, blocked_by=auth_blocked[0], state="CLOSE_REFUSED"
                ),
            }

        # ------------------------------------------------- broker-authoritative
        # A broker-state error is NOT an empty position list. Swallowing it used
        # to produce "no matching position" and then submit the close anyway —
        # closing a ticket whose size, symbol and account were unknown.
        try:
            open_positions = self.adapter.position_details()
        except Exception as exc:
            return self._close_refused(
                ticket_int,
                "broker_state_unavailable",
                f"broker position state unavailable ({exc}) — cannot prove the ticket exists or its size",
            )

        matching_pos: dict[str, Any] | None = None
        for p in open_positions:
            if p.get("ticket") == ticket_int:
                matching_pos = p
                break
        if matching_pos is None:
            # Ticket ownership: the broker does not report this position for
            # this account. Never send a close for a ticket we cannot see.
            return self._close_refused(
                ticket_int,
                "ticket_not_owned",
                f"ticket {ticket_int} is not an open position on this account",
            )

        pos_symbol = str(matching_pos.get("symbol") or "")
        try:
            pos_volume = Decimal(str(matching_pos.get("volume") or "0"))
        except (InvalidOperation, ValueError):
            pos_volume = Decimal("0")
        if pos_volume <= 0:
            return self._close_refused(
                ticket_int,
                "ticket_not_owned",
                f"broker reports non-positive volume {pos_volume} for ticket {ticket_int}",
            )

        # ------------------------------------------------ volume conformance
        try:
            requested = pos_volume if volume is None else Decimal(str(volume))
        except (InvalidOperation, ValueError):
            return self._close_refused(ticket_int, "close_volume_invalid", f"close volume {volume!r} is not a number")
        if requested <= 0:
            return self._close_refused(
                ticket_int, "close_volume_invalid", f"close volume {requested} must be greater than zero"
            )
        if requested > pos_volume:
            return self._close_refused(
                ticket_int,
                "close_volume_invalid",
                f"close volume {requested} exceeds the open volume {pos_volume} of ticket {ticket_int}",
            )
        partial = requested < pos_volume
        if partial:
            # A partial close must still be a tradable size at this broker, and
            # must leave a tradable remainder — otherwise the venue rejects it
            # or strands an unclosable residue.
            spec = None
            with contextlib.suppress(Exception):
                spec = self.adapter.get_symbol_spec(pos_symbol)
            if spec is not None:
                remainder = pos_volume - requested
                step = Decimal(str(spec.volume_step or "0"))
                vmin = Decimal(str(spec.volume_min or "0"))
                problems: list[str] = []
                if vmin > 0 and requested < vmin:
                    problems.append(f"close volume {requested} is below the broker minimum {vmin}")
                if vmin > 0 and remainder < vmin:
                    problems.append(
                        f"a partial close of {requested} would strand {remainder}, below the broker minimum {vmin}"
                    )
                if step > 0 and (requested % step) != 0:
                    problems.append(f"close volume {requested} is not a multiple of the broker step {step}")
                if problems:
                    return self._close_refused(ticket_int, "close_volume_invalid", "; ".join(problems))

        close_comment = comment or f"close-{ticket_int}"
        receipt = self.adapter.close_position(
            ticket_int,
            volume=requested,
            comment=close_comment,
        )

        # --------------------------------------------------- journal matching
        # Broker position id ONLY. The old symbol+side fallback could attach the
        # close (and its P&L) to an unrelated order on the same instrument.
        matched_journal_row: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            for row in self.journal.open_orders():
                if row.get("broker_position_id") and str(row["broker_position_id"]) == str(ticket_int):
                    matched_journal_row = row
                    break

        # Fold the closing deal into local state BEFORE reading P&L, so the
        # realized number comes from executed deals rather than the pre-close
        # unrealized snapshot.
        with contextlib.suppress(Exception):
            self.sync_fills()
        realized, pnl_source = self._realized_pnl_for_close(ticket_int, receipt, matching_pos)

        price_current = matching_pos.get("price_current")
        if matched_journal_row is not None:
            executed = receipt.get("executed_volume") if isinstance(receipt, dict) else None
            try:
                closed_volume = Decimal(str(executed)) if executed not in (None, "") else requested
            except (InvalidOperation, ValueError):
                closed_volume = requested
            remaining = pos_volume - closed_volume
            market_state_exit = {
                "price_current": price_current,
                "close_receipt": receipt,
                "closed_by": actor or self.config.actor,
                "closed_volume": str(closed_volume),
                "remaining_volume": str(remaining if remaining > 0 else Decimal("0")),
                "realized_pnl_source": pnl_source,
            }
            if remaining > 0:
                # A partial close leaves real exposure open. Marking the row
                # CLOSED here used to erase that remaining position from the
                # journal while the broker still held it.
                self.journal.mark_outcome(
                    int(matched_journal_row["journal_id"]),
                    state="OPEN",
                    exit_reason=f"partial-close ({reason})",
                    realized_pnl=realized,
                    market_state_exit=market_state_exit,
                )
            else:
                self.journal.mark_outcome(
                    int(matched_journal_row["journal_id"]),
                    state="CLOSED",
                    exit_reason=reason,
                    realized_pnl=realized,
                    market_state_exit=market_state_exit,
                )

        reconciliation = self.reconcile()
        if reconciliation.get("requires_suspend"):
            self.stage.halt(
                reason=(
                    f"reconciliation drift after closing ticket {ticket_int}: "
                    f"{reconciliation.get('drift')} {reconciliation.get('details')}"
                ),
                actor=actor or self.config.actor,
            )

        return {
            "success": True,
            "ticket": ticket_int,
            "receipt": receipt,
            "realized_pnl": str(realized),
            "realized_pnl_source": pnl_source,
            "partial": partial,
            "closed_volume": str(requested),
            "remaining_volume": str(pos_volume - requested),
            "journal_id": matched_journal_row.get("journal_id") if matched_journal_row else None,
            "reconciliation": reconciliation,
        }

    def _realized_pnl_for_close(
        self,
        ticket: int,
        receipt: dict[str, Any] | Any,
        snapshot: dict[str, Any] | None,
    ) -> tuple[Decimal, str]:
        """Realized P&L from broker deal evidence, with an explicit source label.

        The pre-close ``profit`` field is an *unrealized* mark, not a realized
        result: it excludes the closing spread, slippage, commission and swap.
        Reporting it as realized P&L overstates or understates every closed
        trade. Deal history is authoritative; the snapshot is only ever a
        labelled fallback so the caller can tell the difference.
        """
        deal_id = ""
        if isinstance(receipt, dict):
            deal_id = str(receipt.get("broker_position_id") or "")
        try:
            deals = self.adapter.history_deals(days=1)
        except Exception:
            deals = []
        total = Decimal("0")
        matched = False
        for d in deals or []:
            d_ticket = getattr(d, "position_id", None)
            d_id = str(getattr(d, "ticket", "") or "")
            if (d_ticket is not None and int(d_ticket or 0) == int(ticket)) or (deal_id and d_id == deal_id):
                for field in ("profit", "commission", "swap", "fee"):
                    raw = getattr(d, field, None)
                    if raw in (None, ""):
                        continue
                    with contextlib.suppress(InvalidOperation, ValueError):
                        total += Decimal(str(raw))
                matched = True
        if matched:
            return total, "broker_deal_history"
        if snapshot is not None and snapshot.get("profit") not in (None, ""):
            with contextlib.suppress(InvalidOperation, ValueError):
                return Decimal(str(snapshot["profit"])), "pre_close_snapshot_unverified"
        return Decimal("0"), "unavailable"

    def sync_fills(self) -> int:
        """Fold broker deals into local state (best effort, idempotent).

        An MT5 fill is a *deal*: the portfolio only learns about it when the
        deals are polled. Closing a position through :meth:`MT5Adapter.
        close_position` therefore leaves local state stale until this runs.
        """
        try:
            return len(self.engine.poll_live_fills() or [])
        except Exception:
            return 0

    def reconcile(self) -> dict[str, Any]:
        engine = self.engine
        # Cold-start recovery: a fresh process has an empty in-memory portfolio,
        # so a legitimate broker position would look like drift
        # (UNKNOWN_POSITION) and block everything. Rebuild local state from the
        # broker's deal history FIRST, then compare like with like.
        try:
            if not engine.portfolio.positions and list(engine.broker.positions() or []):
                self.sync_fills()
        except Exception:
            pass
        report = engine.reconcile()
        self._last_reconcile = report
        self._last_reconcile_at = datetime.now(UTC)
        return {
            "drift": str(getattr(report, "drift", "")),
            "details": str(getattr(report, "details", "")),
            "requires_suspend": bool(getattr(report, "requires_suspend", False)),
            "suspended": bool(getattr(engine, "is_suspended", False)),
            "at": self._last_reconcile_at.isoformat(),
        }

    @property
    def engine(self) -> Any:
        """The wired execution engine (risk + idempotency + reconcile)."""
        if self._engine is not None:
            return self._engine
        from qts.adapters.matching import MatchingEngine
        from qts.execution.engine import ExecutionEngine, OrderManager
        from qts.execution.idempotency import IdempotencyStore
        from qts.observability.audit import SqliteAuditLog
        from qts.portfolio.portfolio import Portfolio
        from qts.risk.engine import RiskEngine, RiskLimits

        try:
            audit: Any = SqliteAuditLog()
        except Exception:
            audit = None
        self._idempotency = IdempotencyStore(db_path=self.db_path)
        from qts.risk.authority import resolve_risk_limits

        snapshot = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
        limits = RiskLimits(
            max_quantity=snapshot.limits.max_quantity,
            min_quantity=snapshot.limits.min_quantity,
            quantity_step=snapshot.limits.quantity_step,
            max_notional=snapshot.limits.max_notional,
            max_exposure_lots=snapshot.limits.max_exposure_lots,
            max_leverage=snapshot.limits.max_leverage,
            max_correlated_exposure=snapshot.limits.max_correlated_exposure,
            max_open_orders=snapshot.limits.max_open_orders,
            daily_loss_limit=snapshot.limits.daily_loss_limit,
            max_drawdown=snapshot.limits.max_drawdown,
            kill_switch_enabled=True,
            stop_loss_required=bool(snapshot.limits.stop_loss_required),
        )
        self._risk = RiskEngine(limits, db_path=self.db_path, persist_kill=True)
        portfolio = Portfolio(initial_balance=Decimal("0"))  # broker equity is authoritative
        self._engine = ExecutionEngine(
            OrderManager(audit=audit, idempotency=self._idempotency),
            self._risk,
            self.adapter,
            MatchingEngine(),
            portfolio,
            audit=audit,
            db_path=self.db_path,
            market_data=self.market_data,
        )
        return self._engine

    # -------------------------------------------------------------- gateway
    def build_context(
        self,
        *,
        side: str,
        lots: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        client_order_id: str | None = None,
        entry: Any | None = None,
        autonomous: bool = False,
    ) -> DemoPretradeContext:
        """Probe every live fact the gate needs. Missing fact ⇒ UNKNOWN."""
        from qts.execution.demo_identity import load_pin
        from qts.lifecycle.demo_registry import load_registry, resolve_entry
        from qts.risk.authority import resolve_risk_limits

        policy = self.policy
        permitted, authority_reasons = self.authority.is_execution_permitted()

        identity = None
        with contextlib.suppress(Exception):
            identity = self.adapter.broker_identity()
        pin, pin_reasons = load_pin()

        symbol_probe = self._symbol_probe()
        quote = self._quote_probe()
        bid = Decimal(quote["bid"]) if quote.get("bid") else None
        ask = Decimal(quote["ask"]) if quote.get("ask") else None

        account = None
        with contextlib.suppress(Exception):
            account = self.adapter.account()
        positions: list[Any] = []
        open_orders: list[Any] = []
        with contextlib.suppress(Exception):
            positions = list(self.adapter.positions())
        with contextlib.suppress(Exception):
            open_orders = list(self.adapter.orders())

        kill_state = self.kill_switch_state()
        kill_active = kill_state.get("killed") if kill_state.get("readable") else None
        self_test_ok, self_test_detail = self.kill_switch_self_test()

        # Reconciliation must have run at least once before an order: an
        # unreconciled internal state is not a known state (fail closed). The
        # probe is read-only (positions/orders vs internal) and is attempted at
        # most once per session so a broken link cannot spin.
        if self._last_reconcile is None and not self._reconcile_attempted:
            self._reconcile_attempted = True
            with contextlib.suppress(Exception):
                self.reconcile()

        reconcile_suspended: bool | None = None
        reconcile_drift: str | None = None
        try:
            engine = self.engine
            reconcile_suspended = bool(getattr(engine, "is_suspended", False))
        except Exception:
            reconcile_suspended = None
        age: float | None = None
        if self._last_reconcile_at is not None:
            age = (datetime.now(UTC) - self._last_reconcile_at).total_seconds()
        elif self._last_reconcile is None:
            age = None
        if self._last_reconcile is not None:
            drift = str(getattr(self._last_reconcile, "drift", "") or "")
            reconcile_drift = drift if drift and drift.upper() not in ("OK", "NONE", "") else None

        registry = load_registry()
        entry, _entry_reasons = resolve_entry(registry, entry.strategy_id if entry else None)

        # Cumulative P&L curve for the policy's drawdown limit. Best effort:
        # an unreadable journal leaves the drawdown UNKNOWN, and UNKNOWN fails
        # the gate — it never reads as "no drawdown".
        try:
            drawdown = self.journal.drawdown()
        except Exception:
            drawdown = {"peak": None, "current": None, "drawdown": None}

        # Caps are always the canonical DEMO_EXECUTION limits: even a
        # process that will be refused for its mode is evaluated against the
        # strictest applicable boundary, never a looser one.
        limits = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)

        order_check_ok: bool | None = None
        order_check_detail = ""
        try:
            probe = self._order_check_probe(lots=Decimal(str(lots)))
            order_check_ok = bool(probe.get("ok"))
            order_check_detail = str(probe.get("comment") or probe.get("error") or "")
        except Exception as exc:
            order_check_ok = None
            order_check_detail = f"{type(exc).__name__}: {exc}"

        return DemoPretradeContext(
            policy=policy,
            authorization=policy.authorization,
            authority_permitted=permitted,
            authority_reasons=list(authority_reasons or []),
            mode=self.mode.value,
            stage=self.stage.current().stage,
            identity=identity,
            pin=pin,
            pin_reasons=list(pin_reasons),
            symbol=self.canonical_symbol,
            broker_symbol=(symbol_probe.get("broker_symbol") or self.broker_symbol),
            symbol_map=dict(self.config.symbol_map or {}),
            symbol_visible=symbol_probe.get("visible"),
            symbol_tradable=symbol_probe.get("tradable"),
            spec=(self.adapter.get_symbol_spec(self.canonical_symbol) if symbol_probe.get("ok") else None),
            order_check_ok=order_check_ok,
            order_check_detail=order_check_detail,
            tick=quote,
            tick_age_s=quote.get("age_s"),
            max_tick_age_s=self.config.max_tick_age_s,
            bid=bid,
            ask=ask,
            spread_bps=quote.get("spread_bps"),
            account=account,
            open_positions=positions,
            open_orders=open_orders,
            daily_realized_pnl=self.journal.daily_realized_pnl(),
            side=side,
            intended_lots=Decimal(str(lots)),
            stop_loss=stop_loss,
            take_profit=take_profit,
            # A required stop is a property of the registered policy: the
            # frozen experiment spec decides, not a per-call default.
            stop_required=(
                bool(entry.policy.stop_required())
                if (entry is not None and entry.policy is not None)
                else bool((entry.stop_policy or {}).get("required", True))
                if entry
                else True
            ),
            client_order_id=client_order_id,
            idempotency_status=(
                self._idempotency.get_status(client_order_id)
                if (client_order_id and self._idempotency is not None)
                else None
            ),
            recent_order_epochs=self.journal.recent_order_epochs(60.0),
            min_order_interval_s=self.config.min_order_interval_s,
            autonomous=autonomous,
            kill_switch_active=kill_active,
            kill_switch_readable=bool(kill_state.get("readable")),
            kill_switch_self_test=self_test_ok,
            kill_switch_detail=self_test_detail,
            reconcile_suspended=reconcile_suspended,
            reconcile_drift=reconcile_drift,
            last_reconcile_age_s=age,
            adapter_captures_broker_ids=(
                self.adapter.broker_references_available() if hasattr(self.adapter, "broker_references_available") else None
            ),
            journal_ready=True,
            record_fields_available=DemoOrderJournal.record_fields_available(),
            entry=entry,
            strategy_config_hash=(entry.params_hash if entry else None),
            research_policy=(entry.policy if entry is not None else None),
            registered_broker_symbol=(
                str(entry.raw.get("broker_symbol") or "") if entry is not None and entry.raw.get("broker_symbol") else None
            ),
            pin_symbol=((pin or {}).get("symbol") if isinstance(pin, dict) else None),
            orders_today=self.journal.orders_today(),
            cumulative_pnl=drawdown.get("current"),
            peak_cumulative_pnl=drawdown.get("peak"),
            now=datetime.now(UTC),
            limits=limits,
        )

    def resolve_order_parameters(
        self,
        *,
        side: str,
        lots: Decimal | None = None,
        stop_loss: Decimal | None = None,
        entry: Any | None = None,
    ) -> dict[str, Any]:
        """Size and protective stop for one order, derived deterministically.

        A registered policy that requires a stop must never depend on the
        caller remembering to pass one: the stop is derived from the frozen
        policy (``stop_loss_logic.distance_price``) against the executable side
        of the quote, and rounded AWAY from the entry so the derived distance is
        never smaller than the registered one. An operator-supplied stop is
        used as given and then validated by the gate like any other.
        """
        if entry is None:
            # Same resolution the gate performs: whatever is registered and
            # eligible, so a caller that omits the entry still gets the
            # registered policy's stop rather than an unprotected order.
            from qts.lifecycle.demo_registry import load_registry, resolve_entry

            entry, _reasons = resolve_entry(load_registry())
        size = self._resolve_size(lots, entry)
        quote = self._quote_probe()
        bid = Decimal(str(quote["bid"])) if quote.get("bid") else None
        ask = Decimal(str(quote["ask"])) if quote.get("ask") else None
        reference = ask if side.upper() == "BUY" else bid

        derived = False
        stop = stop_loss
        policy = getattr(entry, "policy", None)
        if stop is None and policy is not None and policy.stop_required():
            distance = policy.stop_distance_price()
            if distance is not None and reference is not None:
                offset = Decimal(str(distance))
                raw = (reference - offset) if side.upper() == "BUY" else (reference + offset)
                stop = self._round_stop(side, raw)
                derived = stop is not None
        return {
            "lots": size,
            "stop_loss": stop,
            "take_profit": None,
            "reference_price": reference,
            "bid": bid,
            "ask": ask,
            "quote": quote,
            "stop_derived_from_policy": derived,
        }

    def _round_stop(self, side: str, price: Decimal) -> Decimal:
        """Snap a price to the symbol's tick size, away from the entry.

        Rounding a protective stop towards the entry would silently shrink the
        registered protection (and can breach the broker's minimum stop
        distance), so a BUY stop rounds DOWN and a SELL stop rounds UP.
        """
        from decimal import ROUND_CEILING, ROUND_FLOOR

        try:
            spec = self.adapter.get_symbol_spec(self.canonical_symbol)
            tick = Decimal(str(spec.tick_size))
            digits = int(spec.digits)
        except Exception:
            return price
        if tick is None or tick <= 0:
            return price.quantize(Decimal(1).scaleb(-max(digits, 0)))
        rounding = ROUND_FLOOR if side.upper() == "BUY" else ROUND_CEILING
        steps = (price / tick).quantize(Decimal("1"), rounding=rounding)
        return (steps * tick).quantize(Decimal(1).scaleb(-max(digits, 0)))

    def preflight(
        self,
        *,
        side: str = "BUY",
        lots: Decimal | None = None,
        stop_loss: Decimal | None = None,
        entry: Any | None = None,
        autonomous: bool = False,
    ) -> dict[str, Any]:
        """Evaluate the full gate for a would-be order — submits nothing."""
        params = self.resolve_order_parameters(side=side, lots=lots, stop_loss=stop_loss, entry=entry)
        size = params["lots"]
        stop = params["stop_loss"]
        ctx = self.build_context(
            side=side,
            lots=size,
            stop_loss=stop,
            client_order_id=new_client_order_id("preflight"),
            entry=entry,
            autonomous=autonomous,
        )
        verdict = run_pretrade_gate(ctx)
        verdict_dict = verdict.as_dict()
        preflight: dict[str, Any] = {
            "verdict": verdict_dict,
            "allowed": bool(verdict.passed),
            "intended_order": {
                "symbol": self.canonical_symbol,
                "broker_symbol": ctx.broker_symbol,
                "side": side,
                "lots": str(size),
                "stop_loss": None if stop is None else str(stop),
                "stop_derived_from_policy": params["stop_derived_from_policy"],
                "reference_price": None if params["reference_price"] is None else str(params["reference_price"]),
            },
            "order_check": self._order_check_probe(lots=size),
            "stage": self.stage.current().as_dict(),
        }
        if not verdict.passed:
            # The dry run explains itself exactly like a real refusal, so the
            # preview and the order tell the operator the same thing.
            from qts.execution.demo_refusal import explain_refusal

            preflight["refusal"] = explain_refusal(
                verdict=verdict_dict, reasons=list(verdict.reasons), state="NO_TRADE"
            )
        return preflight

    def reverify_authority(
        self,
        *,
        confirmed: bool,
        risk_ack: bool,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Re-prove readiness and refresh permission at the CURRENT stage.

        Permission decays after ``REVERIFY_TTL_S`` by design: it must be proven
        against the live terminal, never inherited from an old pass. Refreshing
        it is therefore a normal part of a long session — and it is *not* a
        stage transition, so it must never require an illegal
        ``STAGE_2 → STAGE_2`` move. Every gate of a first enablement applies
        here (fresh readiness, explicit confirmation, risk acknowledgement,
        DEMO scope, broker-capable mode); only the recorded reason differs.
        """
        from qts.lifecycle.demo_authority import readiness_age_seconds
        from qts.lifecycle.demo_gate import demo_forward_readiness_report

        rpt = demo_forward_readiness_report(
            # The session's terminal when one is injected (tests, embedded
            # runs); otherwise the gate resolves the installed terminal from
            # ``terminal_path`` — the same probe ``arm`` has always used.
            mt5_module=self.config.mt5_module,
            terminal_path=self.config.terminal_path,
            symbol=self.canonical_symbol,
            symbol_map=dict(self.config.symbol_map or {}) or None,
        )
        decision = self.authority.refresh(
            readiness=rpt,
            confirmed=confirmed,
            risk_ack=risk_ack,
            readiness_age_s=readiness_age_seconds(rpt),
            actor=actor or f"{self.config.actor}:reverify",
        )
        stage = self.stage.current()
        return {
            "authority": decision.as_dict(),
            "stage": stage.as_dict(),
            "reverified": bool(decision.execution_permitted),
            "readiness": {
                "passed": bool(rpt.get("passed")),
                "blocked_reasons": list(rpt.get("blocked_reasons") or []),
            },
            "mode": self.mode.value,
            "symbol": {"canonical": self.canonical_symbol, "broker": self.broker_symbol},
        }

    def _enforce_policy_kill_conditions(self, verdict: Any, entry: Any | None) -> tuple[str, ...]:
        """Raise the kill switch when the failed checks are policy kill conditions.

        Returns the conditions that fired (empty tuple when the refusal was a
        routine limit, e.g. a wide spread). Raising here rather than only in the
        autopilot means a refusal is a *state change* the operator must clear
        with ``qts demo clear-kill``, so the loop cannot quietly retry past a
        broken control.
        """
        policy = getattr(entry, "policy", None)
        if policy is None:
            return ()
        failed = list(getattr(verdict, "failed", ()) or ()) + list(getattr(verdict, "unknown", ()) or ())
        triggered = policy.must_kill_on(failed)
        if not triggered:
            return ()
        reason = (
            f"policy {policy.policy_id} kill condition(s) triggered: {', '.join(triggered)} "
            f"(failed checks: {', '.join(str(f) for f in failed) or 'none'})"
        )
        with contextlib.suppress(Exception):
            self.raise_kill_switch(reason)
        with contextlib.suppress(Exception):
            self.stage.halt(reason=reason, actor=self.config.actor)
        return triggered

    def _resolve_size(self, lots: Decimal | None, entry: Any | None) -> Decimal:
        if lots is not None:
            return Decimal(str(lots))
        policy = (entry.size_policy or {}) if entry else {}
        mode = str(policy.get("mode") or "broker_minimum").lower()
        try:
            spec = self.adapter.get_symbol_spec(self.canonical_symbol)
            broker_min = Decimal(str(spec.volume_min))
        except Exception:
            broker_min = Decimal("0.01")
        if mode in ("broker_minimum", "minimum", "min"):
            return broker_min
        fixed = policy.get("lots")
        return Decimal(str(fixed)) if fixed else broker_min

    def submit(
        self,
        *,
        side: str,
        lots: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        rationale: str = "",
        entry: Any | None = None,
        signal_id: str | None = None,
        autonomous: bool = False,
    ) -> SubmissionResult:
        """Gate → submit → reconcile → journal. Refuses on any failed check."""
        from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

        if entry is None:
            # Policy enforcement must not depend on the caller passing the
            # entry: the kill conditions and the journal's strategy identity
            # come from the REGISTERED entry, so resolve it here exactly as the
            # gate does. A caller that omitted it used to bypass the policy's
            # kill conditions entirely.
            from qts.lifecycle.demo_registry import load_registry, resolve_entry

            entry, _entry_reasons = resolve_entry(load_registry())

        params = self.resolve_order_parameters(side=side, lots=lots, stop_loss=stop_loss, entry=entry)
        size = params["lots"]
        if stop_loss is None and params["stop_loss"] is not None:
            # Derived from the registered policy — recorded with the order so
            # the audit trail shows what was sent and why that price.
            stop_loss = params["stop_loss"]
        client_order_id = new_client_order_id("demo")
        strategy_id = entry.strategy_id if entry else "unregistered"
        config_hash = entry.params_hash if entry else ""

        ctx = self.build_context(
            side=side,
            lots=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            client_order_id=client_order_id,
            entry=entry,
            autonomous=autonomous,
        )
        verdict = run_pretrade_gate(ctx)
        if not verdict.passed:
            # A policy's kill conditions are a control, not a comment: when the
            # gate fails on one of them the system must stop, not merely decline
            # this order and try again on the next cycle.
            triggered = self._enforce_policy_kill_conditions(verdict, entry)
            self.journal.record_signal(
                strategy_id=strategy_id,
                strategy_config_hash=config_hash,
                symbol=self.canonical_symbol,
                decision="NO_TRADE",
                side=side,
                signal_id=signal_id,
                rationale=rationale,
                reason="; ".join(verdict.reasons),
                authorization_id=(self.authorization.authorization_id if self.authorization else None),
            )
            reasons = list(verdict.reasons)
            if triggered:
                reasons.append(
                    "kill switch RAISED by policy kill condition(s): " + ", ".join(triggered)
                )
            return SubmissionResult(
                allowed=False,
                client_order_id=client_order_id,
                state="NO_TRADE",
                reasons=reasons,
                verdict=verdict.as_dict(),
            )

        # Stage guard (defence in depth — the gate already checked it).
        if self.stage.current().stage not in ORDER_STAGES:
            return SubmissionResult(
                allowed=False,
                client_order_id=client_order_id,
                state="NO_TRADE",
                reasons=[f"stage {self.stage.current().stage} does not permit orders"],
                blocked_by="stage_allows_order",
                verdict=verdict.as_dict(),
            )

        requested_at = datetime.now(UTC)
        quote = self._quote_probe()
        requested_price = Decimal(quote["ask"] if side.upper() == "BUY" else quote["bid"]) if quote.get("ok") else None
        intent = OrderIntent(
            instrument=Instrument(symbol=self.canonical_symbol, venue="MT5"),
            side=Side.BUY if side.upper() == "BUY" else Side.SELL,
            quantity=size,
            order_type=OrderType.MARKET,
            client_order_id=client_order_id,
            strategy_id=strategy_id,
            signal_id=signal_id,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        try:
            order_request = self.adapter.build_broker_request(intent)
        except Exception as exc:
            order_request = {"error": f"{type(exc).__name__}: {exc}"}

        # Reserve the slot ATOMICALLY (check + insert in one transaction):
        # the gate's duplicate/rate check and this insert are otherwise a
        # check-then-act pair that two callers — an operator CLI command during
        # an autopilot cycle, or two processes — could both pass.
        journal_id, claim_reason = self.journal.claim_order_slot(
            client_order_id=client_order_id,
            strategy_id=strategy_id,
            strategy_config_hash=config_hash,
            hypothesis_id=(entry.hypothesis_id if entry else None),
            registry_entry_hash=(entry.params_hash if entry else None),
            symbol=self.canonical_symbol,
            broker_symbol=ctx.broker_symbol,
            side=side,
            requested_lots=size,
            requested_price=requested_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_request=order_request,
            signal_snapshot={"rationale": rationale, "signal_id": signal_id},
            signal_at=requested_at.isoformat(),
            market_state_entry=quote,
            authorization_id=(self.authorization.authorization_id if self.authorization else None),
            notes="RESEARCH_DEMO_ORDER — DEMO account, no real capital",
            min_interval_s=self.config.min_order_interval_s,
        )
        if journal_id is None:
            self.journal.record_signal(
                strategy_id=strategy_id,
                strategy_config_hash=config_hash,
                symbol=self.canonical_symbol,
                decision="NO_TRADE",
                side=side,
                signal_id=signal_id,
                rationale=rationale,
                reason=claim_reason,
                authorization_id=(self.authorization.authorization_id if self.authorization else None),
            )
            return SubmissionResult(
                allowed=False,
                client_order_id=client_order_id,
                state="NO_TRADE",
                reasons=[claim_reason],
                blocked_by="duplicate_order_protection",
                verdict=verdict.as_dict(),
            )

        # Defence in depth: a policy that requires a protective stop must never
        # reach the broker without one, whatever the caller passed or omitted.
        policy = getattr(entry, "policy", None)
        if policy is not None and policy.stop_required() and intent.stop_loss is None:
            self.journal.mark_outcome(journal_id, state="REJECTED", exit_reason="required stop-loss missing")
            return SubmissionResult(
                allowed=False,
                client_order_id=client_order_id,
                journal_id=journal_id,
                state="NO_TRADE",
                reasons=["registered policy requires a stop-loss and none could be derived — refused"],
                blocked_by="stop_loss_required",
                verdict=verdict.as_dict(),
            )

        try:
            order, _fills = self.engine.submit_intent(intent, tick=None)
        except Exception as exc:
            self.journal.mark_outcome(journal_id, state="REJECTED", exit_reason=f"submit error: {exc}")
            self.reconcile()
            return SubmissionResult(
                allowed=False,
                client_order_id=client_order_id,
                journal_id=journal_id,
                state="REJECTED",
                reasons=[f"submission error: {type(exc).__name__}: {exc}"],
                blocked_by="submission_error",
                verdict=verdict.as_dict(),
            )

        receipt = getattr(self.adapter, "last_submission", None) or {}
        submitted_at = datetime.now(UTC)
        latency_ms = (submitted_at - requested_at).total_seconds() * 1000.0
        broker_order_id = str(receipt.get("broker_order_id") or (getattr(order, "exchange_order_id", None) or "") or "")
        broker_position_id = str(receipt.get("broker_position_id") or "")

        if order is None:
            # The engine refused or lost the intent; its own reason (broker
            # retcode, ambiguous transport, risk veto) is far more useful than a
            # generic "veto", and safeguard #15 asks for the broker response.
            refusal = _engine_refusal_detail(self.engine, client_order_id)
            self.journal.mark_outcome(
                journal_id,
                state="REJECTED",
                exit_reason=refusal["reason"] or "; ".join(verdict.reasons) or "risk/engine veto (see audit log)",
                broker_retcode=refusal["retcode"],
            )
            self.reconcile()
            return SubmissionResult(
                allowed=False,
                client_order_id=client_order_id,
                journal_id=journal_id,
                state="NO_TRADE",
                reasons=["execution engine refused the intent — see audit log (risk veto / kill / suspend)"],
                blocked_by="execution_engine_refused",
                verdict=verdict.as_dict(),
            )

        executed_price = receipt.get("executed_price") or ""
        self.journal.mark_submitted(
            journal_id,
            submitted_at=submitted_at.isoformat(),
            broker_order_id=broker_order_id or None,
            broker_position_id=broker_position_id or None,
            broker_retcode=str(receipt.get("retcode") or ""),
            latency_ms=latency_ms,
        )
        if executed_price:
            self.journal.mark_fill(
                journal_id,
                filled_lots=Decimal(str(receipt.get("executed_volume") or size)),
                executed_price=Decimal(str(executed_price)),
                requested_price=requested_price,
                spread_bps=quote.get("spread_bps"),
                market_state_entry=quote,
                broker_position_id=broker_position_id or None,
            )

        # Bring local state up to date with the broker BEFORE reconciling: an
        # MT5 fill is a deal, and the portfolio only learns about it when the
        # deals are polled. Reconciling first would compare a stale empty
        # portfolio against a real venue position and suspend on phantom drift.
        with contextlib.suppress(Exception):
            self.engine.poll_live_fills()

        # Reconciliation after EVERY submitted order (safeguard #13).
        reconciliation = self.reconcile()
        self.journal.mark_reconciled(
            journal_id,
            ok=not reconciliation["requires_suspend"],
            note=f"{reconciliation['drift']} {reconciliation['details']}".strip()[:200],
        )
        if reconciliation["requires_suspend"]:
            self.stage.halt(reason=f"reconciliation drift after {client_order_id}", actor=self.config.actor)

        row = self.journal.get(journal_id) or {}
        return SubmissionResult(
            allowed=True,
            client_order_id=client_order_id,
            journal_id=journal_id,
            broker_order_id=broker_order_id or None,
            broker_position_id=broker_position_id or None,
            state=str(order.state.value if hasattr(order.state, "value") else order.state),
            reasons=[],
            verdict=verdict.as_dict(),
            executed_price=executed_price or None,
            spread_bps=quote.get("spread_bps"),
            slippage_bps=(float(row["slippage_bps"]) if row.get("slippage_bps") is not None else None),
            latency_ms=latency_ms,
        )

def _engine_refusal_detail(engine: Any, client_order_id: str) -> dict[str, Any]:
    """Why the engine returned no order — the broker's answer, verbatim.

    A refusal that only says "risk/engine veto" is not auditable: the operator
    cannot tell a legitimate risk limit from a broker rejection or an ambiguous
    transport timeout, and those have completely different next actions.
    """
    state = None
    reason = None
    try:
        known = engine.om.get(client_order_id)
        if known is not None:
            state = getattr(known, "state", None)
            state = getattr(state, "value", state)
            reason = getattr(known, "reject_reason", None)
    except Exception:
        known = None
    if not reason:
        reason = getattr(engine, "_suspend_reason", None)
    detail = str(reason or "").strip()
    retcode = None
    if "retcode" in detail:
        import re as _re

        match = _re.search(r"retcode\s+(\d+)", detail)
        if match:
            retcode = match.group(1)
    prefix = f"engine state {state}: " if state else ""
    return {"state": state, "retcode": retcode, "reason": (prefix + detail) if detail else None}
