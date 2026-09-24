"""Register (or re-seal) the DEMO forward research policy in the registry.

Why this is a script and not a hand-written JSON edit
----------------------------------------------------
The registry entry pins three hashes:

* ``config_hash`` — the fingerprint of the frozen parameter set;
* ``code_hash``   — the sha256 of the signal-provider source file;
* ``params_hash`` — the registry's own fingerprint of ``params``.

Hand-editing those into a JSON file is how a registry entry comes to *claim* a
hash it does not have. This script recomputes all three from the files on disk,
validates the complete policy with :func:`qts.lifecycle.demo_policy.validate_policy`,
and only then writes the registry. Re-running it after a legitimate,
preregistered change re-seals the entry; running it after an unpreregistered
edit will still seal it, which is exactly why the change-control rule in
``docs/preregistration_demo_execution_probe_2026-09-24.md`` §6 exists and why
the run is auditable in git.

Usage:  python scripts/register_demo_research_policy.py [--check]
        --check  validate the current registry without writing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from qts.lifecycle.demo_policy import POLICY_CLASS, POLICY_SCHEMA, validate_policy  # noqa: E402
from qts.lifecycle.demo_registry import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    REGISTRY_SCHEMA_V2,
    load_registry,
    params_fingerprint,
    resolve_entry,
)
from qts.research.demo_execution_probe import DEFAULT_PARAMS, STRATEGY_ID  # noqa: E402

POLICY_ID = "DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1"
HYPOTHESIS_ID = "H-EXEC-01"
PREREGISTRATION = "docs/preregistration_demo_execution_probe_2026-09-24.md"
PROVIDER_SOURCE = REPO / "src/qts/research/demo_execution_probe.py"

#: Mapping to the broker symbol the DEMO venue actually exposes.
BROKER_SYMBOL = "XAUUSD@"


def build_policy(params: dict, code_hash: str, config_hash: str) -> dict:
    """The complete, frozen specification of the forward experiment."""
    return {
        "schema": POLICY_SCHEMA,
        "policy_id": POLICY_ID,
        "strategy_id": STRATEGY_ID,
        "policy_class": POLICY_CLASS,
        "version": "1.0.0",
        "created_at": "2026-09-24T00:00:00+00:00",
        "preregistration_artifact": PREREGISTRATION,
        "hypothesis_id": HYPOTHESIS_ID,
        "purpose": (
            "Measure the DEMO venue's execution cost and control behaviour — spread at entry, slippage "
            "between requested and executed price, submission latency, protective-stop behaviour, "
            "time-exit behaviour, round-turn cost and reconciliation agreement — so that any future "
            "hypothesis can be judged against a known cost base. No directional or predictive claim."
        ),
        # ---------------------------------------------------------- honesty
        "validated_edge": False,
        "edge_statement": (
            "This policy does not establish a validated edge and must not be read as one: it is a "
            "DEMO forward measurement instrument. Entries are scheduled and direction-neutral, so any "
            "P&L reflects venue cost plus noise. DEMO performance does not constitute evidence of a "
            "durable, live-tradeable edge, and observations recorded under this policy may never be "
            "used to re-fit it or to select another strategy."
        ),
        # ----------------------------------------------------------- logic
        "signal_logic": {
            "type": "scheduled_sampling",
            "description": (
                "At most one entry per UTC hour, gated only on cost and data quality: a two-sided "
                "quote must exist, its age must be within max_tick_age_s, and the spread must be "
                "measurable (and within max_spread_bps before the provider requests an order)."
            ),
            "indicators": [],
            "prediction": "none — this policy makes no directional claim",
        },
        "entry_conditions": {
            "sample_interval_minutes": 60,
            "side_rule": "utc_hour_parity",
            "side_rule_detail": "BUY when the UTC hour is even, SELL when odd — deterministic and direction-neutral across samples",
            "require_two_sided_quote": True,
            "require_spread_measurable": True,
            "require_spread_within_max_spread_bps": True,
            "max_positions_open": 1,
        },
        "exit_conditions": {
            "max_hold_seconds": 900,
            "take_profit": None,
            "close_at_session_end": True,
            "detail": (
                "Close at 900 s, or earlier if the venue protective stop is hit. Exit reason and the "
                "venue's realized P&L are recorded either way; no discretionary exit."
            ),
        },
        "stop_loss_logic": {
            "required": True,
            "type": "fixed_price_distance",
            "distance_price": 2.00,
            "detail": "Protective stop 2.00 USD from the entry reference (ask for BUY, bid for SELL), attached to the order itself.",
        },
        "position_sizing": {
            "mode": "broker_minimum",
            "lots": 0.01,
            "detail": "Broker minimum regardless of equity — deterministic exposure, no equity-dependent sizing.",
        },
        # ---------------------------------------------------------- limits
        "max_simultaneous_exposure_lots": 0.01,
        "max_daily_loss": 5.00,
        "max_drawdown": 10.00,
        "max_orders_per_day": 2,
        "min_order_interval_s": 900,
        # ---------------------------------------------------------- market
        "allowed_symbols": ["XAUUSD"],
        "allowed_trading_hours": {
            "timezone": "UTC",
            "sessions": [
                {
                    "days": ["MON", "TUE", "WED", "THU", "FRI"],
                    "start": "08:00",
                    "end": "16:00",
                }
            ],
            "detail": (
                "London–New York overlap for XAUUSD: the liquid window in which a spread measurement is "
                "representative rather than a rollover artefact. No weekend or rollover sampling."
            ),
        },
        "max_spread_bps": 3.0,
        "max_slippage_bps": 2.0,
        # ------------------------------------------------------- execution
        "execution_delay_assumption_ms": 1500,
        "min_data_requirements": {
            "requires_historical_dataset": False,
            "required_checks": [
                "market_data_fresh",
                "spread_available",
                "broker_order_check",
                "symbol_mapping_canonical",
                "risk_limits_resolved",
                "kill_switch_functional",
                "reconciliation_ready",
            ],
            "detail": "Signal generation uses live venue quotes only; no historical dataset is consumed.",
        },
        "stale_data_protection": {
            "max_tick_age_s": 5.0,
            "on_stale": "NO_TRADE",
        },
        "duplicate_order_protection": {
            "idempotency_required": True,
            "min_order_interval_s": 900,
        },
        # -------------------------------------------------------- controls
        "kill_conditions": [
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
        ],
        "reconciliation_requirements": {
            "after_every_order": True,
            "after_every_close": True,
            "max_age_s": 120.0,
            "on_drift": "HALT",
        },
        # -------------------------------------------------------- provenance
        "code_hash": code_hash,
        "config_hash": config_hash,
        "data_hash": None,
        "data_hash_note": (
            "No historical dataset is consumed: requires_historical_dataset=false. The only data input "
            "is the pinned DEMO venue's live quote stream, whose provenance is the identity pin at "
            "data/evidence/demo_broker_identity_pin.json — there is no static dataset to hash."
        ),
        "code_source": str(PROVIDER_SOURCE.relative_to(REPO).as_posix()),
    }


def build_entry(params: dict, code_hash: str, config_hash: str) -> dict:
    return {
        "strategy_id": STRATEGY_ID,
        # ELIGIBLE_DIAGNOSTIC, not ELIGIBLE: this may trade to MEASURE, and it
        # carries no validated edge. Only a strategy with a validation artifact
        # may be registered as ELIGIBLE.
        "status": "ELIGIBLE_DIAGNOSTIC",
        "hypothesis_id": HYPOTHESIS_ID,
        "preregistration_artifact": PREREGISTRATION,
        "signal_provider": "qts.research.demo_execution_probe:ExecutionCostProbe",
        "params": params,
        "params_hash": params_fingerprint(params),
        "size_policy": {"mode": "broker_minimum", "lots": 0.01},
        "stop_policy": {"required": True, "type": "fixed_price_distance", "distance_price": 2.00},
        "exit_policy": {"max_hold_seconds": 900.0, "close_at_session_end": True},
        "allowed_symbols": ["XAUUSD"],
        "broker_symbol": BROKER_SYMBOL,
        "max_orders_per_day": 2,
        "notes": (
            "DEMO_FORWARD_RESEARCH_POLICY — execution-cost probe for the DEMO account. Not a validated "
            "strategy; see " + PREREGISTRATION + "."
        ),
        "policy": build_policy(params, code_hash, config_hash),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate the registry without writing")
    parser.add_argument("--registry", default=str(REPO / DEFAULT_REGISTRY_PATH))
    args = parser.parse_args()

    params = dict(DEFAULT_PARAMS)
    code_hash = hashlib.sha256(PROVIDER_SOURCE.read_bytes()).hexdigest()
    config_hash = params_fingerprint(params)

    if args.check:
        registry = load_registry(args.registry)
        entry, reasons = resolve_entry(registry)
        print(json.dumps(registry.as_dict(), indent=2, sort_keys=True, default=str))
        if entry is None:
            print("RESOLVED: none — NO_TRADE")
            print("reasons:")
            for r in reasons:
                print("  -", r)
            return 1
        print(f"RESOLVED: {entry.strategy_id} status={entry.status} policy={entry.policy_id}")
        return 0

    entry = build_entry(params, code_hash, config_hash)
    pol, problems = validate_policy(entry["policy"], params)
    if pol is None:
        print("policy refused:")
        for p in problems:
            print("  -", p)
        return 2

    path = Path(args.registry)
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    doc.setdefault("updated_at", "2026-09-23T14:57:17+00:00")
    previous_status = doc.get("current_status")
    if previous_status and previous_status != "TRADING_ELIGIBLE_DIAGNOSTIC":
        history = list(doc.get("status_history") or [])
        history.append(
            {
                "at": str(doc.get("updated_at")),
                "current_status": previous_status,
                "status_note": doc.get("status_note", ""),
            }
        )
        doc["status_history"] = history
    doc["schema"] = REGISTRY_SCHEMA_V2
    doc["updated_at"] = "2026-09-24T00:00:00+00:00"
    doc["current_status"] = "TRADING_ELIGIBLE_DIAGNOSTIC"
    doc["status_note"] = (
        "One registered DEMO_FORWARD_RESEARCH_POLICY (H-EXEC-01, execution-cost probe) with status "
        "ELIGIBLE_DIAGNOSTIC: it may trade on the DEMO account to MEASURE execution cost and control "
        "behaviour, and it carries no validated edge. No strategy is registered as ELIGIBLE because no "
        "hypothesis has passed validation (reports/research_cycle_closure_2026-09-23.json: "
        "NO_VALIDATED_EDGE). DEMO_EXECUTION is authorized; LIVE remains locked; real capital exposure 0."
    )
    doc.setdefault(
        "research_integrity",
        {
            "optimization_allowed": False,
            "no_forward_fitting": True,
            "parameters_frozen": True,
            "demo_results_are_not_edge_evidence": True,
            "forward_observations_never_reused_as_research": True,
        },
    )
    entries = [e for e in (doc.get("entries") or []) if e.get("strategy_id") != STRATEGY_ID]
    entries.append(entry)
    doc["entries"] = entries
    path.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    registry = load_registry(path)
    resolved, reasons = resolve_entry(registry)
    print(f"wrote {path}")
    print(f"registry valid: {registry.valid}")
    print(f"resolved: {resolved.strategy_id if resolved else None} status={resolved.status if resolved else '-'}"
          f" policy={resolved.policy_id if resolved else '-'}")
    for r in reasons:
        print("  -", r)
    return 0 if resolved is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
