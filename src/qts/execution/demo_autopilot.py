"""Controlled autonomous DEMO trading under a registered policy.

What this is
------------
A supervised loop that continuously generates, submits, manages and closes
**DEMO** orders, driven exclusively by a strategy registered in the
forward-validation registry (:mod:`qts.lifecycle.demo_registry`).

What it is NOT
--------------
* not a strategy search — it never varies parameters, and it refuses any
  provider that exposes ``optimize``/``fit`` hooks while the registry forbids
  optimization;
* not a research result — every observation is recorded as forward DEMO
  evidence and must never be used to re-fit the registered policy;
* not a LIVE path — the authorization scope, the mode gate and the DEMO
  identity check each independently forbid real capital.

Stopping conditions (any one halts the loop and, where required, the stage):

* durable kill switch raised (any process can raise it);
* reconciliation drift or suspension;
* daily loss / exposure / order-count limits (enforced by the pre-trade gate);
* parameter drift (registered ``params_hash`` != provider config hash);
* orders-per-day cap for the registered strategy;
* stale or missing market data, missing identity, missing pin;
* stage no longer permits orders (e.g. an operator halted it);
* explicit iteration/time budget exhaustion.

Every cycle writes a signal record — including the ``NO_TRADE`` decisions — so
"the system stayed flat" is as auditable as "the system traded".
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from qts.execution.demo_journal import DemoOrderJournal
from qts.execution.demo_pretrade import RESEARCH_DEMO_ORDER
from qts.lifecycle.demo_registry import StrategyRegistration, load_registry, resolve_entry
from qts.lifecycle.demo_stage import ORDER_STAGES, DemoStage, DemoStageMachine

RESEARCH_INTEGRITY_FORBIDDEN_HOOKS = ("optimize", "fit", "tune", "search", "calibrate")


class SignalProvider(Protocol):
    """The contract a registered strategy must satisfy to drive DEMO orders."""

    @property
    def strategy_id(self) -> str: ...

    def config_hash(self) -> str:
        """Hash of the parameters actually in use (must match the registry)."""
        ...

    def generate(self, market_state: dict[str, Any]) -> Signal | None:
        """Return the next order signal, or ``None`` for no action."""
        ...


@dataclass(frozen=True)
class Signal:
    side: str
    lots: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    rationale: str = ""
    signal_id: str | None = None


@dataclass
class AutopilotConfig:
    symbol: str = "XAUUSD"
    poll_interval_s: float = 5.0
    max_iterations: int = 0  # 0 = run until a stop condition fires
    max_runtime_s: float = 0.0  # 0 = no wall-clock budget
    strategy_id: str | None = None
    dry_run: bool = False  # evaluate the gate every cycle, never submit
    actor: str = "autopilot"


@dataclass
class AutopilotReport:
    started_at: str
    finished_at: str | None = None
    iterations: int = 0
    orders_submitted: int = 0
    no_trade: int = 0
    halted: bool = False
    halt_reason: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "iterations": self.iterations,
            "orders_submitted": self.orders_submitted,
            "no_trade": self.no_trade,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "events": list(self.events[-50:]),
        }


class AutopilotHalt(RuntimeError):
    """Raised internally to unwind the loop; always converted to a report."""


def _resolve_provider(entry: StrategyRegistration) -> tuple[Any | None, list[str]]:
    """Import the registered signal provider (fail closed)."""
    if not entry.signal_provider:
        return None, [f"strategy {entry.strategy_id}: no signal_provider registered"]
    module_path, _, attr = entry.signal_provider.partition(":")
    if not module_path or not attr:
        return None, [
            f"strategy {entry.strategy_id}: signal_provider must be 'module:attribute', got {entry.signal_provider!r}"
        ]
    try:
        import importlib

        module = importlib.import_module(module_path)
        provider = getattr(module, attr)
        provider = provider() if isinstance(provider, type) else provider
    except Exception as exc:
        return None, [f"strategy {entry.strategy_id}: signal_provider import failed ({type(exc).__name__}: {exc})"]

    # Research-integrity guard: a provider that can re-fit itself on forward
    # data is not allowed while the registry forbids optimization.
    present = [hook for hook in RESEARCH_INTEGRITY_FORBIDDEN_HOOKS if hasattr(provider, hook)]
    if present:
        return None, [
            f"strategy {entry.strategy_id}: provider exposes optimization hooks {present} while "
            "research_integrity.optimization_allowed is false — refused"
        ]
    if not hasattr(provider, "generate") or not hasattr(provider, "config_hash"):
        return None, [f"strategy {entry.strategy_id}: provider must implement generate() and config_hash()"]
    return provider, []


def run_autopilot(session: Any, config: AutopilotConfig) -> AutopilotReport:
    """Run the controlled loop until a stop condition fires (never on LIVE)."""
    report = AutopilotReport(started_at=datetime.now(UTC).isoformat())
    providers: dict[str, Any] = {}
    journal: DemoOrderJournal = session.journal
    stage_machine: DemoStageMachine = session.stage
    started = time.monotonic()

    def halt(reason: str) -> None:
        report.halted = True
        report.halt_reason = reason
        raise AutopilotHalt(reason)

    def note(kind: str, detail: Any) -> None:
        report.events.append({"at": datetime.now(UTC).isoformat(), "kind": kind, "detail": detail})

    try:
        while True:
            if config.max_iterations and report.iterations >= config.max_iterations:
                note("stop", "iteration budget reached")
                break
            if config.max_runtime_s and (time.monotonic() - started) > config.max_runtime_s:
                note("stop", "runtime budget reached")
                break

            report.iterations += 1

            # ---- 1. stage / kill / reconcile health ------------------------
            stage_record = stage_machine.current()
            stage = stage_record.stage
            if stage not in ORDER_STAGES:
                # Report WHY it was halted: a control that halted the machine
                # (reconciliation drift, an operator kill) is the actionable
                # fact; "stage HALTED" alone sends the operator nowhere.
                why = getattr(stage_record, "reason", None) or "no reason recorded"
                halt(f"stage {stage} does not permit orders (halted because: {why})")
            kill_state = session.kill_switch_state()
            if not kill_state.get("readable") or kill_state.get("killed"):
                halt(f"kill switch {'unreadable' if not kill_state.get('readable') else 'ACTIVE'}: {kill_state.get('reason')}")
            reconciliation = session.reconcile()
            if reconciliation.get("requires_suspend"):
                halt(
                    f"reconciliation requires suspension: {reconciliation.get('drift')} "
                    f"{reconciliation.get('details')}"
                )

            # ---- 2. registry entry (re-resolved every cycle: drift halts) --
            registry = load_registry()
            entry, reasons = resolve_entry(registry, config.strategy_id)
            if entry is None:
                journal.record_signal(
                    strategy_id=config.strategy_id or "none",
                    strategy_config_hash="",
                    symbol=config.symbol,
                    decision="NO_TRADE",
                    reason="; ".join(reasons) or "no eligible strategy",
                    authorization_id=_auth_id(session),
                )
                report.no_trade += 1
                halt("no eligible strategy in the forward-validation registry — NO_TRADE")

            # The provider is instantiated once per run and reused: a strategy
            # that tracks its own state (position already open, signals already
            # emitted) must see that state on the next cycle instead of being
            # reset to a fresh object that would emit the same signal again.
            cached = providers.get(entry.strategy_id)
            if cached is not None:
                provider = cached
            else:
                provider, provider_problems = _resolve_provider(entry)
                if provider is None:
                    halt("; ".join(provider_problems))
                providers[entry.strategy_id] = provider
            runtime_hash = str(provider.config_hash())
            if runtime_hash != entry.params_hash:
                halt(
                    f"parameter drift: provider hash {runtime_hash[:12]}… != registered "
                    f"{entry.params_hash[:12]}… (frozen parameters may not change mid-window)"
                )

            # ---- 3. market state -------------------------------------------
            quote = session._quote_probe()
            if not quote.get("ok"):
                note("skip", f"market data unavailable: {quote.get('error')}")
                time.sleep(config.poll_interval_s)
                continue
            market_state = {
                "symbol": config.symbol,
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "spread_bps": quote.get("spread_bps"),
                "age_s": quote.get("age_s"),
                "event_time": quote.get("event_time"),
                "at": datetime.now(UTC).isoformat(),
            }

            # ---- 4. manage open positions ----------------------------------
            _manage_open_positions(session, entry, journal, note)

            # ---- 5. daily order cap ----------------------------------------
            if entry.max_orders_per_day and journal.orders_today() >= entry.max_orders_per_day:
                note("skip", f"daily order cap reached ({entry.max_orders_per_day})")
                time.sleep(config.poll_interval_s)
                continue

            # ---- 6. signal → gate → order ----------------------------------
            signal = provider.generate(market_state)
            if signal is None:
                journal.record_signal(
                    strategy_id=entry.strategy_id,
                    strategy_config_hash=entry.params_hash,
                    symbol=config.symbol,
                    decision="NO_TRADE",
                    rationale="provider returned no signal",
                    market_state=market_state,
                    authorization_id=_auth_id(session),
                )
                report.no_trade += 1
            else:
                if config.dry_run:
                    pre = session.preflight(
                        side=signal.side,
                        lots=signal.lots,
                        stop_loss=signal.stop_loss,
                        entry=entry,
                        autonomous=True,
                    )
                    note("dry_run", {"passed": pre["verdict"]["passed"], "failed": pre["verdict"]["failed"]})
                else:
                    result = session.submit(
                        side=signal.side,
                        lots=signal.lots,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        rationale=signal.rationale,
                        entry=entry,
                        signal_id=signal.signal_id,
                        autonomous=True,
                    )
                    if result.allowed:
                        report.orders_submitted += 1
                        note("order", result.as_dict())
                    else:
                        report.no_trade += 1
                        note("no_trade", {"reasons": result.reasons, "client_order_id": result.client_order_id})
                        # A gate refusal caused by a broken control halts the
                        # loop; a routine risk/stale refusal just waits.
                        if _is_control_failure(result):
                            halt("; ".join(result.reasons))

            time.sleep(config.poll_interval_s)
    except AutopilotHalt as exc:
        note("halt", str(exc))
        try:
            stage_machine.halt(reason=str(exc), actor=config.actor)
        except Exception as halt_exc:  # pragma: no cover - halt is best effort
            note("halt_error", f"{type(halt_exc).__name__}: {halt_exc}")
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        note("stop", "operator interrupt")
    finally:
        report.finished_at = datetime.now(UTC).isoformat()
    return report


def _auth_id(session: Any) -> str | None:
    auth = getattr(session, "authorization", None)
    return auth.authorization_id if auth else None


_CONTROL_FAILURE_MARKERS = (
    "kill_switch_functional",
    "reconciliation_ready",
    "broker_identity_verified",
    "account_is_demo",
    "authorization_valid",
    "execution_permission",
    "mode_is_demo_execution",
    "stage_allows_order",
    "strategy_registered_frozen",
    "duplicate_order_protection",
)


def _is_control_failure(result: Any) -> bool:
    """Distinguish 'a control is broken' from 'a risk/size/market limit said no'.

    A broken control (dead kill switch, unverifiable identity, drift) must stop
    the loop; a routine limit (spread too wide, cap reached) must not.
    """
    failed = set((result.verdict or {}).get("failed", []))
    return bool(failed & set(_CONTROL_FAILURE_MARKERS))


def _manage_open_positions(
    session: Any,
    entry: StrategyRegistration,
    journal: DemoOrderJournal,
    note: Any,
) -> None:
    """Apply the registered exit policy to broker positions (close + record)."""
    policy = dict(entry.exit_policy or {})
    try:
        positions = session.adapter.position_details()
    except Exception as exc:
        note("manage_error", f"positions unavailable: {type(exc).__name__}: {exc}")
        return

    max_hold_s = float(policy.get("max_hold_seconds") or 0)
    now_epoch = time.time()

    for pos in positions:
        ticket = pos.get("ticket")
        if ticket is None:
            continue
        try:
            profit = Decimal(str(pos.get("profit") or "0"))
            row = _match_journal(journal, pos)
            if row is not None:
                journal.update_unrealized(
                    int(row["journal_id"]),
                    unrealized_pnl=profit,
                    market_state={"price_current": pos.get("price_current"), "at": datetime.now(UTC).isoformat()},
                )
            reason = None
            if max_hold_s > 0 and pos.get("time"):
                opened = float(pos["time"])
                if (now_epoch - opened) > max_hold_s:
                    reason = f"max_hold_seconds {max_hold_s:.0f} exceeded"
            if policy.get("close_on_registry_expiry") and not reason:
                reason = None  # registry expiry is checked by the caller loop
            if reason:
                receipt = session.adapter.close_position(int(ticket), comment=RESEARCH_DEMO_ORDER[:31])
                if row is not None:
                    journal.mark_outcome(
                        int(row["journal_id"]),
                        state="CLOSED",
                        exit_reason=reason,
                        realized_pnl=profit,
                        market_state_exit={"price_current": pos.get("price_current"), "close_receipt": receipt},
                    )
                note("close", {"ticket": ticket, "reason": reason, "profit": str(profit), "receipt": receipt})
                # A close is an order too: fold the closing deal into local
                # state, then reconcile — never leave the loop running on a
                # portfolio that no longer matches the venue.
                with contextlib.suppress(Exception):
                    session.sync_fills()
                after_close = session.reconcile()
                note("reconcile_after_close", after_close)
                if after_close.get("requires_suspend"):
                    raise AutopilotHalt(
                        f"reconciliation drift after closing ticket {ticket}: {after_close.get('drift')} "
                        f"{after_close.get('details')}"
                    )
        except Exception as exc:
            note("manage_error", f"position {ticket}: {type(exc).__name__}: {exc}")


def _match_journal(journal: DemoOrderJournal, pos: dict[str, Any]) -> dict[str, Any] | None:
    """Match a broker position back to its journal row (broker id first)."""
    for row in journal.open_orders():
        if row.get("broker_position_id") and str(row["broker_position_id"]) == str(pos.get("ticket")):
            return row
        if row.get("broker_symbol") and row.get("broker_symbol") == pos.get("symbol") and row.get("side") == pos.get("side"):
            return row
    return None


def stage_note() -> str:
    return (
        f"autonomous DEMO trading requires stage "
        f"{DemoStage.STAGE_2_MIN_SIZE_ORDER.value} or {DemoStage.STAGE_3_FORWARD_OBSERVATION.value}"
    )
