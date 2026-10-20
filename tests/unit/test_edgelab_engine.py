"""Engine invariants for Edge Lab.

These are the guards that stop a backtest from inventing an edge. The first one
exists because an unshifted position array credited a signal with the move that
preceded it and produced a Sharpe of 5 on XAUUSD daily bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import (
    CostModel,
    alpha_decomposition,
    deflated_sharpe,
    infer_bars_per_year,
    realized_vol,
    run_vector,
    split,
)


def _bars(n: int = 400) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    close = np.linspace(100, 150, n) * (1 + 0.001 * np.sin(np.arange(n)))
    open_ = close * 1.0005
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


def _run(bars, pos, cost=None, execution="close"):
    return run_vector(
        bars,
        pd.Series(pos, index=bars.index),
        cost or CostModel.zero(),
        name="t",
        family="t",
        period="X",
        bars_per_year=24 * 252,
        execution=execution,
    )


def test_always_long_close_fill_reproduces_buy_and_hold():
    bars = _bars()
    r = _run(bars, np.ones(len(bars)))
    expected = bars["close"].iloc[-1] / bars["close"].iloc[0] - 1
    assert r.net_return == pytest.approx(expected, rel=0, abs=1e-12)


def test_always_long_next_open_fill_reproduces_buy_and_hold():
    bars = _bars()
    r = _run(bars, np.ones(len(bars)), execution="next_open")
    expected = bars["open"].iloc[-1] / bars["open"].iloc[1] - 1
    assert r.net_return == pytest.approx(expected, rel=0, abs=1e-12)


def test_flat_position_earns_and_costs_nothing():
    bars = _bars()
    r = _run(bars, np.zeros(len(bars)), CostModel())
    assert r.net_return == 0.0
    assert r.trades == 0


def test_position_is_not_credited_with_the_move_that_preceded_it():
    """The look-ahead guard: shifting a signal by one bar must change P&L."""
    bars = _bars()
    rng = np.random.default_rng(7)
    pos = rng.choice([-1.0, 0.0, 1.0], size=len(bars))
    a = _run(bars, pos)
    b = _run(bars, np.concatenate([[0.0], pos[:-1]]))
    assert a.net_return != b.net_return


def test_costs_monotonically_reduce_returns():
    bars = _bars()
    rng = np.random.default_rng(3)
    pos = rng.choice([-1.0, 1.0], size=len(bars))
    zero = _run(bars, pos, CostModel.zero()).net_return
    base = _run(bars, pos, CostModel()).net_return
    stress = _run(bars, pos, CostModel.stressed(3)).net_return
    assert zero > base > stress


def test_turnover_scales_cost_drag():
    """Doubling position changes roughly doubles cost drag for the same cost model."""
    bars = _bars(800)
    slow = np.zeros(len(bars))
    slow[:] = 1.0
    fast = np.array([1.0 if i % 2 == 0 else -1.0 for i in range(len(bars))])
    r_slow = _run(bars, slow, CostModel())
    r_fast = _run(bars, fast, CostModel())
    assert r_fast.cost_drag > 20 * r_slow.cost_drag


def test_split_periods_are_chronological_and_disjoint():
    idx = pd.date_range("2004-01-01", "2025-01-01", freq="1D", tz="UTC")
    parts = split(idx)
    assert parts["DEV"][-1] < parts["VAL"][0]
    assert parts["VAL"][-1] < parts["TEST"][0]
    for a, b in (("DEV", "VAL"), ("VAL", "TEST")):
        assert set(parts[a]).isdisjoint(set(parts[b]))


def test_deflated_sharpe_punishes_more_trials():
    """Same Sharpe, more configurations tried -> less evidence of skill.

    The Sharpe must be marginal *relative to the sample*, otherwise it saturates
    at 1.0 regardless of trials and the test proves nothing. SR 0.1 over 1000
    bars is a t-stat of ~3.2, which survives a handful of trials but not 500.
    """
    few = deflated_sharpe(sr=0.1, n_trials=1, n_obs=1000)
    many = deflated_sharpe(sr=0.1, n_trials=500, n_obs=1000)
    assert few > many
    assert few > 0.99, "a single trial needs no deflation"
    assert many < 0.95, "500 trials must demote a marginal Sharpe"


def test_deflated_sharpe_rejects_short_samples():
    assert deflated_sharpe(sr=3.0, n_trials=1, n_obs=2) == 0.0


def _market(n: int = 2000, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.01, n))


def test_alpha_decomposition_identifies_pure_beta():
    """A clone of the benchmark must show beta 1 and no alpha."""
    bench = _market()
    stats = alpha_decomposition(bench, bench, 252.0)
    assert stats["beta"] == pytest.approx(1.0, abs=1e-9)
    assert stats["alpha_ann"] == pytest.approx(0.0, abs=1e-9)
    assert stats["ir_vs_bh"] == pytest.approx(0.0, abs=1e-9)


def test_alpha_decomposition_identifies_cash_strategy():
    """Holding cash earns no alpha and has no market exposure — the null case."""
    bench = _market()
    zeros = pd.Series(0.0, index=bench.index)
    stats = alpha_decomposition(zeros, bench, 252.0)
    assert stats["beta"] == pytest.approx(0.0, abs=1e-9)
    assert stats["alpha_ann"] == pytest.approx(0.0, abs=1e-9)


def test_alpha_decomposition_detects_real_timing_skill():
    """Add independent positive drift on top of the market and alpha must appear."""
    bench = _market()
    rng = np.random.default_rng(11)
    skilled = bench * 0.0 + 0.0006 + rng.normal(0.0, 0.002, len(bench))
    stats = alpha_decomposition(skilled, bench, 252.0)
    # Estimated on 2000 noisy bars, so beta is ~0 rather than exactly 0.
    assert stats["beta"] == pytest.approx(0.0, abs=0.05)
    assert stats["alpha_ann"] > 0.10
    assert stats["alpha_t"] > 2.0


def test_realized_vol_is_annualised_on_daily_bars():
    """Daily bars must annualise with sqrt(252), not sqrt(1).

    The bug this pins: annualising with bars-per-*day* returns daily sigma, so a
    15% vol target is never binding and every vol-scaled strategy silently runs at
    full size.
    """
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2015-01-01", periods=1500, tz="UTC")
    rets = rng.normal(0.0, 0.01, len(idx))
    close = pd.Series(100 * np.cumprod(1 + rets), index=idx)
    assert infer_bars_per_year(idx) == pytest.approx(252.0, rel=1e-6)
    vol = realized_vol(close, n=60).dropna()
    # sigma 1%/day -> ~15.9% annualised.
    assert vol.iloc[-1] == pytest.approx(0.01 * np.sqrt(252), rel=0.15)
