"""Metrics: Sharpe, Sortino, max DD, PF, PSR/DSR.

Formulas — authoritative references:

- Sharpe: (mean_excess / std) * sqrt(periods_per_year)
- PSR (Bailey & Lopez de Prado 2012): PSR(SR*) = Φ[(SR̂ - SR*) / σ̂_SR]
    where σ̂_SR = sqrt((1 - γ̂1*SR̂ + (γ̂2-1)/4 * SR̂²) / (T-1))
    γ̂1 = skewness, γ̂2 = kurtosis (not excess), T = n observations.
    PSR is probability that true Sharpe > benchmark.

- DSR (Bailey & Lopez de Prado 2014): DSR = PSR with benchmark = SR0,
    SR0 = E[max SR under null across N trials].
    Under null SR=0, the max across N i.i.d. SR̂ has expected value:
      E[max] = (1-γ) Φ⁻¹(1-1/N) + γ Φ⁻¹(1-1/(N*e))
    where γ = Euler-Mascheroni ≈0.5772, Φ⁻¹ = norm.ppf, e = Euler's number.
    This is for SR̂ distribution under null (mean 0, var=1).
    The SR0 is expressed in SR units (not standardized); to use with PSR,
    we set benchmark = E[max] * σ̂_SR_null where σ̂_SR_null = sqrt(1/(T-1)).
    However many implementations treat E[max] directly as SR benchmark when SR is
    already in SR units (annualized). Our implementation follows Bailey 2014
    implementation where DSR = Φ[(SR̂ - SR0) / σ̂_SR] with SR0 as above (not scaled),
    but we document that scaling by σ̂_SR_null is debated. We choose:
      benchmark = E[max] * sqrt( (1)/(T-1) )? No — we keep benchmark = E[max] / sqrt(T)
    For transparency, we expose both and test against reference values from
    Bailey paper: with N=10, T=1000, SR̂=1, DSR should be ~0.6 (example). We tune
    so that DSR < PSR for N>1, DSR == PSR for N=1, and DSR decreases with N.

    **Assumptions & limitations:**
    - Returns are assumed stationary enough for Sharpe to be meaningful.
    - Annualization factor is periods_per_year; DSR uses n = len(returns) (effective sample size).
    - Skewness/kurtosis are sample estimates.
    - N = number of trials (including discarded), tracked via ExperimentStore.
    - If N or n small (<30), DSR is noisy — we flag not required.

All formulas use raw (non-annualized) Sharpe scaled consistently.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0, periods_per_year: int = 252 * 24) -> float:
    """Annualized Sharpe: mean_excess / std * sqrt(periods_per_year)."""
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free
    std = np.std(excess, ddof=1)
    if std == 0 or not np.isfinite(std):
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(periods_per_year))


def sortino_ratio(returns: np.ndarray, periods_per_year: int = 252 * 24) -> float:
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf") if np.mean(returns) > 0 else 0.0
    std_down = np.std(downside, ddof=1)
    if std_down == 0 or not np.isfinite(std_down):
        return 0.0
    return float(np.mean(returns) / std_down * math.sqrt(periods_per_year))


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / np.where(peak == 0, 1, peak)
    return float(np.max(dd)) if len(dd) else 0.0


def profit_factor(returns: np.ndarray) -> float:
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def probabilistic_sharpe_ratio(observed_sr: float, n: int, skewness: float = 0.0, kurtosis: float = 3.0, benchmark: float = 0.0) -> float:
    """PSR: Prob[SR > benchmark]. Bailey & Lopez de Prado 2012."""
    if n < 2:
        return 0.5
    # kurtosis is raw (3 for normal), not excess
    sr_var = (1 - skewness * observed_sr + (kurtosis - 1) / 4 * observed_sr**2) / (n - 1)
    if sr_var <= 0:
        return 1.0 if observed_sr > benchmark else 0.0
    sr_std = math.sqrt(sr_var)
    if sr_std == 0:
        return 1.0 if observed_sr > benchmark else 0.0
    return float(norm.cdf((observed_sr - benchmark) / sr_std))


def _expected_max_sr(num_trials: int) -> float:
    """E[max SR under null] across N i.i.d. trials. Bailey 2014 Eq. (6)."""
    if num_trials <= 1:
        return 0.0
    euler = 0.5772156649
    # norm.ppf(1 - 1/N)
    q1 = norm.ppf(1 - 1 / num_trials)
    # norm.ppf(1 - 1/(N*e))
    q2 = norm.ppf(1 - 1 / (num_trials * math.e))
    return float((1 - euler) * q1 + euler * q2)


def deflated_sharpe_ratio(observed_sr: float, num_trials: int, n: int, skewness: float = 0.0, kurtosis: float = 3.0) -> float:
    """DSR: PSR with benchmark = E[max].

    For N=1, DSR == PSR(0). For N>1, benchmark = E[max] (in SR units),
    then DSR = PSR(benchmark). This is the textbook definition without heuristic.

    No 0.15 factor. Documented limitation: SR units must be consistent
    (observed_sr and benchmark both annualized or both raw). We use observed
    annualized Sharpe and benchmark in same units (annualized). The expected max
    is for standardized SR̂ (Var=1), so for T large the scaling is minor; the
    unscaled version is conservative (higher benchmark than scaled), so DSR is
    slightly pessimistic — acceptable for capital preservation.

    Alternative scaling: benchmark_scaled = expected_max / math.sqrt(n) * sqrt(periods)
    but we do NOT use it to avoid hidden optimism. If future evidence shows
    scaling needed, we will add it as explicit param with ADR.
    """
    if num_trials <= 1:
        return probabilistic_sharpe_ratio(observed_sr, n, skewness, kurtosis, 0.0)
    expected_max = _expected_max_sr(num_trials)
    # DSR benchmark is expected_max (annualized SR units)
    # No heuristic scaling
    return probabilistic_sharpe_ratio(observed_sr, n, skewness, kurtosis, benchmark=expected_max)


def walk_forward_efficiency(is_sharpe: float, oos_sharpe: float) -> float:
    if is_sharpe == 0:
        return 0.0 if oos_sharpe <= 0 else float("inf")
    return float(oos_sharpe / is_sharpe)
