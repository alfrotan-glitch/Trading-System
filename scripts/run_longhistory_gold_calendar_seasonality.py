#!/usr/bin/env python3
"""Run the one frozen annual gold-demand calendar screen, pre-2000 only."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import stats as ST
from qts.research.longhistory.calendar_seasonality import ACTIVE_MONTHS, calendar_seasonal_plan
from qts.research.longhistory.engine import RunResult
from qts.research.longhistory.hybrid_protocol import candidate_by_id as hybrid_candidate_by_id
from qts.research.longhistory.monthly_protocol import COST_BASE, COST_FINANCING, INITIAL_EQUITY
from qts.research.longhistory.runner import window_positions
from qts.research.longhistory.yield_curve_gate import (
    InputBlocked,
    read_eligible_gold,
)

# Reuse only the frozen H.10 comparator source guard/builder and monthly engine
# helpers. Importing this module does not run or evaluate its rejected Brent
# candidate.
from scripts import run_longhistory_brent_gate as H10_COMMON

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data/raw/yield_curve_inversion"
GOLD_PATH = RAW_ROOT / "gold_panel/data/wb_commodity_price_intelligence_1960_2026.csv"
FX_PATH = RAW_ROOT / "fx/data/daily.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_gold_calendar_seasonality_2026-10-19.md"
AMENDMENT_PATH = REPO_ROOT / "docs/research/amendment_A1_longhistory_yield_curve_inversion_gate_comparator_source_2026-10-19.md"
RESULT_PATH = REPO_ROOT / "data/evidence/longhistory/gold_calendar_seasonality_discovery_dev.json"

HYPOTHESIS_ID = "LH-XAUUSD-GOLD-CALENDAR-SEASONALITY-2026-10-19"
PREREG_SHA256 = "9dc5214bf7adf9403237ccf47dfbb1315877bbcdeb3412b86251e578604d91d1"
PREREG_FREEZE_COMMIT = "e79855e59ea2bc790902c8bbd543cb108b4bee5b"
AMENDMENT_SHA256 = "a8fe14283581f51d53d578c35eef5e4d257a09e47845c6d1f95a043ca789e8a5"
AMENDMENT_FREEZE_COMMIT = "78efd38cccd4ed06fc6d2d6e0479a76ef5ac3de6"
GOLD_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
GOLD_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
GOLD_GIT_BLOB_SHA1 = "b31639d3bbf4c42ecd6406526d21bb7536e24ef9"
H10_COMMIT = "c023dd8b8f879610641a7391c0394c3bbb42d0f7"
H10_SHA256 = "68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa"
CUMULATIVE_TRIALS_BEFORE = 360
CUMULATIVE_TRIALS = 361
WINDOWS = {
    "discovery_selection": ("1973-01-01", "1983-12-31"),
    "discovery_confirmation": ("1984-01-01", "1989-12-31"),
    "development": ("1990-01-01", "1999-12-31"),
}
PERIODS_PER_YEAR = 12
VOL_MONTHS = 12
BOOTSTRAP_DRAWS = 9_999
BOOTSTRAP_BLOCK = 12
BOOTSTRAP_SEED = 20261019
CANDIDATE_NAME = "calendar_seasonal_gold_5m"


class SourceBlocked(InputBlocked):
    """A frozen source or protocol verification gate failed pre-outcome."""


def _sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_frozen_docs() -> dict[str, str]:
    if not PREREG_PATH.is_file() or _sha256_text(PREREG_PATH) != PREREG_SHA256:
        raise SourceBlocked("frozen seasonal preregistration is absent or its SHA-256 changed")
    if not AMENDMENT_PATH.is_file() or _sha256_text(AMENDMENT_PATH) != AMENDMENT_SHA256:
        raise SourceBlocked("frozen comparator amendment is absent or its SHA-256 changed")
    return {
        "preregistration_sha256": PREREG_SHA256,
        "comparator_amendment_sha256": AMENDMENT_SHA256,
    }


def _git_identity() -> dict[str, str]:
    try:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        for pin in (PREREG_FREEZE_COMMIT, AMENDMENT_FREEZE_COMMIT):
            frozen = subprocess.run(
                ["git", "rev-parse", f"{pin}^{{commit}}"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if subprocess.run(
                ["git", "merge-base", "--is-ancestor", frozen, current], cwd=REPO_ROOT, check=False
            ).returncode:
                raise SourceBlocked(f"frozen protocol commit {pin} is not an ancestor of this checkout")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceBlocked(f"cannot prove frozen-document ancestry: {exc}") from exc
    return {
        "runner_checkout_commit": current,
        "preregistration_freeze_commit": PREREG_FREEZE_COMMIT,
        "comparator_amendment_freeze_commit": AMENDMENT_FREEZE_COMMIT,
    }


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
    initial_equity = float(INITIAL_EQUITY)
    full = H10_COMMON.run_plan(
        df,
        plan,
        i0 - 1,
        i1,
        costs,
        initial_equity=initial_equity,
        force_close_end=True,
    )
    expected = pd.DatetimeIndex(df.index[i0:i1])
    if not full.days[1:].equals(expected):
        raise SourceBlocked("frozen monthly runner failed to preserve in-window bar stamps")
    if not np.isclose(float(full.equity[0]), initial_equity, rtol=0.0, atol=1e-9):
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
    df: pd.DataFrame,
    plan: Any,
    start: str,
    end: str,
    costs: Any,
    *,
    trials: int | None,
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


def _evaluate(frame: pd.DataFrame, plans: dict[str, Any]) -> dict[str, Any]:
    runs: dict[str, dict[str, RunResult]] = {}
    metrics_by_window: dict[str, dict[str, Any]] = {}
    comparators = ("ts9_lo", "veto9")
    for window_name, (start, end) in WINDOWS.items():
        runs[window_name] = {}
        metrics_by_window[window_name] = {}
        for name, plan in plans.items():
            trials = CUMULATIVE_TRIALS if window_name == "development" and name == CANDIDATE_NAME else None
            run, metrics = _metrics(frame, plan, start, end, COST_BASE, trials=trials)
            runs[window_name][name] = run
            metrics_by_window[window_name][name] = metrics

    dev_start, dev_end = WINDOWS["development"]
    cost_stress = {
        "2x_base": _metrics(frame, plans[CANDIDATE_NAME], dev_start, dev_end, COST_BASE.scaled(2.0), trials=None)[1],
        "3x_base": _metrics(frame, plans[CANDIDATE_NAME], dev_start, dev_end, COST_BASE.scaled(3.0), trials=None)[1],
        "financing_0_25_bps_day": _metrics(
            frame, plans[CANDIDATE_NAME], dev_start, dev_end, COST_FINANCING, trials=None
        )[1],
    }

    gates: dict[str, bool] = {}
    for window_name in ("discovery_selection", "discovery_confirmation"):
        candidate = metrics_by_window[window_name][CANDIDATE_NAME]
        gates[f"{window_name}_candidate_net_positive"] = float(candidate["net_usd"]) > 0.0
        for comparator in comparators:
            reference = metrics_by_window[window_name][comparator]
            gates[f"{window_name}_beats_{comparator}_sharpe_by_0_10"] = (
                float(candidate["sharpe"]) - float(reference["sharpe"]) >= 0.10
            )

    candidate_dev = metrics_by_window["development"][CANDIDATE_NAME]
    dev_years = [float(value) for value in candidate_dev["annual_returns"].values()]
    gates["development_candidate_net_positive"] = float(candidate_dev["net_usd"]) > 0.0
    gates["development_candidate_sharpe_positive"] = float(candidate_dev["sharpe"]) > 0.0
    gates["development_at_least_20_round_turns"] = int(candidate_dev["round_turns"]) >= 20
    gates["development_at_least_6_positive_years"] = sum(value > 0.0 for value in dev_years) >= 6
    for comparator in comparators:
        reference = metrics_by_window["development"][comparator]
        gates[f"development_beats_{comparator}_by_500_usd"] = (
            float(candidate_dev["net_usd"]) - float(reference["net_usd"]) >= 500.0
        )
        gates[f"development_beats_{comparator}_sharpe_by_0_10"] = (
            float(candidate_dev["sharpe"]) - float(reference["sharpe"]) >= 0.10
        )
    gates["development_positive_at_2x_cost"] = float(cost_stress["2x_base"]["net_usd"]) > 0.0
    gates["development_positive_with_financing_assumption"] = (
        float(cost_stress["financing_0_25_bps_day"]["net_usd"]) > 0.0
    )

    paired = {
        comparator: _paired_bootstrap(runs["development"][CANDIDATE_NAME], runs["development"][comparator], comparator)
        for comparator in comparators
    }
    adjusted = ST.holm({name: float(record["one_sided_p"]) for name, record in paired.items()})
    for comparator, record in paired.items():
        record["holm_adjusted_p"] = adjusted[comparator]
        gates[f"development_{comparator}_bootstrap_lower_95_positive"] = (
            float(record["one_sided_95_lower_bound"]) > 0.0
        )
        gates[f"development_{comparator}_holm_p_le_0_05"] = float(record["holm_adjusted_p"]) <= 0.05

    return {
        "status": "SURVIVED_DISCOVERY_AND_DEVELOPMENT" if all(gates.values()) else "REJECTED",
        "decision_scope": "discovery_and_development_only_not_validation",
        "candidate_outcomes_calculated": True,
        "cumulative_trials_before": CUMULATIVE_TRIALS_BEFORE,
        "cumulative_trials": CUMULATIVE_TRIALS,
        "windows": metrics_by_window,
        "development_cost_stresses": cost_stress,
        "development_paired_bootstrap": paired,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "strategy_promoted": False,
        "post_1999_gold_prices_accessed": False,
        "held_out_span_opened": False,
        "holdout_accessed": False,
        "orders_submitted": 0,
        "live": "LOCKED",
    }


def _preflight() -> dict[str, Any]:
    if RESULT_PATH.exists():
        raise SourceBlocked(f"refusing to overwrite existing result: {RESULT_PATH}")
    docs = _verify_frozen_docs()
    identity = _git_identity()
    gold, gold_meta = read_eligible_gold(
        GOLD_PATH,
        expected_sha256=GOLD_SHA256,
        expected_git_blob_sha1=GOLD_GIT_BLOB_SHA1,
    )
    gold_meta["source_commit"] = GOLD_COMMIT
    try:
        fx_rows, h10_meta = H10_COMMON.read_eligible_fx_rows(FX_PATH, expected_sha256=H10_SHA256)
        if h10_meta.get("source_commit") != H10_COMMIT:
            raise SourceBlocked("H.10 comparator commit metadata differs from Amendment A1")
        usd = H10_COMMON.build_usd_monthly(fx_rows)
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceBlocked(f"frozen H.10 comparator input failed preflight: {exc}") from exc

    frame = H10_COMMON.build_input_frame(gold, usd)
    sizer = ES.tsmom_single(
        frame,
        lookback=9,
        long_only=True,
        vol_n=VOL_MONTHS,
        ann=PERIODS_PER_YEAR,
    )
    seasonal = calendar_seasonal_plan(sizer, pd.DatetimeIndex(frame.index))
    plans = {
        CANDIDATE_NAME: seasonal,
        "ts9_lo": sizer,
        "veto9": hybrid_candidate_by_id("veto9").builder(frame),
    }
    return {
        "identity": identity,
        "frozen_docs": docs,
        "frame": frame,
        "plans": plans,
        "inputs": {
            "gold": gold_meta,
            "h10_comparator": h10_meta,
            "input_start": str(frame.index[0].date()),
            "input_end": str(frame.index[-1].date()),
            "input_months": int(len(frame)),
            "post_1999_gold_prices_converted": 0,
            "post_1999_h10_values_converted": 0,
        },
    }


def _screen_evidence(preflight: dict[str, Any]) -> dict[str, Any]:
    result = _evaluate(preflight["frame"], preflight["plans"])
    return {
        "schema": "qts.longhistory.gold_calendar_seasonality.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "status": result["status"],
        "preregistration_path": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "comparator_amendment_path": str(AMENDMENT_PATH.relative_to(REPO_ROOT)),
        "comparator_amendment_sha256": AMENDMENT_SHA256,
        "identity": preflight["identity"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "data_rights_status": {
            "gold": "MIT-licensed repository; underlying World Bank Pink Sheet-derived values used for internal research",
            "h10_comparator": "pinned Federal Reserve H.10 source, used only to reproduce unchanged veto9",
        },
        "inputs": preflight["inputs"],
        "frozen_parameters": {
            "candidate": {
                "id": CANDIDATE_NAME,
                "active_calendar_months": list(ACTIVE_MONTHS),
                "target_timing": "set at month-t close for the next monthly bar's calendar month",
                "direction": "long-only; flat outside the fixed calendar mask",
                "sizing": "inherited ts9_lo 12-month realized-volatility size",
                "annualized_volatility_target": ES.VOL_TARGET,
                "maximum_notional_fraction": ES.MAX_FRACTION,
                "volatility_lookback_months": VOL_MONTHS,
            },
            "comparators": {
                "ts9_lo": "frozen 9-month gold momentum, long-or-flat",
                "veto9": "frozen 9-month gold trend with 12-month H.10 USD veto",
            },
            "periods_per_year": PERIODS_PER_YEAR,
            "initial_equity_usd_per_window": INITIAL_EQUITY,
            "cost_models": {
                "base": COST_BASE.describe(),
                "2x_base": COST_BASE.scaled(2.0).describe(),
                "3x_base": COST_BASE.scaled(3.0).describe(),
                "financing": COST_FINANCING.describe(),
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
            "cumulative_trials": CUMULATIVE_TRIALS,
            "post_1999_gold_prices_accessed": False,
            "holdout_accessed": False,
        },
        "screen": result,
    }


def _failure_evidence(exc: Exception) -> dict[str, Any]:
    return {
        "schema": "qts.longhistory.gold_calendar_seasonality.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "status": "INCONCLUSIVE",
        "stage": "SOURCE_PREFLIGHT",
        "candidate_outcomes_calculated": False,
        "failure": f"{type(exc).__name__}: {exc}",
        "cumulative_trials_before": CUMULATIVE_TRIALS_BEFORE,
        "cumulative_trials": CUMULATIVE_TRIALS_BEFORE,
        "post_1999_gold_prices_accessed": False,
        "held_out_span_opened": False,
        "holdout_accessed": False,
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
    if isinstance(value, float) and not np.isfinite(value):
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

    try:
        preflight = _preflight()
    except (InputBlocked, H10_COMMON.InputBlocked, OSError, ValueError) as exc:
        evidence = _failure_evidence(exc)
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(_json_safe(evidence), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        print(json.dumps({"hypothesis_id": HYPOTHESIS_ID, "status": "INCONCLUSIVE", "stage": "SOURCE_PREFLIGHT"}))
        return 0

    evidence = _screen_evidence(preflight)
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
                "all_gates_pass": screen["all_gates_pass"],
                "candidate_outcomes_calculated": screen["candidate_outcomes_calculated"],
                "cumulative_trials": screen["cumulative_trials"],
                "held_out_span_opened": False,
                "holdout_accessed": False,
                "orders_submitted": 0,
                "live": "LOCKED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
