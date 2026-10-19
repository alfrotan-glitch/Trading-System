#!/usr/bin/env python3
"""Run the one frozen CPI-acceleration-gated monthly gold-trend screen."""

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
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import stats as ST
from qts.research.longhistory.engine import RunResult, run_plan
from qts.research.longhistory.runner import window_positions
from qts.research.longhistory.signals import Plan

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMODITY_PATH = REPO_ROOT / "data/raw/xauusd_crossmetal_source/data/wb_commodity_price_intelligence_1960_2026.csv"
CPI_PATH = REPO_ROOT / "data/raw/cpi_source/data/cpi.csv"
PREREG_PATH = REPO_ROOT / "docs/research/preregistration_longhistory_cpi_acceleration_gate_2026-10-19.md"
TRIAL_AUDIT_PATH = REPO_ROOT / "docs/research/trial_count_audit_2026-10-19.md"
RESULT_PATH = REPO_ROOT / "data/evidence/longhistory/cpi_acceleration_gate_discovery_dev.json"

HYPOTHESIS_ID = "LH-XAUUSD-CPI-ACCELERATION-GATE-2026-10-19"
PREREG_SHA256 = "3045b7be5b834b5e5815f74f11cf34dc7c0d4cf844c0ee100509aec7ea23f8d1"
PREREG_FREEZE_COMMIT = "82638f7175e7620d5086b504b0bd72c1e2ac0af3"
COMMODITY_COMMIT = "c4a9f734d92df0d0a6c4744a2d7c34417ecd074b"
COMMODITY_SHA256 = "3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf"
CPI_COMMIT = "3750e45064a99b0452deb1423a416e4d5473a58e"
CPI_GIT_BLOB_SHA1 = "20c3e21ab08e993b9ab1eb1b2e4c442f43042b4a"
CUTOFF = date(2000, 1, 1)
SOURCE_MONTHS = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
MODEL_START = "1971-12-31"
MODEL_END = "1999-12-31"
REQUIRED_CPI_YEARS = tuple(range(1968, 1998))
WINDOWS = {
    "discovery_selection": ("1973-01-01", "1983-12-31"),
    "discovery_confirmation": ("1984-01-01", "1989-12-31"),
    "development": ("1990-01-01", "1999-12-31"),
}
PERIODS_PER_YEAR = 12
VOL_MONTHS = 12
CUMULATIVE_TRIALS_BEFORE = 359
CUMULATIVE_TRIALS = 360
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


