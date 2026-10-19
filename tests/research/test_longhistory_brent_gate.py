from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_longhistory_brent_gate import (
    BASKET,
    CUMULATIVE_TRIALS,
    InputBlocked,
    _screen,
    brent_gated_plan,
    build_usd_monthly,
    read_eligible_fx_rows,
    read_eligible_gold_brent,
)

ELIGIBLE_MONTHS = pd.date_range("1960-01-01", "1999-12-01", freq="MS")


def _write_source(
    path: Path,
    *,
    blank_eligible: bool = False,
    omit_gold_month: pd.Timestamp | None = None,
    duplicate_brent_month: pd.Timestamp | None = None,
) -> None:
    fields = ["date", "commodity_name", "price_nominal_usd"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name in ("Gold", "Crude oil, Brent"):
            for i, stamp in enumerate(ELIGIBLE_MONTHS):
                if name == "Gold" and omit_gold_month is not None and stamp == omit_gold_month:
                    continue
                if name == "Crude oil, Brent" and duplicate_brent_month is not None and stamp == duplicate_brent_month:
                    writer.writerow(
                        {
                            "date": stamp.strftime("%Y-%m-%d"),
                            "commodity_name": name,
                            "price_nominal_usd": f"{30.0 + i:.6f}",
                        }
                    )
                price = 100.0 + i * 0.3 if name == "Gold" else 30.0 + i * 0.2
                raw_price = "" if blank_eligible and name == "Gold" and i == 0 else f"{price:.6f}"
                writer.writerow(
                    {
                        "date": stamp.strftime("%Y-%m-%d"),
                        "commodity_name": name,
                        "price_nominal_usd": raw_price,
                    }
                )
            writer.writerow(
                {
                    "date": "2000-01-01",
                    "commodity_name": name,
                    "price_nominal_usd": "POST_CUTOFF_MUST_NOT_PARSE",
                }
            )


def _write_fx_source(path: Path) -> None:
    months = pd.date_range("1971-01-31", "1999-12-31", freq="ME")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Date", "Country", "Exchange rate"])
        writer.writeheader()
        for country_index, country in enumerate(BASKET):
            for month_index, stamp in enumerate(months):
                writer.writerow(
                    {
                        "Date": stamp.strftime("%Y-%m-%d"),
                        "Country": country,
                        "Exchange rate": f"{1.0 + 0.001 * (country_index + month_index):.6f}",
                    }
                )
            writer.writerow(
                {"Date": "2000-01-31", "Country": country, "Exchange rate": "POST_CUTOFF_MUST_NOT_PARSE"}
            )


def _synthetic_screen_inputs() -> tuple[pd.DataFrame, pd.Series]:
    index = pd.date_range("1971-12-31", "1999-12-31", freq="ME")
    steps = np.arange(len(index), dtype=float)
    monthly_returns = 0.004 + 0.012 * np.sin(steps / 10.0) + 0.004 * np.cos(steps / 4.0)
    gold = pd.Series(100.0 * np.cumprod(1.0 + monthly_returns), index=index, name="Gold")
    usd = pd.Series(np.exp(0.001 * steps + 0.02 * np.sin(steps / 24.0)), index=index, name="usd")
    bars = pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd},
        index=index,
    )
    brent_index = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
    brent_steps = np.arange(len(brent_index), dtype=float)
    brent = pd.Series(
        35.0 * np.exp(0.002 * brent_steps + 0.15 * np.sin(brent_steps / 18.0)),
        index=brent_index,
        name="Brent",
    )
    return bars, brent


def _synthetic_bars() -> tuple[pd.DataFrame, pd.Series]:
    index = pd.date_range("1971-12-31", "1979-12-31", freq="ME")
    steps = np.arange(len(index), dtype=float)
    monthly_returns = 0.008 + 0.002 * np.sin(steps / 3.0) + 0.0005 * np.cos(steps / 7.0)
    gold = pd.Series(100.0 * np.cumprod(1.0 + monthly_returns), index=index, name="Gold")
    bars = pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": 1.0},
        index=index,
    )
    brent_index = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
    brent_steps = np.arange(len(brent_index), dtype=float)
    brent = pd.Series(35.0 * np.exp(0.012 * brent_steps), index=brent_index, name="Brent")
    return bars, brent


