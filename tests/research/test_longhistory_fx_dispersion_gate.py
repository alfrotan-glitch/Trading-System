"""Synthetic-only tests for the frozen long-history FX-dispersion runner."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_longhistory_fx_dispersion_gate import (
    BASKET,
    CANDIDATE_ID,
    CUMULATIVE_TRIALS,
    INVERTED_QUOTE_COUNTRIES,
    InputBlocked,
    _screen,
    build_fx_dispersion,
    build_monthly_fx_closes,
    fx_dispersion_gated_plan,
    read_eligible_gold,
)

ELIGIBLE_MONTHS = pd.date_range("1960-01-01", "1999-12-01", freq="MS")


def _write_gold_source(path: Path, *, blank_eligible: bool = False) -> None:
    fields = ["date", "commodity_name", "price_nominal_usd"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        # The loader must ignore unrelated commodity rows without parsing them.
        writer.writerow({"date": "NOT_A_DATE", "commodity_name": "Crude oil, Brent", "price_nominal_usd": "UNUSED"})
        for i, stamp in enumerate(ELIGIBLE_MONTHS):
            raw_price = "" if blank_eligible and i == 0 else f"{180.0 + i * 0.2:.6f}"
            writer.writerow(
                {
                    "date": stamp.strftime("%Y-%m-%d"),
                    "commodity_name": "Gold",
                    "price_nominal_usd": raw_price,
                }
            )
        writer.writerow(
            {
                "date": "2000-01-01",
                "commodity_name": "Gold",
                "price_nominal_usd": "POST_CUTOFF_MUST_NOT_PARSE",
            }
        )


def _oriented_to_raw_rate(country: str, log_level: float) -> float:
    """Convert common currency/USD log level to the source's quote orientation."""
    return float(np.exp(-log_level if country in INVERTED_QUOTE_COUNTRIES else log_level))


def _fx_matrix_with_lagged_returns(months: pd.DatetimeIndex, oriented_12m_returns: np.ndarray) -> pd.DataFrame:
    rates = pd.DataFrame(1.0, index=months, columns=BASKET, dtype=float)
    if len(months) < 14 or oriented_12m_returns.shape != (len(BASKET),):
        raise ValueError("synthetic matrix requires at least 14 months and eight returns")
    # Decision month 13 uses the move from month 0 through month 12.
    for country_index, country in enumerate(BASKET):
        rates.iloc[12, country_index] = _oriented_to_raw_rate(country, float(oriented_12m_returns[country_index]))
    return rates


def _synthetic_screen_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("1971-12-31", "1999-12-31", freq="ME")
    steps = np.arange(len(index), dtype=float)
    monthly_returns = 0.004 + 0.012 * np.sin(steps / 10.0) + 0.004 * np.cos(steps / 4.0)
    gold = pd.Series(100.0 * np.cumprod(1.0 + monthly_returns), index=index, name="Gold")
    usd = pd.Series(np.exp(0.001 * steps + 0.02 * np.sin(steps / 24.0)), index=index, name="usd")
    bars = pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd},
        index=index,
    )

    fx_months = pd.date_range("1971-01-31", "1999-12-31", freq="ME")
    fx_steps = np.arange(len(fx_months), dtype=float)
    fx = pd.DataFrame(index=fx_months, columns=BASKET, dtype=float)
    for country_index, country in enumerate(BASKET):
        common_log_level = 0.015 * np.sin(fx_steps / 9.0)
        differential = (country_index - 3.5) * 0.012 * np.sin(fx_steps / 5.0 + country_index)
        oriented = common_log_level + differential
        source_log_level = -oriented if country in INVERTED_QUOTE_COUNTRIES else oriented
        fx[country] = np.exp(source_log_level)
    return bars, fx


