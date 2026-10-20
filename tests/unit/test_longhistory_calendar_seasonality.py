from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory.calendar_seasonality import ACTIVE_MONTHS, calendar_seasonal_plan
from qts.research.longhistory.signals import Plan
from scripts import run_longhistory_gold_calendar_seasonality as gate_runner


def _sizer(index: pd.DatetimeIndex, size: np.ndarray | None = None) -> Plan:
    n = len(index)
    return Plan(
        target=np.ones(n, dtype=float),
        size=np.full(n, 0.5, dtype=float) if size is None else size,
        stop_dist=np.full(n, np.nan),
        rebalance=np.ones(n, dtype=bool),
        family="synthetic_sizer",
        params={},
    )


def test_fixed_month_mask_targets_the_next_bar_and_only_frozen_months() -> None:
    index = pd.date_range("1999-11-30", "2000-10-31", freq="ME")

    plan = calendar_seasonal_plan(_sizer(index), index)

    expected = [0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0]
    assert ACTIVE_MONTHS == (1, 2, 3, 8, 9)
    assert plan.target.tolist() == expected
    assert plan.family == "fixed_calendar_seasonality_long_only"
    assert np.array_equal(plan.size, np.full(len(index), 0.5))


def test_calendar_mask_preserves_volatility_warmup_as_no_signal() -> None:
    index = pd.date_range("1999-11-30", periods=4, freq="ME")
    size = np.array([np.nan, 0.5, 0.5, 0.5])

    plan = calendar_seasonal_plan(_sizer(index, size), index)

    assert np.isnan(plan.target[0])
    assert plan.target.tolist()[1:] == [1.0, 1.0, 0.0]
    assert np.isnan(plan.size[0])


def test_calendar_plan_rejects_misaligned_sizing_and_invalid_calendar() -> None:
    index = pd.date_range("1999-11-30", periods=3, freq="ME")
    short_sizer = _sizer(index[:2])

    with pytest.raises(ValueError, match="must match the calendar index"):
        calendar_seasonal_plan(short_sizer, index)

    duplicate = pd.DatetimeIndex([index[0], index[0], index[2]])
    with pytest.raises(ValueError, match="clean DatetimeIndex"):
        calendar_seasonal_plan(_sizer(duplicate), duplicate)


def test_screen_runner_executes_a_synthetic_calendar_window() -> None:
    index = pd.date_range("1971-12-31", "1999-12-31", freq="ME")
    steps = np.arange(len(index), dtype=float)
    close = 1_500.0 * np.exp(0.001 * steps + 0.035 * np.sin(steps / 4.0))
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "usd": np.exp(0.002 * np.sin(steps / 9.0)),
        },
        index=index,
    )
    sizer = gate_runner.ES.tsmom_single(
        frame,
        lookback=9,
        long_only=True,
        vol_n=gate_runner.VOL_MONTHS,
        ann=gate_runner.PERIODS_PER_YEAR,
    )
    plan = calendar_seasonal_plan(sizer, index)

    run, metrics = gate_runner._metrics(
        frame,
        plan,
        "1990-01-01",
        "1991-12-31",
        gate_runner.COST_BASE,
        trials=gate_runner.CUMULATIVE_TRIALS,
    )

    assert len(run.days) == 24
    assert metrics["bars"] == 24
    assert metrics["round_turns"] == 4
    assert metrics["deflated"]["num_trials"] == gate_runner.CUMULATIVE_TRIALS


def test_full_screen_gate_evaluation_uses_only_frozen_windows_on_synthetic_inputs() -> None:
    index = pd.date_range("1971-12-31", "1999-12-31", freq="ME")
    steps = np.arange(len(index), dtype=float)
    close = 1_500.0 * np.exp(0.001 * steps + 0.035 * np.sin(steps / 4.0))
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "usd": np.exp(0.002 * np.sin(steps / 9.0)),
        },
        index=index,
    )
    sizer = gate_runner.ES.tsmom_single(
        frame,
        lookback=9,
        long_only=True,
        vol_n=gate_runner.VOL_MONTHS,
        ann=gate_runner.PERIODS_PER_YEAR,
    )
    plans = {
        gate_runner.CANDIDATE_NAME: calendar_seasonal_plan(sizer, index),
        "ts9_lo": sizer,
        "veto9": gate_runner.hybrid_candidate_by_id("veto9").builder(frame),
    }

    result = gate_runner._evaluate(frame, plans)

    assert result["candidate_outcomes_calculated"] is True
    assert result["cumulative_trials_before"] == 360
    assert result["cumulative_trials"] == 361
    assert set(result["windows"]) == set(gate_runner.WINDOWS)
    assert result["windows"]["development"][gate_runner.CANDIDATE_NAME]["deflated"]["num_trials"] == 361
    assert len(result["development_paired_bootstrap"]["ts9_lo"]["monthly_return_differences"]) == 120
