"""Tests for impulse statistics: multiplicity correction, exact binomial, bootstrap."""

from __future__ import annotations

import numpy as np
import pytest

from qts.research.impulse.statistics import (
    binomial_test_vs_baseline,
    bootstrap_ci_mean,
    event_series_sharpe,
    holm_bonferroni,
    two_proportion_diff_ci,
)


class TestHolmBonferroni:
    def test_known_vector(self):
        p = [0.001, 0.01, 0.03, 0.5]
        adj = holm_bonferroni(p)
        # ranks: .001*4=.004, .01*3=.03, .03*2=.06, .5*1=.5 (monotone max applied)
        assert adj[0] == pytest.approx(0.004)
        assert adj[1] == pytest.approx(0.03)
        assert adj[2] == pytest.approx(0.06)
        assert adj[3] == pytest.approx(0.5)

    def test_adjusted_ge_raw_and_capped(self):
        p = [0.9, 0.8, 0.0001, 0.4]
        adj = holm_bonferroni(p)
        for raw, a in zip(p, adj, strict=True):
            assert a >= raw
            assert a <= 1.0

    def test_monotone_in_rank_order(self):
        p = [0.05, 0.01, 0.001]
        adj = holm_bonferroni(p)
        order = sorted(range(3), key=lambda i: p[i])
        vals = [adj[i] for i in order]
        assert vals == sorted(vals)

    def test_stepdown_max_enforcement(self):
        # a later (larger) p can be raised by the running max of earlier steps
        p = [0.02, 0.03]
        adj = holm_bonferroni(p)
        assert adj[0] == pytest.approx(0.04)  # 0.02*2
        assert adj[1] == pytest.approx(0.04)  # max(0.04, 0.03*1)

    def test_empty(self):
        assert holm_bonferroni([]) == []

    def test_all_ones(self):
        assert holm_bonferroni([1.0, 1.0]) == [1.0, 1.0]


class TestBinomial:
    def test_null_match_high_p(self):
        assert binomial_test_vs_baseline(50, 100, 0.5) > 0.9

    def test_extreme_low_p(self):
        assert binomial_test_vs_baseline(90, 100, 0.5) < 1e-10

    def test_zero_n_no_claim(self):
        assert binomial_test_vs_baseline(0, 0, 0.5) == 1.0

    def test_degenerate_baseline_clamped(self):
        # baseline rate 0 must not crash; any success is surprising
        p = binomial_test_vs_baseline(1, 10, 0.0)
        assert 0.0 <= p <= 1.0


class TestBootstrap:
    def test_deterministic_given_seed(self):
        vals = list(np.linspace(-5, 10, 50))
        a = bootstrap_ci_mean(vals, n_boot=500, seed=42)
        b = bootstrap_ci_mean(vals, n_boot=500, seed=42)
        assert a == b

    def test_different_seed_may_differ_but_ci_contains_mean(self):
        vals = list(np.linspace(-5, 10, 50))
        mean, lo, hi = bootstrap_ci_mean(vals, n_boot=500, seed=7)
        assert lo <= mean <= hi

    def test_empty_no_claim(self):
        assert bootstrap_ci_mean([]) == (0.0, 0.0, 0.0)

    def test_constant_series_zero_width(self):
        mean, lo, hi = bootstrap_ci_mean([3.0] * 20, n_boot=200, seed=1)
        assert mean == lo == hi == pytest.approx(3.0)

    def test_diff_ci_deterministic_and_ordered(self):
        d, lo, hi = two_proportion_diff_ci(60, 100, 40, 100, n_boot=500, seed=42)
        d2, lo2, hi2 = two_proportion_diff_ci(60, 100, 40, 100, n_boot=500, seed=42)
        assert (d, lo, hi) == (d2, lo2, hi2)
        assert d == pytest.approx(0.2)
        assert lo <= d <= hi

    def test_diff_ci_empty_inputs(self):
        assert two_proportion_diff_ci(0, 0, 1, 2) == (0.0, 0.0, 0.0)


class TestEventSharpe:
    def test_known_vector(self):
        vals = [1.0, 3.0]  # mean 2, std(ddof=1) sqrt(2)
        assert event_series_sharpe(vals) == pytest.approx(2.0 / np.sqrt(2.0))

    def test_zero_std(self):
        assert event_series_sharpe([2.0, 2.0, 2.0]) == 0.0

    def test_single_value_no_claim(self):
        assert event_series_sharpe([5.0]) == 0.0