def git_blob_sha1(path: Path) -> str:
    """Return Git's content-addressed blob SHA-1 for a standalone source file."""
    digest = hashlib.sha1(usedforsecurity=False)
    size = path.stat().st_size
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_sha256(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise InputBlocked(f"{label} source is absent: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise InputBlocked(f"{label} source SHA-256 mismatch: {actual} != {expected}")
    return actual


def _parse_iso_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise InputBlocked(f"{label} has a non-ISO date: {raw!r}") from exc


def _parse_positive(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InputBlocked(f"{label} has a non-numeric eligible value") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise InputBlocked(f"{label} has a non-positive or non-finite eligible value")
    return value


def read_eligible_gold(
    path: Path, *, expected_sha256: str | None = COMMODITY_SHA256
) -> tuple[pd.Series, dict[str, Any]]:
    """Load raw Gold prices through 1999; never convert a post-1999 price cell."""
    actual_sha = _verify_sha256(path, expected_sha256, "commodity") if expected_sha256 else None
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
            current_date = _parse_iso_date(row.get("date") or "", f"commodity row {row_number}")
            if last_date_seen is not None and current_date <= last_date_seen:
                raise InputBlocked(f"Gold dates are duplicate or non-chronological at row {row_number}")
            last_date_seen = current_date
            if current_date >= CUTOFF:
                # Deliberately do not access or convert row["price_nominal_usd"].
                post_1999_skipped += 1
                continue
            if current_date.day != 1:
                raise InputBlocked(f"eligible Gold date is not the first of a month: {current_date}")
            month_end = pd.Timestamp(current_date) + pd.offsets.MonthEnd(0)
            if month_end in seen_months:
                raise InputBlocked(f"duplicate Gold month: {month_end.date()}")
            price = _parse_positive(row.get("price_nominal_usd") or "", f"Gold {month_end.date()}")
            seen_months.add(month_end)
            eligible.append((month_end, price))

    index = pd.DatetimeIndex([stamp for stamp, _ in eligible], name="date")
    gold = pd.Series(np.asarray([value for _, value in eligible], dtype=np.float64), index=index, name="Gold")
    if not pd.DatetimeIndex(gold.index).equals(SOURCE_MONTHS):
        missing = SOURCE_MONTHS.difference(pd.DatetimeIndex(gold.index))
        extra = pd.DatetimeIndex(gold.index).difference(SOURCE_MONTHS)
        raise InputBlocked(
            f"eligible Gold monthly span is incomplete: rows={len(gold)}, missing={len(missing)}, extra={len(extra)}"
        )
    return gold, {
        "source_path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "source_commit": COMMODITY_COMMIT,
        "source_file_sha256": actual_sha,
        "eligible_gold_months": int(len(gold)),
        "eligible_start": str(SOURCE_MONTHS[0].date()),
        "eligible_end": str(SOURCE_MONTHS[-1].date()),
        "post_1999_rows_skipped_using_date_name_only": post_1999_skipped,
        "post_1999_price_values_converted": 0,
    }


def read_eligible_cpi(
    path: Path, *, expected_blob_sha1: str | None = CPI_GIT_BLOB_SHA1
) -> tuple[pd.Series, dict[str, Any]]:
    """Read only required USA CPI years; post-1999 CPI cells are never parsed."""
    if not path.is_file():
        raise InputBlocked(f"CPI source is absent: {path}")
    actual_blob = git_blob_sha1(path)
    if expected_blob_sha1 is not None and actual_blob != expected_blob_sha1:
        raise InputBlocked(f"CPI Git blob SHA-1 mismatch: {actual_blob} != {expected_blob_sha1}")
    actual_sha256 = sha256_file(path)
    values: dict[int, float] = {}
    last_year_seen: int | None = None
    post_1999_skipped = 0
    other_year_rows_skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"Country Name", "Country Code", "Year", "CPI"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise InputBlocked("CPI CSV schema does not match the frozen World Bank datapackage")
        for row_number, row in enumerate(reader, start=2):
            if (row.get("Country Code") or "").strip() != "USA":
                continue
            try:
                year = int((row.get("Year") or "").strip())
            except ValueError as exc:
                raise InputBlocked(f"USA CPI row {row_number} has a non-integer year") from exc
            if last_year_seen is not None and year <= last_year_seen:
                raise InputBlocked(f"USA CPI years are duplicate or non-chronological at row {row_number}")
            last_year_seen = year
            if year > 1999:
                # Deliberately do not access or convert row["CPI"].
                post_1999_skipped += 1
                continue
            if year not in REQUIRED_CPI_YEARS:
                other_year_rows_skipped += 1
                continue
            value = _parse_positive(row.get("CPI") or "", f"USA CPI {year}")
            values[year] = value

    missing = sorted(set(REQUIRED_CPI_YEARS).difference(values))
    if missing:
        raise InputBlocked(f"required USA CPI annual values are missing: {missing}")
    if set(values) != set(REQUIRED_CPI_YEARS):
        raise InputBlocked("USA CPI coverage differs from the frozen 1969–1997 requirement")
    cpi = pd.Series(values, dtype=np.float64, name="CPI").sort_index()
    return cpi, {
        "source_path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "source_repository": "datasets/cpi",
        "source_commit": CPI_COMMIT,
        "source_git_blob_sha1": actual_blob,
        "source_file_sha256": actual_sha256,
        "country_code": "USA",
        "eligible_annual_values": int(len(cpi)),
        "eligible_year_start": int(cpi.index.min()),
        "eligible_year_end": int(cpi.index.max()),
        "post_1999_rows_skipped_using_country_year_only": post_1999_skipped,
        "post_1999_cpi_values_converted": 0,
        "other_year_rows_skipped_without_value_conversion": other_year_rows_skipped,
        "historical_release_vintages_available": False,
    }


def build_input_frame(gold: pd.Series) -> pd.DataFrame:
    index = pd.date_range(MODEL_START, MODEL_END, freq="ME")
    prices = gold.reindex(index)
    values = prices.to_numpy(dtype=np.float64)
    if prices.isna().any() or not np.isfinite(values).all() or bool((values <= 0.0).any()):
        raise InputBlocked("Gold has a missing, non-finite, or non-positive value in the model input window")
    frame = pd.DataFrame({"open": prices, "high": prices, "low": prices, "close": prices}, index=index)
    frame.index.name = "date"
    return frame


def cpi_acceleration_by_year(cpi: pd.Series) -> pd.Series:
    """Calculate log CPI inflation acceleration only from the preregistered CPI years."""
    if not cpi.index.is_unique or not cpi.index.is_monotonic_increasing:
        raise InputBlocked("CPI year index must be unique and chronological")
    if tuple(int(year) for year in cpi.index) != REQUIRED_CPI_YEARS:
        raise InputBlocked("CPI input years differ from the frozen 1968–1997 requirement")
    values = cpi.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or bool((values <= 0.0).any()):
        raise InputBlocked("CPI input contains a non-positive or non-finite value")
    inflation_values = np.log(values / np.roll(values, 1))
    inflation_values[0] = np.nan
    inflation = pd.Series(inflation_values, index=cpi.index, name="log_cpi_inflation")
    acceleration = inflation - inflation.shift(1)
    return acceleration.dropna().rename("cpi_log_inflation_acceleration")


def cpi_acceleration_plan(df: pd.DataFrame, cpi: pd.Series) -> Plan:
    """Frozen 9m long-only gold trend, gated by annual CPI acceleration at Y-2."""
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise InputBlocked("monthly Gold input index must be unique and chronological")
    acceleration = cpi_acceleration_by_year(cpi)
    decision_years = pd.DatetimeIndex(df.index).year
    feature_years = pd.Index(decision_years - 2, name="year")
    cpi_feature = acceleration.reindex(feature_years).to_numpy(dtype=np.float64)
    gold_trend = ES.tsmom_single(df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    base_target = np.asarray(gold_trend.target, dtype=np.float64)
    size = np.asarray(gold_trend.size, dtype=np.float64).copy()
    valid = np.isfinite(base_target) & np.isfinite(cpi_feature) & np.isfinite(size)
    target = base_target.copy()
    target[valid & (cpi_feature <= 0.0)] = 0.0
    target[~valid] = np.nan
    size[~valid] = np.nan
    return Plan(
        target=target,
        size=size,
        stop_dist=np.asarray(gold_trend.stop_dist, dtype=np.float64).copy(),
        rebalance=np.asarray(gold_trend.rebalance, dtype=bool).copy(),
        family="cpi_acceleration_gated_tsmom",
        params={
            "gold_lookback_months": 9,
            "cpi_measure": "log annual CPI inflation acceleration",
            "cpi_country_code": "USA",
            "cpi_signal_year_lag": 2,
            "cpi_acceleration_threshold": 0.0,
            "long_only": True,
            "volatility_lookback_months": VOL_MONTHS,
            "annualisation": PERIODS_PER_YEAR,
        },
    )


def _annual_returns(run: RunResult) -> dict[str, float]:
    dates = pd.DatetimeIndex(run.days)
    returns = np.asarray(run.returns, dtype=np.float64)
    years = np.unique(dates.year)
    values = [float(np.prod(1.0 + returns[dates.year == year]) - 1.0) for year in years]
    return {str(int(year)): round(value, 6) for year, value in zip(years, values, strict=True)}


def _run_frozen_window(df: pd.DataFrame, plan: Plan, start: str, end: str, costs: Any) -> RunResult:
    """Run an independent fixed-equity window with a pre-window signal anchor."""
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


def _metrics(
    df: pd.DataFrame, plan: Plan, start: str, end: str, costs: Any, *, num_trials: int | None
) -> tuple[RunResult, dict[str, Any]]:
    run = _run_frozen_window(df, plan, start, end, costs)
    metrics = ST.summarize(run, num_trials=num_trials, periods_per_year=PERIODS_PER_YEAR)
    metrics["annual_returns"] = _annual_returns(run)
    return run, metrics


def _paired_bootstrap(candidate: RunResult, comparator: RunResult) -> dict[str, Any]:
    if not candidate.days.equals(comparator.days):
        raise InputBlocked("paired bootstrap windows do not have identical monthly stamps")
    differences = np.asarray(candidate.returns, dtype=np.float64) - np.asarray(comparator.returns, dtype=np.float64)
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
        "comparator": "ts9_lo",
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


def _screen(df: pd.DataFrame, cpi: pd.Series) -> dict[str, Any]:
    candidate = cpi_acceleration_plan(df, cpi)
    comparator = ES.tsmom_single(df, lookback=9, long_only=True, vol_n=VOL_MONTHS, ann=PERIODS_PER_YEAR)
    plans = {"cpi_accel_lag2_ts9_longflat": candidate, "ts9_lo": comparator}
    runs_by_window: dict[str, dict[str, RunResult]] = {}
    metrics_by_window: dict[str, dict[str, Any]] = {}
    for window_name, (start, end) in WINDOWS.items():
        runs: dict[str, RunResult] = {}
        metrics: dict[str, Any] = {}
        for name, plan in plans.items():
            n_trials = CUMULATIVE_TRIALS if window_name == "development" else None
            runs[name], metrics[name] = _metrics(df, plan, start, end, MON.COST_BASE, num_trials=n_trials)
        runs_by_window[window_name] = runs
        metrics_by_window[window_name] = metrics

    candidate_name = "cpi_accel_lag2_ts9_longflat"
    gates: dict[str, bool] = {}
    for window_name in ("discovery_selection", "discovery_confirmation"):
        candidate_metrics = metrics_by_window[window_name][candidate_name]
        comparator_metrics = metrics_by_window[window_name]["ts9_lo"]
        gates[f"{window_name}_candidate_net_positive"] = float(candidate_metrics["net_usd"]) > 0.0
        gates[f"{window_name}_beats_ts9_lo_sharpe_by_0_10"] = (
            float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]) >= 0.10
        )

    dev_start, dev_end = WINDOWS["development"]
    dev_candidate = metrics_by_window["development"][candidate_name]
    dev_comparator = metrics_by_window["development"]["ts9_lo"]
    dev_years = {int(year): float(value) for year, value in dev_candidate["annual_returns"].items()}
    gates["development_candidate_net_positive"] = float(dev_candidate["net_usd"]) > 0.0
    gates["development_candidate_sharpe_positive"] = float(dev_candidate["sharpe"]) > 0.0
    gates["development_at_least_20_round_turns"] = int(dev_candidate["round_turns"]) >= 20
    gates["development_at_least_6_positive_years"] = sum(value > 0.0 for value in dev_years.values()) >= 6
    gates["development_beats_ts9_lo_by_500_usd"] = (
        float(dev_candidate["net_usd"]) - float(dev_comparator["net_usd"]) >= 500.0
    )
    gates["development_beats_ts9_lo_sharpe_by_0_10"] = (
        float(dev_candidate["sharpe"]) - float(dev_comparator["sharpe"]) >= 0.10
    )

    stress_costs = {
        "2x_base": MON.COST_BASE.scaled(2.0),
        "3x_base": MON.COST_BASE.scaled(3.0),
        "financing_0_25_bps_day": MON.COST_FINANCING,
    }
    development_stress = {
        name: _metrics(df, candidate, dev_start, dev_end, costs, num_trials=None)[1]
        for name, costs in stress_costs.items()
    }
    gates["development_positive_at_2x_cost"] = float(development_stress["2x_base"]["net_usd"]) > 0.0
    gates["development_positive_with_financing_assumption"] = (
        float(development_stress["financing_0_25_bps_day"]["net_usd"]) > 0.0
    )

    paired = _paired_bootstrap(runs_by_window["development"][candidate_name], runs_by_window["development"]["ts9_lo"])
    adjusted = ST.holm({"ts9_lo": float(paired["one_sided_p"])})
    paired["holm_adjusted_p"] = adjusted["ts9_lo"]
    gates["development_ts9_lo_bootstrap_lower_95_positive"] = float(paired["one_sided_95_lower_bound"]) > 0.0
    gates["development_ts9_lo_holm_p_le_0_05"] = float(paired["holm_adjusted_p"]) <= 0.05

    all_pass = all(gates.values())
    return {
        "status": "SCREEN_PASS_UNVALIDATED_SOURCE_VINTAGE" if all_pass else "REJECTED",
        "decision_scope": "discovery_and_development_only_not_validation",
        "cumulative_trials": CUMULATIVE_TRIALS,
        "windows": metrics_by_window,
        "development_cost_stresses": development_stress,
        "development_paired_bootstrap": {"ts9_lo": paired},
        "gates": gates,
        "all_gates_pass": all_pass,
        "source_vintage_prevents_validation": True,
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
        ancestor = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", frozen, current], cwd=REPO_ROOT, check=False
            ).returncode
            == 0
        )
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputBlocked(f"cannot prove frozen protocol ancestry: {exc}") from exc
    if not ancestor:
        raise InputBlocked("the frozen protocol commit is not an ancestor of this checkout")
    return {"runner_checkout_commit": current, "preregistration_freeze_commit": frozen, "branch": branch}


def _base_evidence(identity: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": "qts.longhistory.cpi_acceleration_gate_screen.v1",
        "hypothesis_id": HYPOTHESIS_ID,
        "preregistration_path": str(PREREG_PATH.relative_to(REPO_ROOT)),
        "preregistration_sha256": PREREG_SHA256,
        "identity": identity,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "orders_submitted": 0,
        "live": "LOCKED",
    }


def run_screen() -> dict[str, Any]:
    if not PREREG_PATH.is_file() or sha256_file(PREREG_PATH) != PREREG_SHA256:
        raise InputBlocked("frozen preregistration is absent or its SHA-256 changed")
    if not TRIAL_AUDIT_PATH.is_file():
        raise InputBlocked("long-history trial-count audit is absent")
    if RESULT_PATH.exists():
        raise InputBlocked(f"refusing to overwrite an existing result: {RESULT_PATH}")
    identity = _git_identity()
    gold, commodity_meta = read_eligible_gold(COMMODITY_PATH)
    cpi, cpi_meta = read_eligible_cpi(CPI_PATH)
    df = build_input_frame(gold)
    screen = _screen(df, cpi)
    evidence = _base_evidence(identity)
    evidence.update(
        {
            "inputs": {
                "commodity_source": commodity_meta,
                "cpi_source": cpi_meta,
                "model_window_start": MODEL_START,
                "model_window_end": MODEL_END,
                "input_months": int(len(df)),
                "post_1999_price_values_converted": 0,
                "post_1999_cpi_values_converted": 0,
            },
            "frozen_parameters": {
                "candidate": {
                    "id": "cpi_accel_lag2_ts9_longflat",
                    "gold_rule": "long if ln(Gold_t / Gold_(t-9)) > 0",
                    "cpi_inflation": "pi_y = ln(CPI_y / CPI_(y-1))",
                    "cpi_acceleration": "accel_y = pi_y - pi_(y-1)",
                    "cpi_gate": "for decision year Y, require accel_(Y-2) > 0",
                    "position": "long if both rules pass; otherwise flat",
                    "gold_lookback_months": 9,
                    "cpi_calendar_year_lag": 2,
                    "cpi_country_code": "USA",
                    "cpi_threshold": 0.0,
                    "long_only": True,
                },
                "comparator": {"ts9_lo": "frozen 9-month Gold momentum, long-or-flat"},
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
                    "comparisons": 1,
                    "holm_alpha": 0.05,
                },
                "cumulative_trials_before": CUMULATIVE_TRIALS_BEFORE,
                "cumulative_trials_if_evaluated": CUMULATIVE_TRIALS,
                "historical_cpi_vintages_available": False,
            },
            "screen": screen,
        }
    )
    return evidence


