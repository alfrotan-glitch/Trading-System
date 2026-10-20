#!/usr/bin/env python3
"""Run the single preregistered Sahm/U3 gate screen, pre-2000 only."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import hybrid_protocol as HYB
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import stats as ST
from qts.research.longhistory.engine import RunResult, run_plan
from qts.research.longhistory.runner import window_positions
from qts.research.longhistory.sahm_u3_gate import (
    InputBlocked,
    apply_sahm_gate,
    lagged_sahm_gap,
    read_eligible_u3,
)
from qts.research.longhistory.yield_curve_gate import (
    GOLD_MONTHS,
    MODEL_MONTHS,
    read_eligible_gold,
)

# Reuse only the prior, frozen H.10 reader, USD construction, and input-frame
# helpers to reproduce `veto9` unchanged. No Brent feature or result is read.
from scripts import run_longhistory_brent_gate as H10_COMMON

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data/raw/sahm_u3_gate"
GOLD_PATH = RAW_ROOT / "gold_panel/data/wb_commodity_price_intelligence_1960_2026.csv"
FX_PATH = RAW_ROOT / "fx/data/daily.csv"
U3_PATH = RAW_ROOT / "u3/raw/UNRATE.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_sahm_unemployment_gate_2026-10-20.md"
TRIAL_AUDIT_PATH = REPO_ROOT / "docs/research/trial_count_audit_2026-10-19.md"
PROJECT_CONTROL_PATH = REPO_ROOT / "QTS_PROJECT_CONTROL.md"
RESULT_PATH = REPO_ROOT / "data/evidence/longhistory/sahm_u3_gate_discovery_dev.json"

HYPOTHESIS_ID = "LH-XAUUSD-SAHM-U3-GATE-2026-10-20"
PREREG_SHA256 = "160a2babca41d9f9cf0886d9ece8921b284bdb00ab0bfd38dffcd6751936d73d"
PREREG_FREEZE_COMMIT = "54d8e4b2b1364f3f72f71a2a3ea567965491d0c7"
GOLD_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
GOLD_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
GOLD_GIT_BLOB_SHA1 = "b31639d3bbf4c42ecd6406526d21bb7536e24ef9"
H10_COMMIT = "c023dd8b8f879610641a7391c0394c3bbb42d0f7"
H10_SHA256 = "68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa"
U3_SHA256 = "c3be736b31e2ea488076b46190efbfa1762ea0bdf6171e92585e710523840a78"
U3_GIT_BLOB_SHA1 = "3e09b6924c5a010da67ffc2e850f9331bd7cdb4b"
CUMULATIVE_TRIALS_BEFORE = 361
CUMULATIVE_TRIALS = 362
WINDOWS = {
    "discovery_selection": ("1973-01-01", "1983-12-31"),
    "discovery_confirmation": ("1984-01-01", "1989-12-31"),
    "development": ("1990-01-01", "1999-12-31"),
}
PERIODS_PER_YEAR = 12
VOL_MONTHS = 12
BOOTSTRAP_DRAWS = 9_999
BOOTSTRAP_BLOCK = 12
BOOTSTRAP_SEED = 20261020


class SourceBlocked(InputBlocked):
    """A frozen protocol, source, schema, or boundary preflight failed."""


def _sha256_text(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_identity() -> dict[str, str]:
    try:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        frozen = subprocess.run(
            ["git", "rev-parse", f"{PREREG_FREEZE_COMMIT}^{{commit}}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", frozen, current], cwd=REPO_ROOT, check=False
        ).returncode == 0
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceBlocked(f"cannot prove frozen protocol ancestry: {exc}") from exc
    if not ancestor:
        raise SourceBlocked("the frozen Sahm/U3 protocol commit is not an ancestor of this checkout")
    return {"runner_checkout_commit": current, "preregistration_freeze_commit": frozen}


def _verify_frozen_docs() -> dict[str, str]:
    if not PREREG_PATH.is_file() or _sha256_text(PREREG_PATH) != PREREG_SHA256:
        raise SourceBlocked("frozen Sahm/U3 preregistration is absent or its SHA-256 changed")
    if not TRIAL_AUDIT_PATH.is_file() or "current long-history denominator is `N=361`" not in TRIAL_AUDIT_PATH.read_text(
        encoding="utf-8"
    ):
        raise SourceBlocked("trial-count audit does not confirm the frozen inherited N=361")
    if not PROJECT_CONTROL_PATH.is_file() or "long-history `N_TRIALS = 361`" not in PROJECT_CONTROL_PATH.read_text(
        encoding="utf-8"
    ):
        raise SourceBlocked("project control does not confirm the frozen inherited N=361")
    return {"preregistration_sha256": PREREG_SHA256}


def _build_model_frame(gold: pd.Series, usd: pd.Series) -> pd.DataFrame:
    frame = H10_COMMON.build_input_frame(gold, usd)
    if not frame.index.equals(MODEL_MONTHS):
        raise SourceBlocked("model frame does not match the frozen pre-2000 monthly input index")
    if not frame.index.isin(GOLD_MONTHS).all():
        raise SourceBlocked("model frame contains a month outside eligible Gold source coverage")
    return frame


def _build_plans(frame: pd.DataFrame, u3: pd.Series) -> tuple[dict[str, Any], pd.Series]:
    base_long = ES.tsmom_single(frame, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    sahm_gap = lagged_sahm_gap(u3, pd.DatetimeIndex(frame.index))
    if sahm_gap.isna().any() or not np.isfinite(sahm_gap.to_numpy(dtype=float)).all():
        raise SourceBlocked("lagged Sahm feature is incomplete in the authorized model input")
    candidate = apply_sahm_gate(base_long, sahm_gap, index=pd.DatetimeIndex(frame.index))
    veto9 = HYB.candidate_by_id("veto9").builder(frame)
    return {"sahm_u3_ts9_longflat": candidate, "ts9_lo": base_long, "veto9": veto9}, sahm_gap


def _annual_returns(run: RunResult) -> dict[str, float]:
    dates = pd.DatetimeIndex(run.days)
    returns = np.asarray(run.returns, dtype=float)
    years = np.unique(dates.year)
    values = [float(np.prod(1.0 + returns[dates.year == year]) - 1.0) for year in years]
    return {str(int(year)): round(value, 6) for year, value in zip(years, values, strict=True)}


def _run_window(df: pd.DataFrame, plan: Any, start: str, end: str, costs: Any) -> RunResult:
    i0, i1 = window_positions(df, start, end)
    if i0 < 1:
        raise SourceBlocked(f"window {start} has no pre-window signal anchor")
    full = run_plan(
        df,
        plan,
        i0 - 1,
        i1,
        costs,
        initial_equity=float(MON.INITIAL_EQUITY),
        force_close_end=True,
    )
    expected = pd.DatetimeIndex(df.index[i0:i1])
    if not full.days[1:].equals(expected):
        raise SourceBlocked("frozen monthly runner failed to preserve exact in-window bar stamps")
    if not np.isclose(float(full.equity[0]), float(MON.INITIAL_EQUITY), rtol=0.0, atol=1e-9):
        raise SourceBlocked("pre-window anchor changed account equity before the measurement window")
    return RunResult(
        days=full.days[1:],
        equity=full.equity[1:],
        returns=full.returns[1:],
        held=full.held[1:],
        trades=full.trades,
        initial_equity=full.initial_equity,
        turnover_fraction=full.turnover_fraction,
        financing_usd=full.financing_usd,
        cost_usd=full.cost_usd,
        gross_usd=full.gross_usd,
        cost_basis=full.cost_basis,
        accounting_model_version=full.accounting_model_version,
    )


def _metrics(
    df: pd.DataFrame, plan: Any, start: str, end: str, costs: Any, *, trials: int | None
) -> tuple[RunResult, dict[str, Any]]:
    run = _run_window(df, plan, start, end, costs)
    metrics = ST.summarize(run, num_trials=trials, periods_per_year=PERIODS_PER_YEAR)
    metrics["annual_returns"] = _annual_returns(run)
    return run, metrics


def _paired_bootstrap(candidate: RunResult, comparator: RunResult, comparator_name: str) -> dict[str, Any]:
    if not candidate.days.equals(comparator.days):
        raise SourceBlocked("paired bootstrap windows do not have identical monthly stamps")
    differences = np.asarray(candidate.returns, dtype=float) - np.asarray(comparator.returns, dtype=float)
    if differences.size != 120 or not np.isfinite(differences).all():
        raise SourceBlocked(f"development paired sample must be 120 finite months, got {differences.size}")
    observed = float(differences.mean())
    raw = ST.circular_block_bootstrap(
        differences, lambda values: float(np.mean(values)), BOOTSTRAP_DRAWS, BOOTSTRAP_BLOCK, BOOTSTRAP_SEED
    )
    null = ST.circular_block_bootstrap(
        differences - observed,
        lambda values: float(np.mean(values)),
        BOOTSTRAP_DRAWS,
        BOOTSTRAP_BLOCK,
        BOOTSTRAP_SEED,
    )
    p_value = float((1 + np.count_nonzero(null >= observed)) / (BOOTSTRAP_DRAWS + 1))
    return {
        "comparator": comparator_name,
        "observed_mean_monthly_excess_return": observed,
        "one_sided_95_lower_bound": float(np.percentile(raw, 5.0)),
        "one_sided_p": p_value,
        "monthly_return_differences": [
            {
                "month": str(stamp.date()),
                "candidate_net_return": float(candidate_return),
                "comparator_net_return": float(comparator_return),
                "candidate_minus_comparator": float(difference),
            }
            for stamp, candidate_return, comparator_return, difference in zip(
                candidate.days, candidate.returns, comparator.returns, differences, strict=True
            )
        ],
    }


def _screen(df: pd.DataFrame, plans: dict[str, Any], sahm_gap: pd.Series) -> dict[str, Any]:
    runs_by_window: dict[str, dict[str, RunResult]] = {}
    metrics_by_window: dict[str, dict[str, Any]] = {}
    candidate_id = "sahm_u3_ts9_longflat"
    for window_name, (start, end) in WINDOWS.items():
        runs: dict[str, RunResult] = {}
        metrics: dict[str, Any] = {}
        for name, plan in plans.items():
            trials = CUMULATIVE_TRIALS if window_name == "development" else None
            runs[name], metrics[name] = _metrics(df, plan, start, end, MON.COST_BASE, trials=trials)
        runs_by_window[window_name] = runs
        metrics_by_window[window_name] = metrics

    dev_start, dev_end = WINDOWS["development"]
    stress_costs = {
        "2x_base": MON.COST_BASE.scaled(2.0),
        "3x_base": MON.COST_BASE.scaled(3.0),
        "financing_0_25_bps_day": MON.COST_FINANCING,
    }
    development_stress = {
        name: _metrics(df, plans[candidate_id], dev_start, dev_end, costs, trials=None)[1]
        for name, costs in stress_costs.items()
    }

    gates: dict[str, bool] = {}
    for window_name in ("discovery_selection", "discovery_confirmation"):
        candidate_metrics = metrics_by_window[window_name][candidate_id]
        gates[f"{window_name}_candidate_net_positive"] = float(candidate_metrics["net_usd"]) > 0.0
        for comparator in ("ts9_lo", "veto9"):
            comparator_metrics = metrics_by_window[window_name][comparator]
            gates[f"{window_name}_beats_{comparator}_sharpe_by_0_10"] = (
                float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]) >= 0.10
            )

    dev_candidate = metrics_by_window["development"][candidate_id]
    dev_years = {int(year): float(value) for year, value in dev_candidate["annual_returns"].items()}
    gates["development_candidate_net_positive"] = float(dev_candidate["net_usd"]) > 0.0
    gates["development_candidate_sharpe_positive"] = float(dev_candidate["sharpe"]) > 0.0
    gates["development_at_least_20_round_turns"] = int(dev_candidate["round_turns"]) >= 20
    gates["development_at_least_6_positive_years"] = sum(value > 0.0 for value in dev_years.values()) >= 6
    for comparator in ("ts9_lo", "veto9"):
        comparator_metrics = metrics_by_window["development"][comparator]
        gates[f"development_beats_{comparator}_by_500_usd"] = (
            float(dev_candidate["net_usd"]) - float(comparator_metrics["net_usd"]) >= 500.0
        )
        gates[f"development_beats_{comparator}_sharpe_by_0_10"] = (
            float(dev_candidate["sharpe"]) - float(comparator_metrics["sharpe"]) >= 0.10
        )
    gates["development_positive_at_2x_cost"] = float(development_stress["2x_base"]["net_usd"]) > 0.0
    gates["development_positive_with_financing_assumption"] = (
        float(development_stress["financing_0_25_bps_day"]["net_usd"]) > 0.0
    )

    paired = {
        comparator: _paired_bootstrap(
            runs_by_window["development"][candidate_id],
            runs_by_window["development"][comparator],
            comparator,
        )
        for comparator in ("ts9_lo", "veto9")
    }
    adjusted = ST.holm({name: float(result["one_sided_p"]) for name, result in paired.items()})
    for comparator, result in paired.items():
        result["holm_adjusted_p"] = adjusted[comparator]
        gates[f"development_{comparator}_bootstrap_lower_95_positive"] = (
            float(result["one_sided_95_lower_bound"]) > 0.0
        )
        gates[f"development_{comparator}_holm_p_le_0_05"] = float(result["holm_adjusted_p"]) <= 0.05

    return {
        "status": "SURVIVED_DISCOVERY_AND_DEVELOPMENT" if all(gates.values()) else "REJECTED",
        "decision_scope": "discovery_and_development_only_not_validation",
        "candidate_outcomes_calculated": True,
        "cumulative_trials_before": CUMULATIVE_TRIALS_BEFORE,
        "cumulative_trials": CUMULATIVE_TRIALS,
        "windows": metrics_by_window,
        "development_cost_stresses": development_stress,
        "development_paired_bootstrap": paired,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "sahm_feature": {
            "name": "sahm_gap_lag2_pp",
            "threshold_percentage_points": 0.50,
            "dates": [str(stamp.date()) for stamp in sahm_gap.index],
            "values": [float(value) for value in sahm_gap.to_numpy(dtype=float)],
        },
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "orders_submitted": 0,
        "live": "LOCKED",
    }


def _preflight() -> dict[str, Any]:
    prereg = _verify_frozen_docs()
    identity = _git_identity()
    gold, gold_meta = read_eligible_gold(
        GOLD_PATH,
        expected_sha256=GOLD_SHA256,
        expected_git_blob_sha1=GOLD_GIT_BLOB_SHA1,
        expected_months=GOLD_MONTHS,
    )
    fx_rows, fx_meta = H10_COMMON.read_eligible_fx_rows(FX_PATH, expected_sha256=H10_SHA256)
    usd = H10_COMMON.build_usd_monthly(fx_rows)
    u3, u3_meta = read_eligible_u3(
        U3_PATH,
        expected_sha256=U3_SHA256,
        expected_git_blob_sha1=U3_GIT_BLOB_SHA1,
    )
    frame = _build_model_frame(gold, usd)
    plans, sahm_gap = _build_plans(frame, u3)
    return {
        "identity": identity,
        "frozen_document_hashes": prereg,
        "gold": gold_meta,
        "h10": fx_meta,
        "u3": u3_meta,
        "frame": frame,
        "plans": plans,
        "sahm_gap": sahm_gap,
    }


def _failure_evidence(exc: Exception) -> dict[str, Any]:
    return {
        "schema": "qts.longhistory.sahm_u3_gate_screen.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "preregistration_path": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "INCONCLUSIVE",
        "error": {"type": type(exc).__name__, "message": str(exc)},
        "inputs": {
            "post_1999_gold_price_values_converted": 0,
            "post_1999_h10_values_converted": 0,
            "post_1999_u3_values_converted": 0,
            "holdout_accessed": False,
        },
        "screen": {
            "status": "INCONCLUSIVE",
            "decision_scope": "source_preflight_only",
            "candidate_outcomes_calculated": False,
            "cumulative_trials_before": CUMULATIVE_TRIALS_BEFORE,
            "cumulative_trials": CUMULATIVE_TRIALS_BEFORE,
            "strategy_promoted": False,
            "held_out_span_opened": False,
            "orders_submitted": 0,
            "live": "LOCKED",
        },
    }


def run_screen() -> dict[str, Any]:
    if RESULT_PATH.exists():
        raise SourceBlocked(f"refusing to overwrite existing result: {RESULT_PATH}")
    try:
        preflight = _preflight()
    except (InputBlocked, H10_COMMON.InputBlocked, OSError, ValueError, subprocess.CalledProcessError) as exc:
        return _failure_evidence(exc)

    screen = _screen(preflight["frame"], preflight["plans"], preflight["sahm_gap"])
    return {
        "schema": "qts.longhistory.sahm_u3_gate_screen.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "preregistration_path": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "identity": preflight["identity"],
        "frozen_document_hashes": preflight["frozen_document_hashes"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            "gold_source": preflight["gold"],
            "h10_source": preflight["h10"],
            "u3_source": preflight["u3"],
            "model_window_start": str(preflight["frame"].index.min().date()),
            "model_window_end": str(preflight["frame"].index.max().date()),
            "model_months": int(len(preflight["frame"])),
            "post_1999_gold_price_values_converted": preflight["gold"]["post_1999_price_values_converted"],
            "post_1999_h10_values_converted": preflight["h10"]["post_1999_rate_values_converted"],
            "post_1999_u3_values_converted": preflight["u3"]["post_1999_u3_values_converted"],
            "post_1999_gold_prices_accessed": False,
            "post_1999_u3_values_accessed": False,
            "holdout_accessed": False,
        },
        "frozen_parameters": {
            "candidate": {
                "id": "sahm_u3_ts9_longflat",
                "gold_rule": "long if ln(Gold_t / Gold_(t-9)) > 0",
                "labor_market_gate": "Sahm gap at t-2 >= 0.50 percentage points",
                "sahm_gap": "mean(U3_s,U3_(s-1),U3_(s-2)) minus minimum of prior 12 three-month means",
                "u3_reference_month_s": "decision month t minus two full calendar months",
                "position": "long if both Gold momentum and Sahm gate pass; otherwise flat",
            },
            "comparators": {
                "ts9_lo": "frozen 9-month Gold momentum, long-or-flat",
                "veto9": "frozen 9-month Gold trend with 12-month H.10 USD veto",
            },
            "annualized_volatility_target": ES.VOL_TARGET,
            "volatility_lookback_months": VOL_MONTHS,
            "maximum_notional_fraction": ES.MAX_FRACTION,
            "periods_per_year": PERIODS_PER_YEAR,
            "initial_equity_usd_per_window": MON.INITIAL_EQUITY,
            "cost_models": {
                "base": MON.COST_BASE.describe(),
                "2x_base": MON.COST_BASE.scaled(2.0).describe(),
                "3x_base": MON.COST_BASE.scaled(3.0).describe(),
                "financing": MON.COST_FINANCING.describe(),
            },
            "window_bounds": WINDOWS,
            "bootstrap": {
                "method": "paired circular block bootstrap of monthly net-return differences",
                "block_months": BOOTSTRAP_BLOCK,
                "draws": BOOTSTRAP_DRAWS,
                "seed": BOOTSTRAP_SEED,
                "comparisons": 2,
                "holm_alpha": 0.05,
            },
            "cumulative_trials_before": CUMULATIVE_TRIALS_BEFORE,
            "cumulative_trials_if_evaluated": CUMULATIVE_TRIALS,
            "u3_point_in_time_vintage_available": False,
        },
        "screen": screen,
        "strategy_promoted": False,
        "orders_submitted": 0,
        "live": "LOCKED",
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("screen",), required=True)
    args = parser.parse_args()
    if args.stage != "screen":
        raise AssertionError("unreachable stage")
    if RESULT_PATH.exists():
        raise SourceBlocked(f"refusing to overwrite existing result: {RESULT_PATH}")
    evidence = run_screen()
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(_json_safe(evidence), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    screen = evidence["screen"]
    print(
        json.dumps(
            {
                "hypothesis_id": HYPOTHESIS_ID,
                "status": screen["status"],
                "candidate_outcomes_calculated": screen["candidate_outcomes_calculated"],
                "cumulative_trials": screen["cumulative_trials"],
                "result_path": str(RESULT_PATH.relative_to(REPO_ROOT)),
                "held_out_span_opened": False,
                "orders_submitted": 0,
                "live": "LOCKED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
