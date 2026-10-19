from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_longhistory_cpi_acceleration_gate import (
    CUMULATIVE_TRIALS,
    REQUIRED_CPI_YEARS,
    InputBlocked,
    _screen,
    build_input_frame,
    cpi_acceleration_by_year,
    cpi_acceleration_plan,
    read_eligible_cpi,
    read_eligible_gold,
)

ELIGIBLE_MONTHS = pd.date_range("1960-01-01", "1999-12-01", freq="MS")


def _write_gold_source(path: Path, *, missing_month: pd.Timestamp | None = None) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["date", "commodity_name", "price_nominal_usd"])
        writer.writeheader()
        for i, stamp in enumerate(ELIGIBLE_MONTHS):
            if missing_month is not None and stamp == missing_month:
                continue
            writer.writerow(
                {
                    "date": stamp.strftime("%Y-%m-%d"),
                    "commodity_name": "Gold",
                    "price_nominal_usd": f"{100.0 + i * 0.25:.6f}",
                }
            )
        writer.writerow(
            {
                "date": "2000-01-01",
                "commodity_name": "Gold",
                "price_nominal_usd": "POST_CUTOFF_MUST_NOT_PARSE",
            }
        )


def _synthetic_cpi_values() -> pd.Series:
    years = list(REQUIRED_CPI_YEARS)
    levels = np.empty(len(years), dtype=float)
    fixed = {1968: 100.0, 1969: 101.0, 1970: 103.0, 1971: 106.0, 1972: 108.0}
    for i, year in enumerate(years):
        if year in fixed:
            levels[i] = fixed[year]
        elif year > 1972:
            levels[i] = levels[i - 1] * 1.01
        else:
            levels[i] = levels[i - 1] * 1.005
    return pd.Series(levels, index=pd.Index(years, name="Year"), name="CPI")


def _write_cpi_source(path: Path, *, omit_year: int | None = None, duplicate_year: int | None = None) -> None:
    fields = ["Country Name", "Country Code", "Year", "CPI"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        cpi = _synthetic_cpi_values()
        for year in REQUIRED_CPI_YEARS:
            if year == omit_year:
                continue
            row = {
                "Country Name": "United States",
                "Country Code": "USA",
                "Year": str(year),
                "CPI": f"{cpi.loc[year]:.8f}",
            }
            writer.writerow(row)
            if year == duplicate_year:
                writer.writerow(row)
        writer.writerow(
            {
                "Country Name": "United States",
                "Country Code": "USA",
                "Year": "2000",
                "CPI": "POST_CUTOFF_MUST_NOT_PARSE",
            }
        )


def _synthetic_bars() -> pd.DataFrame:
    index = pd.date_range("1971-12-31", "1999-12-31", freq="ME")
    prices = pd.Series(100.0 * np.exp(0.004 * np.arange(len(index))), index=index, name="Gold")
    return pd.DataFrame({"open": prices, "high": prices, "low": prices, "close": prices}, index=index)


def test_gold_loader_skips_unparseable_post_cutoff_price_cell(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_gold_source(path)

    gold, metadata = read_eligible_gold(path, expected_sha256=None)

    assert len(gold) == 480
    assert gold.index[0] == pd.Timestamp("1960-01-31")
    assert gold.index[-1] == pd.Timestamp("1999-12-31")
    assert metadata["post_1999_rows_skipped_using_date_name_only"] == 1
    assert metadata["post_1999_price_values_converted"] == 0


def test_gold_loader_fails_on_missing_pre_2000_month(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_gold_source(path, missing_month=pd.Timestamp("1975-03-01"))

    with pytest.raises(InputBlocked, match="eligible Gold monthly span is incomplete"):
        read_eligible_gold(path, expected_sha256=None)


def test_cpi_loader_uses_only_required_usa_years_and_skips_post_cutoff_value(tmp_path: Path) -> None:
    path = tmp_path / "cpi.csv"
    _write_cpi_source(path)

    cpi, metadata = read_eligible_cpi(path, expected_blob_sha1=None)

    assert tuple(cpi.index) == REQUIRED_CPI_YEARS
    assert len(cpi) == 30
    assert metadata["post_1999_rows_skipped_using_country_year_only"] == 1
    assert metadata["post_1999_cpi_values_converted"] == 0
    assert metadata["historical_release_vintages_available"] is False


def test_cpi_loader_fails_closed_on_missing_required_year(tmp_path: Path) -> None:
    path = tmp_path / "cpi.csv"
    _write_cpi_source(path, omit_year=1984)

    with pytest.raises(InputBlocked, match="required USA CPI annual values are missing"):
        read_eligible_cpi(path, expected_blob_sha1=None)


def test_cpi_loader_fails_closed_on_duplicate_required_year(tmp_path: Path) -> None:
    path = tmp_path / "cpi.csv"
    _write_cpi_source(path, duplicate_year=1984)

    with pytest.raises(InputBlocked, match="duplicate or non-chronological"):
        read_eligible_cpi(path, expected_blob_sha1=None)


def test_acceleration_uses_only_lagged_annual_values_and_preserves_sign() -> None:
    cpi = _synthetic_cpi_values()
    acceleration = cpi_acceleration_by_year(cpi)

    assert acceleration.loc[1971] > 0.0
    assert acceleration.loc[1972] < 0.0

    bars = _synthetic_bars()
    plan = cpi_acceleration_plan(bars, cpi)
    jan_1973 = bars.index.get_loc(pd.Timestamp("1973-01-31"))
    jan_1974 = bars.index.get_loc(pd.Timestamp("1974-01-31"))
    assert plan.target[jan_1973] > 0.0  # 1973 decision uses acceleration from 1971.
    assert plan.target[jan_1974] == 0.0  # 1974 decision uses acceleration from 1972.

    future_changed = cpi.copy()
    future_changed.loc[1972:] = future_changed.loc[1972:] * 7.0
    future_plan = cpi_acceleration_plan(bars, future_changed)
    np.testing.assert_allclose(future_plan.target[: jan_1973 + 1], plan.target[: jan_1973 + 1], equal_nan=True)


def test_input_frame_has_only_the_registered_pre_2000_gold_window() -> None:
    index = pd.date_range("1960-01-31", "1999-12-31", freq="ME")
    gold = pd.Series(100.0 + np.arange(len(index)), index=index, name="Gold")

    frame = build_input_frame(gold)

    assert frame.index[0] == pd.Timestamp("1971-12-31")
    assert frame.index[-1] == pd.Timestamp("1999-12-31")
    assert len(frame) == 337
    assert set(frame.columns) == {"open", "high", "low", "close"}


def test_synthetic_screen_is_single_trial_and_keeps_all_safety_locks() -> None:
    result = _screen(_synthetic_bars(), _synthetic_cpi_values())

    assert result["cumulative_trials"] == CUMULATIVE_TRIALS == 360
    assert result["status"] in {"REJECTED", "SCREEN_PASS_UNVALIDATED_SOURCE_VINTAGE"}
    assert set(result["gates"].values()).issubset({True, False})
    assert result["source_vintage_prevents_validation"] is True
    assert result["strategy_promoted"] is False
    assert result["held_out_span_opened"] is False
    assert result["orders_submitted"] == 0
    assert result["live"] == "LOCKED"
