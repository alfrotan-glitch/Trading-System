"""Statistical machinery for impulse research — multiplicity-penalized.

Everything here is deterministic given a seed. We reuse the repository's
existing validation statistics (deflated Sharpe ratio, minimum backtest
length) wherever they apply, and add only what the event-study design
requires: exact binomial tests against a baseline rate, Holm-Bonferroni
correction across the pre-registered family space, and seeded bootstrap
confidence intervals for net expectancy.
"""

from __future__ import annotations

import numpy as np
from scipy import stats as sps


def binomial_test_vs_baseline(successes: int, n: int, baseline_rate: float) -> float:
    """Two-sided exact binomial p-value: is the event continuation rate
    distinguishable from the non-impulse baseline rate?"""
    if n <= 0:
        return 1.0
    p0 = min(max(baseline_rate, 1e-9), 1 - 1e-9)
    return float(sps.binomtest(successes, n, p0, alternative="two-sided").pvalue)


def holm_bonferroni(p_values: list[float]) -> list[float]:
    """Holm step-down adjusted p-values (monotone, capped at 1.0).

    Adjusted p for the k-th smallest raw p (0-indexed rank r) is
    max over all smaller-or-equal ranks of (m - r) * p, where m = number of
    hypotheses. Returns values in the ORIGINAL input order.
    """
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running_max = 0.0
    for rank, idx in enumerate(order):
        val = (m - rank) * p_values[idx]
        running_max = max(running_max, val)
        adjusted[idx] = min(1.0, running_max)
    return adjusted


def bootstrap_ci_mean(
    values: list[float] | np.ndarray, n_boot: int = 2000, alpha: float = 0.05, seed: int = 42
) -> tuple[float, float, float]:
    """Seeded percentile bootstrap CI for the mean. Returns (mean, lo, hi).

    Empty input -> (0.0, 0.0, 0.0): no data, no claim.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    lo = float(np.quantile(means, alpha / 2))
    hi = float(np.quantile(means, 1 - alpha / 2))
    return float(arr.mean()), lo, hi


def two_proportion_diff_ci(
    k1: int, n1: int, k2: int, n2: int, alpha: float = 0.05, seed: int = 42, n_boot: int = 2000
) -> tuple[float, float, float]:
    """Seeded bootstrap CI for p1 - p2 (event rate minus baseline rate)."""
    if n1 == 0 or n2 == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    p1, p2 = k1 / n1, k2 / n2
    b1 = rng.binomial(n1, p1, size=n_boot) / n1
    b2 = rng.binomial(n2, p2, size=n_boot) / n2
    diffs = b1 - b2
    lo = float(np.quantile(diffs, alpha / 2))
    hi = float(np.quantile(diffs, 1 - alpha / 2))
    return p1 - p2, lo, hi


def event_series_sharpe(net_returns_bps: list[float] | np.ndarray) -> float:
    """Per-event Sharpe-like ratio of net returns (mean/std), no annualization.

    Event studies have irregular timing; annualizing would fabricate a
    frequency claim. Reported as-is and labeled per-event.
    """
    arr = np.asarray(net_returns_bps, dtype=float)
    if arr.size < 2:
        return 0.0
    sd = float(np.std(arr, ddof=1))
    if sd == 0:
        return 0.0
    return float(arr.mean() / sd)
