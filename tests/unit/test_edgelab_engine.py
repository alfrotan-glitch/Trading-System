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

    Uses a Sharpe that looks respectable (0.6 over 17.8 years is t=2.5): it is
    convincing as a single pre-registered test and unconvincing as the best of 500.
    The earlier version of this test used SR 0.1, whose "pass" was an artefact of
    the annualised/per-bar units bug rather than a property of the statistic.
    """
    few = deflated_sharpe(sr_annualised=0.6, n_trials=1, n_obs=4481, bars_per_year=252)
    many = deflated_sharpe(sr_annualised=0.6, n_trials=500, n_obs=4481, bars_per_year=252)
    assert few > many
    assert few > 0.99, "a single trial needs no deflation"
    assert many < 0.95, "500 trials must demote a marginal Sharpe"


def test_deflated_sharpe_rejects_short_samples():
    assert deflated_sharpe(sr_annualised=3.0, n_trials=1, n_obs=2, bars_per_year=252) == 0.0


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


def test_deflated_sharpe_does_not_saturate_on_annualised_input():
    """Regression: an annualised Sharpe was fed to a per-bar formula.

    The benchmark is `E[max SR] * sqrt(P/(n-1))`, so mixing frequencies inflated
    the t-statistic by sqrt(252) and returned ~1.0 for every input. The guard then
    passed pure noise. These are tsmom_d5's real DEV numbers (SR 0.513, 4481 bars,
    9 trials in its family): it must be judged insufficiently proven, not certain.
    """
    dsr = deflated_sharpe(sr_annualised=0.513, n_trials=9, n_obs=4481, bars_per_year=252)
    assert dsr < 0.95, "a Sharpe of 0.513 over 17.8 years is not proof after 9 trials"
    assert dsr == pytest.approx(0.74, abs=0.02)


def test_deflated_sharpe_units_are_self_consistent():
    """Annualised and per-bar inputs must agree when each is scaled correctly.

    If the two conventions disagree, one of them is wrong — which is exactly the
    bug this pins.
    """
    annual = deflated_sharpe(sr_annualised=1.0, n_trials=20, n_obs=2000, bars_per_year=252)
    per_bar = deflated_sharpe(
        sr_annualised=1.0 / np.sqrt(252), n_trials=20, n_obs=2000, bars_per_year=1
    )
    assert annual == pytest.approx(per_bar, abs=1e-9)


def test_deflated_sharpe_gets_harder_with_more_trials_at_realistic_sharpe():
    """The deflation must bite where it matters: a plausible, mid-range Sharpe."""
    few = deflated_sharpe(sr_annualised=0.6, n_trials=1, n_obs=4481, bars_per_year=252)
    many = deflated_sharpe(sr_annualised=0.6, n_trials=45, n_obs=4481, bars_per_year=252)
    assert few > 0.95
    assert many < few