def test_gold_loader_skips_post_cutoff_prices_and_unregistered_commodities(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_gold_source(path)

    gold, metadata = read_eligible_gold(path, expected_sha256=None)

    assert len(gold) == 480
    assert gold.index[0] == pd.Timestamp("1960-01-31")
    assert gold.index[-1] == pd.Timestamp("1999-12-31")
    assert metadata["post_1999_price_values_converted"] == 0
    assert metadata["post_1999_rows_skipped_using_date_name_only"] == 1


def test_gold_loader_fails_closed_on_blank_eligible_price(tmp_path: Path) -> None:
    path = tmp_path / "commodity.csv"
    _write_gold_source(path, blank_eligible=True)

    with pytest.raises(InputBlocked, match="non-numeric eligible price"):
        read_eligible_gold(path, expected_sha256=None)


def test_monthly_fx_close_uses_last_valid_observation_without_monthly_forward_fill() -> None:
    rows: list[tuple[pd.Timestamp, str, float]] = []
    jan = pd.Timestamp("1971-01-31")
    feb = pd.Timestamp("1971-02-28")
    mar = pd.Timestamp("1971-03-31")
    for country_index, country in enumerate(BASKET):
        rows.append((pd.Timestamp("1971-01-05"), country, 1.0 + country_index))
        rows.append((pd.Timestamp("1971-01-25"), country, 2.0 + country_index))
        if country != "Canada":
            rows.append((pd.Timestamp("1971-02-20"), country, 3.0 + country_index))
        rows.append((pd.Timestamp("1971-03-10"), country, 4.0 + country_index))
    source = pd.DataFrame(rows, columns=("date", "country", "rate"))

    closes = build_monthly_fx_closes(source)

    assert closes.index.equals(pd.DatetimeIndex([jan, feb, mar], name="date"))
    assert closes.loc[jan, "Australia"] == 2.0
    assert np.isnan(closes.loc[feb, "Canada"])
    assert closes.loc[mar, "Canada"] == 5.0


def test_fx_dispersion_orients_quotes_then_computes_cross_sectional_population_sd() -> None:
    months = pd.date_range("1971-01-31", periods=14, freq="ME")
    common_move = _fx_matrix_with_lagged_returns(months, np.full(len(BASKET), 0.08))
    common_dispersion = build_fx_dispersion(common_move)
    assert common_dispersion.loc[months[13]] == pytest.approx(0.0, abs=1e-12)

    divergent_moves = np.array([0.06] * 4 + [-0.06] * 4, dtype=float)
    divergent = _fx_matrix_with_lagged_returns(months, divergent_moves)
    dispersion = build_fx_dispersion(divergent)
    assert dispersion.loc[months[13]] == pytest.approx(0.06, abs=1e-12)
    assert np.isnan(dispersion.loc[months[12]])


def test_fx_dispersion_uses_one_month_lag() -> None:
    months = pd.date_range("1971-01-31", periods=30, freq="ME")
    rates = pd.DataFrame(index=months, columns=BASKET, dtype=float)
    for country_index, country in enumerate(BASKET):
        oriented = 0.01 * np.sin(np.arange(len(months), dtype=float) / (2.0 + country_index))
        rates[country] = [_oriented_to_raw_rate(country, float(value)) for value in oriented]
    original = build_fx_dispersion(rates)
    target_idx = 20
    shocked = rates.copy()
    shocked.iloc[target_idx:, :] *= np.linspace(1.2, 0.7, len(months) - target_idx)[:, None]
    after_current_month_shock = build_fx_dispersion(shocked)

    np.testing.assert_allclose(
        after_current_month_shock.iloc[: target_idx + 1],
        original.iloc[: target_idx + 1],
        equal_nan=True,
    )


def test_candidate_long_flat_gate_and_missing_currency_coverage() -> None:
    months = pd.date_range("1971-01-31", periods=72, freq="ME")
    fx = pd.DataFrame(1.0, index=months, columns=BASKET, dtype=float)
    target_date = pd.Timestamp("1975-06-30")
    target_fx_idx = months.get_loc(target_date)
    lagged_returns = np.array([0.06] * 4 + [-0.06] * 4, dtype=float)
    for country_index, country in enumerate(BASKET):
        fx.iloc[target_fx_idx - 1, country_index] = _oriented_to_raw_rate(country, float(lagged_returns[country_index]))

    bar_index = pd.date_range("1971-12-31", "1976-12-31", freq="ME")
    steps = np.arange(len(bar_index), dtype=float)
    log_returns = 0.008 + 0.002 * np.sin(steps / 3.0) + 0.0005 * np.cos(steps / 7.0)
    prices = 100.0 * np.exp(np.cumsum(log_returns))
    bars = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices, "usd": 1.0},
        index=bar_index,
    )

    plan = fx_dispersion_gated_plan(bars, fx)
    target_bar_idx = bar_index.get_loc(target_date)
    assert plan.target[target_bar_idx] == 1.0
    assert plan.target[target_bar_idx] in {0.0, 1.0}

    insufficient = fx.copy()
    insufficient.loc[:, list(BASKET[-3:])] = np.nan
    unavailable_plan = fx_dispersion_gated_plan(bars, insufficient)
    assert unavailable_plan.target[target_bar_idx] == 0.0

    quiet = fx.copy()
    for country_index, country in enumerate(BASKET):
        # One common-oriented USD move is not cross-sectional dispersion.
        quiet.iloc[target_fx_idx - 1, country_index] = _oriented_to_raw_rate(country, 0.08)
    quiet_plan = fx_dispersion_gated_plan(bars, quiet)
    assert quiet_plan.target[target_bar_idx] == 0.0


def test_synthetic_screen_uses_trial_count_358_and_stays_research_only() -> None:
    bars, monthly_fx = _synthetic_screen_inputs()

    result = _screen(bars, monthly_fx)

    assert result["cumulative_trials"] == CUMULATIVE_TRIALS == 358
    assert CANDIDATE_ID in result["windows"]["development"]
    assert result["status"] in {"REJECTED", "SURVIVED_DISCOVERY_AND_DEVELOPMENT"}
    assert set(result["gates"].values()).issubset({True, False})
    assert result["strategy_promoted"] is False
    assert result["held_out_span_opened"] is False
    assert result["orders_submitted"] == 0
    assert result["live"] == "LOCKED"
