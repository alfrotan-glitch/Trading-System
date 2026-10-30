#!/usr/bin/env python3
"""Run the one frozen FX-dispersion-gated monthly gold-trend screen, pre-2000 only."""

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

# Reuse only the already-tested long-history monthly engine, comparators, H.10
# source guard, and generic window/statistics helpers. Importing this module does
# not load Brent data or execute the rejected Brent-gate screen.
from scripts import run_longhistory_brent_gate as COMMON

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMODITY_PATH = REPO_ROOT / "data/raw/xauusd_crossmetal_source/data/wb_commodity_price_intelligence_1960_2026.csv"
FX_PATH = REPO_ROOT / "data/raw/fx/data/daily.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_fx_dispersion_gate_2026-10-19.md"
TRIAL_AUDIT_PATH = REPO_ROOT / "docs/research/trial_count_audit_2026-10-19.md"
RESULT_PATH = REPO_ROOT / "data/evidence/longhistory/fx_dispersion_gate_discovery_dev.json"

HYPOTHESIS_ID = "LH-XAUUSD-FX-DISPERSION-GATE-2026-10-19"
PREREG_SHA256 = "8f879945749943a19223db709b371c0eb75a4eb2de2fdfc03ef1c2b6f18d909c"
PREREG_FREEZE_COMMIT = "7be45522c9e962c963614159d37546bd813a87a7"
COMMODITY_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
COMMODITY_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
FX_COMMIT = "c023dd8b8f879610641a7391c0394c3bbb42d0f7"
FX_SHA256 = "68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa"
CUTOFF = date(2000, 1, 1)
SOURCE_MONTHS = COMMON.SOURCE_MONTHS
BASKET = COMMON.BASKET
INVERTED_QUOTE_COUNTRIES = frozenset({"Australia", "New Zealand", "United Kingdom"})
INPUT_START = COMMON.INPUT_START
INPUT_END = COMMON.INPUT_END
WINDOWS = COMMON.WINDOWS
PERIODS_PER_YEAR = COMMON.PERIODS_PER_YEAR
VOL_MONTHS = COMMON.VOL_MONTHS
FX_RETURN_MONTHS = 12
FX_PUBLICATION_LAG_MONTHS = 1
FX_DISPERSION_THRESHOLD = 0.05
MIN_CURRENCIES = 6
CUMULATIVE_TRIALS = 358
BOOTSTRAP_DRAWS = COMMON.BOOTSTRAP_DRAWS
BOOTSTRAP_BLOCK = COMMON.BOOTSTRAP_BLOCK
BOOTSTRAP_SEED = COMMON.BOOTSTRAP_SEED
CANDIDATE_ID = "fxdisp12_lag1_ge5pct_ts9_longflat"


InputBlocked = COMMON.InputBlocked


def read_eligible_gold(
    path: Path, *, expected_sha256: str | None = COMMODITY_SHA256
) -> tuple[pd.Series, dict[str, Any]]:
    """Load only eligible Gold monthly prices; never convert post-1999 cells."""
    actual_sha = COMMON._verify_source(path, expected_sha256, "commodity") if expected_sha256 else None
    eligible: list[tuple[pd.Timestamp, float]] = []
    seen_months: set[pd.Timestamp] = set()
    last_date_seen: date | None = None
    post_1999_skipped = 0

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "commodity_name", "price_nominal_usd"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise InputBlocked("commodity CSV is missing a registered date/name/price column")
        for row_number, row in enumerate(reader, start=2):
            if (row.get("commodity_name") or "").strip() != "Gold":
                continue
            current_date = COMMON._parse_iso_date(row.get("date") or "", f"commodity row {row_number}")
            if last_date_seen is not None and current_date <= last_date_seen:
                raise InputBlocked(f"Gold dates are duplicate or non-chronological at row {row_number}")
            last_date_seen = current_date
            if current_date >= CUTOFF:
                # Deliberately do not access or convert row["price_nominal_usd"].
                post_1999_skipped += 1
                continue
            if current_date.day != 1:
                raise InputBlocked(f"Gold eligible monthly date is not the first of a month: {current_date}")
            month_end = pd.Timestamp(current_date) + pd.offsets.MonthEnd(0)
            if month_end in seen_months:
                raise InputBlocked(f"duplicate Gold month: {month_end.date()}")
            price = COMMON._parse_positive_price(row.get("price_nominal_usd") or "", f"Gold {month_end.date()}")
            seen_months.add(month_end)
            eligible.append((month_end, price))

    index = pd.DatetimeIndex([stamp for stamp, _ in eligible], name="date")
    gold = pd.Series(np.asarray([value for _, value in eligible], dtype=np.float64), index=index, name="Gold")
    gold = gold.sort_index()
    if not pd.DatetimeIndex(gold.index).equals(SOURCE_MONTHS):
        missing = SOURCE_MONTHS.difference(pd.DatetimeIndex(gold.index))
        extra = pd.DatetimeIndex(gold.index).difference(SOURCE_MONTHS)
        raise InputBlocked(
            f"Gold eligible monthly span is incomplete: rows={len(gold)}, missing={len(missing)}, extra={len(extra)}"
        )
    return gold, {
        "source_path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "source_commit": COMMODITY_COMMIT,
        "source_file_sha256": actual_sha,
        "eligible_months": int(len(gold)),
        "eligible_start": str(SOURCE_MONTHS[0].date()),
        "eligible_end": str(SOURCE_MONTHS[-1].date()),
        "post_1999_rows_skipped_using_date_name_only": post_1999_skipped,
        "post_1999_price_values_converted": 0,
    }


