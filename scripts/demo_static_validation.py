"""Offline validation of the DEMO execution boundary (no terminal required).

Run this before the first DEMO order — and after any change to the
authorization, the registry or the gate. It checks everything that can be
checked **without** a broker: mode resolution, the LIVE lock, the authorization
artifact and its scope, the registered research policy, the risk-limit
relationship, the journal and the kill switch.

Anything that genuinely needs the terminal (identity pin, quote, symbol spec,
reconciliation) is reported as `NEEDS TERMINAL` with the command that proves it,
never as a pass. Exit code 0 means every offline check passed.

    python scripts/demo_static_validation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from qts.domain.modes import ExecutionMode  # noqa: E402
from qts.execution.demo_journal import DemoOrderJournal, summarize  # noqa: E402
from qts.lifecycle.demo_authorization import (  # noqa: E402
    authorization_status,
    resolve_demo_execution_policy,
)
from qts.lifecycle.demo_registry import load_registry, registry_status  # noqa: E402
from qts.lifecycle.demo_stage import ORDER_STAGES, DemoStage, DemoStageMachine  # noqa: E402
from qts.risk.authority import resolve_risk_limits  # noqa: E402

PASS, FAIL, INFO = "PASS", "FAIL", "NEEDS TERMINAL"
ROWS: list[tuple[str, str, str]] = []


def row(item: str, status: str, detail: str) -> None:
    ROWS.append((item, status, detail))


def main() -> int:
    failures = 0

    # ---------------------------------------------------------- authorization
    status = authorization_status()
    demo_policy = resolve_demo_execution_policy(mode="DEMO_EXECUTION")
    row(
        "authorization (DEMO_EXECUTION)",
        PASS if demo_policy.enabled else FAIL,
        f"{demo_policy.state} — {demo_policy.authorization_id or 'no artifact'}",
    )
    failures += 0 if demo_policy.enabled else 1

    # ---------------------------------------------------------------- LIVE lock
    live = resolve_demo_execution_policy(mode="LIVE")
    row("LIVE is locked", PASS if not live.enabled else FAIL, f"LIVE -> {live.state}: {live.reasons[0] if live.reasons else ''}")
    failures += 0 if not live.enabled else 1

    observation_modes = [m for m in ExecutionMode if not m.can_submit_broker_orders]
    refused = [m.value for m in observation_modes if not resolve_demo_execution_policy(mode=m.value).enabled]
    row(
        "non-broker modes cannot trade",
        PASS if len(refused) == len(observation_modes) else FAIL,
        f"{', '.join(sorted(refused))} refused",
    )
    failures += 0 if len(refused) == len(observation_modes) else 1

    # ------------------------------------------------------------- scope rules
    if status.authorization is not None:
        scope = status.authorization.document.scope
        scope_ok = (
            str(scope.account_type).lower() == "demo"
            and scope.live_locked
            and "LIVE" not in {str(m).upper() for m in scope.modes_allowed}
            and float(scope.real_capital_exposure_usd) == 0.0
            and not scope.funds_transfer_permitted
            and not scope.broker_switch_permitted
        )
        row(
            "authorization scope (DEMO only, LIVE locked, no transfers)",
            PASS if scope_ok else FAIL,
            f"account_type={scope.account_type} modes={scope.modes_allowed} "
            f"real_capital={scope.real_capital_exposure_usd} transfers={scope.funds_transfer_permitted} "
            f"broker_switch={scope.broker_switch_permitted}",
        )
        failures += 0 if scope_ok else 1
        row(
            "authorization integrity (hash + not revoked)",
            PASS if status.valid and not status.revoked else FAIL,
            f"revoked={status.revoked} reasons={status.reasons or 'none'}",
        )
        failures += 0 if status.valid and not status.revoked else 1
    else:
        row("authorization scope", FAIL, "no valid artifact")
        failures += 1

    # ------------------------------------------------------- registered policy
    registry = registry_status()
    entry = registry.get("resolved_strategy")
    if entry is None:
        row("registered experiment", PASS, f"none — {registry['trading_state']} (nothing may trade)")
    else:
        policy_artifact = Path(entry.get("preregistration_artifact") or "")
        policy_ok = (
            entry.get("policy_class") == "DEMO_FORWARD_RESEARCH_POLICY"
            and bool(entry.get("policy_id"))
            and bool(entry.get("hypothesis_id"))
            and policy_artifact.exists()
        )
        row(
            "registered experiment",
            PASS if policy_ok else FAIL,
            f"{entry['strategy_id']} status={entry['status']} class={entry.get('policy_class')} "
            f"validated_edge={entry.get('validated_edge')} hypothesis={entry.get('hypothesis_id')}",
        )
        failures += 0 if policy_ok else 1
        row(
            "preregistration artifact exists",
            PASS if policy_artifact.exists() else FAIL,
            str(policy_artifact) if policy_artifact.exists() else f"missing: {policy_artifact}",
        )
        failures += 0 if policy_artifact.exists() else 1

        # Code hash: the registered policy must pin the provider source on disk.
        import hashlib
        import importlib
        import inspect

        raw = load_registry().raw
        raw_entry = next((e for e in raw.get("entries", []) if e.get("strategy_id") == entry["strategy_id"]), {})
        provider = raw_entry.get("signal_provider") or ""
        code_ok, code_detail = False, "no signal_provider registered"
        if provider:
            try:
                module_path, _, attr = provider.partition(":")
                cls = getattr(importlib.import_module(module_path), attr)
                source = inspect.getsourcefile(cls)
                declared = (raw_entry.get("policy") or {}).get("code_hash") or ""
                actual = hashlib.sha256(Path(source).read_bytes()).hexdigest()
                code_ok = declared.lower() == actual
                code_detail = f"{provider} ({'match' if code_ok else f'DRIFT {declared[:12]} != {actual[:12]}'})"
            except Exception as exc:  # noqa: BLE001 - report, never guess
                code_detail = f"{provider}: {type(exc).__name__}: {exc}"
        row("provider code hash matches the registration", PASS if code_ok else FAIL, code_detail)
        failures += 0 if code_ok else 1

        # The policy may only tighten the canonical DEMO limits.
        limits = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
        policy_limits = (raw_entry.get("policy") or {})
        widening = []
        pairs = (
            ("max_spread_bps", "max_spread_bps"),
            ("max_simultaneous_exposure_lots", "max_quantity"),
            ("max_simultaneous_exposure_lots", "max_exposure_lots"),
            ("max_daily_loss", "daily_loss_limit"),
        )
        for policy_key, limit_key in pairs:
            declared = policy_limits.get(policy_key)
            canonical = getattr(limits.limits, limit_key, None)
            if declared is not None and canonical is not None and float(declared) > float(canonical):
                widening.append(f"{policy_key}={declared} > {limit_key}={canonical}")
        row(
            "policy tightens (never loosens) the DEMO limits",
            PASS if not widening else FAIL,
            "; ".join(widening) if widening else f"canonical {ExecutionMode.DEMO_EXECUTION.value} limits respected",
        )
        failures += 0 if not widening else 1

        row(
            "minimum size handling",
            PASS if str((raw_entry.get("size_policy") or {}).get("mode")) in ("broker_minimum", "fixed") else FAIL,
            f"size_policy={json.dumps(raw_entry.get('size_policy') or {})}",
        )

    # ------------------------------------------------------------ journal state
    journal = DemoOrderJournal()
    summary = summarize(journal)
    row(
        "order journal (DEMO evidence)",
        PASS,
        f"orders={summary.orders} realized_pnl={summary.realized_pnl} "
        f"open={len(journal.open_orders())} db={journal.db_path}",
    )
    dd = journal.drawdown()
    row(
        "drawdown measurement available",
        PASS,
        f"peak={dd['peak']} current={dd['current']} drawdown={dd['drawdown']} samples={dd['samples']}",
    )

    # ----------------------------------------------------------- kill switch
    record = DemoStageMachine().current()
    known = record.stage in {s.value for s in DemoStage}
    row(
        "stage machine",
        PASS if known else FAIL,
        f"stage={record.stage} orders_permitted={record.stage in ORDER_STAGES} "
        f"(order stages: {', '.join(sorted(ORDER_STAGES))})",
    )
    failures += 0 if known else 1

    # ------------------------------------------------------- terminal-bound
    for item, command in (
        ("broker identity pin", "qts demo connectivity --pin     # then --confirm-pin"),
        ("account is DEMO + broker identity verified", "qts demo connectivity"),
        ("symbol mapping (XAUUSD -> broker alias)", "qts demo connectivity"),
        ("14-check readiness (fresh)", "qts demo connectivity"),
        ("reconciliation vs the venue", "qts demo verify"),
        ("pre-trade gate on a live quote", "qts demo preflight --side BUY"),
    ):
        row(item, INFO, command)

    width = max(len(i) for i, _, _ in ROWS)
    print(f"{'check'.ljust(width)}  status           detail")
    print("-" * 120)
    for item, state, detail in ROWS:
        print(f"{item.ljust(width)}  {state.ljust(15)}  {detail}")
    print("-" * 120)
    print(f"offline checks failed: {failures}")
    print("covered by tests (run: pytest --run-integration):")
    for name, what in (
        ("tests/integration/test_demo_session_wiring.py", "identity, symbol, quote, order-check, 29-check gate"),
        ("tests/integration/test_demo_autopilot_loop.py", "autonomous loop: submit, manage, close, reconcile"),
        ("tests/integration/test_demo_research_policy_loop.py", "registered policy enforcement, code drift, hours, budget"),
        ("tests/integration/test_demo_failure_modes.py", "idempotency, cold start, concurrency, kill switch, failure-closed"),
        ("tests/integration/test_demo_cli.py", "the documented operator procedure"),
        ("tests/adversarial/", "authorization scope, LIVE lock, per-safeguard refusals"),
        ("tests/unit/test_demo_research_policy.py", "policy schema completeness"),
    ):
        print(f"  {name.ljust(52)} {what}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
