"""Prequential gold model invariants: no future features, targets or scaler fits."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab.causal_ml import (
    OnlineModelConfig,
    daily_long_position,
    prequential_monthly_predictions,
    trailing_feature_frame,
)


def _inputs(days: int = 2700) -> tuple[pd.Series, pd.DataFrame]:
    index = pd.bdate_range("2012-01-02", periods=days, tz="UTC")
    generator = np.random.default_rng(123)
    close = pd.Series(
        1300 * np.exp(np.cumsum(generator.normal(0.0002, 0.008, days))),
        index=index,
    )
    c = 20.0 + 2.0 * np.sin(np.arange(days) / 40)
    curve = pd.DataFrame({"VIX": c, "VIX3M": c + 1.5}, index=index)
    return close, curve


def test_current_decision_cannot_see_future_gold_or_volatility():
    gold, curve = _inputs()
    base_features = trailing_feature_frame(gold, curve)
    base = prequential_monthly_predictions(base_features)

    cut = gold.index[2000]
    altered_gold = gold.copy()
    altered_curve = curve.copy()
    altered_gold.loc[altered_gold.index > cut] *= 1.8
    altered_curve.loc[altered_curve.index > cut, "VIX3M"] *= 0.15
    changed = prequential_monthly_predictions(
        trailing_feature_frame(altered_gold, altered_curve)
    )
    earlier = base.index[base.index <= cut]
    pd.testing.assert_series_equal(
        base.loc[earlier, "target_long"],
        changed.loc[earlier, "target_long"],
    )
    pd.testing.assert_series_equal(
        base.loc[earlier, "forecast_next_month"],
        changed.loc[earlier, "forecast_next_month"],
    )


def test_training_set_never_includes_current_month():
    gold, curve = _inputs()
    predictions = prequential_monthly_predictions(trailing_feature_frame(gold, curve))
    usable = predictions.loc[predictions["usable"]]
    assert len(usable) >= 20
    assert (usable["training_rows"] >= 60).all()
    assert (pd.DatetimeIndex(usable["training_last_date"]) < usable.index).all()
    assert set(predictions["target_long"].unique()) <= {0.0, 1.0}


def test_unusable_features_never_enable_trading():
    gold, curve = _inputs()
    curve = curve.iloc[:140]
    feat = trailing_feature_frame(gold, curve)
    pred = prequential_monthly_predictions(feat)
    assert (pred["target_long"] == 0.0).all()
    daily = daily_long_position(pred, gold.index)
    assert float(daily.sum()) == 0.0


def test_model_refuses_invalid_fit_configuration():
    with pytest.raises(ValueError, match="training"):
        OnlineModelConfig(lookback_months=48, min_train_months=60)
    with pytest.raises(ValueError, match="ridge"):
        OnlineModelConfig(ridge_strength=0)
    with pytest.raises(ValueError, match="threshold"):
        OnlineModelConfig(entry_threshold=-1.0)


def test_daily_position_holds_only_previous_monthly_decisions():
    gold, curve = _inputs()
    pred = prequential_monthly_predictions(trailing_feature_frame(gold, curve))
    daily = daily_long_position(pred, gold.index)
    assert daily.index.equals(gold.index)
    assert set(daily.unique()) <= {0.0, 1.0}
    assert daily.iloc[0] == 0.0


def test_runner_uses_next_open_execution_and_calendar_funding():
    from scripts.edgelab_online_model_run import _portfolio_evaluate

    gold, _ = _inputs(650)
    idx = gold.index
    open_prices = gold * 0.999
    bars = pd.DataFrame({"open": open_prices, "close": gold}, index=idx)
    pos = pd.Series(0.5, index=idx)
    base, _ = _portfolio_evaluate(
        bars, pos, financing_bps_per_calendar_day=0.0, label="test"
    )
    stressed, _ = _portfolio_evaluate(
        bars, pos, financing_bps_per_calendar_day=2.0, label="test"
    )
    assert stressed["funding_drag_total"] > 0
    assert stressed["cagr"] < base["cagr"]
    assert stressed["avg_held_exposure"] == pytest.approx(base["avg_held_exposure"])