def build_monthly_fx_closes(fx_rows: pd.DataFrame) -> pd.DataFrame:
    """Take each currency's last nonblank eligible observation in each month."""
    required = {"date", "country", "rate"}
    if not required.issubset(fx_rows.columns):
        raise InputBlocked("H.10 rows are missing a registered date/country/rate column")
    frame = fx_rows.loc[fx_rows["country"].isin(BASKET), ["date", "country", "rate"]].copy()
    if frame.empty:
        raise InputBlocked("no eligible H.10 rows are available for the frozen currency basket")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise InputBlocked("H.10 eligible rows contain an invalid date")
    if bool((frame["date"].dt.date >= CUTOFF).any()):
        raise InputBlocked("post-1999 H.10 row reached the monthly-close builder")
    frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
    numeric_rates = frame["rate"].to_numpy(dtype=float)
    if not np.isfinite(numeric_rates).all() or bool((numeric_rates <= 0.0).any()):
        raise InputBlocked("H.10 eligible rates must be finite and strictly positive")
    if bool(frame.duplicated(["country", "date"]).any()):
        raise InputBlocked("H.10 eligible rows contain duplicate country/date observations")

    frame["month"] = frame["date"].dt.to_period("M")
    last_valid = frame.sort_values(["country", "date"]).groupby(["country", "month"], sort=True, as_index=False).tail(1)
    closes = last_valid.pivot(index="month", columns="country", values="rate")
    closes = closes.reindex(columns=BASKET).sort_index()
    month_index = pd.PeriodIndex(closes.index)
    closes.index = pd.DatetimeIndex(month_index.to_timestamp("M"), name="date")
    if not closes.index.is_unique or not closes.index.is_monotonic_increasing:
        raise InputBlocked("H.10 monthly close index must be unique and chronological")
    return closes


def build_fx_dispersion(monthly_fx: pd.DataFrame) -> pd.Series:
    """Build lagged population SD of common-orientation 12m FX log returns."""
    if set(monthly_fx.columns) != set(BASKET):
        raise InputBlocked("monthly FX matrix must contain exactly the eight frozen currencies")
    if not monthly_fx.index.is_unique or not monthly_fx.index.is_monotonic_increasing:
        raise InputBlocked("monthly FX index must be unique and chronological")
    rates = monthly_fx.reindex(columns=BASKET).astype(float)
    numeric = rates.to_numpy(dtype=float)
    invalid = np.isfinite(numeric) & (numeric <= 0.0)
    if bool(invalid.any()):
        raise InputBlocked("monthly FX closes must be positive where observed")

    oriented_log_levels = pd.DataFrame(np.log(rates.to_numpy(dtype=float)), index=rates.index, columns=rates.columns)
    for country in INVERTED_QUOTE_COUNTRIES:
        oriented_log_levels[country] = -oriented_log_levels[country]
    lagged_returns = oriented_log_levels.diff(FX_RETURN_MONTHS).shift(FX_PUBLICATION_LAG_MONTHS)
    coverage = lagged_returns.notna().sum(axis=1)
    dispersion = lagged_returns.std(axis=1, ddof=0).where(coverage >= MIN_CURRENCIES)
    dispersion.name = "fx_dispersion_12m_lag1"
    return dispersion