def _inconclusive_evidence(reason: str) -> dict[str, Any]:
    """Record source/preflight failure without calculating trading outcomes."""
    identity = _git_identity()
    evidence = _base_evidence(identity)
    evidence.update(
        {
            "status": "INCONCLUSIVE",
            "reason": reason,
            "candidate_outcomes_calculated": False,
            "cumulative_trials": CUMULATIVE_TRIALS_BEFORE,
            "strategy_promoted": False,
            "held_out_span_opened": False,
            "orders_submitted": 0,
            "live": "LOCKED",
        }
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("screen",), required=True)
    parser.parse_args()
    if not PREREG_PATH.is_file() or sha256_file(PREREG_PATH) != PREREG_SHA256:
        raise InputBlocked("frozen preregistration is absent or its SHA-256 changed")
    if RESULT_PATH.exists():
        raise InputBlocked(f"refusing to overwrite an existing result: {RESULT_PATH}")
    try:
        evidence = run_screen()
    except InputBlocked as exc:
        evidence = _inconclusive_evidence(str(exc))
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(_json_safe(evidence), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    screen = evidence.get("screen", {})
    status = screen.get("status", evidence.get("status", "UNKNOWN"))
    print(
        json.dumps(
            {
                "hypothesis_id": HYPOTHESIS_ID,
                "status": status,
                "all_gates_pass": screen.get("all_gates_pass", False),
                "result_path": str(RESULT_PATH.relative_to(REPO_ROOT)),
                "candidate_outcomes_calculated": evidence.get("candidate_outcomes_calculated", "screen" in evidence),
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