def test_loader_uses_only_eligible_prices_and_skips_unparseable_post_cutoff_values(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_source(path)

    series, metadata = read_eligible_gold_brent(path, expected_sha256=None)

    assert len(series["Gold"]) == 480
    assert len(series["Crude oil, Brent"]) == 480
    assert series["Gold"].index[0] == pd.Timestamp("1960-01-31")
    assert series["Crude oil, Brent"].index[-1] == pd.Timestamp("1999-12-31")
    assert metadata["post_1999_price_values_converted"] == 0
    assert metadata["post_1999_rows_skipped_by_series_using_date_name_only"] == {
        "Gold": 1,
        "Crude oil, Brent": 1,
    }


def test_h10_loader_skips_post_cutoff_values_and_builds_expected_monthly_index(tmp_path: Path) -> None:
    path = tmp_path / "fx.csv"
    _write_fx_source(path)

    rows, metadata = read_eligible_fx_rows(path, expected_sha256=None)
    usd = build_usd_monthly(rows)

    assert len(usd) == 348
    assert usd.index[0] == pd.Timestamp("1971-01-31")
    assert usd.index[-1] == pd.Timestamp("1999-12-31")
    assert metadata["post_1999_rate_values_converted"] == 0
    assert set(metadata["post_1999_rows_skipped_by_country_using_date_name_only"].values()) == {1}


def test_loader_fails_on_blank_eligible_price(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_source(path, blank_eligible=True)

    with pytest.raises(InputBlocked, match="non-numeric eligible price"):
        read_eligible_gold_brent(path, expected_sha256=None)


def test_loader_fails_on_missing_eligible_month(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_source(path, omit_gold_month=pd.Timestamp("1975-03-01"))

    with pytest.raises(InputBlocked, match="eligible monthly span is incomplete"):
        read_eligible_gold_brent(path, expected_sha256=None)


def test_loader_fails_on_duplicate_eligible_month(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_source(path, duplicate_brent_month=pd.Timestamp("1975-03-01"))

    with pytest.raises(InputBlocked, match="duplicate or non-chronological"):
        read_eligible_gold_brent(path, expected_sha256=None)


def test_brent_gate_is_long_flat_and_uses_one_month_lag() -> None:
    bars, brent = _synthetic_bars()
    plan = brent_gated_plan(bars, brent)
    finite = plan.target[np.isfinite(plan.target)]
    assert set(np.unique(finite)).issubset({0.0, 1.0})

    target_date = pd.Timestamp("1976-06-30")
    original_at_target = plan.target[bars.index.get_loc(target_date)]
    future_shock = brent.copy()
    future_shock.loc[target_date:] = future_shock.loc[target_date:] * 0.01
    shocked = brent_gated_plan(bars, future_shock)
    target_idx = bars.index.get_loc(target_date)
    np.testing.assert_allclose(
        shocked.target[: target_idx + 1], plan.target[: target_idx + 1], equal_nan=True
    )
    assert shocked.target[target_idx] == original_at_target


def test_synthetic_screen_runs_once_as_research_only_with_inherited_trial_count() -> None:
    bars, brent = _synthetic_screen_inputs()

    result = _screen(bars, brent)

    assert result["cumulative_trials"] == CUMULATIVE_TRIALS == 357
    assert result["status"] in {"REJECTED", "SURVIVED_DISCOVERY_AND_DEVELOPMENT"}
    assert set(result["gates"].values()).issubset({True, False})
    assert result["strategy_promoted"] is False
    assert result["held_out_span_opened"] is False
    assert result["orders_submitted"] == 0
    assert result["live"] == "LOCKED"


def test_brent_gate_turns_flat_when_lagged_twelve_month_momentum_is_nonpositive() -> None:
    bars, brent = _synthetic_bars()
    target_date = pd.Timestamp("1976-06-30")
    shocked = brent.copy()
    t = shocked.index.get_loc(target_date)
    # The target at t uses Brent through t-1, so impose a falling 12-month path
    # that ends at t-1 while leaving the gold trend unchanged.
    shocked.iloc[t - 13 : t] = np.linspace(200.0, 100.0, 13)

    plan = brent_gated_plan(bars, shocked)
    assert plan.target[bars.index.get_loc(target_date)] == 0.0