def fx_dispersion_gated_plan(df: pd.DataFrame, monthly_fx: pd.DataFrame) -> Plan:
    """Frozen 9m long-only gold trend, active only above lagged FX dispersion 0.05."""
    dispersion = build_fx_dispersion(monthly_fx).reindex(df.index)
    gold_trend = ES.tsmom_single(df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    base_target = np.asarray(gold_trend.target, dtype=float)
    sizes = np.asarray(gold_trend.size, dtype=float)
    valid_gold = np.isfinite(base_target) & np.isfinite(sizes)
    feature = dispersion.to_numpy(dtype=float)
    gate = np.isfinite(feature) & (feature >= FX_DISPERSION_THRESHOLD)
    target = base_target.copy()
    # Missing/insufficient FX history is explicitly flat; an invalid gold trend
    # remains NaN so the inherited warm-up behavior is unchanged.
    target[valid_gold & ~gate] = 0.0
    target[~valid_gold] = np.nan
    size = sizes.copy()
    size[~valid_gold] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(gold_trend.stop_dist, dtype=float).copy(),
        rebalance=np.asarray(gold_trend.rebalance, dtype=bool).copy(),
        family="fx_dispersion_gated_tsmom",
        params={
            "gold_lookback_months": 9,
            "fx_return_lookback_months": FX_RETURN_MONTHS,
            "fx_publication_lag_months": FX_PUBLICATION_LAG_MONTHS,
            "fx_dispersion_statistic": "population_std_of_common_orientation_currency_12m_log_returns",
            "fx_dispersion_threshold": FX_DISPERSION_THRESHOLD,
            "minimum_valid_currencies": MIN_CURRENCIES,
            "long_only": True,
            "volatility_lookback_months": VOL_MONTHS,
            "annualisation": PERIODS_PER_YEAR,
        },
    )


def _screen(df: pd.DataFrame, monthly_fx: pd.DataFrame) -> dict[str, Any]:
    candidate = fx_dispersion_gated_plan(df, monthly_fx)
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
    gold, gold_meta = read_eligible_gold(COMMODITY_PATH)
    fx_rows, fx_meta = COMMON.read_eligible_fx_rows(FX_PATH)
    monthly_fx = build_monthly_fx_closes(fx_rows)
    expected_fx_months = pd.date_range("1971-01-31", "1999-12-31", freq="ME")
    if not monthly_fx.index.equals(expected_fx_months):
        actual_fx_months = pd.DatetimeIndex(monthly_fx.index)
        missing = expected_fx_months.difference(actual_fx_months)
        extra = actual_fx_months.difference(expected_fx_months)
        raise InputBlocked(f"H.10 monthly-close span is incomplete: missing={len(missing)}, extra={len(extra)}")
    monthly_coverage = monthly_fx.notna().sum(axis=1)
    usd = COMMON.build_usd_monthly(fx_rows)
    df = COMMON.build_input_frame(gold, usd)
    result = _screen(df, monthly_fx)
    return {
        "schema": "qts.longhistory.fx_dispersion_gate_screen.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "preregistration_path": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "identity": identity,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            "commodity_source": gold_meta,
            "fx_source": fx_meta,
            "input_window_start": INPUT_START,
            "input_window_end": INPUT_END,
            "input_months": len(df),
            "fx_monthly_closes": {
                "months": int(len(monthly_fx)),
                "start": str(monthly_fx.index[0].date()),
                "end": str(monthly_fx.index[-1].date()),
                "minimum_currency_coverage": int(monthly_coverage.min()),
                "months_with_at_least_six_currencies": int((monthly_coverage >= MIN_CURRENCIES).sum()),
            },
            "post_1999_price_values_converted": 0,
            "post_1999_fx_values_converted": 0,
        },
        "frozen_parameters": {
            "candidate": {
                "id": CANDIDATE_ID,
                "gold_rule": "long if ln(Gold_t / Gold_(t-9)) > 0",
                "fx_dispersion_gate": (
                    "long allowed if population_std across eight common-orientation "
                    "12m FX log returns ending at t-1 is >= 0.05"
                ),
                "fx_currency_basket": list(BASKET),
                "fx_inverted_quote_countries": sorted(INVERTED_QUOTE_COUNTRIES),
                "fx_lookback_months": FX_RETURN_MONTHS,
                "fx_publication_lag_months": FX_PUBLICATION_LAG_MONTHS,
                "fx_dispersion_threshold": FX_DISPERSION_THRESHOLD,
                "minimum_valid_currencies": MIN_CURRENCIES,
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
