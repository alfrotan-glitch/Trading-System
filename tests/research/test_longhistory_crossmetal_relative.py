"""Synthetic-only tests for the frozen long-history cross-metal runner."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.longhistory.engine import CostModel
from qts.research.longhistory.signals import Plan
from scripts.build_longhistory_monthly_dataset import BASKET as PINNED_H10_BASKET
from scripts.run_longhistory_crossmetal_relative import (
    BASKET,
    EXPECTED_METAL_MONTHS,
    build_usd_monthly,
    crossmetal_plan,
    read_eligible_fx_rows,
    read_eligible_metal_rows,
    run_frozen_window,
)


def test_h10_basket_matches_pinned_monthly_builder() -> None:
    assert BASKET == PINNED_H10_BASKET


def test_metal_loader_never_converts_post_1999_price_cells(tmp_path: Path) -> None:
    path = tmp_path / "metals.csv"
    fieldnames = ["date", "commodity_name", "price_nominal_usd"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for name in ("Gold", "Silver", "Platinum"):
            for offset, month_end in enumerate(EXPECTED_METAL_MONTHS):
                first = month_end.to_period("M").start_time.date().isoformat()
                writer.writerow(
                    {"date": first, "commodity_name": name, "price_nominal_usd": str(100 + offset / 10)}
                )
            writer.writerow({"date": "2000-01-01", "commodity_name": name, "price_nominal_usd": "MUST_NOT_PARSE"})

    metals, metadata = read_eligible_metal_rows(path, expected_sha256=None)

    assert all(len(metals[name]) == 480 for name in ("Gold", "Silver", "Platinum"))
    assert metadata["post_1999_rows_skipped_by_series_using_date_name_only"] == {
        "Gold": 1,
        "Silver": 1,
        "Platinum": 1,
    }
    assert metadata["post_1999_price_values_converted"] == 0


def test_fx_loader_never_converts_post_1999_rates(tmp_path: Path) -> None:
    path = tmp_path / "fx.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Date", "Country", "Exchange rate"])
        writer.writeheader()
        for country in BASKET:
            writer.writerow({"Date": "1971-01-04", "Country": country, "Exchange rate": ""})
            writer.writerow({"Date": "1971-01-05", "Country": country, "Exchange rate": "1.0"})
            writer.writerow({"Date": "1999-12-31", "Country": country, "Exchange rate": "1.5"})
            writer.writerow({"Date": "2000-01-03", "Country": country, "Exchange rate": "MUST_NOT_PARSE"})

    rows, metadata = read_eligible_fx_rows(path, expected_sha256=None)

    assert len(rows) == 2 * len(BASKET)
    assert rows["date"].max() == pd.Timestamp("1999-12-31")
    assert set(rows["country"]) == set(BASKET)
    assert all(metadata["missing_eligible_rate_rows_skipped_by_country"][name] == 1 for name in BASKET)
    assert all(metadata["post_1999_rows_skipped_by_country_using_date_name_only"][name] == 1 for name in BASKET)
    assert metadata["post_1999_rate_values_converted"] == 0


def test_h10_geometric_index_build_is_complete_and_month_end_aligned() -> None:
    month_ends = pd.date_range("1971-01-31", "1999-12-31", freq="ME")
    rows = [
        (stamp, country, float(country_index + 1) * (1.0 + offset / 10000.0))
        for country_index, country in enumerate(BASKET)
        for offset, stamp in enumerate(month_ends)
    ]
    fx = pd.DataFrame(rows, columns=("date", "country", "rate"))

    usd = build_usd_monthly(fx)

    assert usd.index.equals(month_ends)
    assert len(usd) == 348
    assert np.isfinite(usd.to_numpy()).all()
    assert (usd > 0.0).all()


def test_crossmetal_signal_is_long_or_flat_from_lagged_12_month_relative_return() -> None:
    index = pd.date_range("1971-12-31", periods=37, freq="ME")
    gold = np.full(len(index), 100.0)
    silver = np.full(len(index), 100.0)
    platinum = np.full(len(index), 100.0)
    for month in range(1, 13):
        gold[month] = gold[month - 1] * 1.01
    for month in range(13, len(index)):
        gold[month] = gold[month - 1] * (1.0 + 0.002 * np.sin(month))
    for month in range(13, 25):
        silver[month] = silver[month - 1] * 1.02
        platinum[month] = platinum[month - 1] * 1.02
    for month in range(25, len(index)):
        silver[month] = silver[month - 1] * (1.0 + 0.001 * np.cos(month))
        platinum[month] = platinum[month - 1] * (1.0 + 0.001 * np.sin(month))

    metals = {
        "Gold": pd.Series(gold, index=index),
        "Silver": pd.Series(silver, index=index),
        "Platinum": pd.Series(platinum, index=index),
    }
    frame = pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": np.linspace(100.0, 104.0, len(index))},
        index=index,
    )

    plan = crossmetal_plan(frame, metals)

    assert plan.target[12] == 1.0
    assert plan.target[24] == 0.0
    assert np.isnan(plan.target[11])  # no 12-month lookback/sizing yet
    assert np.isfinite(plan.size[12])
    assert np.isfinite(plan.size[24])
    assert np.nanmin(plan.target) == 0.0
    assert np.nanmax(plan.target) == 1.0

    log_returns = 0.01 + 0.002 * np.sin(np.arange(len(index)))
    equal_prices = 100.0 * np.exp(np.cumsum(log_returns))
    equal_metals = {name: pd.Series(equal_prices, index=index) for name in ("Gold", "Silver", "Platinum")}
    equal_frame = pd.DataFrame(
        {
            "open": equal_prices,
            "high": equal_prices,
            "low": equal_prices,
            "close": equal_prices,
            "usd": np.linspace(100.0, 104.0, len(index)),
        },
        index=index,
    )
    equal_plan = crossmetal_plan(equal_frame, equal_metals)
    assert equal_plan.target[12] == 0.0  # exact relative-strength tie is flat


def test_window_uses_pre_window_signal_to_fill_first_in_window_month() -> None:
    index = pd.date_range("1972-11-30", periods=5, freq="ME")
    prices = np.array([100.0, 105.0, 110.0, 115.0, 120.0])
    frame = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices},
        index=index,
    )
    target = np.full(len(index), np.nan)
    size = np.full(len(index), np.nan)
    rebalance = np.zeros(len(index), dtype=bool)
    target[1] = 1.0  # signal at December close; fill at the January open
    size[1] = 0.5
    rebalance[1] = True
    plan = Plan(target, size, np.full(len(index), np.nan), rebalance, "synthetic", {})
    zero_cost = CostModel(
        spread_bps=0.0,
        slippage_bps=0.0,
        commission_usd_per_lot_side=0.0,
    )

    run = run_frozen_window(frame, plan, "1973-01-01", "1973-02-28", zero_cost)

    assert run.days.equals(index[2:4])
    assert len(run.trades) == 1
    assert run.trades[0].entry_day == index[2]
    assert run.trades[0].entry_price == prices[2]
    assert run.net_usd > 0.0
