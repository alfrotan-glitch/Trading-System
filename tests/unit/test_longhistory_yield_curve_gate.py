from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory.signals import Plan
from qts.research.longhistory.yield_curve_gate import (
    InputBlocked,
    apply_inversion_gate,
    lagged_term_spread,
    read_daily_dff_monthly,
    read_eligible_gold,
    read_monthly_gs10,
)
from scripts import run_longhistory_yield_curve_inversion_gate as gate_runner


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_lagged_spread_uses_previous_complete_month_and_strict_inversion() -> None:
    index = pd.date_range("1999-10-31", periods=4, freq="ME")
    gs10 = pd.Series([3.0, 1.0, 4.0, 2.0], index=index)
    dff = pd.Series([4.0, 2.0, 4.0, 3.0], index=index)

    feature = lagged_term_spread(gs10, dff, index=index)

    assert np.isnan(feature.iloc[0])
    assert feature.iloc[1] == -1.0
    assert feature.iloc[2] == -1.0
    assert feature.iloc[3] == 0.0
    assert bool(feature.iloc[1] < 0.0)
    assert not bool(feature.iloc[3] < 0.0)


def test_inversion_gate_flattens_normal_or_zero_spreads_and_preserves_warmup() -> None:
    index = pd.date_range("1999-10-31", periods=4, freq="ME")
    base = Plan(
        target=np.array([np.nan, 1.0, 1.0, 1.0]),
        size=np.array([np.nan, 0.5, 0.5, 0.5]),
        stop_dist=np.full(4, np.nan),
        rebalance=np.array([False, True, True, True]),
        family="tsmom_single",
        params={"lookback": 9},
    )
    feature = pd.Series([np.nan, -0.01, 0.0, 0.25], index=index)

    gated = apply_inversion_gate(base, feature, index=index)

    assert np.isnan(gated.target[0])
    assert gated.target.tolist()[1:] == [1.0, 0.0, 0.0]
    assert gated.size.tolist()[1:] == [0.5, 0.5, 0.5]
    assert gated.family == "yield_curve_inversion_gated_tsmom"


def test_inversion_gate_fails_closed_if_feature_missing_for_tradable_base() -> None:
    index = pd.date_range("1999-10-31", periods=2, freq="ME")
    base = Plan(
        target=np.array([np.nan, 1.0]),
        size=np.array([np.nan, 0.5]),
        stop_dist=np.full(2, np.nan),
        rebalance=np.zeros(2, dtype=bool),
        family="tsmom_single",
        params={"lookback": 9},
    )
    feature = pd.Series([np.nan, np.nan], index=index)

    with pytest.raises(InputBlocked, match="missing where the base trend is tradable"):
        apply_inversion_gate(base, feature, index=index)


def test_gold_loader_skips_post_cutoff_price_cell_before_numeric_conversion(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "gold.csv",
        "date,commodity_name,price_nominal_usd\n"
        "1999-11-01,Gold,10.0\n"
        "1999-12-01,Gold,11.0\n"
        "2000-01-01,Gold,THIS_MUST_NOT_BE_PARSED\n",
    )
    expected = pd.date_range("1999-11-30", "1999-12-31", freq="ME")

    gold, meta = read_eligible_gold(
        path,
        expected_sha256=None,
        expected_git_blob_sha1=None,
        expected_months=expected,
    )

    assert gold.to_list() == [10.0, 11.0]
    assert meta["post_1999_rows_skipped_by_date_name_only"] == 1
    assert meta["post_1999_price_values_converted"] == 0


def test_gs10_loader_skips_post_cutoff_rate_cell_before_numeric_conversion(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "gs10.csv",
        "Date,Rate\n1999-11-01,5.8\n1999-12-01,5.7\n2000-01-01,NOT_A_RATE\n",
    )
    expected = pd.date_range("1999-11-30", "1999-12-31", freq="ME")

    gs10, meta = read_monthly_gs10(
        path,
        expected_git_blob_sha1=None,
        expected_months=expected,
    )

    assert gs10.to_list() == [5.8, 5.7]
    assert meta["post_1999_rate_values_converted"] == 0


def test_dff_loader_skips_post_cutoff_rate_cell_before_numeric_conversion(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "dff.csv",
        "Date,ffr_effective,ffr_targ,ffr_targ_low,ffr_targ_high\n"
        "1999-11-01,5.2,,,\n"
        "1999-11-02,5.4,,,\n"
        "1999-12-01,5.1,,,\n"
        "2000-01-03,NOT_A_RATE,,,\n",
    )
    expected = pd.date_range("1999-11-30", "1999-12-31", freq="ME")

    dff, meta = read_daily_dff_monthly(
        path,
        expected_git_blob_sha1=None,
        expected_months=expected,
    )

    assert dff.iloc[0] == pytest.approx(5.3)
    assert dff.iloc[1] == pytest.approx(5.1)
    assert meta["post_1999_rate_values_converted"] == 0


def test_gs10_loader_rejects_duplicate_months(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "gs10.csv",
        "Date,Rate\n1999-11-01,5.8\n1999-11-15,5.7\n",
    )

    with pytest.raises(InputBlocked, match="duplicate GS10 month"):
        read_monthly_gs10(path, expected_git_blob_sha1=None)


def test_screen_runner_builds_candidate_and_metrics_from_synthetic_monthly_inputs() -> None:
    model_index = gate_runner.MODEL_MONTHS
    rate_index = gate_runner.GOLD_MONTHS
    model_steps = np.arange(len(model_index), dtype=float)
    rate_steps = np.arange(len(rate_index), dtype=float)
    close = 1_500.0 * np.exp(0.0015 * model_steps + 0.04 * np.sin(model_steps / 5.0))
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "usd": np.exp(0.002 * np.sin(model_steps / 7.0)),
        },
        index=model_index,
    )
    gs10 = pd.Series(3.0 + 0.7 * np.sin(rate_steps / 11.0), index=rate_index)
    dff = pd.Series(3.0 - 0.7 * np.sin(rate_steps / 11.0 + 0.4), index=rate_index)

    plans, spread = gate_runner._build_plans(frame, gs10, dff)

    base = plans["ts9_lo"]
    gated = plans["yc_inversion_ts9_lo"]
    finite = np.isfinite(base.target)
    expected = np.where(spread.to_numpy()[finite] < 0.0, base.target[finite], 0.0)
    assert np.array_equal(gated.target[finite], expected)
    assert np.nanmin(gated.target) >= 0.0

    run, metrics = gate_runner._metrics(
        frame,
        gated,
        "1990-01-01",
        "1991-12-31",
        gate_runner.COST_BASE,
        trials=gate_runner.CUMULATIVE_TRIALS,
    )

    assert len(run.days) == 24
    assert str(run.days[0].date()) == "1990-01-31"
    assert str(run.days[-1].date()) == "1991-12-31"
    assert metrics["bars"] == 24
    assert metrics["deflated"]
