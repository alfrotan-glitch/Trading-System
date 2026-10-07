"""Re-seal the shipped DEMO forward research policy in the registry.

Why this is a script and not a hand-written JSON edit
-----------------------------------------------------
The registry entry pins four hashes:

* ``params_hash`` — registry fingerprint of the frozen parameter set;
* ``config_hash`` — the same fingerprint inside the policy document;
* ``code_hash``   — sha256 of the signal-provider source file on disk;
* ``policy_hash`` — fingerprint of the policy document itself.

Hand-editing them is how a registry comes to *claim* a hash it does not have —
which is exactly the state this repository shipped once (the entry's ``params``
block and its declared ``params_hash`` disagreed, so the registry was invalid
and the strategy ineligible). This script recomputes every hash from the files
on disk, proves that each quantity registered twice (parsed parameters vs the
policy's mirrored limits) still agrees, validates the complete policy, and only
then writes the registry.

The frozen parameters are read from the provider module's ``DEFAULT_PARAMS`` —
the single source of truth — never from a copy kept inside this script, so a
parameter cannot drift without the runtime ``config_hash()`` drifting with it.

Usage::

    python scripts/register_demo_research_policy.py            # re-seal
    python scripts/register_demo_research_policy.py --check    # validate only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from qts.adapters.mt5_adapter import MT5Adapter  # noqa: E402
from qts.lifecycle.demo_policy import policy_fingerprint  # noqa: E402
from qts.lifecycle.demo_registry import (  # noqa: E402
    DIAGNOSTIC_STATUSES,
    load_registry,
    params_fingerprint,
    resolve_entry,
)
from qts.research import demo_trend_tsmom  # noqa: E402

#: The registry file is the shipped evidence document; this script edits it in place.
REGISTRY_PATH = REPO / "data/evidence/demo_forward_validation_registry_2026-09-23.json"
PROVIDER_SOURCE = Path(demo_trend_tsmom.__file__).resolve()


def _mirrors(entry: dict, params: dict) -> list[str]:
    """Every quantity that is registered twice must still agree.

    A parsed parameter drives the signal; the policy's copy is what the gate
    enforces. Two declarations of the same number that are never compared is how
    an order comes to carry a stop nobody registered.
    """
    policy = dict(entry.get("policy") or {})
    entry_conditions = dict(policy.get("entry_conditions") or {})
    problems: list[str] = []

    def compare(label: str, left, right) -> None:
        if left is None or right is None:
            problems.append(f"{label}: one side is missing ({left!r} vs {right!r})")
            return
        try:
            if abs(float(left) - float(right)) > 1e-9:
                problems.append(f"{label}: {left!r} != {right!r}")
        except (TypeError, ValueError):
            if left != right:
                problems.append(f"{label}: {left!r} != {right!r}")

    compare("entry_conditions.fast_ema", entry_conditions.get("fast_ema"), params.get("fast_ema"))
    compare("entry_conditions.slow_ema", entry_conditions.get("slow_ema"), params.get("slow_ema"))
    compare(
        "signal_logic.bar_timeframe_minutes",
        (policy.get("signal_logic") or {}).get("bar_timeframe_minutes"),
        params.get("bar_timeframe_minutes"),
    )
    compare(
        "entry_conditions.bar_timeframe_minutes",
        entry_conditions.get("bar_timeframe_minutes"),
        params.get("bar_timeframe_minutes"),
    )
    compare(
        "stop_loss_logic.distance_price",
        (policy.get("stop_loss_logic") or {}).get("distance_price"),
        params.get("stop_distance_price"),
    )
    compare(
        "exit_conditions.max_hold_seconds",
        (policy.get("exit_conditions") or {}).get("max_hold_seconds"),
        params.get("max_hold_seconds"),
    )
    compare(
        "stale_data_protection.max_tick_age_s",
        (policy.get("stale_data_protection") or {}).get("max_tick_age_s"),
        params.get("max_tick_age_s"),
    )
    compare("position_sizing.lots", (policy.get("position_sizing") or {}).get("lots"), params.get("lots"))
    compare("size_policy.lots", (entry.get("size_policy") or {}).get("lots"), params.get("lots"))
    compare(
        "stop_policy.distance_price",
        (entry.get("stop_policy") or {}).get("distance_price"),
        params.get("stop_distance_price"),
    )
    compare(
        "exit_policy.max_hold_seconds",
        (entry.get("exit_policy") or {}).get("max_hold_seconds"),
        params.get("max_hold_seconds"),
    )
    compare("max_orders_per_day", policy.get("max_orders_per_day"), entry.get("max_orders_per_day"))
    return problems


def _provider_instance():
    """A provider instance used only to read its declared warmup plan."""
    return demo_trend_tsmom.TrendTimeSeriesMomentum()


def reseal(doc: dict) -> tuple[dict, list[str]]:
    """Return the registry document with every hash recomputed from disk."""
    problems: list[str] = []
    doc = json.loads(json.dumps(doc))  # never mutate the caller's document
    params = json.loads(json.dumps(demo_trend_tsmom.DEFAULT_PARAMS))  # JSON types, verbatim
    strategy_id = demo_trend_tsmom.STRATEGY_ID

    entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict)]
    target = next((e for e in entries if e.get("strategy_id") == strategy_id), None)
    if target is None:
        return doc, [
            f"refusing to register: {strategy_id} is not the shipped registry entry "
            f"(found {[e.get('strategy_id') for e in entries]})"
        ]

    status = str(target.get("status") or "").upper()
    if status not in DIAGNOSTIC_STATUSES:
        problems.append(f"entry {strategy_id}: status {status!r} is not a DEMO diagnostic status — fail closed")
    if str(target.get("signal_provider") or "") != (
        f"{demo_trend_tsmom.__name__}:{demo_trend_tsmom.TrendTimeSeriesMomentum.__name__}"
    ):
        problems.append(
            f"entry {strategy_id}: signal_provider {target.get('signal_provider')!r} does not point at the provider"
        )
    preregistration = str(target.get("preregistration_artifact") or "")
    if not preregistration or not (REPO / preregistration).exists():
        problems.append(f"entry {strategy_id}: preregistration_artifact {preregistration!r} does not exist")

    policy = target.get("policy")
    if not isinstance(policy, dict):
        return doc, problems + [f"entry {strategy_id}: no policy block — an unspecified experiment may not trade"]

    problems.extend(f"entry {strategy_id}: {p}" for p in _mirrors(target, params))
    if policy.get("validated_edge") is not False:
        problems.append(f"entry {strategy_id}: validated_edge must be false — no validated edge is claimed")

    # The bounded restart window is a *registered* quantity, not an implementation
    # detail: it decides how much history a restarted process consults before it
    # is allowed to trade.
    data_requirements = dict(policy.get("min_data_requirements") or {})
    if data_requirements.get("requires_historical_dataset") is not False:
        problems.append(
            f"entry {strategy_id}: min_data_requirements.requires_historical_dataset must be false — "
            "warmup reads a bounded restart window, not a backtest dataset"
        )
    plan = demo_trend_tsmom.TrendTimeSeriesMomentum.warmup_plan(_provider_instance())
    data_requirements["restart_warmup"] = {
        "timeframe_minutes": int(plan["timeframe_minutes"]),
        "bars": int(plan["bars"]),
        "completed_only": bool(plan["completed_only"]),
        "max_bars": int(MT5Adapter.MAX_WARMUP_BARS),
        "source": "broker completed M15 bars (forming bar excluded)",
        "on_unavailable": "start cold and warm up live; never fabricate history",
    }
    policy["min_data_requirements"] = data_requirements

    code_hash = hashlib.sha256(PROVIDER_SOURCE.read_bytes()).hexdigest()
    params_hash = params_fingerprint(params)

    if problems:
        return doc, problems

    target["params"] = params
    target["params_hash"] = params_hash
    policy["config_hash"] = params_hash
    policy["code_hash"] = code_hash
    policy["code_source"] = str(PROVIDER_SOURCE.relative_to(REPO)).replace("\\", "/")
    policy["policy_hash"] = policy_fingerprint(policy)
    return doc, []


def _stale_fields(on_disk: dict, sealed: dict) -> list[str]:
    """Which registered quantities no longer match the files on disk."""
    stale: list[str] = []

    def entry_of(doc: dict):
        return next((e for e in (doc.get("entries") or []) if e.get("strategy_id") == demo_trend_tsmom.STRATEGY_ID), None)

    before, after = entry_of(on_disk), entry_of(sealed)
    if after is None or before is None:
        return [f"{demo_trend_tsmom.STRATEGY_ID} is not a registry entry"]
    if before.get("params") != after.get("params"):
        stale.append("params")
    for field in ("params_hash",):
        if before.get(field) != after.get(field):
            stale.append(field)
    for field in ("code_hash", "config_hash", "policy_hash"):
        if (before.get("policy") or {}).get(field) != (after.get("policy") or {}).get(field):
            stale.append(f"policy.{field}")
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without writing the registry")
    args = parser.parse_args(argv)

    on_disk = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    sealed, problems = reseal(on_disk)
    if problems:
        print("policy NOT sealed:")
        for problem in problems:
            print(f"  - {problem}")
        return 2

    stale = _stale_fields(on_disk, sealed)
    if args.check:
        if stale:
            print(f"registry STALE — {REGISTRY_PATH.relative_to(REPO)} does not match the files on disk:")
            for field in stale:
                print(f"  - {field}")
            print("run: python scripts/register_demo_research_policy.py")
            return 1
        print(f"registry up to date: {', '.join(stale) or 'all registered hashes match the files on disk'}")
        return 0

    stale = _stale_fields(on_disk, sealed)
    REGISTRY_PATH.write_text(json.dumps(sealed, indent=2) + "\n", encoding="utf-8")
    if stale:
        print(f"re-sealed {REGISTRY_PATH.relative_to(REPO)} ({len(stale)} field(s) updated: {', '.join(stale)})")
    else:
        print(f"re-sealed {REGISTRY_PATH.relative_to(REPO)} (already up to date)")

    registry = load_registry(REGISTRY_PATH)
    entry, reasons = resolve_entry(registry, demo_trend_tsmom.STRATEGY_ID)
    if not registry.valid or entry is None:
        print("registry INVALID after seal:")
        for reason in registry.reasons or reasons:
            print(f"  - {reason}")
        return 3
    if _stale_fields(json.loads(REGISTRY_PATH.read_text(encoding="utf-8")), sealed):
        print("seal did not persist — refusing to report success")
        return 3

    print(f"registry valid: {entry.strategy_id} [{entry.status}] policy={entry.policy_id}")
    print(f"  params_hash/config_hash = {entry.params_hash}")
    print(f"  code_hash               = {entry.policy.code_hash}")
    print(f"  policy_hash             = {entry.policy.raw.get('policy_hash')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
