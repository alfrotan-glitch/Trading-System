#!/usr/bin/env python3
"""Run the frozen 1973–1999 cross-metal relative-strength screen only.

Protocol: docs/research/preregistration_longhistory_crossmetal_relative_2026-10-19.md
This runner has no stage that reads or evaluates 2000+ price values and no broker/order path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import ensemble_signals as ES  # noqa: E402
from qts.research.longhistory import hybrid_protocol as HYB  # noqa: E402
from qts.research.longhistory import monthly_protocol as MON  # noqa: E402
from qts.research.longhistory import stats as ST  # noqa: E402
from qts.research.longhistory.engine import RunResult, run_plan  # noqa: E402
from qts.research.longhistory.runner import window_positions  # noqa: E402
from qts.research.longhistory.signals import Plan, _plan  # noqa: E402

METALS_PATH = REPO_ROOT / "data/raw/xauusd_crossmetal_source/data/wb_commodity_price_intelligence_1960_2026.csv"
FX_PATH = REPO_ROOT / "data/raw/fx/data/daily.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_crossmetal_relative_2026-10-19.md"
EVIDENCE_PATH = REPO_ROOT / "data/evidence/longhistory/crossmetal_relative_discovery_dev.json"
REPORT_PATH = REPO_ROOT / "docs/research/crossmetal_relative_results_2026-10-19.md"

METALS_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
FX_SHA256 = "68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa"
METALS_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
FX_COMMIT = "c023dd8b8f879610641a7391c0394c3bbb42d0f7"
PREREG_FREEZE_COMMIT = "072be30"
PREREG_SHA256 = "82b2c27826d49c82a544696a3bd762106842ef606726fef0462a4e28bf4d78de"
TRIAL_COUNT_AUDIT_PATH = REPO_ROOT / "docs/research/trial_count_audit_2026-10-19.md"
INGESTION_AUDIT_PATH = REPO_ROOT / "docs/research/crossmetal_ingest_boundary_audit_2026-10-19.md"
TARGET_METALS = ("Gold", "Silver", "Platinum")
BASKET = (
    "Australia",
    "Canada",
    "Denmark",
    "Japan",
    "New Zealand",
    "Sweden",
    "Switzerland",
    "United Kingdom",
)
CUTOFF = date(2000, 1, 1)
EXPECTED_METAL_MONTHS = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
INPUT_START = pd.Timestamp("1971-12-31")
INPUT_END = pd.Timestamp("1999-12-31")
WINDOWS = {
    "discovery_selection": ("1973-01-01", "1983-12-31"),
    "discovery_confirmation": ("1984-01-01", "1989-12-31"),
    "development": ("1990-01-01", "1999-12-31"),
}
PERIODS_PER_YEAR = 12
VOL_MONTHS = 12
CUMULATIVE_TRIALS = 356
BOOTSTRAP_DRAWS = 9999
BOOTSTRAP_BLOCK = 12
BOOTSTRAP_SEED = 20261019


class InputBlocked(ValueError):
    """A source or time-boundary condition failed closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_source(path: Path, expected_sha256: str, label: str) -> str:
    if not path.is_file():
        raise InputBlocked(f"{label} source is absent: {path}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise InputBlocked(f"{label} source SHA-256 mismatch: {actual} != {expected_sha256}")
    return actual


def _parse_iso_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise InputBlocked(f"{label} has a non-ISO date: {raw!r}") from exc


def _parse_positive_price(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InputBlocked(f"{label} has a non-numeric eligible price") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise InputBlocked(f"{label} has a non-positive or non-finite eligible price")
    return value


def read_eligible_metal_rows(
    path: Path, *, expected_sha256: str | None = METALS_SHA256
) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """Read only 1960–1999 metal prices; post-1999 price cells are never converted.

    The source is long-form and grouped by commodity, so scanning date/name fields
    must continue past post-1999 rows for earlier commodities to reach Gold, Silver
    and Platinum. Only the three registered series are retained, and only rows
    dated before the locked 2000 cutoff have their price cell interpreted.
    """
    actual_sha = _verify_source(path, expected_sha256, "metals") if expected_sha256 else None
    eligible: dict[str, list[tuple[pd.Timestamp, float]]] = {name: [] for name in TARGET_METALS}
    months_seen: dict[str, set[pd.Timestamp]] = {name: set() for name in TARGET_METALS}
    last_date_seen: dict[str, date] = {}
    post_1999_skipped = dict.fromkeys(TARGET_METALS, 0)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "commodity_name", "price_nominal_usd"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise InputBlocked("metals CSV schema does not contain the registered date/name/price columns")
        for row_number, row in enumerate(reader, start=2):
            name = (row.get("commodity_name") or "").strip()
            if name not in eligible:
                continue
            current_date = _parse_iso_date(row.get("date") or "", f"metals row {row_number}")
            previous = last_date_seen.get(name)
            if previous is not None and current_date <= previous:
                raise InputBlocked(f"{name} dates are duplicate or non-chronological at row {row_number}")
            last_date_seen[name] = current_date
            if current_date >= CUTOFF:
                # Deliberately do not read or convert row["price_nominal_usd"].
                post_1999_skipped[name] += 1
                continue
            if current_date.day != 1:
                raise InputBlocked(f"{name} eligible monthly date is not the first of a month: {current_date}")
            month_end = pd.Timestamp(current_date) + pd.offsets.MonthEnd(0)
            if month_end in months_seen[name]:
                raise InputBlocked(f"duplicate {name} month: {month_end.date()}")
            price = _parse_positive_price(row.get("price_nominal_usd") or "", f"{name} {month_end.date()}")
            months_seen[name].add(month_end)
            eligible[name].append((month_end, price))

    series: dict[str, pd.Series] = {}
    for name in TARGET_METALS:
        rows = eligible[name]
        index = pd.DatetimeIndex([stamp for stamp, _ in rows], name="date")
        values = np.asarray([value for _, value in rows], dtype=np.float64)
        item = pd.Series(values, index=index, name=name).sort_index()
        item_index = pd.DatetimeIndex(item.index)
        if not item_index.equals(EXPECTED_METAL_MONTHS):
            missing = EXPECTED_METAL_MONTHS.difference(item_index)
            extra = item_index.difference(EXPECTED_METAL_MONTHS)
            raise InputBlocked(
                f"{name} pre-2000 monthly span is incomplete: rows={len(item)}, "
                f"missing={len(missing)}, extra={len(extra)}"
            )
        series[name] = item

    metadata = {
        "source_file_sha256": actual_sha,
        "source_commit": METALS_COMMIT,
        "eligible_months_by_series": {name: len(series[name]) for name in TARGET_METALS},
        "eligible_start": str(EXPECTED_METAL_MONTHS[0].date()),
        "eligible_end": str(EXPECTED_METAL_MONTHS[-1].date()),
        "post_1999_rows_skipped_by_series_using_date_name_only": post_1999_skipped,
        "post_1999_price_values_converted": 0,
    }
    return series, metadata


def read_eligible_fx_rows(
    path: Path, *, expected_sha256: str | None = FX_SHA256
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read the registered H.10 basket through 1999; skip post-1999 rates."""
    actual_sha = _verify_source(path, expected_sha256, "Federal Reserve H.10") if expected_sha256 else None
    rows: list[tuple[pd.Timestamp, str, float]] = []
    last_date_seen: dict[str, date] = {}
    seen: set[tuple[str, date]] = set()
    post_1999_skipped = dict.fromkeys(BASKET, 0)
    missing_eligible = dict.fromkeys(BASKET, 0)
    basket = set(BASKET)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"Date", "Country", "Exchange rate"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise InputBlocked("H.10 CSV schema does not match the registered source")
        for row_number, row in enumerate(reader, start=2):
            country = (row.get("Country") or "").strip()
            if country not in basket:
                continue
            current_date = _parse_iso_date(row.get("Date") or "", f"H.10 row {row_number}")
            previous = last_date_seen.get(country)
            if previous is not None and current_date <= previous:
                raise InputBlocked(f"H.10 {country} dates are duplicate or non-chronological at row {row_number}")
            last_date_seen[country] = current_date
            if current_date >= CUTOFF:
                # Deliberately do not read or convert row["Exchange rate"].
                post_1999_skipped[country] += 1
                continue
            key = (country, current_date)
            if key in seen:
                raise InputBlocked(f"duplicate H.10 observation: {country} {current_date}")
            raw_rate = row.get("Exchange rate") or ""
            if not raw_rate.strip():
                # Match the pinned builder: read_csv maps empty cells to NaN and dropna removes them.
                missing_eligible[country] += 1
                continue
            rate = _parse_positive_price(raw_rate, f"H.10 {country} {current_date}")
            seen.add(key)
            rows.append((pd.Timestamp(current_date), country, rate))

    if not rows:
        raise InputBlocked("no pre-2000 rows found for the registered H.10 basket")
    frame = pd.DataFrame(rows, columns=("date", "country", "rate")).sort_values(["country", "date"])
    country_counts = frame.groupby("country")["rate"].count().to_dict()
    if set(country_counts) != basket:
        missing = sorted(basket.difference(country_counts))
        raise InputBlocked(f"H.10 basket is missing registered countries: {missing}")
    return frame, {
        "source_file_sha256": actual_sha,
        "source_commit": FX_COMMIT,
        "eligible_rows_by_country": {name: int(country_counts[name]) for name in BASKET},
        "missing_eligible_rate_rows_skipped_by_country": missing_eligible,
        "post_1999_rows_skipped_by_country_using_date_name_only": post_1999_skipped,
        "post_1999_rate_values_converted": 0,
    }


def build_usd_monthly(fx_rows: pd.DataFrame) -> pd.Series:
    """Reproduce the pinned eight-country equal-weight geometric USD index."""
    frame = fx_rows.sort_values(["country", "date"]).copy()
    frame["base"] = frame.groupby("country")["rate"].transform("first")
    frame["log_rate"] = np.log(frame["rate"] / frame["base"])
    pivot = frame.pivot(index="date", columns="country", values="log_rate").sort_index()
    coverage = pivot.notna().sum(axis=1)
    if coverage.empty or int(coverage.min()) < 1:
        raise InputBlocked("H.10 daily USD basket has an empty quote day")
    pivot_dates = pd.DatetimeIndex(pivot.index)
    last_rows = pivot.groupby(pivot_dates.to_period("M")).tail(1)
    if bool((last_rows.notna().sum(axis=1) < 6).any()):
        raise InputBlocked("H.10 monthly last-observation coverage is below 6/8 currencies")
    daily_index = np.exp(pivot.mean(axis=1))
    monthly = daily_index.groupby(daily_index.index.to_period("M")).last()
    monthly.index = monthly.index.to_timestamp("M")
    monthly.name = "usd"
    expected = pd.date_range("1971-01-31", "1999-12-31", freq="ME")
    if not monthly.index.equals(expected):
        missing = expected.difference(monthly.index)
        extra = monthly.index.difference(expected)
        raise InputBlocked(f"H.10 monthly index incomplete: missing={len(missing)}, extra={len(extra)}")
    return monthly


def build_research_frame(metals: dict[str, pd.Series], usd: pd.Series) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Build the causal input frame, retaining only warm-up through 1999."""
    index = pd.date_range(INPUT_START, INPUT_END, freq="ME")
    selected = {name: values.reindex(index) for name, values in metals.items()}
    for name, values in selected.items():
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise InputBlocked(f"{name} has a missing/non-finite eligible price in the model input window")
    usd_selected = usd.reindex(index)
    if usd_selected.isna().any() or not np.isfinite(usd_selected.to_numpy(dtype=float)).all():
        raise InputBlocked("H.10 USD index is missing within the model input window")
    gold = selected["Gold"]
    frame = pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd_selected},
        index=index,
    )
    frame.index.name = "date"
    return frame, selected


def crossmetal_plan(df: pd.DataFrame, metals: dict[str, pd.Series]) -> Plan:
    gold = metals["Gold"].reindex(df.index)
    silver = metals["Silver"].reindex(df.index)
    platinum = metals["Platinum"].reindex(df.index)
    gold_values = gold.to_numpy(dtype=float)
    silver_values = silver.to_numpy(dtype=float)
    platinum_values = platinum.to_numpy(dtype=float)
    gold_lag = gold.shift(12).to_numpy(dtype=float)
    silver_lag = silver.shift(12).to_numpy(dtype=float)
    platinum_lag = platinum.shift(12).to_numpy(dtype=float)
    relative = np.log(gold_values / gold_lag) - 0.5 * (
        np.log(silver_values / silver_lag) + np.log(platinum_values / platinum_lag)
    )
    size = ES.vol_size(df, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    target = np.where(relative > 0.0, 1.0, 0.0)
    target[~np.isfinite(relative) | ~np.isfinite(size.to_numpy(dtype=float))] = np.nan
    return _plan(
        df,
        "crossmetal_relative_momentum",
        {
            "lookback_months": 12,
            "basket": "50/50 Silver/Platinum geometric mean",
            "threshold": 0.0,
            "long_only": True,
            "vol_n": VOL_MONTHS,
            "annualisation": PERIODS_PER_YEAR,
        },
        target,
        size,
        np.full(len(df), np.nan),
        np.ones(len(df), dtype=bool),
    )


def _annual_returns(run: Any) -> dict[str, float]:
    dates = pd.DatetimeIndex(run.days)
    returns = np.asarray(run.returns, dtype=float)
    years = np.unique(dates.year)
    values = [float(np.prod(1.0 + returns[dates.year == year]) - 1.0) for year in years]
    return {str(int(year)): round(value, 6) for year, value in zip(years, values, strict=True)}


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


def run_frozen_window(df: pd.DataFrame, plan: Plan, start: str, end: str, costs: Any) -> RunResult:
    """Run one independent account, using the prior close's signal for the first window bar.

    The anchor bar is warm-up only: the account is flat there, the close-time
    target is queued, and execution happens at the first bar in the measurement
    window. The returned RunResult drops that zero-P&L anchor bar while keeping
    the original $10,000 starting equity and the full in-window accounting.
    """
    i0, i1 = window_positions(df, start, end)
    if i0 < 1:
        raise InputBlocked(f"window {start} has no pre-window signal bar")
    initial_equity = float(MON.INITIAL_EQUITY)
    full = run_plan(
        df,
        plan,
        i0 - 1,
        i1,
        costs,
        initial_equity=initial_equity,
        force_close_end=True,
    )
    if not full.days[1:].equals(pd.DatetimeIndex(df.index[i0:i1])):
        raise InputBlocked("window runner failed to preserve exact in-window month stamps")
    if not np.isclose(float(full.equity[0]), initial_equity, rtol=0.0, atol=1e-9):
        raise InputBlocked("pre-window anchor bar changed account equity before measurement began")
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


def _run_metrics(
    df: pd.DataFrame,
    plan: Plan,
    start: str,
    end: str,
    costs: Any,
    *,
    num_trials: int | None = None,
) -> tuple[Any, dict[str, Any]]:
    run = run_frozen_window(df, plan, start, end, costs)
    metrics = ST.summarize(run, num_trials=num_trials, periods_per_year=PERIODS_PER_YEAR)
    metrics["annual_returns"] = _annual_returns(run)
    return run, metrics


def paired_block_bootstrap(
    candidate_run: Any, comparator_run: Any, comparator_name: str
) -> dict[str, Any]:
    if not np.array_equal(pd.DatetimeIndex(candidate_run.days), pd.DatetimeIndex(comparator_run.days)):
        raise InputBlocked("paired bootstrap windows do not have identical month stamps")
    differences = np.asarray(candidate_run.returns, dtype=float) - np.asarray(comparator_run.returns, dtype=float)
    if differences.size != 120 or not np.isfinite(differences).all():
        raise InputBlocked(f"development paired-return sample must be 120 finite months, got {differences.size}")
    observed_mean = float(differences.mean())
    raw_distribution = ST.circular_block_bootstrap(
        differences,
        lambda values: float(np.mean(values)),
        BOOTSTRAP_DRAWS,
        BOOTSTRAP_BLOCK,
        BOOTSTRAP_SEED,
    )
    null_distribution = ST.circular_block_bootstrap(
        differences - observed_mean,
        lambda values: float(np.mean(values)),
        BOOTSTRAP_DRAWS,
        BOOTSTRAP_BLOCK,
        BOOTSTRAP_SEED,
    )
    lower_95 = float(np.percentile(raw_distribution, 5.0))
    p_value = float((1 + np.count_nonzero(null_distribution >= observed_mean)) / (BOOTSTRAP_DRAWS + 1))
    candidate_returns = np.asarray(candidate_run.returns, dtype=float)
    comparator_returns = np.asarray(comparator_run.returns, dtype=float)
    dates = pd.DatetimeIndex(candidate_run.days)
    return {
        "comparator": comparator_name,
        "observed_mean_monthly_excess_return": observed_mean,
        "one_sided_95_lower_bound": lower_95,
        "one_sided_p": p_value,
        "monthly_return_differences": [
            {
                "month": str(stamp.date()),
                "candidate_net_return": float(candidate_return),
                "comparator_net_return": float(comparator_return),
                "candidate_minus_comparator": float(difference),
            }
            for stamp, candidate_return, comparator_return, difference in zip(
                dates, candidate_returns, comparator_returns, differences, strict=True
            )
        ],
    }


def _screen(metals: dict[str, pd.Series], input_frame: pd.DataFrame) -> dict[str, Any]:
    candidate = crossmetal_plan(input_frame, metals)
    ts9_lo = ES.tsmom_single(
        input_frame, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR
    )
    veto9 = HYB.candidate_by_id("veto9").builder(input_frame)
    plans = {"cmr12_longflat": candidate, "ts9_lo": ts9_lo, "veto9": veto9}

    window_runs: dict[str, dict[str, Any]] = {}
    window_metrics: dict[str, dict[str, Any]] = {}
    for window_name, (start, end) in WINDOWS.items():
        runs: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        for name, plan in plans.items():
            # The frozen N=356 DSR is descriptive and applies only to the 1990–1999 development view.
            n_trials = CUMULATIVE_TRIALS if window_name == "development" else None
            runs[name], metrics[name] = _run_metrics(
                input_frame, plan, start, end, MON.COST_BASE, num_trials=n_trials
            )
        window_runs[window_name] = runs
        window_metrics[window_name] = metrics

    stress_costs = {
        "2x_base": MON.COST_BASE.scaled(2.0),
        "3x_base": MON.COST_BASE.scaled(3.0),
        "financing_0_25_bps_day": MON.COST_FINANCING,
    }
    dev_start, dev_end = WINDOWS["development"]
    development_stress: dict[str, Any] = {}
    for name, costs in stress_costs.items():
        _, metrics = _run_metrics(input_frame, candidate, dev_start, dev_end, costs)
        development_stress[name] = metrics

    gates: dict[str, bool] = {}
    for window_name in ("discovery_selection", "discovery_confirmation"):
        candidate_metrics = window_metrics[window_name]["cmr12_longflat"]
        gates[f"{window_name}_candidate_net_positive"] = float(candidate_metrics["net_usd"]) > 0.0
        for comparator in ("ts9_lo", "veto9"):
            comparator_metrics = window_metrics[window_name][comparator]
            gates[f"{window_name}_beats_{comparator}_sharpe_by_0_10"] = (
                float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]) >= 0.10
            )

    dev_candidate = window_metrics["development"]["cmr12_longflat"]
    dev_years = {int(year): float(value) for year, value in dev_candidate["annual_returns"].items()}
    gates["development_candidate_net_positive"] = float(dev_candidate["net_usd"]) > 0.0
    gates["development_candidate_sharpe_positive"] = float(dev_candidate["sharpe"]) > 0.0
    gates["development_at_least_20_round_turns"] = int(dev_candidate["round_turns"]) >= 20
    gates["development_at_least_6_positive_years"] = sum(value > 0.0 for value in dev_years.values()) >= 6
    for comparator in ("ts9_lo", "veto9"):
        comparator_metrics = window_metrics["development"][comparator]
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
        comparator: paired_block_bootstrap(
            window_runs["development"]["cmr12_longflat"],
            window_runs["development"][comparator],
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
        "cumulative_trials": CUMULATIVE_TRIALS,
        "windows": window_metrics,
        "development_cost_stresses": development_stress,
        "development_paired_bootstrap": paired,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
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
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", frozen, current], cwd=REPO_ROOT, check=False
        ).returncode == 0
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputBlocked(f"cannot prove the frozen protocol commit is in this checkout: {exc}") from exc
    if not ancestor:
        raise InputBlocked("the registered protocol commit is not an ancestor of the runner checkout")
    return {"runner_commit": current, "preregistration_commit": frozen}


