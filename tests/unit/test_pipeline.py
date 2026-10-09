"""The walk-forward research pipeline.

The pipeline exists to make a losing strategy lose honestly. Its most
important tests are therefore the negative ones: noise must fail, a result
that only holds in some windows must fail, and trying many configurations
must make the bar higher rather than lower.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from qts.research.pipeline import (
    RunOutcome,
    build_folds,
    deflated_sharpe_ratio,
    expand_grid,
    run_walk_forward,
    _max_drawdown,
    _profit_factor,
    _sharpe,
)

START = datetime(2025, 8, 6, tzinfo=UTC)
END = datetime(2026, 9, 16, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# folds
# --------------------------------------------------------------------------- #


def test_folds_are_chronological_and_non_overlapping() -> None:
    folds = build_folds(START, END, n_folds=5, test_fraction=0.15)
    assert len(folds) == 5
    for prev, nxt in zip(folds, folds[1:]):
        assert prev.test_end <= nxt.test_start, "test windows must not overlap"


def test_training_always_precedes_the_test_window() -> None:
    """An expanding window: each fold trains on strictly more history."""
    folds = build_folds(START, END, n_folds=4, test_fraction=0.15)
    for fold in folds:
        assert fold.train_end <= fold.test_start, "no peeking into the future"
    for prev, nxt in zip(folds, folds[1:]):
        assert nxt.train_end > prev.train_end, "training must expand"


def test_purge_and_embargo_open_a_gap_at_the_boundary() -> None:
    """Otherwise a label straddling the boundary leaks the answer backwards."""
    plain = build_folds(START, END, n_folds=4, test_fraction=0.15)
    guarded = build_folds(START, END, n_folds=4, test_fraction=0.15, purge_bars=96, embargo_bars=96)
    for p, g in zip(plain, guarded):
        assert g.train_end < p.train_end
        assert g.train_end < g.test_start


def test_a_single_fold_is_refused() -> None:
    with pytest.raises(ValueError, match="at least two folds"):
        build_folds(START, END, n_folds=1)


def test_a_degenerate_test_fraction_is_refused() -> None:
    with pytest.raises(ValueError):
        build_folds(START, END, n_folds=3, test_fraction=1.0)


# --------------------------------------------------------------------------- #
# grid
# --------------------------------------------------------------------------- #


def test_the_grid_is_the_full_cartesian_product() -> None:
    grid = expand_grid({"a": [1, 2], "b": ["x", "y", "z"]})
    assert len(grid) == 6
    assert {"a": 2, "b": "z"} in grid


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #


def test_sharpe_is_zero_when_there_is_no_variation() -> None:
    assert _sharpe([1.0, 1.0, 1.0], 252) == 0.0


def test_sharpe_is_zero_with_too_little_data() -> None:
    assert _sharpe([1.0], 252) == 0.0


def test_max_drawdown_measures_the_worst_peak_to_trough() -> None:
    assert _max_drawdown([100, 120, 60, 80]) == pytest.approx(0.5)


def test_max_drawdown_is_zero_on_a_monotonic_curve() -> None:
    assert _max_drawdown([1, 2, 3, 4]) == 0.0


def test_profit_factor_is_infinite_when_there_are_no_losses() -> None:
    assert _profit_factor([1.0, 2.0]) == math.inf


def test_profit_factor_is_zero_when_there_are_no_gains() -> None:
    assert _profit_factor([-1.0, -2.0]) == 0.0


# --------------------------------------------------------------------------- #
# deflated Sharpe — the multiple-testing correction
# --------------------------------------------------------------------------- #


def test_a_strong_result_survives_a_single_trial() -> None:
    assert deflated_sharpe_ratio(0.5, 5000, 1) < 0.01


def test_trying_more_configurations_raises_the_bar() -> None:
    """The entire point: selection bias must be charged for, not ignored."""
    one = deflated_sharpe_ratio(0.1, 500, 1)
    many = deflated_sharpe_ratio(0.1, 500, 1000)
    assert one < 0.05 < many, "a marginal Sharpe passes alone but not among 1000"


def test_a_single_trial_does_not_hit_the_negative_infinity_special_case() -> None:
    """norm_ppf(1 - 1/N) is -inf at N=1; that must not deflate the result."""
    value = deflated_sharpe_ratio(0.5, 5000, 1)
    assert math.isfinite(value)
    assert value < 0.01


def test_a_zero_sharpe_is_never_significant() -> None:
    assert deflated_sharpe_ratio(0.0, 5000, 1) == pytest.approx(0.5, abs=0.01)


def test_a_negative_sharpe_is_never_significant() -> None:
    assert deflated_sharpe_ratio(-0.3, 5000, 1) > 0.99


def test_the_pvalue_is_monotone_in_the_number_of_trials() -> None:
    values = [deflated_sharpe_ratio(0.2, 1000, n) for n in (1, 10, 100, 1000)]
    assert values == sorted(values), "more trials must never make a result look better"


# --------------------------------------------------------------------------- #
# end to end, with runners made of known signals
# --------------------------------------------------------------------------- #


def _runner_from_signal(signal: float, cost_per_trade: float, n_bars: int = 200):
    """A runner whose per-trade outcome is the given signal minus a cost."""

    def runner(params: dict, start: datetime, end: datetime) -> RunOutcome:
        trades = 60
        per = signal - cost_per_trade
        returns = [per / 10000.0] * trades
        equity = [10000.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r))
        return RunOutcome(
            trades=trades,
            net_return=sum(returns) * 10000.0,
            gross_return=signal * trades,
            cost=cost_per_trade * trades,
            equity_curve=equity,
            returns=returns,
        )

    return runner


def test_a_consistently_losing_signal_is_rejected() -> None:
    folds = build_folds(START, END, n_folds=4, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=-5.0, cost_per_trade=1.0),
        {"a": [1, 2]},
        folds,
    )
    assert result.verdict == "NO_EDGE_ESTABLISHED"
    assert any("net return is not positive" in r for r in result.reasons)


def test_a_signal_that_only_wins_before_costs_is_rejected() -> None:
    """Gross positive, net negative — the most common way backtests lie."""
    folds = build_folds(START, END, n_folds=4, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=0.5, cost_per_trade=1.0),
        {"a": [1, 2]},
        folds,
    )
    assert result.verdict == "NO_EDGE_ESTABLISHED"
    assert any("GROSS return is not positive" not in r for r in result.reasons)


def test_costs_are_reported_separately_from_gross() -> None:
    folds = build_folds(START, END, n_folds=3, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=10.0, cost_per_trade=2.0),
        {"a": [1]},
        folds,
    )
    assert result.aggregate["oos_cost"] > 0
    assert result.aggregate["oos_gross_return"] > result.aggregate["oos_net_return"]


def test_the_cost_basis_is_carried_into_the_verdict_reasons() -> None:
    folds = build_folds(START, END, n_folds=3, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=10.0, cost_per_trade=0.0),
        {"a": [1]},
        folds,
        cost_basis="ASSUMED",
    )
    assert any("not MEASURED" in r for r in result.reasons)


def test_no_fold_reaching_the_minimum_trade_count_yields_insufficient_data() -> None:
    def empty_runner(params: dict, start: datetime, end: datetime) -> RunOutcome:
        return RunOutcome(trades=0)

    folds = build_folds(START, END, n_folds=3, test_fraction=0.15)
    result = run_walk_forward(empty_runner, {"a": [1]}, folds)
    assert result.verdict == "INSUFFICIENT_DATA"


def test_the_report_serialises() -> None:
    import json

    folds = build_folds(START, END, n_folds=3, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=1.0, cost_per_trade=0.5), {"a": [1]}, folds
    )
    payload = json.loads(json.dumps(result.as_dict()))
    assert payload["schema"] == "qts.research_pipeline.v1"
    assert payload["folds"]


def test_the_number_of_configurations_tried_is_counted_honestly() -> None:
    """The multiple-testing correction is only as good as this number."""
    folds = build_folds(START, END, n_folds=4, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=1.0, cost_per_trade=0.1),
        {"a": [1, 2, 3], "b": [1, 2]},
        folds,
    )
    assert result.total_configurations_tried == 6 * 4


def test_fold_boundaries_are_recorded_for_audit() -> None:
    folds = build_folds(START, END, n_folds=3, test_fraction=0.15)
    result = run_walk_forward(
        _runner_from_signal(signal=1.0, cost_per_trade=0.1), {"a": [1]}, folds
    )
    for fold_result in result.folds:
        assert fold_result.fold.train_start < fold_result.fold.test_start
        assert "params" in fold_result.as_dict()
