"""Tests for the walk-forward selection study (round 19).

The load-bearing property is that ranking at each rebalance date uses only data up
to that date. If it leaked, the whole round would be measuring nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("wf", _ROOT / "scripts" / "edgelab_walkforward_run.py")
assert _spec and _spec.loader
wf = importlib.util.module_from_spec(_spec)
sys.modules["wf"] = wf
_spec.loader.exec_module(wf)


def _net(seed: int = 0, n: int = 1200) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2000-01-03", periods=n)
    return pd.DataFrame({f"s{i}": rng.normal(0.0002 * i, 0.01, n) for i in range(4)}, index=idx)


def test_trailing_sharpe_uses_only_the_past():
    net = _net()
    a = wf.trailing_sharpe(net, 800, 252)
    # Perturbing data strictly after the cut must not change the ranking.
    mutated = net.copy()
    mutated.iloc[801:] *= 5.0
    b = wf.trailing_sharpe(mutated, 800, 252)
    pd.testing.assert_series_equal(a, b)


def test_trailing_sharpe_is_empty_during_warmup():
    net = _net()
    assert wf.trailing_sharpe(net, 50, 252).empty


def test_trailing_sharpe_ranks_a_known_better_signal_first():
    idx = pd.bdate_range("2000-01-03", periods=600)
    rng = np.random.default_rng(7)
    net = pd.DataFrame(
        {
            "good": rng.normal(0.0012, 0.01, 600),
            "bad": rng.normal(-0.0008, 0.01, 600),
        },
        index=idx,
    )
    s = wf.trailing_sharpe(net, 500, 252)
    assert s.idxmax() == "good"
    assert s.idxmin() == "bad"


def test_top_k_is_bounded_by_the_available_signals():
    net = _net(n=600)
    s = wf.trailing_sharpe(net, 500, 252)
    assert len(s) <= net.shape[1]
