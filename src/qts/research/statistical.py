"""Statistical Research Stack — extensions beyond PSR/DSR/PBO."""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm


def white_reality_check(returns: np.ndarray, benchmark: float = 0.0, n_bootstrap: int = 1000, seed: int = 42) -> dict:
    """White Reality Check (1996) — test max Sharpe across trials against bootstrap null.
    Purpose: control for data snooping when multiple strategies tested.
    Assumptions: stationary bootstrap, null of no edge.
    Inputs: returns (T), benchmark, n_bootstrap.
    Limitations: requires sufficient T, assumes i.i.d. under null.
    """
    rng = np.random.default_rng(seed)
    obs_max = float(np.max(returns)) if len(returns) else 0.0
    # Bootstrap max
    boot_max = []
    for _ in range(n_bootstrap):
        sample = rng.choice(returns, size=len(returns), replace=True)
        boot_max.append(float(np.max(sample)))
    p_value = float(np.mean(np.array(boot_max) >= obs_max))
    return {
        "observed_max": obs_max,
        "p_value": p_value,
        "n_bootstrap": n_bootstrap,
        "purpose": "White Reality Check — is best strategy just luck?",
        "limitations": "needs large T, assumes stationary",
    }


def hansen_spa(returns_list: list[np.ndarray], benchmark: float = 0.0, n_bootstrap: int = 1000, seed: int = 42) -> dict:
    """Hansen SPA (2005) — superior predictive ability, improvements over White.
    Purpose: test if any strategy beats benchmark after multiple testing.
    """
    rng = np.random.default_rng(seed)
    # Simplified SPA: compute t-stats per strategy, SPA is max t
    t_stats = []
    for rets in returns_list:
        if len(rets) < 2:
            continue
        m = np.mean(rets) - benchmark
        s = np.std(rets, ddof=1) / math.sqrt(len(rets)) if np.std(rets) else 1.0
        t = m / s if s else 0.0
        t_stats.append(t)
    obs_spa = float(np.max(t_stats)) if t_stats else 0.0
    # Bootstrap SPA
    boot_spa = []
    for _ in range(n_bootstrap):
        b_t = []
        for rets in returns_list:
            sample = rng.choice(rets, size=len(rets), replace=True)
            m = np.mean(sample) - benchmark
            s = np.std(sample, ddof=1) / math.sqrt(len(sample)) if np.std(sample) else 1.0
            b_t.append(m / s if s else 0.0)
        boot_spa.append(float(np.max(b_t)) if b_t else 0.0)
    p_value = float(np.mean(np.array(boot_spa) >= obs_spa))
    return {
        "observed_spa": obs_spa,
        "p_value": p_value,
        "purpose": "Hansen SPA — superior predictive ability",
        "limitations": "bootstrap assumes no temporal dependence",
    }


def permutation_test(returns: np.ndarray, n_perm: int = 1000, seed: int = 42) -> dict:
    """Permutation test for Sharpe — shuffles labels to test significance."""
    rng = np.random.default_rng(seed)
    from qts.validation.metrics import sharpe_ratio

    obs_sr = sharpe_ratio(returns)
    perm_srs = []
    for _ in range(n_perm):
        perm = rng.permutation(returns)
        perm_srs.append(sharpe_ratio(perm))
    p_value = float(np.mean(np.array(perm_srs) >= obs_sr))
    return {
        "observed_sharpe": obs_sr,
        "p_value": p_value,
        "purpose": "Permutation — is Sharpe just random ordering?",
        "n_perm": n_perm,
    }


def minimum_backtest_length(sharpe: float, target_psr: float = 0.95, skew: float = 0.0, kurt: float = 3.0) -> int:
    """Minimum T for PSR target — track-record requirement."""
    # Invert PSR formula to solve for n
    # Approx: need n such that (sharpe - 0)/sigma = z_target
    # sigma = sqrt((1 - skew*sr + (kurt-1)/4*sr^2)/(n-1))
    # Solve n-1 = (z * sigma_factor?) Simplified
    if sharpe <= 0:
        return 999999
    _z = norm.ppf(target_psr)
    # Approx iterative
    for n in [50, 100, 200, 500, 1000, 2000, 5000]:
        from qts.validation.metrics import probabilistic_sharpe_ratio

        psr = probabilistic_sharpe_ratio(sharpe, n=n, skewness=skew, kurtosis=kurt, benchmark=0.0, annualized=False)
        if psr >= target_psr:
            return n
    return 5000


def drawdown_distribution(equity: np.ndarray, n_bootstrap: int = 500, seed: int = 42) -> dict:
    """Drawdown distribution and expected shortfall diagnostics."""
    rng = np.random.default_rng(seed)
    from qts.validation.metrics import max_drawdown

    obs_dd = max_drawdown(equity)
    # Bootstrap equity paths via returns
    rets = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0.0])
    boot_dds = []
    for _ in range(n_bootstrap):
        sample_rets = rng.choice(rets, size=len(rets), replace=True)
        eq = np.cumprod(1 + sample_rets) * equity[0]
        boot_dds.append(max_drawdown(eq))
    return {
        "observed_max_dd": float(obs_dd),
        "bootstrap_mean_dd": float(np.mean(boot_dds)),
        "bootstrap_95_dd": float(np.percentile(boot_dds, 95)),
        "expected_shortfall": float(np.mean([d for d in boot_dds if d >= np.percentile(boot_dds, 95)]))
        if boot_dds
        else 0.0,
    }


def parameter_surface_analysis(param_sharpes: dict[str, float]) -> dict:
    """Stability analysis of parameter surface — is optimum isolated spike?"""
    vals = list(param_sharpes.values())
    if not vals:
        return {"stability": "unknown"}
    mean = float(np.mean(vals))
    std = float(np.std(vals))
    peak = float(np.max(vals))
    stability = "stable" if (peak - mean) < 2 * std else "unstable isolated peak"
    return {
        "mean": mean,
        "std": std,
        "peak": peak,
        "stability": stability,
        "purpose": "Detect overfit to specific params",
    }
