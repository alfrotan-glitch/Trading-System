"""Synthetic-only tests for the frozen raw-price commodity-breadth runner."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import run_longhistory_brent_gate as COMMON
from scripts.run_longhistory_commodity_breadth_gate import (
    BASKET,
    CANDIDATE_ID,
    CUMULATIVE_TRIALS,
    REGISTERED_SERIES,
    InputBlocked,
    _screen,
    build_commodity_breadth,
    commodity_breadth_gated_plan,
    read_eligible_commodity_panel,
)

ELIGIBLE_MONTHS = pd.date_range("1960-01-01", "1999-12-01", freq="MS")


def _write_commodity_source(
    path: Path,
    *,
    blank_eligible: tuple[str, pd.Timestamp] | None = None,
    omit_month: tuple[str, pd.Timestamp] | None = None,
    duplicate_month: tuple[str, pd.Timestamp] | None = None,
) -> None:
    fields = ["date", "commodity_name", "price_nominal_usd"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"date": "NOT_A_DATE", "commodity_name": "Crude oil, Brent", "price_nominal_usd": "UNUSED"})
        for series_index, name in enumerate(REGISTERED_SERIES):
            for i, stamp in enumerate(ELIGIBLE_MONTHS):
                if omit_month == (name, stamp):
                    continue
                if duplicate_month == (name, stamp):
                    writer.writerow(
                        {
                            "date": stamp.strftime("%Y-%m-%d"),
                            "commodity_name": name,
                            "price_nominal_usd": f"{100.0 + series_index + i * 0.1:.6f}",
                        }
                    )
                raw_price = "" if blank_eligible == (name, stamp) else f"{100.0 + series_index + i * 0.1:.6f}"
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


def _synthetic_prices(
    months: pd.DatetimeIndex, *, positive_series: int = 28, trending_panel: bool = False
) -> dict[str, pd.Series]:
    steps = np.arange(len(months), dtype=float)
    gold_log_levels = 0.008 * steps + 0.002 * np.sin(steps / 3.0)
    prices: dict[str, pd.Series] = {"Gold": pd.Series(100.0 * np.exp(gold_log_levels), index=months, name="Gold")}
    for i, name in enumerate(BASKET):
        if trending_panel:
            drift = 0.001 if i < 30 else -0.001
            monthly_log_returns = drift + 0.0002 * np.sin(steps / (4.0 + (i % 5)) + i)
            log_levels = np.cumsum(monthly_log_returns)
        else:
            log_levels = np.zeros(len(months), dtype=float)
            if len(months) > 12:
                if i < positive_series:
                    log_levels[12] = 0.1
                elif i == positive_series and positive_series < len(BASKET):
                    log_levels[12] = 0.0
                else:
                    log_levels[12] = -0.1
        prices[name] = pd.Series(100.0 * np.exp(log_levels), index=months, name=name)
    return prices


def _bars_from_gold(gold: pd.Series) -> pd.DataFrame:
    steps = np.arange(len(gold), dtype=float)
    usd = pd.Series(np.exp(0.001 * steps + 0.02 * np.sin(steps / 24.0)), index=gold.index)
    return pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd},
        index=gold.index,
    )


def test_loader_uses_raw_prices_and_never_parses_post_cutoff_values(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_commodity_source(path)

    prices, metadata = read_eligible_commodity_panel(path, expected_sha256=None)

    assert set(prices) == set(REGISTERED_SERIES)
    assert all(len(item) == 480 for item in prices.values())
    assert prices["Gold"].index[0] == pd.Timestamp("1960-01-31")
    assert prices[BASKET[-1]].index[-1] == pd.Timestamp("1999-12-31")
    assert metadata["registered_series_count"] == 43
    assert metadata["post_1999_price_values_converted"] == 0
    assert set(metadata["post_1999_rows_skipped_by_series_using_date_name_only"].values()) == {1}


def test_loader_fails_closed_on_blank_eligible_or_missing_month(tmp_path: Path) -> None:
    blank_path = tmp_path / "blank.csv"
    _write_commodity_source(
        blank_path,
        blank_eligible=(BASKET[0], pd.Timestamp("1960-01-01")),
    )
    with pytest.raises(InputBlocked, match="non-numeric eligible price"):
        read_eligible_commodity_panel(blank_path, expected_sha256=None)

    missing_path = tmp_path / "missing.csv"
    _write_commodity_source(
        missing_path,
        omit_month=(BASKET[0], pd.Timestamp("1975-03-01")),
    )
    with pytest.raises(InputBlocked, match="eligible monthly span is incomplete"):
        read_eligible_commodity_panel(missing_path, expected_sha256=None)


def test_breadth_counts_strictly_positive_returns_and_uses_two_thirds_threshold() -> None:
    months = pd.date_range("1960-01-31", periods=24, freq="ME")
    at_threshold = _synthetic_prices(months, positive_series=28)
    above = build_commodity_breadth(at_threshold)
    assert above.loc[months[13]] == pytest.approx(2.0 / 3.0)

    below_threshold = _synthetic_prices(months, positive_series=27)
    below = build_commodity_breadth(below_threshold)
    assert below.loc[months[13]] == pytest.approx(27.0 / 42.0)
    assert below.loc[months[13]] < 2.0 / 3.0


def test_breadth_feature_is_one_month_lagged() -> None:
    months = pd.date_range("1960-01-31", periods=36, freq="ME")
    prices = _synthetic_prices(months, positive_series=28)
    original = build_commodity_breadth(prices)
    target_idx = 20
    shocked = {name: series.copy() for name, series in prices.items()}
    for name in BASKET:
        shocked[name].iloc[target_idx:] *= np.linspace(1.5, 0.6, len(months) - target_idx)
    after_current_month_shock = build_commodity_breadth(shocked)

    np.testing.assert_allclose(
        after_current_month_shock.iloc[: target_idx + 1],
        original.iloc[: target_idx + 1],
        equal_nan=True,
    )


def test_candidate_is_long_only_and_flats_below_the_breadth_threshold() -> None:
    months = pd.date_range("1971-12-31", periods=48, freq="ME")
    target_date = months[13]

    at_threshold = _synthetic_prices(months, positive_series=28)
    bars = _bars_from_gold(at_threshold["Gold"])
    long_plan = commodity_breadth_gated_plan(bars, at_threshold)
    target_idx = bars.index.get_loc(target_date)
    assert long_plan.target[target_idx] == 1.0
    assert set(np.unique(long_plan.target[np.isfinite(long_plan.target)])).issubset({0.0, 1.0})

    below_threshold = _synthetic_prices(months, positive_series=27)
    flat_plan = commodity_breadth_gated_plan(_bars_from_gold(below_threshold["Gold"]), below_threshold)
    assert flat_plan.target[target_idx] == 0.0


def test_synthetic_screen_inherits_trial_count_359_and_research_only_flags() -> None:
    months = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
    prices = _synthetic_prices(months, trending_panel=True)
    usd_months = pd.date_range("1971-01-31", "1999-12-31", freq="ME")
    usd_steps = np.arange(len(usd_months), dtype=float)
    usd = pd.Series(np.exp(0.001 * usd_steps + 0.02 * np.sin(usd_steps / 24.0)), index=usd_months)
    bars = COMMON.build_input_frame(prices["Gold"], usd)

    result = _screen(bars, prices)

    assert result["cumulative_trials"] == CUMULATIVE_TRIALS == 359
    assert CANDIDATE_ID in result["windows"]["development"]
    assert result["status"] in {"REJECTED", "SURVIVED_DISCOVERY_AND_DEVELOPMENT"}
    assert set(result["gates"].values()).issubset({True, False})
    assert result["strategy_promoted"] is False
    assert result["held_out_span_opened"] is False
    assert result["orders_submitted"] == 0
    assert result["live"] == "LOCKED"
