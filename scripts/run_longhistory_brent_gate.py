#!/usr/bin/env python3
"""Run the one frozen Brent-gated monthly gold-trend screen, pre-2000 only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from datetime import UTC, date, datetime
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
from qts.research.longhistory.signals import Plan

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMODITY_PATH = REPO_ROOT / "data/raw/xauusd_crossmetal_source/data/wb_commodity_price_intelligence_1960_2026.csv"
FX_PATH = REPO_ROOT / "data/raw/fx/data/daily.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_brent_inflation_gate_2026-10-19.md"
TRIAL_AUDIT_PATH = REPO_ROOT / "docs/research/trial_count_audit_2026-10-19.md"
RESULT_PATH = REPO_ROOT / "data/evidence/longhistory/brent_gate_discovery_dev.json"

HYPOTHESIS_ID = "LH-XAUUSD-BRENT-GATE-2026-10-19"
PREREG_SHA256 = "764a31ab214877ca41c5692704f9eff6358861939cab20aa916072e5d02d9f5b"
PREREG_FREEZE_COMMIT = "038ecfbf55838ad21dfce7d8a79bc893bbc2c5bd"
COMMODITY_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
COMMODITY_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
FX_COMMIT = "c023dd8b8f879610641a7391c0394c3bbb42d0f7"
FX_SHA256 = "68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa"
CUTOFF = date(2000, 1, 1)
SOURCE_MONTHS = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
INPUT_START = "1971-12-31"
INPUT_END = "1999-12-31"
WINDOWS = {
    "discovery_selection": ("1973-01-01", "1983-12-31"),
    "discovery_confirmation": ("1984-01-01", "1989-12-31"),
    "development": ("1990-01-01", "1999-12-31"),
}
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
PERIODS_PER_YEAR = 12
VOL_MONTHS = 12
CUMULATIVE_TRIALS = 357
BOOTSTRAP_DRAWS = 9_999
BOOTSTRAP_BLOCK = 12
BOOTSTRAP_SEED = 20261019


class InputBlocked(ValueError):
    """A source, identity, or time-boundary condition failed closed."""


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


def read_eligible_gold_brent(
    path: Path, *, expected_sha256: str | None = COMMODITY_SHA256
) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """Load only eligible Gold/Brent monthly values; never convert post-1999 prices."""
    actual_sha = _verify_source(path, expected_sha256, "commodity") if expected_sha256 else None
    names = ("Gold", "Crude oil, Brent")
    eligible: dict[str, list[tuple[pd.Timestamp, float]]] = {name: [] for name in names}
    seen_months: dict[str, set[pd.Timestamp]] = {name: set() for name in names}
    last_date_seen: dict[str, date] = {}
    post_1999_skipped = dict.fromkeys(names, 0)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "commodity_name", "price_nominal_usd"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise InputBlocked("commodity CSV is missing a registered date/name/price column")
        for row_number, row in enumerate(reader, start=2):
            name = (row.get("commodity_name") or "").strip()
            if name not in eligible:
                continue
            current_date = _parse_iso_date(row.get("date") or "", f"commodity row {row_number}")
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
            price = _parse_positive_price(row.get("price_nominal_usd") or "", f"{name} {month_end.date()}")
            seen_months[name].add(month_end)
            eligible[name].append((month_end, price))

    series: dict[str, pd.Series] = {}
    for name in names:
        rows = eligible[name]
        index = pd.DatetimeIndex([stamp for stamp, _ in rows], name="date")
        values = np.asarray([value for _, value in rows], dtype=np.float64)
        item = pd.Series(values, index=index, name=name).sort_index()
        if not pd.DatetimeIndex(item.index).equals(SOURCE_MONTHS):
            missing = SOURCE_MONTHS.difference(pd.DatetimeIndex(item.index))
            extra = pd.DatetimeIndex(item.index).difference(SOURCE_MONTHS)
            raise InputBlocked(
                f"{name} eligible monthly span is incomplete: rows={len(item)}, "
                f"missing={len(missing)}, extra={len(extra)}"
            )
        series[name] = item

    return series, {
        "source_path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "source_commit": COMMODITY_COMMIT,
        "source_file_sha256": actual_sha,
        "eligible_months_by_series": {name: int(len(series[name])) for name in names},
        "eligible_start": str(SOURCE_MONTHS[0].date()),
        "eligible_end": str(SOURCE_MONTHS[-1].date()),
        "post_1999_rows_skipped_by_series_using_date_name_only": post_1999_skipped,
        "post_1999_price_values_converted": 0,
    }


def read_eligible_fx_rows(
    path: Path, *, expected_sha256: str | None = FX_SHA256
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the registered H.10 basket through 1999; skip later rate cells."""
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
                # Deliberately do not access or convert row["Exchange rate"].
                post_1999_skipped[country] += 1
                continue
            key = (country, current_date)
            if key in seen:
                raise InputBlocked(f"duplicate H.10 observation: {country} {current_date}")
            raw_rate = row.get("Exchange rate") or ""
            if not raw_rate.strip():
                # Match the pinned builder's read_csv/dropna behavior.
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
        "source_path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "source_commit": FX_COMMIT,
        "source_file_sha256": actual_sha,
        "eligible_rows_by_country": {name: int(country_counts[name]) for name in BASKET},
        "missing_eligible_rate_rows_skipped_by_country": missing_eligible,
        "post_1999_rows_skipped_by_country_using_date_name_only": post_1999_skipped,
        "post_1999_rate_values_converted": 0,
    }


