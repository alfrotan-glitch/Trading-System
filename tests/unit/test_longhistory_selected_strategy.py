"""Regression coverage for the named, research-only XAUUSD candidate.

Every price in this file is synthetic and deliberately simple. The checked-in
smoke-run numbers test signal/engine/cost wiring and reproducibility only; they
are not performance evidence and cannot support an edge claim.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory import checks as C
from qts.research.longhistory import protocol as P
from qts.research.longhistory import signals as G
from qts.research.longhistory.selected import (
    SELECTED_CANDIDATE_ID,
    SELECTED_PROTOCOL_ID,
    build_selected_plan,
    run_selected_window,
    selected_candidate,
)
from scripts.run_selected_strategy_smoke import DEFAULT_OUTPUT, build_smoke_report, synthetic_daily_bars


def test_named_candidate_is_the_existing_frozen_ma_cross_definition():
    candidate = selected_candidate()
    assert SELECTED_PROTOCOL_ID == P.PREREG_ID == "LH-XAUUSD-D1-2026-10-10"
    assert SELECTED_CANDIDATE_ID == candidate.cid == "ma_20_100_atr3"
    assert candidate.role == "CANDIDATE"
    assert candidate.group == "ma_cross"
    assert candidate.builder.func is G.ma_cross
    assert candidate.builder.keywords == {"fast": 20, "slow": 100, "stop_mult": 3.0}

    # functools.partial is mutable even though Candidate is frozen. A caller
    # inspecting the selected snapshot must not be able to mutate the protocol.
    candidate.builder.keywords["fast"] = 2
    assert P.candidate_by_id(SELECTED_CANDIDATE_ID).builder.keywords == {
        "fast": 20,
        "slow": 100,
        "stop_mult": 3.0,
    }
    assert selected_candidate().builder.keywords == {"fast": 20, "slow": 100, "stop_mult": 3.0}


def test_default_cost_model_keeps_each_component_and_unknown_financing_honest():
    costs = P.COST_BASE.describe()
    assert costs == {
        "basis": "ASSUMED",
        "spread_bps_full": 3.0,
        "slippage_bps_per_side": 1.0,
        "commission_usd_per_lot_side": 7.0,
        "financing_bps_per_day": 0.0,
        "financing_convention": "symmetric_time_prorated_bps_per_calendar_day",
        "cost_multiplier": 1.0,
        "round_turn_bps_at_1300": 6.077,
    }
    # Financing was not measured; its zero is an explicit protocol assumption,
    # not a claim that a broker charges no swap.
    assert P.COST_BASE.basis == "ASSUMED"


def test_daily_wrapper_refuses_intraday_unsorted_or_invalid_ohlc():
    daily = synthetic_daily_bars()
    intraday = daily.iloc[:3].copy()
    intraday.index = pd.date_range("2020-01-02", periods=3, freq="15min")
    with pytest.raises(ValueError, match="is daily"):
        build_selected_plan(intraday)

    unsorted = daily.iloc[[1, 0, *range(2, len(daily))]]
    with pytest.raises(ValueError, match="strictly increasing"):
        build_selected_plan(unsorted)

    invalid = daily.copy()
    invalid.iloc[3, invalid.columns.get_loc("high")] = invalid["close"].iloc[3] - 1.0
    with pytest.raises(ValueError, match="OHLC range"):
        build_selected_plan(invalid)


def test_selected_plan_is_causal_and_uses_three_atr_stops():
    bars = synthetic_daily_bars()
    plan = build_selected_plan(bars)
    report = C.truncation_check(build_selected_plan, bars, cuts=range(101, len(bars)))
    assert report.passed, report.mismatches[:3]
    assert report.cuts_checked == len(bars) - 101

    atr = G.atr(bars)
    valid = np.isfinite(plan.target)
    assert valid.any()
    np.testing.assert_allclose(plan.stop_dist[valid], (3.0 * atr.to_numpy())[valid], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(plan.size[valid], G.size_stop_based(bars, 3.0).to_numpy()[valid])


def test_smoke_backtest_is_next_open_costed_and_reproducible():
    """Fixed synthetic output guards the selected strategy-to-engine contract."""
    bars = synthetic_daily_bars()
    start, end = str(bars.index[0].date()), str(bars.index[-1].date())
    plan = build_selected_plan(bars)
    run = run_selected_window(bars, start, end)
    repeated = run_selected_window(bars.copy(), start, end)

    # First non-NaN signal is at bar 99 close; entry must be at bar 100 open,
    # never on the decision bar's close or its already-known range.
    first_signal = int(np.flatnonzero(np.isfinite(plan.target))[0])
    assert first_signal == 99
    assert run.trades[0].entry_day == bars.index[first_signal + 1]
    assert run.trades[0].entry_price == pytest.approx(bars["open"].iloc[first_signal + 1])
    assert repeated.net_usd == pytest.approx(run.net_usd, abs=1e-12)
    assert repeated.cost_usd == pytest.approx(run.cost_usd, abs=1e-12)

    report = build_smoke_report()
    base = report["base_cost_run"]
    assert base["round_turns"] == 3
    assert base["accounting_model_version"] == "fixed_units.v2"
    assert base["gross_usd"] == 277.105
    assert base["cost_usd"] == 17.2546
    assert base["financing_usd"] == 0.0
    assert base["net_usd"] == 259.8504
    assert base["final_equity_usd"] == 10259.8504
    assert base["cost_basis"] == "ASSUMED"
    assert report["data"]["class"] == "SYNTHETIC_MECHANISM_ONLY"
    assert report["validation"] == {
        "performance_validation": "BLOCKED",
        "claim": "NONE",
        "claim_eligible": False,
        "reason": "synthetic input only; reliable independent market data and measured broker costs are unavailable",
    }
    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == report
    assert run.net_usd == pytest.approx(run.gross_usd - run.cost_usd - run.financing_usd, abs=1e-8)


def test_selected_candidate_executes_protective_stop_conservatively():
    bars = synthetic_daily_bars()
    plan = build_selected_plan(bars)
    transitions = [
        i
        for i in range(1, len(plan.target))
        if np.isfinite(plan.target[i - 1]) and plan.target[i - 1] == -1.0 and plan.target[i] == 1.0
    ]
    assert transitions
    signal_idx = transitions[0]
    entry_idx = signal_idx + 1
    entry_open = float(bars["open"].iloc[entry_idx])
    stop_price = entry_open - float(plan.stop_dist[signal_idx])

    # Force the stop through the entry bar's low. The decision was made at the
    # previous close and the order enters at this bar's open, so a later
    # intrabar stop on that same bar is causal; it must fill at the stop level.
    stopped_bars = bars.copy()
    stopped_bars.iloc[entry_idx, stopped_bars.columns.get_loc("low")] = stop_price - 0.1
    start, end = str(bars.index[0].date()), str(bars.index[-1].date())
    run = run_selected_window(stopped_bars, start, end)

    stopped_longs = [trade for trade in run.trades if trade.direction == 1 and trade.stopped]
    assert len(stopped_longs) == 1
    assert stopped_longs[0].entry_day == bars.index[entry_idx]
    assert stopped_longs[0].exit_day == bars.index[entry_idx]
    assert stopped_longs[0].entry_price == pytest.approx(entry_open)
    assert stopped_longs[0].exit_price == pytest.approx(stop_price)
    # The long target remains unchanged after the stop, so the engine must not
    # silently reopen the same direction until the signal state changes.
    assert sum(trade.direction == 1 for trade in run.trades) == 1


def test_wrapper_refuses_unbound_costs_labeled_as_measured():
    from dataclasses import replace

    bars = synthetic_daily_bars()
    with pytest.raises(ValueError, match="only accepts ASSUMED costs"):
        run_selected_window(
            bars,
            str(bars.index[0].date()),
            str(bars.index[-1].date()),
            costs=replace(P.COST_BASE, basis="MEASURED"),
        )


def test_cost_stress_increases_cost_and_reduces_net_without_changing_signal():
    bars = synthetic_daily_bars()
    start, end = str(bars.index[0].date()), str(bars.index[-1].date())
    base = run_selected_window(bars, start, end)
    double_cost = run_selected_window(bars, start, end, costs=P.COST_BASE.scaled(2.0))

    assert len(double_cost.trades) == len(base.trades)
    assert double_cost.cost_usd > base.cost_usd
    assert double_cost.net_usd < base.net_usd
    assert double_cost.cost_basis == "ASSUMED"