def run_screen() -> dict[str, Any]:
    if sha256_file(PREREG_PATH) != PREREG_SHA256:
        raise InputBlocked("the frozen preregistration file hash changed after its commit")
    identity = _git_identity()
    if not TRIAL_COUNT_AUDIT_PATH.is_file() or not INGESTION_AUDIT_PATH.is_file():
        raise InputBlocked("a required pre-measurement audit note is absent")
    metals, metals_meta = read_eligible_metal_rows(METALS_PATH)
    fx_rows, fx_meta = read_eligible_fx_rows(FX_PATH)
    metals_meta["source_path"] = str(METALS_PATH.relative_to(REPO_ROOT))
    fx_meta["source_path"] = str(FX_PATH.relative_to(REPO_ROOT))
    usd = build_usd_monthly(fx_rows)
    input_frame, selected_metals = build_research_frame(metals, usd)
    screen = _screen(selected_metals, input_frame)
    return {
        "schema": "qts.longhistory.crossmetal_relative_screen.v1",
        "hypothesis_id": "LH-XAUUSD-CMR-2026-10-19",
        "preregistration": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "identity": identity,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "frozen_parameters": {
            "candidate": {
                "id": "cmr12_longflat",
                "formula": "ln(Gold_t/Gold_t-12) - 0.5*(ln(Silver_t/Silver_t-12)+ln(Platinum_t/Platinum_t-12))",
                "rule": "long if relative return > 0; otherwise flat",
                "silver_platinum_weights": [0.5, 0.5],
                "lookback_months": 12,
            },
            "comparators": {
                "ts9_lo": {"builder": "ensemble_signals.tsmom_single", "lookback_months": 9, "long_only": True},
                "veto9": {"builder": "hybrid_protocol.candidate_by_id('veto9').builder"},
            },
            "volatility_target_annualized": ES.VOL_TARGET,
            "volatility_lookback_months": VOL_MONTHS,
            "maximum_notional_fraction": ES.MAX_FRACTION,
            "periods_per_year": PERIODS_PER_YEAR,
            "initial_equity_usd_per_window": MON.INITIAL_EQUITY,
            "bar_convention": "open=high=low=close=monthly average; next-month average fill",
            "window_bounds": WINDOWS,
            "cost_models": {
                "base": MON.COST_BASE.describe(),
                "2x_base": MON.COST_BASE.scaled(2.0).describe(),
                "3x_base": MON.COST_BASE.scaled(3.0).describe(),
                "financing": MON.COST_FINANCING.describe(),
            },
            "bootstrap": {
                "procedure": "paired circular block bootstrap of monthly net-return differences",
                "block_months": BOOTSTRAP_BLOCK,
                "draws": BOOTSTRAP_DRAWS,
                "seed": BOOTSTRAP_SEED,
                "comparisons": 2,
                "one_sided": True,
                "holm_alpha": 0.05,
            },
        },
        "trial_count_audit": {
            "audit_note": str(TRIAL_COUNT_AUDIT_PATH.relative_to(REPO_ROOT)),
            "status": "SCOPED_REGISTRIES_DISTINGUISHED",
            "longhistory_inherited_trials": 355,
            "this_cycle_candidate_trials": 1,
            "descriptive_development_dsr_trials": CUMULATIVE_TRIALS,
            "separate_qts_edge_experiment_ledger_count": 304,
            "qts_edge_database_snapshot_available": False,
            "cross_registry_total_claimed": False,
        },
        "ingestion_audit": {
            "audit_note": str(INGESTION_AUDIT_PATH.relative_to(REPO_ROOT)),
            "premeasurement_attempt_blocked_before_outcome_calculation": True,
            "empty_eligible_fx_rows_skipped_per_pinned_builder": fx_meta[
                "missing_eligible_rate_rows_skipped_by_country"
            ],
        },
        "source": {
            "metals": metals_meta,
            "fx": fx_meta,
            "input_start": str(input_frame.index[0].date()),
            "input_end": str(input_frame.index[-1].date()),
            "performance_rows_after_1999": 0,
            "post_1999_price_or_rate_values_converted": 0,
        },
        "measured": screen,
        "safety": {
            "strategy_promoted": False,
            "held_out_span_opened": False,
            "held_out_rows_read": 0,
            "orders_submitted": 0,
            "DEMO_EXECUTION": "UNCHANGED",
            "LIVE": "LOCKED",
            "REAL_CAPITAL_EXPOSURE": 0,
        },
    }