def build_usd_monthly(fx_rows: pd.DataFrame) -> pd.Series:
    """Reproduce the pinned eight-currency equal-weight geometric USD index."""
    frame = fx_rows.sort_values(["country", "date"]).copy()
    frame["base"] = frame.groupby("country")["rate"].transform("first")
    frame["log_rate"] = np.log(frame["rate"] / frame["base"])
    pivot = frame.pivot(index="date", columns="country", values="log_rate").sort_index()
    if pivot.empty:
        raise InputBlocked("H.10 daily USD basket is empty")
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


def build_input_frame(gold: pd.Series, usd: pd.Series) -> pd.DataFrame:
    index = pd.date_range(INPUT_START, INPUT_END, freq="ME")
    gold_input = gold.reindex(index)
    usd_input = usd.reindex(index)
    for name, values in (("Gold", gold_input), ("H.10 USD", usd_input)):
        array = values.to_numpy(dtype=float)
        if values.isna().any() or not np.isfinite(array).all():
            raise InputBlocked(f"{name} has a missing/non-finite value in the model input window")
    frame = pd.DataFrame(
        {"open": gold_input, "high": gold_input, "low": gold_input, "close": gold_input, "usd": usd_input},
        index=index,
    )
    frame.index.name = "date"
    return frame


def brent_gated_plan(df: pd.DataFrame, brent: pd.Series) -> Plan:
    """Frozen 9m gold trend, active only when lagged 12m Brent return is positive."""
    if not brent.index.is_monotonic_increasing or brent.index.has_duplicates:
        raise InputBlocked("Brent series index must be unique and chronological")
    brent_return_lagged = np.log(brent).diff(12).shift(1).reindex(df.index)
    gold_trend = ES.tsmom_single(
        df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR
    )
    base_target = np.asarray(gold_trend.target, dtype=float)
    oil_feature = brent_return_lagged.to_numpy(dtype=float)
    valid = np.isfinite(base_target) & np.isfinite(oil_feature) & np.isfinite(gold_trend.size)
    target = base_target.copy()
    gate = oil_feature > 0.0
    target[valid & ~gate] = 0.0
    target[~valid] = np.nan
    size = np.asarray(gold_trend.size, dtype=float).copy()
    size[~valid] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(gold_trend.stop_dist, dtype=float).copy(),
        rebalance=np.asarray(gold_trend.rebalance, dtype=bool).copy(),
        family="brent_gated_tsmom",
        params={
            "gold_lookback_months": 9,
            "brent_lookback_months": 12,
            "brent_publication_lag_months": 1,
            "brent_log_return_threshold": 0.0,
            "long_only": True,
            "volatility_lookback_months": VOL_MONTHS,
            "annualisation": PERIODS_PER_YEAR,
        },
    )


def _annual_returns(run: RunResult) -> dict[str, float]:
    dates = pd.DatetimeIndex(run.days)
    returns = np.asarray(run.returns, dtype=float)
    years = np.unique(dates.year)
    values = [float(np.prod(1.0 + returns[dates.year == year]) - 1.0) for year in years]
    return {str(int(year)): round(value, 6) for year, value in zip(years, values, strict=True)}


def _run_frozen_window(df: pd.DataFrame, plan: Plan, start: str, end: str, costs: Any) -> RunResult:
    """Run an independent fixed-equity window with one pre-window signal anchor."""
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
    expected_days = pd.DatetimeIndex(df.index[i0:i1])
    if not full.days[1:].equals(expected_days):
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


def _metrics(df: pd.DataFrame, plan: Plan, start: str, end: str, costs: Any, *, num_trials: int | None) -> tuple[RunResult, dict[str, Any]]:
    run = _run_frozen_window(df, plan, start, end, costs)
    metrics = ST.summarize(run, num_trials=num_trials, periods_per_year=PERIODS_PER_YEAR)
    metrics["annual_returns"] = _annual_returns(run)
    return run, metrics


