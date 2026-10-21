"""Tests for the regime classifier and the allocation layer.

The properties that matter here are *causality* (no bar may see the future) and
*policy fidelity* (the allocator must do exactly what the config says, including
refusing to trade).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab.portfolio import AllocationConfig, allocate, eligible_positions, vol_scale
from qts.research.edgelab.regime import (
    MarketRegime,
    RegimeConfig,
    classify,
    efficiency_ratio,
    regime_summary,
    trailing_percentile,
)

_HAS_DATA = (Path(__file__).resolve().parents[2] / "data" / "raw" / "longgold").exists()
needs_data = pytest.mark.skipif(not _HAS_DATA, reason="raw data not present (gitignored)")


def _bars(index: pd.DatetimeIndex, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(index)))), index=index)
    out = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=index)
    out["volume"] = 0.0
    return out


# ---------------------------------------------------------------- classifier


def test_efficiency_ratio_bounds():
    idx = pd.bdate_range("2010-01-04", periods=400)
    straight = pd.Series(np.linspace(100, 200, 400), index=idx)
    assert (efficiency_ratio(straight, 20).dropna() - 1.0).abs().max() < 1e-9
    noisy = pd.Series(100 + np.random.default_rng(0).normal(0, 1, 400), index=idx)
    assert efficiency_ratio(noisy, 20).dropna().max() < 1.0


def test_trailing_percentile_ignores_the_future():
    """The rank at bar t must be identical whether or not later bars exist."""
    idx = pd.bdate_range("2010-01-04", periods=300)
    s = pd.Series(np.random.default_rng(5).normal(0, 1, 300).cumsum(), index=idx)
    full = trailing_percentile(s, 60)
    cut = 200
    part = trailing_percentile(s.iloc[:cut], 60)
    pd.testing.assert_series_equal(full.iloc[:cut].dropna(), part.dropna(), check_names=False)


def test_classify_is_causal():
    """Truncating the bars must not change any earlier regime label."""
    idx = pd.bdate_range("2005-01-03", periods=900)
    bars = _bars(idx)
    full = classify(bars)
    cut = 700
    part = classify(bars.iloc[:cut])
    pd.testing.assert_series_equal(full["regime"].iloc[:cut], part["regime"], check_names=False)


def test_classify_produces_only_declared_states():
    idx = pd.bdate_range("2005-01-03", periods=900)
    out = classify(_bars(idx))
    declared = {r.value for r in MarketRegime}
    assert set(out["regime"].unique()) <= declared
    assert out["allow_trade"].dtype == bool


def test_no_trade_is_off_in_the_top_volatility_percentile():
    idx = pd.bdate_range("2005-01-03", periods=1500)
    # A volatility spike near the end must land in the no-trade bucket.
    rng = np.random.default_rng(11)
    rets = rng.normal(0, 0.005, 1500)
    rets[-30:] = rng.normal(0, 0.06, 30)
    close = pd.Series(1000 * np.exp(np.cumsum(rets)), index=idx)
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)
    out = classify(bars)
    assert out["allow_trade"].iloc[-1] in (False, np.bool_(False))
    assert out["regime"].iloc[-1] == MarketRegime.HIGH_VOL.value


def test_regime_summary_shares_sum_to_one():
    idx = pd.bdate_range("2005-01-03", periods=900)
    summary = regime_summary(classify(_bars(idx)))
    assert summary["share"].sum() == pytest.approx(1.0)
    assert summary["bars"].sum() == 900


def test_config_validation():
    with pytest.raises(ValueError):
        RegimeConfig(trend_window=2)
    with pytest.raises(ValueError):
        RegimeConfig(high_vol_quantile=0.99, no_trade_quantile=0.95)
    with pytest.raises(ValueError):
        RegimeConfig(trend_quantile=0.2)


# ---------------------------------------------------------------- allocator


@pytest.fixture()
def signals() -> pd.DataFrame:
    idx = pd.bdate_range("2010-01-04", periods=600)
    rng = np.random.default_rng(2)
    return pd.DataFrame(
        {
            "trend_a": (rng.random(600) > 0.5).astype(float),
            "meanrev_a": (rng.random(600) > 0.5).astype(float),
            "macro_a": np.ones(600),
        },
        index=idx,
    )


@pytest.fixture()
def regimes(signals: pd.DataFrame) -> pd.DataFrame:
    idx = signals.index
    regime = np.where(np.arange(len(idx)) % 3 == 0, MarketRegime.TREND_UP.value, MarketRegime.RANGE.value)
    return pd.DataFrame(
        {
            "regime": regime,
            "efficiency_ratio": 0.5,
            "trend_percentile": 0.5,
            "realized_vol": 0.15,
            "vol_percentile": 0.5,
            "allow_trade": True,
        },
        index=idx,
    )


def test_eligibility_masks_by_family(signals, regimes):
    fams = {"trend_a": "trend", "meanrev_a": "meanrev", "macro_a": "real_yield"}
    out = eligible_positions(signals, regimes, fams, AllocationConfig())
    in_range = regimes["regime"] == MarketRegime.RANGE.value
    assert (out.loc[in_range, "trend_a"] == 0.0).all(), "trend rule traded in a range"
    assert (out.loc[in_range, "meanrev_a"] == signals.loc[in_range, "meanrev_a"]).all()
    assert (out["macro_a"] == signals["macro_a"]).all(), "regime-agnostic family was gated"


def test_no_trade_state_blocks_everything(signals, regimes):
    fams = {"trend_a": "trend", "meanrev_a": "meanrev", "macro_a": "real_yield"}
    muted = regimes.copy()
    muted.iloc[100:200, muted.columns.get_loc("allow_trade")] = False
    out = allocate(signals, muted, fams, AllocationConfig())
    assert (out["position"].iloc[100:200] == 0.0).all()


def test_exposure_never_exceeds_the_cap(signals, regimes):
    fams = {"trend_a": "trend", "meanrev_a": "meanrev", "macro_a": "real_yield"}
    cfg = AllocationConfig(max_leverage=0.5)
    out = allocate(signals, regimes, fams, cfg)
    assert out["position"].max() <= 0.5 + 1e-12


def test_vol_scale_is_zero_without_measured_volatility():
    idx = pd.bdate_range("2010-01-04", periods=10)
    vol = pd.Series(np.nan, index=idx)
    out = vol_scale(vol, AllocationConfig())
    assert (out == 0.0).all(), "an unmeasured market must not receive risk"


def test_vol_scale_respects_bounds():
    idx = pd.bdate_range("2010-01-04", periods=100)
    vol = pd.Series(np.linspace(0.01, 2.0, 100), index=idx)
    out = vol_scale(vol, AllocationConfig(target_vol=0.12, max_leverage=1.0))
    assert out.max() <= 1.0 and out.min() >= 0.0


def test_allocation_config_validation():
    with pytest.raises(ValueError):
        AllocationConfig(target_vol=0.0)
    with pytest.raises(ValueError):
        AllocationConfig(max_leverage=-1.0)


@needs_data
def test_real_gold_regime_mix_is_sane():
    """On 52 years of gold, every declared state must actually occur."""
    from qts.research.edgelab.longgold import load_long_gold

    out = classify(load_long_gold())
    shares = out["regime"].value_counts(normalize=True)
    for state in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.RANGE, MarketRegime.HIGH_VOL):
        assert shares.get(state.value, 0.0) > 0.01, f"{state} is absent — the classifier is degenerate"
    assert 0.7 < float(out["allow_trade"].mean()) < 1.0


@needs_data
def test_regime_endpoint_reports_the_live_state_and_refuses_to_claim_an_edge():
    """The product surface must state what it is, including that it is not an edge."""
    from fastapi.testclient import TestClient

    from qts.api.server import app

    body = TestClient(app).get("/api/research/regime").json()
    assert body["available"] is True
    assert body["regime"] in {r.value for r in MarketRegime}
    assert isinstance(body["allow_trade"], bool)
    assert body["adds_value_vs_control"] is False, "round 17 found no robust gain; the API must say so"
    assert body["live_locked"] is True
    assert body["real_capital_exposure_usd"] == 0
    # A "current" regime must come from the tradable series, not the research store
    # that stops in 2019 to protect the spent holdout.
    assert body["as_of"] >= "2024-01-01"
    assert "trend" in body["eligibility"]
