from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from qts.cli.research import research
from qts.research.longhistory.adaptive_backtest import build_adaptive_plan
from qts.research.longhistory.adaptive_router import (
    AdaptiveRoutingConfig,
    classify_market_regime,
    route_by_regime,
)
from qts.research.longhistory.engine import CostModel
from qts.research.longhistory.signals import Plan


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
    assert result["selected_strategy"].iloc[20:30].isna().all()
    assert (result["selected_strategy"].iloc[30:] == "winner").all()


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



def test_regime_classifier_is_causal_and_labels_warmup():
    index = pd.date_range("2020-01-01", periods=150, freq="D")
    close = pd.Series(np.linspace(100.0, 130.0, len(index)), index=index)
    bars = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close},
        index=index,
    )
    kwargs = {
        "trend_lookback": 10,
        "trend_threshold": 0.3,
        "range_threshold": 0.2,
        "atr_lookback": 5,
        "volatility_window": 10,
    }
    baseline = classify_market_regime(bars, **kwargs)
    changed = bars.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 1000.0
    altered = classify_market_regime(changed, **kwargs)
    assert baseline.iloc[:40].equals(altered.iloc[:40])
    assert (baseline.iloc[:15] == "warming_up").all()
    assert baseline.iloc[-1].startswith("trend_up_")


def test_regime_classifier_rejects_invalid_thresholds():
    index = pd.date_range("2020-01-01", periods=20, freq="D")
    close = pd.Series(np.linspace(100.0, 110.0, len(index)), index=index)
    bars = pd.DataFrame(
        {"high": close + 1.0, "low": close - 1.0, "close": close},
        index=index,
    )
    with pytest.raises(ValueError, match="thresholds"):
        classify_market_regime(bars, trend_threshold=0.2, range_threshold=0.3)


def test_adaptive_backtest_uses_costed_engine_and_returns_a_valid_routed_plan():
    n = 80
    index = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(2000.0 + np.arange(n, dtype=float), index=index)
    bars = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        },
        index=index,
    )
    long_plan = Plan(
        target=np.ones(n),
        size=np.full(n, 0.5),
        stop_dist=np.full(n, np.nan),
        rebalance=np.zeros(n, dtype=bool),
        family="test_long",
        params={},
    )
    short_plan = Plan(
        target=-np.ones(n),
        size=np.full(n, 0.5),
        stop_dist=np.full(n, np.nan),
        rebalance=np.zeros(n, dtype=bool),
        family="test_short",
        params={},
    )
    config = AdaptiveRoutingConfig(lookback=20, min_observations=3)
    routed, diagnostics, candidate_returns = build_adaptive_plan(
        bars,
        {"long": long_plan, "short": short_plan},
        CostModel(
            spread_bps=0.0,
            slippage_bps=0.0,
            commission_usd_per_lot_side=0.0,
            financing_bps_per_day=0.0,
            basis="TEST_ZERO_COST",
        ),
        routing_config=config,
        trend_lookback=3,
        trend_threshold=0.3,
        range_threshold=0.2,
        atr_lookback=2,
        volatility_window=2,
    )
    assert routed.family == "adaptive_regime_router"
    assert len(routed.target) == n
    assert candidate_returns.index.equals(index)
    assert set(candidate_returns.columns) == {"long", "short"}
    assert diagnostics["selected_strategy"].iloc[:6].isna().all()
    assert (diagnostics["selected_strategy"].iloc[6:] == "long").all()
    assert (routed.target[6:] == 1.0).all()



def test_adaptive_xauusd_cli_writes_diagnostic_report(tmp_path):
    n = 360
    index = pd.date_range("2023-01-01", periods=n, freq="D")
    close = 1900.0 + np.arange(n, dtype=float) * 0.4 + np.sin(np.arange(n) / 5.0)
    bars = pd.DataFrame(
        {
            "timestamp": index.astype(str),
            "open": close - 0.1,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
        }
    )
    source = tmp_path / "xauusd.csv"
    output = tmp_path / "adaptive.json"
    bars.to_csv(source, index=False)

    result = CliRunner().invoke(
        research,
        [
            "adaptive-xauusd",
            "--input",
            str(source),
            "--out",
            str(output),
            "--lookback",
            "20",
            "--min-observations",
            "5",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "RESEARCH_DIAGNOSTIC_ONLY"
    assert report["symbol"] == "XAUUSD"
    assert report["data"]["bars"] == n
    assert report["data"]["train_bars"] == 252
    assert report["data"]["holdout_bars"] == 108
    assert report["evaluation"].startswith("chronological holdout")
    assert report["routing_config"]["candidate_count"] == 6
    assert "adaptive_router" in report
    assert "candidate_strategies" in report
