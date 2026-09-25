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


def _setup_symbol_map() -> tuple[dict[str, str], str | None]:
    """The operator's canonical -> venue alias table, and where it came from.

    The table lives in the machine-local setup (``data/setup/mt5_setup.json``,
    override ``QTS_SETUP_FILE``) — it is gitignored on purpose, because it is a
    fact about THIS broker account, not about the repository. ``None`` as the
    second element means no setup file exists on this machine, so the binding
    can only be proven where the terminal is.
    """
    import os

    from qts.config.wizard import setup_file

    path = setup_file()
    if not path.exists():
        env = os.getenv("QTS_MT5_SYMBOL_MAP") or ""
        out: dict[str, str] = {}
        for pair in env.replace(";", ",").split(","):
            if ":" in pair:
                key, _, value = pair.partition(":")
                out[key.strip()] = value.strip()
        return (out, f"QTS_MT5_SYMBOL_MAP={env or '<unset>'}" if out else None)
    try:
        from qts.config.wizard import load_setup

        saved = load_setup()
    except Exception as exc:  # noqa: BLE001 - report, never guess
        return {}, f"{path}: unreadable ({type(exc).__name__}: {exc})"
    raw = saved.get("symbol_map")
    table = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    return table, f"{path} symbol={saved.get('symbol')!r} symbol_map={table or '<none declared>'}"


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

        # The policy document itself must be sealed: config_hash pins the
        # parameters and code_hash the provider, so without policy_hash the
        # limits, hours and kill conditions could be rewritten after
        # registration while every other hash still matched.
        from qts.lifecycle.demo_policy import policy_fingerprint

        policy_doc = raw_entry.get("policy") or {}
        declared_hash = str(policy_doc.get("policy_hash") or "")
        computed_hash = policy_fingerprint(policy_doc)
        sealed = bool(declared_hash) and declared_hash == computed_hash
        if not declared_hash:
            seal_detail = "policy_hash missing — the policy document is not pinned"
        elif sealed:
            seal_detail = f"{declared_hash[:16]}… matches the document"
        else:
            seal_detail = f"DRIFT: declared {declared_hash[:16]}…, computed {computed_hash[:16]}…"
        row(
            "policy document is sealed (policy_hash)",
            PASS if sealed else FAIL,
            seal_detail,
        )
        failures += 0 if sealed else 1

        # Symbol binding: the venue alias the entry was verified against must
        # resolve back to the canonical symbol the policy allows. A policy that
        # allows XAUUSD must not be satisfiable by a session configured as
        # XAUUSD@ that never normalises (the defect the real terminal exposed).
        from qts.adapters.mt5_adapter import canonical_symbol

        registered_alias = str(raw_entry.get("broker_symbol") or "")
        allowed = [str(x) for x in (policy_doc.get("allowed_symbols") or [])]
        pinned_ok = bool(registered_alias) and bool(allowed)
        row(
            "registry pins the venue alias and the policy its canonical symbol",
            PASS if pinned_ok else FAIL,
            f"broker_symbol={registered_alias or '<MISSING>'} allowed_symbols={allowed or '<MISSING>'}",
        )
        failures += 0 if pinned_ok else 1

        # Resolving the alias to the canonical symbol needs THIS machine's
        # alias table, which is machine-local by design — so it is a terminal-
        # side fact unless a setup file exists here to check.
        setup_symbol_map, setup_source = _setup_symbol_map()
        if pinned_ok:
            resolved = canonical_symbol(registered_alias, setup_symbol_map)
            if setup_source is None:
                row(
                    "venue alias resolves to the policy's canonical symbol",
                    INFO,
                    "no machine-local setup on this host — prove it with: "
                    "qts demo connectivity   (or declare symbol_map in data/setup/mt5_setup.json)",
                )
            else:
                resolved_ok = resolved in allowed
                remedy = (
                    ""
                    if resolved_ok
                    else f'; remedy: add "symbol_map": {{"{allowed[0]}": "{registered_alias}"}} '
                    "to data/setup/mt5_setup.json"
                )
                row(
                    "venue alias resolves to the policy's canonical symbol",
                    PASS if resolved_ok else FAIL,
                    f"{registered_alias} -> {resolved} (policy allows {allowed}); {setup_source}{remedy}",
                )
                failures += 0 if resolved_ok else 1

        # Stop-loss contract: a policy requiring a stop must declare the
        # distance used to derive it, or no order can ever carry one.
        stop_logic = policy_doc.get("stop_loss_logic") or {}
        stop_ok = (not stop_logic.get("required")) or (stop_logic.get("distance_price") is not None)
        row(
            "required stop-loss is derivable from the policy",
            PASS if stop_ok else FAIL,
            f"required={stop_logic.get('required')} distance_price={stop_logic.get('distance_price')} "
            f"source={stop_logic.get('source')}",
        )
        failures += 0 if stop_ok else 1

    # ------------------------------------------------- authority refresh path
    # Permission decays after REVERIFY_TTL_S by design, so a refresh path must
    # exist that does NOT require an illegal stage self-transition.
    from qts.lifecycle.demo_authority import REVERIFY_TTL_S, DemoExecutionAuthority
    from qts.lifecycle.demo_stage import _TRANSITIONS

    refresh_ok = callable(getattr(DemoExecutionAuthority, "refresh", None))
    row(
        "explicit authority re-verification path (qts demo reverify)",
        PASS if refresh_ok else FAIL,
        f"DemoExecutionAuthority.refresh present={refresh_ok}; REVERIFY_TTL_S={REVERIFY_TTL_S}s (unchanged)",
    )
    failures += 0 if refresh_ok else 1

    self_edges = [
        f"{src.value} -> {dst.value}" for src, targets in _TRANSITIONS.items() for dst in targets if src == dst
    ]
    row(
        "stage machine has no self-transitions",
        PASS if not self_edges else FAIL,
        f"self-edges: {self_edges or 'none'} — a refresh never needs STAGE_2 -> STAGE_2",
    )
    failures += 0 if not self_edges else 1

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
        ("identity pin symbol provenance (canonical <-> alias)", "qts demo connectivity --pin"),
        ("authority refresh after the 120 s readiness window", "qts demo reverify --confirm --risk-ack"),
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
        ("tests/integration/test_demo_session_wiring.py", "identity, symbol, quote, order-check, 31-check gate"),
        ("tests/integration/test_demo_autopilot_loop.py", "autonomous loop: submit, manage, close, reconcile"),
        ("tests/integration/test_demo_research_policy_loop.py", "registered policy enforcement, code drift, hours, budget"),
        ("tests/integration/test_demo_failure_modes.py", "idempotency, cold start, concurrency, kill switch, failure-closed"),
        ("tests/integration/test_demo_cli.py", "the documented operator procedure"),
        ("tests/adversarial/", "authorization scope, LIVE lock, per-safeguard refusals"),
        ("tests/unit/test_demo_research_policy.py", "policy schema completeness, policy_hash sealing"),
        ("tests/integration/test_demo_lifecycle_audit.py", "real-terminal defects: symbol binding, TTL refresh, SL derivation"),
    ):
        print(f"  {name.ljust(52)} {what}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
