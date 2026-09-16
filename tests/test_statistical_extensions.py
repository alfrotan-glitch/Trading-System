"""Statistical extensions unit tests — White Reality Check, Hansen SPA, permutation, min length, drawdown, parameter surface."""

import numpy as np
import pytest
from qts.research.statistical import (
    white_reality_check,
    hansen_spa,
    permutation_test,
    minimum_backtest_length,
    drawdown_distribution,
    parameter_surface_analysis,
)


def test_white_reality_check():
    rets = np.random.randn(100) * 0.01
    res = white_reality_check(rets, n_bootstrap=100, seed=42)
    assert "p_value" in res
    assert 0 <= res["p_value"] <= 1
    assert res["purpose"].startswith("White")
    assert "limitations" in res
    # failure mode: needs large T — with small T p close to 0.5
    assert isinstance(res["observed_max"], float)


def test_hansen_spa():
    rets = np.random.randn(100) * 0.01
    res = hansen_spa([rets, rets*0.5], n_bootstrap=100, seed=42)
    assert "p_value" in res
    assert 0 <= res["p_value"] <= 1
    assert "Hansen" in res["purpose"]


def test_permutation():
    rets = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    res = permutation_test(rets, n_perm=100, seed=42)
    assert "p_value" in res
    assert 0 <= res["p_value"] <= 1


def test_minimum_backtest_length():
    n = minimum_backtest_length(0.5, target_psr=0.95)
    assert n > 0
    # failure mode: sharpe <=0 needs huge track record
    n2 = minimum_backtest_length(0.0)
    assert n2 == 999999
    n3 = minimum_backtest_length(1.0)
    assert n3 < n2


def test_drawdown_distribution():
    eq = np.cumprod(1 + np.random.randn(100)*0.01) * 10000
    res = drawdown_distribution(eq, n_bootstrap=50, seed=42)
    assert "observed_max_dd" in res
    assert "bootstrap_mean_dd" in res
    assert "expected_shortfall" in res


def test_parameter_surface():
    res = parameter_surface_analysis({"a": 1.0, "b": 0.9, "c": 1.1, "d": 0.8})
    assert "stability" in res
    assert res["stability"] in ("stable", "unstable isolated peak")
    # failure mode: sparse grid -> unstable detection may be noisy
    res2 = parameter_surface_analysis({"a": 1.0})
    assert len(res2) > 0