def render_report(result: dict[str, Any]) -> str:
    measured = result["measured"]
    lines = [
        "# Cross-Metal Relative-Momentum Screen — 2026-10-19",
        "",
        f"**Status:** `{measured['status']}` — discovery/development only; not validation.",
        "",
        "This is the single frozen `cmr12_longflat` rule. No 2000+ price/rate values were converted or evaluated. The 730-day MT5 holdout remains closed.",
        "",
        "## Predeclared window outcomes",
        "",
        "| Window | Rule | Net USD | Gross USD | Fill costs | Financing | Sharpe | DSR* | Max DD | Exposure | Turns |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for window_name, rows in measured["windows"].items():
        for name, metrics in rows.items():
            deflated = metrics.get("deflated", {})
            dsr = deflated.get("dsr")
            dsr_text = f"{dsr:.4f}" if isinstance(dsr, (float, int)) and math.isfinite(dsr) else "—"
            lines.append(
                f"| {window_name} | {name} | {metrics['net_usd']:.2f} | {metrics['gross_usd']:.2f} | "
                f"{metrics['cost_usd']:.2f} | {metrics['financing_usd']:.2f} | {metrics['sharpe']:.4f} | "
                f"{dsr_text} | {metrics['max_drawdown']:.4f} | {metrics['exposure']:.4f} | {metrics['round_turns']} |"
            )
    lines.extend(
        [
            "",
            "*DSR is reported only for the 1990–1999 development window, using the frozen descriptive denominator `N=356`; it is not a gate.*",
            "",
            "### Calendar-year returns",
            "",
            "| Window | Rule | Calendar-year returns |",
            "|---|---|---|",
        ]
    )
    for window_name, rows in measured["windows"].items():
        for name, metrics in rows.items():
            annual = metrics["annual_returns"]
            formatted = ", ".join(f"{year} {value:+.2%}" for year, value in annual.items())
            lines.append(f"| {window_name} | {name} | {formatted} |")
    lines.extend(
        [
            "",
            "## Development cost stresses",
            "",
            "| Cost regime | Net USD | Gross USD | Fill costs | Financing | Sharpe |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for name, metrics in measured["development_cost_stresses"].items():
        lines.append(
            f"| {name} | {metrics['net_usd']:.2f} | {metrics['gross_usd']:.2f} | "
            f"{metrics['cost_usd']:.2f} | {metrics['financing_usd']:.2f} | {metrics['sharpe']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Paired development uncertainty",
            "",
            "| Comparator | Mean monthly excess | One-sided 95% lower bound | Raw p | Holm p |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, metrics in measured["development_paired_bootstrap"].items():
        lines.append(
            f"| {name} | {metrics['observed_mean_monthly_excess_return']:.8f} | "
            f"{metrics['one_sided_95_lower_bound']:.8f} | {metrics['one_sided_p']:.4f} | "
            f"{metrics['holm_adjusted_p']:.4f} |"
        )
    lines.extend(
        [
            "",
            "The complete 120-month candidate/comparator net-return pairs and differences are preserved in the JSON evidence artifact.",
            "",
            "## Frozen gates",
            "",
            "| Gate | Result |",
            "|---|---|",
        ]
    )
    for name, passed in measured["gates"].items():
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "Trial-count note: `N=356` is the long-history lineage denominator used only for development DSR. The separate `qts edge` experiment ledger records 304 in a distinct registry; the counts are not combined.",
            "Source-ingestion audit: `docs/research/crossmetal_ingest_boundary_audit_2026-10-19.md` records a premeasurement blank-rate correction; the frozen protocol and candidate were unchanged.",
            "Costs are ASSUMED. No candidate is promoted; no broker or order path was used; LIVE remains locked.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=("screen",), required=True)
    args = parser.parse_args(argv)
    if args.stage != "screen":  # defensive; argparse already enforces this
        raise SystemExit("only the frozen discovery/development screen is authorized")
    if EVIDENCE_PATH.exists() or REPORT_PATH.exists():
        print("BLOCKED — a prior screen artifact exists; this frozen run cannot overwrite or repeat it", file=sys.stderr)
        return 2
    try:
        result = run_screen()
    except (InputBlocked, OSError, ValueError, KeyError) as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        return 2
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["measured"]["status"],
                "all_gates_pass": result["measured"]["all_gates_pass"],
                "held_out_span_opened": False,
                "orders_submitted": 0,
                "live": "LOCKED",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
