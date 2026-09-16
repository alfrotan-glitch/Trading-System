"""Metrics: Sharpe, Sortino, max DD, PF, PSR/DSR — Bailey & López de Prado.

References:
- Bailey & López de Prado (2012) The Sharpe Ratio Efficient Frontier, PSR.
- Bailey & López de Prado (2014) The Deflated Sharpe Ratio, DSR.
- Prado (2018) Advances in Financial Machine Learning, Chapter 14.

Units and scaling — EXPLICIT (Blocker 4):
- `sharpe_ratio` returns **annualized** Sharpe: mean_excess/std * sqrt(periods_per_year).
- `probabilistic_sharpe_ratio` and `deflated_sharpe_ratio` work in **same units** as
  `observed_sr` and `benchmark`. We support both per-period and annualized, but
  you must be consistent: if observed_sr is annualized, benchmark must be annualized
  and `periods_per_year` must be supplied so variance is scaled correctly.
- Risk: silently mixing annualized Sharpe (e.g., 1.5) with per-period standard
  error sqrt(1/(n-1)) (≈0.1 for n=100) understates variance by sqrt(P) and
  overstates PSR/DSR. We avoid this by explicitly scaling.

Formulas:
- Sharpe (annualized): SR_ann = mean(R - rf)/std(R) * sqrt(P)
- PSR: PSR(SR*) = Φ[ (SR̂ - SR*) / σ̂_SR ]
    σ̂_SR = sqrt( (1 - γ̂1*SR̂_per + (γ̂2-1)/4 * SR̂_per²) * P / (T-1) )  if SR̂ is annualized
           = sqrt( (1 - γ̂1*SR̂ + (γ̂2-1)/4 * SR̂²) / (T-1) )                 if per-period
  where SR̂_per = SR̂_ann / sqrt(P), γ̂1=skew, γ̂2=kurtosis raw, T=n.
  Implementation converts to per-period internally to keep variance correct.

- Expected maximum Sharpe under null (N iid):
    E[max] = μ + σ * ((1-γ) Φ⁻¹(1-1/N) + γ Φ⁻¹(1-1/(Ne)))
  where μ=0, σ = sqrt(P/(T-1)) for annualized, σ = sqrt(1/(T-1)) for per-period,
  γ≈0.5772. This is SR0 (benchmark) for DSR.

- DSR = PSR(SR0) with σ̂ computed from observed SR (same formula).

No heuristic constants. No mixing.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm


def periods_per_year_for_timeframe(timeframe: str) -> int:
    """Derive P (periods per year) from timeframe string. No silent fallback.

    Supported: 1m, 5m, 15m, 30m, 1H, 4H, 1D. For unknown, raises ValueError to fail closed.
    Uses 252 trading days for traditional markets, 24h for XAUUSD.
    """
    tf = timeframe.strip()
    # Normalize: allow 1H, 1h, H1, M1 etc — support common variants
    mapping = {
        "1m": 252 * 24 * 60,
        "5m": 252 * 24 * 12,
        "15m": 252 * 24 * 4,
        "30m": 252 * 24 * 2,
        "1H": 252 * 24,
        "1h": 252 * 24,
        "4H": 252 * 6,
        "4h": 252 * 6,
        "1D": 252,
        "1d": 252,
        "D1": 252,
    }
    if tf in mapping:
        return mapping[tf]
    # Try generic: e.g., "M1" -> 1m, "H1" -> 1H
    normalized = tf.upper()
    if normalized == "M1":
        return 252 * 24 * 60
    if normalized == "H1":
        return 252 * 24
    raise ValueError(f"unknown timeframe {timeframe!r}: cannot derive periods_per_year (fail closed)")


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0, periods_per_year: int = 252 * 24) -> float:
    """Annualized Sharpe: mean_excess / std * sqrt(periods_per_year).

    periods_per_year: 252*24 for 1H XAUUSD (24h, 252 trading days), 252*24*60 for 1m, etc.
    For daily: 252. For 24/7 crypto hourly: 8760.
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free
    std = np.std(excess, ddof=1)
    if std == 0 or not np.isfinite(std):
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(periods_per_year))


def sharpe_ratio_per_period(returns: np.ndarray, risk_free: float = 0.0) -> float:
    """Per-period Sharpe (not annualized): mean/std."""
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free
    std = np.std(excess, ddof=1)
    if std == 0 or not np.isfinite(std):
        return 0.0
    return float(np.mean(excess) / std)


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


