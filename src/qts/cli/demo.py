"""QTS CLI — DEMO execution."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import click

from qts.config.paths import default_db_path, paths_report


def _demo_session(symbol: str, db: str, terminal_path: str | None = None) -> Any:
    from qts.config.wizard import load_setup
    from qts.execution.demo_session import DemoSession, DemoSessionConfig

    saved = load_setup()
    symbol_map = saved.get("symbol_map")
    return DemoSession(
        DemoSessionConfig(
            symbol=symbol or saved.get("symbol") or "XAUUSD",
            terminal_path=terminal_path or saved.get("terminal_path") or None,
            symbol_map=symbol_map if isinstance(symbol_map, dict) else {},
            db_path=Path(db),
            actor="cli",
        )
    )


@click.group()
def demo() -> None:
    """Controlled DEMO execution (authorization-gated; LIVE stays locked)."""


@demo.command("paths")
def demo_paths() -> None:
    """Show the machine-local state root and every resolved artefact path.

    The UI and the CLI must read the SAME setup, pin, authorization, registry and
    database. This prints what this process resolved (and from where), so a
    disagreement is a comparison of two outputs rather than a guess.
    """
    report = paths_report()
    click.echo(f"state root: {report['state_root']}")
    click.echo(f"  why:      {report['state_root_source']}")
    click.echo(f"  cwd:      {report['working_directory']} (not used for defaults)")
    for name, item in report["artifacts"].items():
        click.echo(f"  {name.ljust(15)} {'EXISTS ' if item['exists'] else 'absent '} {item['path']}")
        click.echo(f"  {''.ljust(15)} source: {item['source']}")
    click.echo(json.dumps(report, indent=2, default=str))


@demo.command("authorization")
def demo_authorization() -> None:
    """Show the owner authorization artifact and its validation result."""
    from qts.lifecycle.demo_authorization import authorization_status, resolve_demo_execution_policy

    status = authorization_status()
    click.echo(json.dumps(status.as_dict(), indent=2, default=str))
    policy = resolve_demo_execution_policy(mode="DEMO_EXECUTION")
    click.echo(f"policy(DEMO_EXECUTION): {policy.state}")
    live_policy = resolve_demo_execution_policy(mode="LIVE")
    click.echo(f"policy(LIVE): {live_policy.state} — {'; '.join(live_policy.reasons)}")


@demo.command("status")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
def demo_status(symbol: str | None, db: str) -> None:
    """One honest snapshot: policy, stage, registry, journal, kill switch."""
    from qts.domain.modes import mode_source
    from qts.execution.demo_journal import summarize
    from qts.lifecycle.demo_registry import registry_status

    session = _demo_session(symbol or "", db)
    policy = session.policy
    out = {
        # The RESOLVED mode with its provenance. This field used to be the
        # literal "DEMO_EXECUTION" regardless of what the process had actually
        # resolved — a label that contradicted the policy block printed right
        # below it ("mode DEVELOPMENT cannot submit broker orders").
        "mode": session.mode.value,
        "mode_source": mode_source(),
        "policy": policy.as_dict(),
        "stage": session.stage.as_dict(),
        "registry": registry_status(),
        "kill_switch": session.kill_switch_state(),
        "journal": summarize(session.journal).as_dict(),
        "live_locked": True,
        "real_capital_exposure_usd": 0,
    }
    click.echo(json.dumps(out, indent=2, default=str))


@demo.command("verify")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--terminal-path", default=None)
@click.option("--json", "json_out", default=None, help="write the full triage report to this path")
def demo_verify(symbol: str | None, db: str, terminal_path: str | None, json_out: str | None) -> None:
    """Read-only triage: what is blocking DEMO execution, and what to do next.

    Touches nothing — no order, no stage change, no enablement. It answers one
    question an operator actually has: "where am I, and which single command
    comes next?" Exit code 0 means every gate that can be checked now passes;
    exit code 2 means something is blocking (the report says what).
    """
    from qts.domain.modes import mode_source
    from qts.lifecycle.demo_registry import registry_status
    from qts.lifecycle.demo_stage import ORDER_STAGES

    session = _demo_session(symbol or "", db, terminal_path)
    policy = session.policy
    connectivity = session.connectivity_report()
    registry = registry_status()
    stage_record = session.stage.current()
    kill = session.kill_switch_state()
    reconciliation = session.reconcile()

    entry = registry.get("resolved_strategy")
    readiness = connectivity.get("readiness") or {}
    identity = connectivity.get("identity") or {}
    pin = connectivity.get("identity_pin") or {}
    mapping = connectivity.get("symbol_mapping") or {}
    pin_present = bool(pin.get("pinned"))
    pin_confirmed = str(pin.get("status") or "") == "CONFIRMED"
    pin_verified = pin.get("verified") is True

    preflight: dict[str, Any] | None = None
    if entry is not None:
        # Probe the gate with the smallest possible order — it submits nothing.
        # No stop is supplied on purpose: the registered policy requires one, so
        # this also proves the deterministic derivation from the frozen policy
        # produces a stop the gate accepts.
        outcome = session.preflight(side="BUY")
        preflight = {
            "passed": bool(outcome["verdict"]["passed"]),
            "failed": list(outcome["verdict"]["failed"]),
            "unknown": list(outcome["verdict"]["unknown"]),
        }

    checks = {
        "mode_is_demo_execution": str(getattr(session, "mode", "DEMO_EXECUTION")) == "DEMO_EXECUTION",
        "authorization_valid": bool(policy.enabled),
        "terminal_reachable": bool(identity.get("ok")),
        "account_is_demo": identity.get("is_demo") is True,
        "identity_pinned": pin_present,
        "identity_confirmed": pin_confirmed,
        "identity_verified": pin_verified,
        "readiness_passed": bool(readiness.get("passed")),
        "authority_permitted": bool(session.authority.current().execution_permitted),
        "stage_allows_orders": stage_record.stage in ORDER_STAGES,
        "strategy_registered": entry is not None,
        "kill_switch_clear": (not kill.get("killed")) and bool(kill.get("readable")),
        "reconciliation_clean": not reconciliation.get("requires_suspend"),
        "preflight_passed": None if preflight is None else bool(preflight["passed"]),
    }

    # Blockers and the next action are listed in the order an operator must
    # resolve them: the FIRST blocker is the one the NEXT command addresses.
    blockers: list[str] = []

    def block(reason: str) -> None:
        blockers.append(reason)

    if not checks["mode_is_demo_execution"]:
        block(
            f"process mode is {getattr(session, 'mode', 'unknown')} — the DEMO order path exists only in "
            "DEMO_EXECUTION (set QTS_MODE=demo_execution for this shell, or `qts mode declare demo_execution` "
            "so the CLI and the web backend resolve the same mode); LIVE stays locked in every mode"
        )
    if not checks["authorization_valid"]:
        block(f"no valid owner authorization ({policy.state}) — DEMO_EXECUTION stays DISABLED BY POLICY")
    if not checks["terminal_reachable"]:
        block(f"terminal unreachable: {identity.get('error')}")
    if checks["terminal_reachable"] and not checks["account_is_demo"]:
        block(f"connected account is not DEMO (is_demo={identity.get('is_demo')})")
    if not checks["identity_pinned"]:
        block("broker identity is not pinned")
    elif not checks["identity_confirmed"]:
        block("identity pin is recorded but not owner-confirmed")
    elif not checks["identity_verified"]:
        block(f"identity does not match the confirmed pin: {'; '.join(pin.get('detail') or ['mismatch'])}")
    if not checks["readiness_passed"]:
        block(f"readiness failed: {'; '.join(readiness.get('blocked_reasons') or ['unknown'])}")
    if not checks["kill_switch_clear"]:
        block(f"kill switch {'ACTIVE' if kill.get('killed') else 'unreadable'}: {kill.get('reason')}")
    if not checks["reconciliation_clean"]:
        block(f"reconciliation: {reconciliation.get('drift')} {reconciliation.get('details')}".strip())
    if not checks["stage_allows_orders"]:
        block(f"stage {stage_record.stage} does not permit orders")
    elif not checks["authority_permitted"]:
        authority = session.authority.current()
        expired = bool(getattr(authority, "readiness_expired", False))
        block(
            "durable execution permission is not in force — "
            + (
                "its readiness evidence expired (re-prove it against the live terminal)"
                if expired
                else "; ".join(authority.reasons) or "not granted"
            )
        )
    if not checks["strategy_registered"]:
        block(
            "no eligible strategy in the forward-validation registry — NO_TRADE "
            f"(registry: {registry['registry']['path']})"
            + (f"; reasons: {'; '.join(registry['reasons'])}" if registry.get("reasons") else "")
        )
    if preflight is not None and not preflight["passed"]:
        block(f"pre-trade gate: failed={preflight['failed']} unknown={preflight['unknown']}")

    # One next action, in the order an operator must do things.
    if not checks["mode_is_demo_execution"]:
        action = (
            "qts mode declare demo_execution   (or set QTS_MODE=demo_execution for this shell only — "
            "LIVE and the observation modes have no DEMO order path)"
        )
    elif not checks["authorization_valid"]:
        action = (
            "record an owner authorization artifact (DEMO only, LIVE locked) at "
            "QTS_DEMO_AUTHORIZATION — see docs/demo_execution_authorization_and_safety_2026-09-23.md §2"
        )
    elif not checks["terminal_reachable"] or not checks["account_is_demo"]:
        action = f"qts demo connectivity --db {db}"
    elif not checks["identity_pinned"]:
        action = f"qts demo connectivity --pin --db {db}"
    elif not checks["identity_confirmed"]:
        action = f"qts demo connectivity --confirm-pin --db {db}"
    elif not checks["identity_verified"]:
        action = f"qts demo connectivity --db {db}   # the account no longer matches the pin — re-review"
    elif not checks["readiness_passed"]:
        action = f"qts demo connectivity --db {db}   # fix the failing readiness checks above"
    elif not checks["kill_switch_clear"]:
        # Arming cannot succeed while the kill switch is raised, so clearing it
        # comes first — and the stage stays HALTED until re-armed afterwards.
        action = f"qts demo clear-kill --reason '<why>' --confirm --db {db}"
    elif not checks["reconciliation_clean"]:
        action = f"qts demo connectivity --db {db}   # reconcile broker vs internal state first"
    elif not checks["stage_allows_orders"]:
        action = f"qts demo arm --stage 2 --confirm --risk-ack --db {db}"
    elif not checks["authority_permitted"]:
        # The stage already permits orders: refreshing permission is a
        # re-verification, NOT a transition — suggesting `arm --stage 2` here
        # used to point at an illegal STAGE_2 → STAGE_2 self-edge.
        action = f"qts demo reverify --confirm --risk-ack --db {db}"
    elif not checks["strategy_registered"]:
        action = (
            f"register a preregistered experiment in {registry['registry']['path']} "
            "(status ELIGIBLE with a validation artifact, or ELIGIBLE_DIAGNOSTIC with a complete "
            "DEMO_FORWARD_RESEARCH_POLICY) — see scripts/register_demo_research_policy.py"
        )
    elif preflight is not None and not preflight["passed"]:
        action = f"qts demo preflight --side BUY --db {db}   # inspect the failing checks above"
    else:
        strat = entry["strategy_id"] if entry else "<strategy_id>"
        action = (
            f"qts demo run --strategy {strat} --db {db}"
            if stage_record.stage == "STAGE_3_FORWARD_OBSERVATION"
            else f"qts demo order --side BUY --stop-loss <price> --db {db}"
        )

    report: dict[str, Any] = {
        "checked_at": connectivity.get("checked_at"),
        "ready_to_trade": not blockers,
        "next_action": action,
        "blockers": blockers,
        "checks": checks,
        "mode": str(getattr(session, "mode", "unknown")),
        "mode_source": mode_source(),
        "state": paths_report(),
        "policy": policy.as_dict(),
        "identity": {"is_demo": identity.get("is_demo"), "login": identity.get("login"), "server": identity.get("server")},
        "identity_pin": {
            "pinned": pin_present,
            "status": pin.get("status"),
            "confirmed": pin_confirmed,
            "verified": pin.get("verified"),
            "detail": pin.get("detail") or [],
        },
        "symbol": {"canonical": mapping.get("canonical"), "broker": mapping.get("broker_symbol"), "tradable": mapping.get("tradable")},
        "readiness": {"passed": readiness.get("passed"), "blocked_reasons": readiness.get("blocked_reasons", [])},
        "registry": {
            "path": registry["registry"]["path"],
            "trading_state": registry["trading_state"],
            "entries": registry["registry"]["entry_count"],
            "reasons": list(registry.get("reasons") or []),
        },
        "resolved_policy": (
            None
            if entry is None
            else {
                "strategy_id": entry["strategy_id"],
                "status": entry["status"],
                "policy_id": entry.get("policy_id"),
                "policy_class": entry.get("policy_class"),
                "validated_edge": entry.get("validated_edge"),
                "hypothesis_id": entry.get("hypothesis_id"),
                "preregistration_artifact": entry.get("preregistration_artifact"),
            }
        ),
        "stage": {"stage": stage_record.stage, "orders_permitted": stage_record.stage in ORDER_STAGES},
        "controls": {"kill_switch": kill, "reconciliation": reconciliation},
        "preflight": preflight,
        "live_locked": True,
        "real_capital_exposure_usd": 0,
    }

    click.echo(f"mode: {getattr(session, 'mode', 'unknown')}   (decided by: {mode_source()})")
    click.echo(f"state root: {paths_report()['state_root']}   setup: {paths_report()['artifacts']['setup']['path']}")
    click.echo(f"authorization: {policy.state} ({'valid' if policy.enabled else 'NOT valid'}) — LIVE locked, real capital 0")
    click.echo(f"account: demo={identity.get('is_demo')} login={identity.get('login')} server={identity.get('server')}")
    click.echo(
        f"identity pin: pinned={pin_present} status={pin.get('status')} verified={pin.get('verified')}"
    )
    click.echo(f"symbol: {mapping.get('canonical')} -> {mapping.get('broker_symbol')} tradable={mapping.get('tradable')}")
    click.echo(f"readiness: passed={bool(readiness.get('passed'))} blockers={readiness.get('blocked_reasons', [])}")
    click.echo(f"registry: entries={registry['registry']['entry_count']} trading_state={registry['trading_state']}")
    if entry is not None:
        click.echo(
            f"policy: {entry['strategy_id']} status={entry['status']} "
            f"class={entry.get('policy_class')} validated_edge={entry.get('validated_edge')} "
            f"hypothesis={entry.get('hypothesis_id')}"
        )
    click.echo(f"stage: {stage_record.stage} orders_permitted={stage_record.stage in ORDER_STAGES}")
    if preflight is not None:
        click.echo(f"preflight: passed={preflight['passed']} failed={preflight['failed']} unknown={preflight['unknown']}")
    click.echo(f"controls: kill_switch={'ACTIVE' if kill.get('killed') else 'clear'} reconciliation={reconciliation.get('drift')}")
    click.echo(f"READY: {not blockers}")
    for reason in blockers:
        click.echo(f"  BLOCKED: {reason}", err=True)
    click.echo(f"NEXT: {action}")

    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        click.echo(f"report written to {json_out}")

    if blockers:
        raise SystemExit(2)


@demo.command("clear-kill")
@click.option("--db", default=default_db_path)
@click.option("--reason", required=True, help="why the halt is being lifted (recorded)")
@click.option("--confirm", is_flag=True, help="explicit operator confirmation (required)")
def demo_clear_kill(db: str, reason: str, confirm: bool) -> None:
    """Clear the durable kill switch — recorded; the stage stays HALTED.

    Clearing the flag does NOT resume trading: the stage machine remains
    HALTED, so orders stay refused until an operator re-arms explicitly and
    the whole staged progression is proved again.
    """
    if not confirm or not reason.strip():
        click.echo("REFUSED: clearing a kill switch requires --confirm and a non-empty --reason", err=True)
        raise SystemExit(2)

    from qts.risk.engine import RiskEngine, RiskLimits

    engine = RiskEngine(RiskLimits(), db_path=Path(db), persist_kill=True)
    was_killed = bool(engine.is_killed())
    engine.reset_kill()

    session = _demo_session("", db)
    stage_record = session.stage.current()

    # Audit the recovery: a lifted halt must be as traceable as the halt itself.
    audit_note = None
    try:
        from qts.domain.events import DomainEvent, EventType
        from qts.observability.audit import SqliteAuditLog

        audit = SqliteAuditLog()
        audit.emit(
            DomainEvent(
                event_type=EventType.KILL_SWITCH,
                payload={
                    "action": "cleared",
                    "was_killed": was_killed,
                    "reason": reason,
                    "stage": stage_record.stage,
                    "actor": "cli:demo-clear-kill",
                },
            )
        )
        audit_note = "audit event recorded"
    except Exception as exc:  # pragma: no cover - audit best effort
        audit_note = f"audit event NOT recorded: {type(exc).__name__}: {exc}"

    out = {
        "was_killed": was_killed,
        "killed": bool(engine.is_killed()),
        "reason": reason,
        "stage": stage_record.as_dict(),
        "audit": audit_note,
        "next": f"qts demo arm --stage 1 --confirm --risk-ack --db {db}",
    }
    click.echo(json.dumps(out, indent=2, default=str))
    click.echo("kill switch cleared — the stage remains HALTED; re-arm explicitly before any order.")


@demo.command("connectivity")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--terminal-path", default=None)
@click.option("--pin", is_flag=True, help="record the observed identity as a pin (PENDING_REVIEW)")
@click.option("--confirm-pin", is_flag=True, help="owner confirmation of the recorded pin")
@click.option("--json-out", default=None, help="write the full report to this path")
def demo_connectivity(
    symbol: str | None,
    db: str,
    terminal_path: str | None,
    pin: bool,
    confirm_pin: bool,
    json_out: str | None,
) -> None:
    """Stage 1 — verify terminal, DEMO account, broker, symbol, quote. No orders."""
    session = _demo_session(symbol or "", db, terminal_path)
    report = session.connectivity_report()

    if pin:
        from qts.execution.demo_identity import write_pin

        with contextlib.suppress(Exception):
            identity = session.adapter.broker_identity()
            # Record the symbol provenance alongside the account: the pin is
            # the artefact the owner confirms, so it should state which
            # canonical/venue symbol pair was verified on this account.
            path = write_pin(identity, actor="cli", symbol=report.get("symbol_mapping"))
            report["pin_written"] = str(path)
            click.echo(f"identity pin written (PENDING_REVIEW): {path}")
    if confirm_pin:
        from qts.execution.demo_identity import confirm_pin as do_confirm_pin

        ok, detail = do_confirm_pin(actor="owner")
        report["pin_confirmation"] = {"ok": ok, "detail": detail}
        click.echo(f"pin confirmation: {detail}")

    readiness = report.get("readiness") or {}
    click.echo(f"readiness passed: {bool(readiness.get('passed'))} blockers={readiness.get('blocked_reasons', [])}")
    identity = report.get("identity") or {}
    click.echo(
        f"account: demo={identity.get('is_demo')} login={identity.get('login')} "
        f"server={identity.get('server')} company={identity.get('company')} type={identity.get('account_type')}"
    )
    mapping = report.get("symbol_mapping") or {}
    click.echo(
        f"symbol: {mapping.get('canonical')} -> {mapping.get('broker_symbol')} "
        f"visible={mapping.get('visible')} tradable={mapping.get('tradable')}"
    )
    quote = report.get("quote") or {}
    click.echo(f"quote: bid={quote.get('bid')} ask={quote.get('ask')} age={quote.get('age_s')} spread_bps={quote.get('spread_bps')}")
    click.echo(f"order_check dry-run: {report.get('order_check')}")
    click.echo(f"STAGE_1_READY: {report['ready_for_stage_1']}")

    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        click.echo(f"report written to {json_out}")


@demo.command("arm")
@click.option("--stage", required=True, type=click.Choice(["1", "2", "3"]))
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--confirm", is_flag=True, help="explicit operator confirmation (required)")
@click.option("--risk-ack", is_flag=True, help="explicit risk acknowledgement (required)")
@click.option("--strategy", default=None, help="registry strategy_id (required for stage 3)")
def demo_arm(stage: str, symbol: str | None, db: str, confirm: bool, risk_ack: bool, strategy: str | None) -> None:
    """Advance the DEMO stage machine. Each stage proves its prerequisites."""
    from qts.lifecycle.demo_stage import DemoStage, StageTransitionError

    session = _demo_session(symbol or "", db)
    target = {"1": DemoStage.STAGE_1_CONNECTIVITY, "2": DemoStage.STAGE_2_MIN_SIZE_ORDER,
              "3": DemoStage.STAGE_3_FORWARD_OBSERVATION}[stage]

    prereq: dict[str, bool] = {}
    if target in (DemoStage.STAGE_1_CONNECTIVITY, DemoStage.STAGE_2_MIN_SIZE_ORDER,
                  DemoStage.STAGE_3_FORWARD_OBSERVATION):
        report = session.connectivity_report()
        prereq["readiness_passed"] = bool((report.get("readiness") or {}).get("passed"))
        prereq["account_is_demo"] = (report.get("identity") or {}).get("is_demo") is True
        prereq["symbol_ok"] = bool((report.get("symbol_mapping") or {}).get("ok"))
        prereq["quote_fresh"] = bool((report.get("quote") or {}).get("fresh"))
    if target in (DemoStage.STAGE_2_MIN_SIZE_ORDER, DemoStage.STAGE_3_FORWARD_OBSERVATION):
        prereq["policy_authorized"] = session.policy.enabled
        prereq["identity_pinned_confirmed"] = (report.get("identity_pin") or {}).get("verified") is True
        prereq["operator_confirmation"] = bool(confirm and risk_ack)
        if prereq["operator_confirmation"]:
            from qts.lifecycle.demo_authority import readiness_age_seconds
            from qts.lifecycle.demo_gate import demo_forward_readiness_report

            rpt = demo_forward_readiness_report(
                mt5_module=None,
                terminal_path=session.config.terminal_path,
                symbol=session.canonical_symbol,
                symbol_map=session.config.symbol_map or None,
            )
            decision = session.authority.enable(
                readiness=rpt,
                confirmed=True,
                risk_ack=True,
                readiness_age_s=readiness_age_seconds(rpt),
                actor="cli:demo-arm",
            )
            prereq["authority_enabled"] = bool(decision.execution_permitted)
            click.echo(f"authority: {decision.state} permitted={decision.execution_permitted} {decision.reasons}")
        else:
            prereq["authority_enabled"] = False
    if target is DemoStage.STAGE_3_FORWARD_OBSERVATION:
        from qts.execution.demo_journal import summarize

        summary = summarize(session.journal)
        prereq["stage2_order_recorded"] = summary.orders > 0
        prereq["strategy_selected"] = bool(strategy)

    current_stage = session.stage.current().stage
    if current_stage == target.value:
        # Re-arming the stage we are already in is NOT a transition (the state
        # machine has no self-edge, by design). What the operator actually wants
        # here is to re-prove the prerequisites — most often the readiness
        # evidence, which decays every REVERIFY_TTL_S — so refresh the durable
        # permission and report it as a re-verification. Suggesting an illegal
        # transition would leave the operator stuck with a command that can
        # never succeed.
        if not (confirm and risk_ack):
            click.echo(
                f"already at {current_stage} — re-verifying requires explicit confirmation: "
                f"qts demo arm --stage {stage} --confirm --risk-ack --db {db}",
                err=True,
            )
            click.echo(json.dumps(prereq, indent=2, default=str), err=True)
            raise SystemExit(2)
        outcome = session.reverify_authority(confirmed=True, risk_ack=True, actor="cli:demo-arm")
        click.echo(f"already at {current_stage} — re-verified (no stage change)")
        click.echo(json.dumps(outcome, indent=2, default=str))
        if not outcome["reverified"]:
            raise SystemExit(2)
        return

    try:
        record = session.stage.advance(
            target, actor="cli", reason=f"operator arm to stage {stage}", prerequisites=prereq
        )
    except StageTransitionError as exc:
        click.echo(f"REFUSED: {exc}", err=True)
        click.echo(json.dumps(prereq, indent=2, default=str), err=True)
        raise SystemExit(2) from exc
    click.echo(json.dumps(record.as_dict(), indent=2, default=str))


@demo.command("reverify")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--confirm", is_flag=True, help="explicit operator confirmation (required)")
@click.option("--risk-ack", is_flag=True, help="explicit risk acknowledgement (required)")
def demo_reverify(symbol: str | None, db: str, confirm: bool, risk_ack: bool) -> None:
    """Re-prove readiness and refresh DEMO execution permission at the current stage.

    Permission is proven against the live terminal and decays after
    ``REVERIFY_TTL_S`` (120 s) by design — an expired window is a normal event
    during a long session, not a failure. This is the explicit refresh path:
    it re-runs the readiness probe and re-enables the durable authority while
    leaving the stage unchanged, so no illegal stage self-transition is ever
    required. Every gate of ``qts demo arm`` still applies (fresh readiness,
    explicit confirmation, risk acknowledgement, DEMO scope, broker-capable
    mode), and each refresh is audited as ``demo_execution_reverified``.
    """
    from qts.lifecycle.demo_stage import ORDER_STAGES

    session = _demo_session(symbol or "", db)
    stage = session.stage.current()
    if stage.stage not in ORDER_STAGES:
        click.echo(
            f"stage {stage.stage} does not hold execution permission — advance first: "
            f"qts demo arm --stage 2 --confirm --risk-ack --db {db}",
            err=True,
        )
        raise SystemExit(2)
    if not (confirm and risk_ack):
        click.echo(
            "re-verification requires explicit confirmation and risk acknowledgement: "
            f"qts demo reverify --confirm --risk-ack --db {db}",
            err=True,
        )
        raise SystemExit(2)

    outcome = session.reverify_authority(confirmed=True, risk_ack=True, actor="cli:demo-reverify")
    click.echo(f"mode: {outcome['mode']}")
    click.echo(f"symbol: {outcome['symbol']['canonical']} -> {outcome['symbol']['broker']}")
    click.echo(f"stage: {outcome['stage']['stage']} (unchanged — this is not a transition)")
    click.echo(f"readiness: passed={outcome['readiness']['passed']} blockers={outcome['readiness']['blocked_reasons']}")
    click.echo(
        f"authority: {outcome['authority']['state']} permitted={outcome['authority']['execution_permitted']} "
        f"{outcome['authority']['reasons']}"
    )
    click.echo(f"REVERIFIED: {outcome['reverified']}")
    if not outcome["reverified"]:
        raise SystemExit(2)


@demo.command("preflight")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--side", default="BUY", type=click.Choice(["BUY", "SELL"]))
@click.option("--lots", default=None)
@click.option("--stop-loss", default=None)
def demo_preflight(symbol: str | None, db: str, side: str, lots: str | None, stop_loss: str | None) -> None:
    """Run the full pre-trade gate for a would-be order. Submits nothing."""
    from decimal import Decimal

    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    session = _demo_session(symbol or "", db)
    registry = load_registry()
    entry, _reasons = resolve_entry(registry)
    out = session.preflight(
        side=side,
        lots=Decimal(lots) if lots else None,
        stop_loss=Decimal(stop_loss) if stop_loss else None,
        entry=entry,
    )
    verdict = out["verdict"]
    intended = out.get("intended_order") or {}
    click.echo(f"PREFLIGHT {'PASS' if verdict['passed'] else 'REFUSE'}")
    click.echo(
        f"  order: {intended.get('symbol')} -> {intended.get('broker_symbol')} {intended.get('side')} "
        f"{intended.get('lots')} lots stop={intended.get('stop_loss')}"
        f"{' (derived from the registered policy)' if intended.get('stop_derived_from_policy') else ''}"
    )
    for name, check in verdict["checks"].items():
        click.echo(f"  [{check['status']:7}] {name}: {check['detail']}")
    if not verdict["passed"]:
        click.echo(f"blocked by: {', '.join(verdict['failed'])}")


@demo.command("order")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--side", required=True, type=click.Choice(["BUY", "SELL"]))
@click.option("--lots", default=None)
@click.option("--stop-loss", default=None)
@click.option("--take-profit", default=None)
@click.option("--strategy", default=None)
@click.option("--rationale", default="")
@click.option("--dry-run", is_flag=True, help="evaluate the gate without submitting")
def demo_order(
    symbol: str | None,
    db: str,
    side: str,
    lots: str | None,
    stop_loss: str | None,
    take_profit: str | None,
    strategy: str | None,
    rationale: str,
    dry_run: bool,
) -> None:
    """Submit ONE DEMO order through the gate (or dry-run it)."""
    from decimal import Decimal

    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    session = _demo_session(symbol or "", db)
    registry = load_registry()
    entry, reasons = resolve_entry(registry, strategy)
    if entry is None:
        click.echo(f"NO_TRADE — {'; '.join(reasons)}", err=True)
        raise SystemExit(2)
    if dry_run:
        out = session.preflight(
            side=side,
            lots=Decimal(lots) if lots else None,
            stop_loss=Decimal(stop_loss) if stop_loss else None,
            entry=entry,
        )
        click.echo(json.dumps(out, indent=2, default=str))
        return
    result = session.submit(
        side=side,
        lots=Decimal(lots) if lots else None,
        stop_loss=Decimal(stop_loss) if stop_loss else None,
        take_profit=Decimal(take_profit) if take_profit else None,
        rationale=rationale or "operator-initiated RESEARCH_DEMO_ORDER",
        entry=entry,
    )
    click.echo(json.dumps(result.as_dict(), indent=2, default=str))
    if not result.allowed:
        raise SystemExit(2)


@demo.command("run")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--strategy", default=None)
@click.option("--poll-interval", default=5.0, type=float)
@click.option("--max-iterations", default=0, type=int)
@click.option("--max-runtime", default=0.0, type=float)
@click.option("--dry-run", is_flag=True, help="evaluate the gate every cycle, submit nothing")
@click.option("--confirm", is_flag=True, help="explicit operator confirmation (required unless --dry-run)")
@click.option("--risk-ack", is_flag=True, help="explicit risk acknowledgement (required unless --dry-run)")
def demo_run(
    symbol: str | None,
    db: str,
    strategy: str | None,
    poll_interval: float,
    max_iterations: int,
    max_runtime: float,
    dry_run: bool,
    confirm: bool,
    risk_ack: bool,
) -> None:
    """Autonomous DEMO trading under the registered policy (never LIVE).

    DEMO execution permission is proven against the live terminal and decays
    after 120 s, so a run longer than that must re-prove it. That requires the
    operator's explicit confirmation and risk acknowledgement — captured once
    here (``--confirm --risk-ack``) rather than per refresh — and every refresh
    re-runs the full readiness probe and is audited. Without the flags the loop
    still runs, but it stops as soon as the permission window closes instead of
    refreshing it.
    """
    from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot

    session = _demo_session(symbol or "", db)
    if not dry_run and not (confirm and risk_ack):
        click.echo(
            "autonomous DEMO trading requires explicit confirmation and risk acknowledgement: "
            f"qts demo run --strategy <id> --confirm --risk-ack --db {db}",
            err=True,
        )
        raise SystemExit(2)
    config = AutopilotConfig(
        symbol=session.canonical_symbol,
        poll_interval_s=poll_interval,
        max_iterations=max_iterations,
        max_runtime_s=max_runtime,
        strategy_id=strategy,
        dry_run=dry_run,
        actor="cli:demo-run",
        refresh_authority=bool(confirm and risk_ack),
        confirmed=bool(confirm),
        risk_ack=bool(risk_ack),
    )
    report = run_autopilot(session, config)
    click.echo(json.dumps(report.as_dict(), indent=2, default=str))
    if report.halted:
        click.echo(f"HALTED: {report.halt_reason}", err=True)


@demo.command("positions")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
def demo_positions(symbol: str | None, db: str) -> None:
    """Show open DEMO positions on the broker."""
    session = _demo_session(symbol or "", db)
    positions = session.positions()
    if not positions:
        click.echo("no open positions on DEMO venue")
        return
    for pos in positions:
        click.echo(
            f"ticket={pos.get('ticket')} {pos.get('side')} {pos.get('volume')} {pos.get('symbol')} "
            f"open_px={pos.get('price_open')} cur_px={pos.get('price_current')} "
            f"pnl={pos.get('profit')} sl={pos.get('sl')} tp={pos.get('tp')} "
            f"journal_id={pos.get('journal_id')}"
        )


@demo.command("close")
@click.option("--ticket", required=True, type=int, help="broker position ticket to close")
@click.option("--symbol", default=None)
@click.option("--db", default=default_db_path)
@click.option("--volume", default=None, help="volume to close (defaults to full position)")
@click.option("--reason", default="operator close via CLI")
@click.option("--confirm", is_flag=True, help="explicit operator confirmation")
@click.option("--risk-ack", is_flag=True, help="explicit risk acknowledgement")
def demo_close(
    ticket: int,
    symbol: str | None,
    db: str,
    volume: str | None,
    reason: str,
    confirm: bool,
    risk_ack: bool,
) -> None:
    """Close an open DEMO position by ticket."""
    from decimal import Decimal

    if not (confirm and risk_ack):
        click.echo(
            "closing a DEMO position requires explicit confirmation and risk acknowledgement: "
            f"qts demo close --ticket {ticket} --confirm --risk-ack --db {db}",
            err=True,
        )
        raise SystemExit(2)

    session = _demo_session(symbol or "", db)
    vol = Decimal(volume) if volume is not None else None
    try:
        out = session.close_position(ticket, volume=vol, reason=reason, actor="cli:demo-close")
        click.echo(json.dumps(out, indent=2, default=str))
    except Exception as exc:
        click.echo(f"failed to close position {ticket}: {exc}", err=True)
        raise SystemExit(2) from exc


@demo.command("kill")
@click.option("--db", default=default_db_path)
@click.option("--reason", default="operator kill via CLI")
def demo_kill(db: str, reason: str) -> None:
    """Raise the durable kill switch and halt the DEMO stage machine."""
    session = _demo_session("", db)
    out = session.raise_kill_switch(reason)
    click.echo(json.dumps(out, indent=2, default=str))


@demo.command("journal")
@click.option("--db", default=default_db_path)
@click.option("--limit", default=20, type=int)
@click.option("--export", "export_path", default=None)
def demo_journal(db: str, limit: int, export_path: str | None) -> None:
    """Show/export the DEMO order journal (forward-observation audit trail)."""
    session = _demo_session("", db)
    if export_path:
        path = session.journal.export_jsonl(export_path)
        click.echo(f"exported to {path}")
        return
    for row in session.journal.list_orders(limit=limit):
        click.echo(
            f"#{row['journal_id']} {row['created_at']} {row['label']} {row['side']} {row['requested_lots']} "
            f"{row['symbol']} state={row['state']} broker_order={row['broker_order_id']} "
            f"pos={row['broker_position_id']} px={row['executed_price']} slip_bps={row['slippage_bps']} "
            f"pnl={row['realized_pnl']} exit={row['exit_reason']}"
        )


@demo.command("revoke")
@click.option("--reason", required=True)
@click.option("--actor", default="owner")
def demo_revoke(reason: str, actor: str) -> None:
    """Revoke the DEMO authorization (additive record; artifact is never edited)."""
    from qts.lifecycle.demo_authorization import revoke_authorization

    path = revoke_authorization(reason=reason, actor=actor)
    click.echo(f"revocation written: {path}")
    click.echo("DEMO_EXECUTION is DISABLED BY POLICY again until a new authorization artifact is recorded.")

