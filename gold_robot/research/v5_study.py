"""QTS V5 frozen prospective champion/challenger protocol.

Same broker native Strategy Tester source/broker/date/risk, two actual
simulations. A proposal drafted from past trades never validates itself.
Run comparison only after a distinct evaluation period finishes. NO orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ten_trade_learning import validate_positions

SCHEMA = "qts.mt5.v5.preregistered_study.v1"
OUTPUT_SCHEMA = "qts.mt5.v5.native_champion_challenger_comparison.v1"
VARIANTS = ("ADAPTIVE_V4", "ADAPTIVE_V5_VETO")


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso_date(value: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y.%m.%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("Use exact yyyy.MM.dd study dates") from exc
    if parsed.strftime("%Y.%m.%d") != value:
        raise ValueError("Noncanonical date")
    return parsed


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("Study/evidence file already exists; never silently overwrite")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def freeze(reflection: dict, manifest_bytes: bytes, *,
           style: int, regime: str, checkpoint: int,
           from_date: str, to_date: str,
           now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Freeze requires timezone-aware UTC time")
    if reflection.get("schema") != "qts.mt5.ten_trade_reflection.v1" or (
        reflection.get("live"), reflection.get("can_self_promote_strategy"),
        reflection.get("can_send_orders"), reflection.get("edge_validated")) != (
        "LOCKED", False, False, False):
        raise ValueError("Untrusted 10-trade research-only source")
    if not isinstance(reflection.get("read_only_native_attribution_sha256"), str):
        raise ValueError("Native broker source hash absent")
    expected = reflection.get("complete_checkpoints")
    if type(expected) is not int or expected < 1:
        raise ValueError("No fully observed 10-trade checkpoint")
    if type(style) is not int or style not in (0, 1, 2, 3, 4, 5, 6, 8):
        raise ValueError("Invalid frozen strategy")
    if regime not in ("RANGE", "TRANSITION", "TREND"):
        raise ValueError("Invalid frozen market regime")
    if type(checkpoint) is not int or checkpoint < 1 or checkpoint > expected:
        raise ValueError("Unobserved or invalid checkpoint")
    batches = reflection.get("nonoverlapping_chronological_checkpoints")
    if not isinstance(batches, list) or len(batches) != expected:
        raise ValueError("Incomplete frozen 10-trade batch history")
    batch = batches[checkpoint-1]
    if batch.get("checkpoint") != checkpoint or type(batch.get("last_exit_ms")) is not int:
        raise ValueError("Untrusted checkpoint exit clock")
    if not isinstance(reflection.get("proposed_shadow_only_revisions"), list) or not any(
        p.get("checkpoint") == checkpoint and p.get("style") == style and
        p.get("regime") == regime and
        p.get("candidate_repair") == "SHADOW_ONLY_SKIP_STYLE_IN_SPECIFIC_REGIME"
        for p in reflection["proposed_shadow_only_revisions"] if isinstance(p, dict)
    ):
        raise ValueError("No recorded original strategy/regime proposal exists")
    start, end = iso_date(from_date), iso_date(to_date)
    seen_last = datetime.fromtimestamp(batch["last_exit_ms"]/1000, timezone.utc).date()
    if start <= seen_last or start <= now.astimezone(timezone.utc).date():
        raise ValueError("Evaluation must START after all training exits and the plan creation day")
    if end <= start or (end-start).days > 370:
        raise ValueError("Use bounded separate future test window")
    try:
        checks = json.loads(manifest_bytes)
        assert isinstance(checks["sha256_files"], list)
    except (ValueError, KeyError, TypeError, AssertionError) as exc:
        raise ValueError("Missing canonical source SHA256 manifest") from exc
    report_bytes = canonical(reflection)
    plan = {
        "schema": SCHEMA,
        "created_at_utc": now.astimezone(timezone.utc).isoformat(),
        "from_date": from_date, "to_date": to_date,
        "frozen_style": style, "frozen_regime": regime,
        "frozen_regime_id": {"RANGE": 0, "TRANSITION": 1, "TREND": 2}[regime],
        "origin_checkpoint": checkpoint,
        "origin_last_broker_exit_ms": batch["last_exit_ms"],
        "reflection_sha256": digest(report_bytes),
        "native_attribution_sha256": reflection["read_only_native_attribution_sha256"],
        "source_manifest_sha256": digest(manifest_bytes),
        "native_symbol": "XAUUSD@", "native_model": 4, "native_timeframe": "M15",
        "native_deposit_usd": 3000,
        "broker_fees_qualified": False,
        "real_time_broker_execution_proven": False,
        "hypothesis": "SKIP_EXACT_V4_SELECTED_STYLE_IN_ORIGINAL_CLOSED_BAR_REGIME",
        "champion": VARIANTS[0], "challenger": VARIANTS[1],
        "no_extra_selections_on_veto": True,
        "live": "LOCKED", "edge_validated": False,
        "auto_promote": False, "real_orders_permitted": False,
    }
    plan["study_id"] = digest(canonical(plan))
    return plan


def verify(plan: dict, *, manifest_bytes: bytes,
           now: datetime | None = None, completed: bool = False) -> None:
    now = now or datetime.now(timezone.utc)
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError("Unknown prospective study schema")
    content = {key: value for key, value in plan.items() if key != "study_id"}
    if plan.get("study_id") != digest(canonical(content)):
        raise ValueError("Preregistered study content changed after freeze")
    if plan.get("source_manifest_sha256") != digest(manifest_bytes):
        raise ValueError("Native source changed; freeze a different future study")
    if (plan.get("live") != "LOCKED" or plan.get("edge_validated") is not False or
        plan.get("auto_promote") is not False or
        plan.get("real_orders_permitted") is not False or
        plan.get("broker_fees_qualified") is not False or
        plan.get("no_extra_selections_on_veto") is not True or
        plan.get("champion") != VARIANTS[0] or plan.get("challenger") != VARIANTS[1]):
        raise ValueError("Study no longer preserves original research safety")
    if plan.get("frozen_style") not in (0,1,2,3,4,5,6,8) or plan.get("frozen_regime_id") not in (0,1,2):
        raise ValueError("Veto code out of policy")
    if {0:"RANGE",1:"TRANSITION",2:"TREND"}[plan["frozen_regime_id"]] != plan.get("frozen_regime"):
        raise ValueError("Regime identity mismatch")
    created = datetime.fromisoformat(plan["created_at_utc"])
    if created.tzinfo is None:
        raise ValueError("Freeze timestamp must include timezone")
    start, end = iso_date(plan["from_date"]), iso_date(plan["to_date"])
    origin = datetime.fromtimestamp(plan["origin_last_broker_exit_ms"]/1000, timezone.utc).date()
    if (start <= created.astimezone(timezone.utc).date() or start <= origin or
            end <= start or (end-start).days > 370):
        raise ValueError("Lookahead/overlap in proposed future evaluation")
    if completed and now.astimezone(timezone.utc).date() < end:
        raise ValueError("Future test window has not completed")


def run_facts(folder: Path, variant: str, plan: dict) -> tuple[dict, list[dict]]:
    run = json.loads((folder / "OPEN_RESULTS.json").read_text(encoding="utf-8-sig"))
    attr = json.loads((folder / "QTS_V4_POSITION_ATTRIBUTION.json").read_text(encoding="utf-8-sig"))
    if run.get("research_variant") != variant or run.get("source_manifest_sha256") != plan["source_manifest_sha256"]:
        raise ValueError("Native source/variant differs across study arms")
    if run.get("from_date") != plan["from_date"] or run.get("to_date") != plan["to_date"]:
        raise ValueError("Native evaluation dates differ from registered study")
    if (run.get("symbol") != "XAUUSD@" or run.get("model") != 4 or
        run.get("timeframe") != "M15" or run.get("deposit_usd") != 3000 or
        run.get("selected_styles") != [7] or run.get("targeted") is not True or
        run.get("live") != "LOCKED" or run.get("validated_edge") is not False or
        run.get("real_money_orders") is not False or
        run.get("state") != "SELECTED_TESTS_FINISHED_REVIEW_REQUIRED"):
        raise ValueError("Native broker evaluation is missing or inconsistent")
    if variant == "ADAPTIVE_V5_VETO":
        if (run.get("challenger_veto_style") != plan["frozen_style"] or
            run.get("challenger_veto_regime") != plan["frozen_regime_id"]):
            raise ValueError("Actual native veto differs from frozen proposal")
    elif run.get("challenger_veto_style") is not None or run.get("challenger_veto_regime") is not None:
        raise ValueError("Champion is contaminated by challenger parameters")
    if attr.get("status") != "ATTRIBUTED_FOR_RESEARCH_ONLY" or attr.get("issues") != []:
        raise ValueError("Incomplete original native broker deal attribution")
    positions = validate_positions(attr)
    if variant == "ADAPTIVE_V5_VETO" and any(
        r["selected_style"] == plan["frozen_style"] and
        r["regime"] == plan["frozen_regime"] for r in positions
    ):
        raise ValueError("Native challenger violated its frozen veto")
    return run, positions


def cohort_metrics(rows: list[dict], extra_per_lot: float) -> dict:
    stream = sorted(rows, key=lambda r: (r["exit_time_msc"], r["position_id"]))
    net = [r["broker_net_usd"]-extra_per_lot*r["lots"] for r in stream]
    pnl = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in net:
        pnl += value
        peak = max(peak, pnl)
        drawdown = max(drawdown, peak-pnl)
    return {
        "trades": len(stream),
        "broker_net_usd": round(sum(r["broker_net_usd"] for r in stream), 2),
        "additional_cost_stress_usd_per_lot": extra_per_lot,
        "stressed_net_usd": round(sum(net), 2),
        "closed_trade_drawdown_usd_not_floating_equity": round(drawdown,2),
        "stressed_win_rate": round(sum(x>0 for x in net)/len(net),4) if net else None,
        "broker_stop_exits": sum(r["exit_reason"]=="DEAL_REASON_SL" for r in stream),
        "broker_stopouts": sum(r["exit_reason"]=="DEAL_REASON_SO" for r in stream),
    }


def compare(plan: dict, manifest_bytes: bytes, champion_dir: Path,
            challenger_dir: Path, *, extra_per_lot: float = 10.0,
            now: datetime | None = None) -> dict:
    verify(plan, manifest_bytes=manifest_bytes, now=now, completed=True)
    if not math.isfinite(extra_per_lot) or extra_per_lot < 0:
        raise ValueError("Unbounded or negative fee stress")
    cr, cp = run_facts(champion_dir, VARIANTS[0], plan)
    vr, vp = run_facts(challenger_dir, VARIANTS[1], plan)
    champion = cohort_metrics(cp, extra_per_lot)
    challenger = cohort_metrics(vp, extra_per_lot)
    vetoed = [p for p in cp if
              p["selected_style"] == plan["frozen_style"] and
              p["regime"] == plan["frozen_regime"]]
    if champion["trades"] == 0 or challenger["trades"] == 0:
        status = "INSUFFICIENT_NATIVE_POSITIONS_NO_GO"
    elif len(vetoed) == 0:
        status = "FROZEN_VETO_UNEXERCISED_NO_GO"
    else:
        status = "DESCRIPTIVE_NATIVE_COMPARISON_NO_RELEASE"
    return {
        "schema": OUTPUT_SCHEMA, "status": status,
        "study_id": plan["study_id"], "source_manifest_sha256": plan["source_manifest_sha256"],
        "from_date": plan["from_date"], "to_date": plan["to_date"],
        "champion": champion, "challenger": challenger,
        "actual_champion_positions_matching_veto": len(vetoed),
        "observed_stressed_net_difference_challenger_minus_champion_usd": round(
            challenger["stressed_net_usd"]-champion["stressed_net_usd"],2),
        "realised_result_not_a_statistical_edge": True,
        "floating_equity_drawdown_unavailable": True,
        "real_broker_execution_and_fees_not_qualified": True,
        "requires_native_html_csv_and_tick_provenance_audit": True,
        "requires_independent_statistical_multiple_comparison_review": True,
        "live": "LOCKED", "edge_validated": False, "auto_promote": False,
        "real_orders_permitted": False,
        "warning": "Native historical simulation after freeze is a comparison, not a live forward test. Real costs, independent month-block uncertainty, and exposure changes remain unvalidated.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    cmd = p.add_subparsers(dest="command", required=True)
    f = cmd.add_parser("freeze")
    f.add_argument("--reflection", type=Path, required=True)
    f.add_argument("--style", type=int, required=True)
    f.add_argument("--regime", required=True)
    f.add_argument("--checkpoint", type=int, required=True)
    f.add_argument("--from-date", required=True)
    f.add_argument("--to-date", required=True)
    f.add_argument("--manifest", type=Path, required=True)
    f.add_argument("--output", type=Path, required=True)
    v = cmd.add_parser("verify")
    v.add_argument("--plan", type=Path, required=True)
    v.add_argument("--manifest", type=Path, required=True)
    v.add_argument("--completed", action="store_true")
    c = cmd.add_parser("compare")
    c.add_argument("--plan", type=Path, required=True)
    c.add_argument("--manifest", type=Path, required=True)
    c.add_argument("--champion", type=Path, required=True)
    c.add_argument("--challenger", type=Path, required=True)
    c.add_argument("--extra-cost-usd-per-lot", type=float, default=10.0)
    c.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    raw = a.manifest.read_bytes()
    if a.command == "freeze":
        reflection = json.loads(a.reflection.read_text(encoding="utf-8-sig"))
        plan = freeze(reflection, raw, style=a.style, regime=a.regime, checkpoint=a.checkpoint,
                      from_date=a.from_date, to_date=a.to_date)
        save_json(a.output, plan)
        print("FROZEN STUDY "+plan["study_id"]+"; LIVE LOCKED")
    else:
        plan = json.loads(a.plan.read_text(encoding="utf-8-sig"))
        if a.command == "verify":
            verify(plan, manifest_bytes=raw, completed=a.completed)
            print("FROZEN STUDY VALIDATED; NO TRADE AUTHORITY")
        else:
            result = compare(plan, raw, a.champion, a.challenger,
                             extra_per_lot=a.extra_cost_usd_per_lot)
            save_json(a.output, result)
            print("V5 COMPARISON "+result["status"]+"; LIVE LOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
