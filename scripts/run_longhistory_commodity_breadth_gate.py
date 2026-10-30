#!/usr/bin/env python3
"""Run the one frozen commodity-breadth-gated monthly gold screen, pre-2000 only."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import stats as ST
from qts.research.longhistory.signals import Plan

# Reuse only the already-tested monthly engine, comparator builders, H.10 source
# guard, and generic statistics/window helpers. Importing it does not load Brent
# prices or execute either of the prior screens.
from scripts import run_longhistory_brent_gate as COMMON

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMODITY_PATH = REPO_ROOT / "data/raw/xauusd_crossmetal_source/data/wb_commodity_price_intelligence_1960_2026.csv"
FX_PATH = REPO_ROOT / "data/raw/fx/data/daily.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_commodity_breadth_gate_2026-10-19.md"
TRIAL_AUDIT_PATH = REPO_ROOT / "docs/research/trial_count_audit_2026-10-19.md"
RESULT_PATH = REPO_ROOT / "data/evidence/longhistory/commodity_breadth_gate_discovery_dev.json"

HYPOTHESIS_ID = "LH-XAUUSD-COMMODITY-BREADTH-GATE-2026-10-19"
PREREG_SHA256 = "d8b7ffae856d92eaba4ace166097c9809fdda51a7cc5003c8a56fd8e966f7bd2"
PREREG_FREEZE_COMMIT = "a303e3af418a0eb5ea816f608d1e58ae94de0d09"
COMMODITY_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
COMMODITY_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
CUTOFF = date(2000, 1, 1)
SOURCE_MONTHS = COMMON.SOURCE_MONTHS
BASKET = (
    "Aluminum",
    "Banana, US",
    "Barley",
    "Beef",
    "Chicken",
    "Cocoa",
    "Coconut oil",
    "Coffee, Arabica",
    "Coffee, Robusta",
    "Copper",
    "Cotton, A Index",
    "Groundnut oil",
    "Iron ore, cfr spot",
    "Lead",
    "Logs, Malaysian",
    "Maize",
    "Nickel",
    "Orange",
    "Palm oil",
    "Phosphate rock",
    "Potassium chloride",
    "Rice, Thai 5%",
    "Rubber, RSS3",
    "Sawnwood, Malaysian",
    "Shrimps, Mexican",
    "Sorghum",
    "Soybean meal",
    "Soybean oil",
    "Soybeans",
    "Sugar, EU",
    "Sugar, US",
    "Sugar, world",
    "TSP",
    "Tea, Colombo",
    "Tea, Kolkata",
    "Tea, Mombasa",
    "Tea, avg 3 auctions",
    "Tin",
    "Tobacco, US import u.v.",
    "Urea",
    "Wheat, US HRW",
    "Zinc",
)
REGISTERED_SERIES = ("Gold", *BASKET)
INPUT_START = COMMON.INPUT_START
INPUT_END = COMMON.INPUT_END
WINDOWS = COMMON.WINDOWS
PERIODS_PER_YEAR = COMMON.PERIODS_PER_YEAR
VOL_MONTHS = COMMON.VOL_MONTHS
RETURN_LOOKBACK_MONTHS = 12
PUBLICATION_LAG_MONTHS = 1
BREADTH_THRESHOLD = 2.0 / 3.0
MIN_POSITIVE_SERIES = 28
CUMULATIVE_TRIALS = 359
BOOTSTRAP_DRAWS = COMMON.BOOTSTRAP_DRAWS
BOOTSTRAP_BLOCK = COMMON.BOOTSTRAP_BLOCK
BOOTSTRAP_SEED = COMMON.BOOTSTRAP_SEED
CANDIDATE_ID = "commodity_breadth12_lag1_ge2thirds_ts9_longflat"

InputBlocked = COMMON.InputBlocked


def read_eligible_commodity_panel(
    path: Path, *, expected_sha256: str | None = COMMODITY_SHA256
) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """Read only Gold and the fixed breadth basket; skip all post-1999 prices."""
    actual_sha = COMMON._verify_source(path, expected_sha256, "commodity") if expected_sha256 else None
    eligible: dict[str, list[tuple[pd.Timestamp, float]]] = {name: [] for name in REGISTERED_SERIES}
    seen_months: dict[str, set[pd.Timestamp]] = {name: set() for name in REGISTERED_SERIES}
    last_date_seen: dict[str, date] = {}
    post_1999_skipped = dict.fromkeys(REGISTERED_SERIES, 0)
    registered = set(REGISTERED_SERIES)

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "commodity_name", "price_nominal_usd"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise InputBlocked("commodity CSV is missing a registered date/name/price column")
        for row_number, row in enumerate(reader, start=2):
            name = (row.get("commodity_name") or "").strip()
            if name not in registered:
                continue
            current_date = COMMON._parse_iso_date(row.get("date") or "", f"commodity row {row_number}")
            previous = last_date_seen.get(name)
            if previous is not None and current_date <= previous:
                raise InputBlocked(f"{name} dates are duplicate or non-chronological at row {row_number}")
            last_date_seen[name] = current_date
            if current_date >= CUTOFF:
                # Deliberately do not access or convert row["price_nominal_usd"].
                post_1999_skipped[name] += 1
                continue
            if current_date.day != 1:
                raise InputBlocked(f"{name} eligible monthly date is not the first of a month: {current_date}")
            month_end = pd.Timestamp(current_date) + pd.offsets.MonthEnd(0)
            if month_end in seen_months[name]:
                raise InputBlocked(f"duplicate {name} month: {month_end.date()}")
            price = COMMON._parse_positive_price(row.get("price_nominal_usd") or "", f"{name} {month_end.date()}")
            seen_months[name].add(month_end)
            eligible[name].append((month_end, price))

    series: dict[str, pd.Series] = {}
    for name in REGISTERED_SERIES:
        rows = eligible[name]
        index = pd.DatetimeIndex([stamp for stamp, _ in rows], name="date")
        values = np.asarray([value for _, value in rows], dtype=np.float64)
        item = pd.Series(values, index=index, name=name).sort_index()
        if not pd.DatetimeIndex(item.index).equals(SOURCE_MONTHS):
            missing = SOURCE_MONTHS.difference(pd.DatetimeIndex(item.index))
            extra = pd.DatetimeIndex(item.index).difference(pd.DatetimeIndex(SOURCE_MONTHS))
            raise InputBlocked(
                f"{name} eligible monthly span is incomplete: rows={len(item)}, "
                f"missing={len(missing)}, extra={len(extra)}"
            )
        series[name] = item

    return series, {
        "source_path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "source_commit": COMMODITY_COMMIT,
        "source_file_sha256": actual_sha,
        "registered_series_count": len(REGISTERED_SERIES),
        "eligible_months_by_series": {name: int(len(series[name])) for name in REGISTERED_SERIES},
        "eligible_start": str(SOURCE_MONTHS[0].date()),
        "eligible_end": str(SOURCE_MONTHS[-1].date()),
        "post_1999_rows_skipped_by_series_using_date_name_only": post_1999_skipped,
        "post_1999_price_values_converted": 0,
    }


def build_commodity_breadth(prices: dict[str, pd.Series]) -> pd.Series:
    """Compute equal-vote breadth from 42 raw, one-month-lagged 12m returns."""
    if set(prices) != set(REGISTERED_SERIES):
        missing = sorted(set(REGISTERED_SERIES).difference(prices))
        extra = sorted(set(prices).difference(REGISTERED_SERIES))
        raise InputBlocked(f"registered commodity panel mismatch: missing={missing}, extra={extra}")
    index = pd.DatetimeIndex(prices["Gold"].index)
    if not index.is_unique or not index.is_monotonic_increasing:
        raise InputBlocked("commodity panel dates must be unique and chronological")
    price_matrix = pd.DataFrame(index=index, columns=BASKET, dtype=float)
    for name in REGISTERED_SERIES:
        item = prices[name]
        item_index = pd.DatetimeIndex(item.index)
        if not item_index.equals(index):
            raise InputBlocked(f"{name} dates do not align exactly with the registered panel")
        values = item.to_numpy(dtype=float)
        if not np.isfinite(values).all() or bool((values <= 0.0).any()):
            raise InputBlocked(f"{name} prices must be finite and positive")
        if name != "Gold":
            price_matrix[name] = values

    log_levels = pd.DataFrame(np.log(price_matrix.to_numpy(dtype=float)), index=index, columns=BASKET)
    lagged_returns = log_levels.diff(RETURN_LOOKBACK_MONTHS).shift(PUBLICATION_LAG_MONTHS)
    valid_series = lagged_returns.notna().sum(axis=1)
    positive_count = lagged_returns.gt(0.0).sum(axis=1)
    breadth = (positive_count / len(BASKET)).where(valid_series == len(BASKET))
    breadth.name = "commodity_breadth_12m_lag1"
    return breadth


def commodity_breadth_gated_plan(df: pd.DataFrame, prices: dict[str, pd.Series]) -> Plan:
    """Frozen 9m long-only gold trend, active only at >=28/42 breadth."""
    gold = prices.get("Gold")
    if gold is None:
        raise InputBlocked("registered Gold price series is missing")
    gold_values = gold.reindex(df.index).to_numpy(dtype=float)
    frame_values = df["close"].to_numpy(dtype=float)
    if not np.isfinite(gold_values).all() or not np.allclose(gold_values, frame_values, rtol=0.0, atol=1e-10):
        raise InputBlocked("Gold panel series does not match the frozen execution frame")

    breadth = build_commodity_breadth(prices).reindex(df.index)
    gold_trend = ES.tsmom_single(df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    base_target = np.asarray(gold_trend.target, dtype=float)
    sizes = np.asarray(gold_trend.size, dtype=float)
    valid_gold = np.isfinite(base_target) & np.isfinite(sizes)
    feature = breadth.to_numpy(dtype=float)
    gate = np.isfinite(feature) & (feature >= BREADTH_THRESHOLD)
    target = base_target.copy()
    target[valid_gold & ~gate] = 0.0
    target[~valid_gold] = np.nan
    size = sizes.copy()
    size[~valid_gold] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(gold_trend.stop_dist, dtype=float).copy(),
        rebalance=np.asarray(gold_trend.rebalance, dtype=bool).copy(),
        family="commodity_breadth_gated_tsmom",
        params={
            "gold_lookback_months": 9,
            "commodity_return_lookback_months": RETURN_LOOKBACK_MONTHS,
            "commodity_publication_lag_months": PUBLICATION_LAG_MONTHS,
            "breadth_basket": list(BASKET),
            "breadth_threshold": BREADTH_THRESHOLD,
            "minimum_positive_series": MIN_POSITIVE_SERIES,
            "long_only": True,
            "volatility_lookback_months": VOL_MONTHS,
            "annualisation": PERIODS_PER_YEAR,
        },
    )


def _screen(df: pd.DataFrame, prices: dict[str, pd.Series]) -> dict[str, Any]:
    candidate = commodity_breadth_gated_plan(df, prices)
    ts9_lo = ES.tsmom_single(df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    veto9 = COMMON.HYB.candidate_by_id("veto9").builder(df)
    plans = {CANDIDATE_ID: candidate, "ts9_lo": ts9_lo, "veto9": veto9}

    runs_by_window: dict[str, dict[str, Any]] = {}
    metrics_by_window: dict[str, dict[str, Any]] = {}
    for window_name, (start, end) in WINDOWS.items():
        runs: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        for name, plan in plans.items():
            n_trials = CUMULATIVE_TRIALS if window_name == "development" else None
            runs[name], metrics[name] = COMMON._metrics(df, plan, start, end, COMMON.MON.COST_BASE, num_trials=n_trials)
        runs_by_window[window_name] = runs
        metrics_by_window[window_name] = metrics

    dev_start, dev_end = WINDOWS["development"]
    stress_costs = {
        "2x_base": COMMON.MON.COST_BASE.scaled(2.0),
        "3x_base": COMMON.MON.COST_BASE.scaled(3.0),
        "financing_0_25_bps_day": COMMON.MON.COST_FINANCING,
    }
    development_stress = {
        name: COMMON._metrics(df, candidate, dev_start, dev_end, costs, num_trials=None)[1]
        for name, costs in stress_costs.items()
    }

    gates: dict[str, bool] = {}
    for window_name in ("discovery_selection", "discovery_confirmation"):
        candidate_metrics = metrics_by_window[window_name][CANDIDATE_ID]
        gates[f"{window_name}_candidate_net_positive"] = float(candidate_metrics["net_usd"]) > 0.0
        for comparator in ("ts9_lo", "veto9"):
            comparator_metrics = metrics_by_window[window_name][comparator]
            gates[f"{window_name}_beats_{comparator}_sharpe_by_0_10"] = (
                float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]) >= 0.10
            )

    dev_candidate = metrics_by_window["development"][CANDIDATE_ID]
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
        comparator: COMMON._paired_bootstrap(
            runs_by_window["development"][CANDIDATE_ID],
            runs_by_window["development"][comparator],
            comparator,
        )
        for comparator in ("ts9_lo", "veto9")
    }
    adjusted = ST.holm({name: float(result["one_sided_p"]) for name, result in paired.items()})
    for comparator, result in paired.items():
        result["holm_adjusted_p"] = adjusted[comparator]
        gates[f"development_{comparator}_bootstrap_lower_95_positive"] = float(result["one_sided_95_lower_bound"]) > 0.0
        gates[f"development_{comparator}_holm_p_le_0_05"] = float(result["holm_adjusted_p"]) <= 0.05

    all_pass = all(gates.values())
    return {
        "status": "SURVIVED_DISCOVERY_AND_DEVELOPMENT" if all_pass else "REJECTED",
        "decision_scope": "discovery_and_development_only_not_validation",
        "cumulative_trials": CUMULATIVE_TRIALS,
        "windows": metrics_by_window,
        "development_cost_stresses": development_stress,
        "development_paired_bootstrap": paired,
        "gates": gates,
        "all_gates_pass": all_pass,
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "orders_submitted": 0,
        "live": "LOCKED",
    }


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
        ancestor = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", frozen, current], cwd=REPO_ROOT, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputBlocked(f"cannot prove frozen protocol ancestry: {exc}") from exc
    if not ancestor:
        raise InputBlocked("the frozen protocol commit is not an ancestor of this checkout")
    return {"runner_checkout_commit": current, "preregistration_freeze_commit": frozen}


def run_screen() -> dict[str, Any]:
    if not PREREG_PATH.is_file() or COMMON.sha256_file(PREREG_PATH) != PREREG_SHA256:
        raise InputBlocked("frozen preregistration is absent or its SHA-256 changed")
    if not TRIAL_AUDIT_PATH.is_file():
        raise InputBlocked("long-history trial-count audit is absent")
    if RESULT_PATH.exists():
        raise InputBlocked(f"refusing to overwrite an existing result: {RESULT_PATH}")
    identity = _git_identity()
    prices, commodity_meta = read_eligible_commodity_panel(COMMODITY_PATH)
    fx_rows, fx_meta = COMMON.read_eligible_fx_rows(FX_PATH)
    usd = COMMON.build_usd_monthly(fx_rows)
    df = COMMON.build_input_frame(prices["Gold"], usd)
    result = _screen(df, prices)
    return {
        "schema": "qts.longhistory.commodity_breadth_gate_screen.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "preregistration_path": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "identity": identity,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            "commodity_source": commodity_meta,
            "fx_source": fx_meta,
            "input_window_start": INPUT_START,
            "input_window_end": INPUT_END,
            "input_months": len(df),
            "post_1999_price_values_converted": 0,
            "post_1999_fx_values_converted": 0,
        },
        "frozen_parameters": {
            "candidate": {
                "id": CANDIDATE_ID,
                "gold_rule": "long if ln(Gold_t / Gold_(t-9)) > 0",
                "breadth_rule": "long allowed if at least 28 of 42 registered 12m log returns ending at t-1 are > 0",
                "breadth_basket": list(BASKET),
                "breadth_lookback_months": RETURN_LOOKBACK_MONTHS,
                "publication_lag_months": PUBLICATION_LAG_MONTHS,
                "breadth_threshold": BREADTH_THRESHOLD,
                "minimum_positive_series": MIN_POSITIVE_SERIES,
                "position": "long if both rules pass; otherwise flat",
            },
            "comparators": {
                "ts9_lo": "frozen 9-month gold momentum, long-or-flat",
                "veto9": "frozen 9-month gold trend with 12-month USD veto",
            },
            "annualized_volatility_target": ES.VOL_TARGET,
            "volatility_lookback_months": VOL_MONTHS,
            "maximum_notional_fraction": ES.MAX_FRACTION,
            "periods_per_year": PERIODS_PER_YEAR,
            "initial_equity_usd_per_window": COMMON.MON.INITIAL_EQUITY,
            "cost_models": {
                "base": COMMON.MON.COST_BASE.describe(),
                "2x_base": COMMON.MON.COST_BASE.scaled(2.0).describe(),
                "3x_base": COMMON.MON.COST_BASE.scaled(3.0).describe(),
                "financing": COMMON.MON.COST_FINANCING.describe(),
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
        },
        "screen": result,
    }


def _json_safe(value: Any) -> Any:
    return COMMON._json_safe(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("screen",), required=True)
    args = parser.parse_args()
    if args.stage != "screen":
        raise AssertionError("unreachable stage")
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
                "all_gates_pass": screen["all_gates_pass"],
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