def probabilistic_sharpe_ratio(
    observed_sr: float,
    n: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    benchmark: float = 0.0,
    periods_per_year: int = 252 * 24,
    annualized: bool = True,
) -> float:
    """PSR: Prob[SR > benchmark]. Bailey & López de Prado 2012.

    observed_sr and benchmark must be in same units (both annualized if annualized=True,
    both per-period if False). n = number of return observations (T).
    skewness, kurtosis are of returns (sample estimates, kurtosis raw 3 for normal).
    periods_per_year used to correctly scale variance when annualized=True.

    Variance formula (annualized case):
      SR_per = SR_ann / sqrt(P)
      var_per = (1 - skew*SR_per + (kurt-1)/4 * SR_per^2)/(n-1)
      var_ann = var_per * P
      sigma = sqrt(var_ann)
    For per-period (annualized=False): var = (1 - skew*SR + (kurt-1)/4*SR^2)/(n-1)

    Returns Φ[ (SR - benchmark)/sigma ].
    """
    if n < 2:
        return 0.5
    P = periods_per_year if annualized else 1
    # Convert to per-period for variance calc if annualized
    if annualized and P != 1:
        sr_per = observed_sr / math.sqrt(P)
        bench_per = benchmark / math.sqrt(P)
        # skew/kurt are of returns, same for per-period
        var_per = (1 - skewness * sr_per + (kurtosis - 1) / 4 * sr_per**2) / (n - 1)
        if var_per <= 0:
            return 1.0 if observed_sr > benchmark else 0.0
        sigma_ann = math.sqrt(var_per * P)
        if sigma_ann == 0 or not math.isfinite(sigma_ann):
            return 1.0 if observed_sr > benchmark else 0.0
        return float(norm.cdf((observed_sr - benchmark) / sigma_ann))
    else:
        # per-period or P=1
        var = (1 - skewness * observed_sr + (kurtosis - 1) / 4 * observed_sr**2) / (n - 1)
        if var <= 0:
            return 1.0 if observed_sr > benchmark else 0.0
        sigma = math.sqrt(var)
        if sigma == 0:
            return 1.0 if observed_sr > benchmark else 0.0
        return float(norm.cdf((observed_sr - benchmark) / sigma))


def _expected_max_std(num_trials: int) -> float:
    """E[max of N standard normals]. Bailey 2014 Eq. (6) without sigma scaling."""
    if num_trials <= 1:
        return 0.0
    euler = 0.5772156649
    q1 = norm.ppf(1 - 1 / num_trials)
    q2 = norm.ppf(1 - 1 / (num_trials * math.e))
    return float((1 - euler) * q1 + euler * q2)


def expected_max_sharpe_ratio(num_trials: int, sharpe_std: float, mean: float = 0.0) -> float:
    """Expected maximum Sharpe under null.

    mean, sharpe_std: location/scale of Sharpe distribution under null.
    For per-period Sharpe: sharpe_std = sqrt(1/(n-1))
    For annualized Sharpe: sharpe_std = sqrt(P/(n-1))
    Returns mean + sharpe_std * expected_max_std
    """
    if num_trials <= 1 or sharpe_std <= 0:
        return float(mean)
    return float(mean + sharpe_std * _expected_max_std(num_trials))


def deflated_sharpe_ratio(
    observed_sr: float,
    num_trials: int,
    n: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    periods_per_year: int = 252 * 24,
    annualized: bool = True,
) -> float:
    """DSR: PSR with benchmark = expected maximum under N trials.

    observed_sr: Sharpe in same units as benchmark (annualized if annualized=True)
    num_trials: N including discarded (must be tracked via ExperimentStore)
    n: number of return observations (T)
    skewness/kurtosis: of returns
    periods_per_year: for correct scaling when annualized
    annualized: whether observed_sr is annualized

    Benchmark SR0 = expected_max_sharpe_ratio(N, sharpe_std_null)
    where sharpe_std_null = sqrt(P/(n-1)) if annualized else sqrt(1/(n-1))
    (variance under null with SR=0, skew=0, kurt=3 => Var = P/(n-1) or 1/(n-1))

    DSR = PSR( SR0 )

    Properties (tested):
      - N=1 => DSR == PSR(0)
      - DSR < PSR for N>1 when SR>0
      - DSR decreases with N
      - With more n, DSR -> PSR (less uncertainty)
    No heuristic 0.15 factor. No mixing.
    """
    if num_trials <= 1:
        return probabilistic_sharpe_ratio(observed_sr, n, skewness, kurtosis, 0.0, periods_per_year, annualized)
    P = periods_per_year if annualized else 1
    # std of Sharpe under null (SR=0): var = P/(n-1) for annualized, 1/(n-1) per-period
    if n <= 1:
        return 0.5
    sharpe_std_null = math.sqrt(P / (n - 1)) if annualized else math.sqrt(1 / (n - 1))
    # For exact Prado formula, variance under null should be 1/(n-1) for per-period,
    # but if observed is annualized, scale accordingly.
    # However alternative is to use var_null = (1)/(n-1) for per-period and then annualize benchmark:
    # benchmark_ann = expected_max_std * sqrt(P/(n-1))
    # That's equivalent to sharpe_std_null * expected_max_std
    benchmark = expected_max_sharpe_ratio(num_trials, sharpe_std_null, mean=0.0)
    return probabilistic_sharpe_ratio(observed_sr, n, skewness, kurtosis, benchmark, periods_per_year, annualized)


def walk_forward_efficiency(is_sharpe: float, oos_sharpe: float) -> float:
    if is_sharpe == 0:
        return 0.0 if oos_sharpe <= 0 else float("inf")
    return float(oos_sharpe / is_sharpe)
