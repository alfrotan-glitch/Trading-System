from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory.adaptive_router import AdaptiveRoutingConfig, route_by_regime


def sample_inputs(n: int = 40):
    index = pd.date_range("2024-01-01", periods=n, freq="D")
    regimes = pd.Series(["trend"] * n, index=index, name="regime")
    returns = pd.DataFrame(
        {"winner": np.full(n, 0.02), "loser": np.full(n, -0.01)},
        index=index,
    )
    targets = pd.DataFrame({"winner": np.ones(n), "loser": -np.ones(n)}, index=index)
    return regimes, returns, targets


def test_router_uses_only_prior_returns_and_selects_positive_net_candidate():
    regimes, returns, targets = sample_inputs()
    config = AdaptiveRoutingConfig(lookback=20, min_observations=10)
    result = route_by_regime(regimes, returns, targets, config)
    assert result["selected_strategy"].iloc[:10].isna().all()
    assert (result["selected_strategy"].iloc[10:] == "winner").all()
    assert (result["target"].iloc[10:] == 1.0).all()


def test_current_bar_return_cannot_change_current_decision():
    regimes, returns, targets = sample_inputs()
    config = AdaptiveRoutingConfig(lookback=20, min_observations=10)
    baseline = route_by_regime(regimes, returns, targets, config)
    changed = returns.copy()
    changed.iloc[20, :] = [-100.0, 100.0]
    altered = route_by_regime(regimes, changed, targets, config)
    assert altered.loc[regimes.index[20], "selected_strategy"] == baseline.loc[
        regimes.index[20], "selected_strategy"
    ]


def test_router_stays_flat_when_no_candidate_has_positive_mean():
    regimes, returns, targets = sample_inputs()
    returns.loc[:, :] = -0.001
    result = route_by_regime(
        regimes, returns, targets, AdaptiveRoutingConfig(lookback=20, min_observations=10)
    )
    assert result["selected_strategy"].isna().all()
    assert (result["target"] == 0.0).all()


def test_router_uses_only_history_from_matching_regime():
    regimes, returns, targets = sample_inputs()
    regimes.iloc[20:] = "range"
    result = route_by_regime(
        regimes, returns, targets, AdaptiveRoutingConfig(lookback=20, min_observations=10)
    )
    assert result["selected_strategy"].iloc[20:].isna().all()


def test_invalid_position_states_are_rejected():
    regimes, returns, targets = sample_inputs()
    targets.iloc[0, 0] = 0.5
    with pytest.raises(ValueError, match="targets"):
        route_by_regime(regimes, returns, targets)


def test_missing_target_fails_flat_not_into_another_candidate():
    regimes, returns, targets = sample_inputs()
    targets.iloc[15, 0] = np.nan
    result = route_by_regime(
        regimes, returns, targets, AdaptiveRoutingConfig(lookback=20, min_observations=10)
    )
    assert result.loc[regimes.index[15], "selected_strategy"] == "winner"
    assert result.loc[regimes.index[15], "target"] == 0.0