def _paired_bootstrap(candidate: RunResult, comparator: RunResult, comparator_name: str) -> dict[str, Any]:
    if not candidate.days.equals(comparator.days):
        raise InputBlocked("paired bootstrap windows do not have identical monthly stamps")
    differences = np.asarray(candidate.returns, dtype=float) - np.asarray(comparator.returns, dtype=float)
    if differences.size != 120 or not np.isfinite(differences).all():
        raise InputBlocked(f"development paired-return sample must be 120 finite months, got {differences.size}")
    observed_mean = float(differences.mean())
    raw_distribution = ST.circular_block_bootstrap(
        differences, lambda values: float(np.mean(values)), BOOTSTRAP_DRAWS, BOOTSTRAP_BLOCK, BOOTSTRAP_SEED
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
                candidate.days, candidate.returns, comparator.returns, differences, strict=True
            )
        ],
    }


def _screen(df: pd.DataFrame, brent: pd.Series) -> dict[str, Any]:
    candidate = brent_gated_plan(df, brent)
    ts9_lo = ES.tsmom_single(df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    veto9 = HYB.candidate_by_id("veto9").builder(df)
    plans = {"brent12_lag1_ts9_longflat": candidate, "ts9_lo": ts9_lo, "veto9": veto9}

    runs_by_window: dict[str, dict[str, RunResult]] = {}
    metrics_by_window: dict[str, dict[str, Any]] = {}
    for window_name, (start, end) in WINDOWS.items():
        runs: dict[str, RunResult] = {}
        metrics: dict[str, Any] = {}
        for name, plan in plans.items():
            n_trials = CUMULATIVE_TRIALS if window_name == "development" else None
            runs[name], metrics[name] = _metrics(
                df, plan, start, end, MON.COST_BASE, num_trials=n_trials
            )
        runs_by_window[window_name] = runs
        metrics_by_window[window_name] = metrics

    dev_start, dev_end = WINDOWS["development"]
    stress_costs = {
        "2x_base": MON.COST_BASE.scaled(2.0),
        "3x_base": MON.COST_BASE.scaled(3.0),
        "financing_0_25_bps_day": MON.COST_FINANCING,
    }
    development_stress = {
        name: _metrics(df, candidate, dev_start, dev_end, costs, num_trials=None)[1]
        for name, costs in stress_costs.items()
    }

    gates: dict[str, bool] = {}
    for window_name in ("discovery_selection", "discovery_confirmation"):
        candidate_metrics = metrics_by_window[window_name]["brent12_lag1_ts9_longflat"]
        gates[f"{window_name}_candidate_net_positive"] = float(candidate_metrics["net_usd"]) > 0.0
        for comparator in ("ts9_lo", "veto9"):
            comparator_metrics = metrics_by_window[window_name][comparator]
            gates[f"{window_name}_beats_{comparator}_sharpe_by_0_10"] = (
                float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]) >= 0.10
            )

    dev_candidate = metrics_by_window["development"]["brent12_lag1_ts9_longflat"]
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
            runs_by_window["development"]["brent12_lag1_ts9_longflat"],
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
        "cumulative_trials": CUMULATIVE_TRIALS,
        "windows": metrics_by_window,
        "development_cost_stresses": development_stress,
        "development_paired_bootstrap": paired,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "strategy_promoted": False,
        "held_out_span_opened": False,
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
        raise InputBlocked(f"cannot prove frozen protocol ancestry: {exc}") from exc
    if not ancestor:
        raise InputBlocked("the frozen protocol commit is not an ancestor of this checkout")
    return {"runner_checkout_commit": current, "preregistration_freeze_commit": frozen}


def run_screen() -> dict[str, Any]:
    if not PREREG_PATH.is_file() or sha256_file(PREREG_PATH) != PREREG_SHA256:
        raise InputBlocked("frozen preregistration is absent or its SHA-256 changed")
    if not TRIAL_AUDIT_PATH.is_file():
        raise InputBlocked("long-history trial-count audit is absent")
    if RESULT_PATH.exists():
        raise InputBlocked(f"refusing to overwrite an existing result: {RESULT_PATH}")
    identity = _git_identity()
    series, commodity_meta = read_eligible_gold_brent(COMMODITY_PATH)
    fx_rows, fx_meta = read_eligible_fx_rows(FX_PATH)
    usd = build_usd_monthly(fx_rows)
    df = build_input_frame(series["Gold"], usd)
    result = _screen(df, series["Crude oil, Brent"])
    return {
        "schema": "qts.longhistory.brent_gate_screen.v1",
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
                "id": "brent12_lag1_ts9_longflat",
                "gold_rule": "long if ln(Gold_t / Gold_(t-9)) > 0",
                "brent_gate": "long allowed if ln(Brent_(t-1) / Brent_(t-13)) > 0",
                "position": "long if both rules pass; otherwise flat",
                "gold_lookback_months": 9,
                "brent_lookback_months": 12,
                "brent_publication_lag_months": 1,
            },
            "comparators": {
                "ts9_lo": "frozen 9-month gold momentum, long-or-flat",
                "veto9": "frozen 9-month gold trend with 12-month USD veto",
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
            "cumulative_trials": CUMULATIVE_TRIALS,
        },
        "screen": result,
    }


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
