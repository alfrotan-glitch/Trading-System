"""Unit tests for the Agent 4 independent validation engine (scripts/agent4_independent_validation.py).

The engine, signal builders and statistics there are a from-scratch
re-implementation used to cross-check the frozen long-history studies. These
tests pin its core invariants on synthetic data only: the accounting identity,
stop-fill semantics, cost arithmetic, signal causality and the deflated-Sharpe
implementation. Real-data cross-checks require the gitignored processed series
and are performed by the script itself, not here.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from scripts.agent4_independent_validation import (
    INITIAL_EQUITY,
    M15_PPY,
    XPlan,
    compare,
    side_rate,
    sma,
    trading_day,
    window_bounds,
    x_donchian,
    x_ma_cross,
    xdsr,
    xholm,
    xmaxdd,
    xrun,
    xsharpe,
)


def _ohlc(index: pd.DatetimeIndex, close: np.ndarray, spread: float = 0.4) -> pd.DataFrame:
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) + spread,
            "low": np.minimum(opens, close) - spread,
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


def _walk(n: int, seed: int = 5, drift: float = 0.0002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="15min")
    close = 1200.0 * np.exp(np.cumsum(rng.normal(drift, 0.004, n)))
    return _ohlc(idx, close)


def _always_long_plan(n: int) -> XPlan:
    target = np.full(n, np.nan)
    target[0] = 1.0
    size = np.full(n, np.nan)
    size[0] = 1.0
    return XPlan(target, size, np.full(n, np.nan), "always_long")


# ------------------------------------------------------------------ engine invariants


def test_accounting_identity_equity_equals_trade_ledger() -> None:
    df = _walk(4000)
    plan = x_ma_cross(df, 32, 128, 3.0, M15_PPY, 5520)
    run = xrun(df, plan.target, plan.size, plan.stop, 0, len(df))
    ledger = sum(t.net_usd for t in run.trades)
    assert run.trades, "expected trades on a random walk"
    assert run.equity[-1] - INITIAL_EQUITY == pytest.approx(ledger, abs=1e-6)


def test_zero_cost_matches_zero_multiplier() -> None:
    df = _walk(3000, seed=11)
    plan = x_ma_cross(df, 16, 64, 3.0, M15_PPY, 5520)
    paid = xrun(df, plan.target, plan.size, plan.stop, 0, len(df), mult=1.0)
    free = xrun(df, plan.target, plan.size, plan.stop, 0, len(df), mult=0.0)
    assert free.cost_usd == pytest.approx(0.0, abs=1e-9)
    assert paid.cost_usd > 0.0
    # each round turn pays entry + exit at the side rate of its fill price
    expected = sum(t.cost_usd for t in paid.trades)
    assert paid.cost_usd == pytest.approx(expected, abs=1e-6)
    assert free.net_usd > paid.net_usd


def test_side_rate_matches_prereg_cost_model() -> None:
    # prereg §4: 3 bps spread + 1 bp slippage per side + $7/lot/side (100 oz)
    rate = side_rate(1300.0)
    expected = 3.0 / 2.0 / 1e4 + 1.0 / 1e4 + 7.0 / (100.0 * 1300.0)
    assert rate == pytest.approx(expected)
    assert 2 * rate * 1e4 == pytest.approx(6.077, abs=0.01)  # documented round-turn bps


def test_stop_fills_at_stop_level_and_blocks_reentry() -> None:
    # price rises, then collapses through the stop; SAR state stays long
    closes = np.concatenate([np.linspace(1300.0, 1320.0, 50), np.linspace(1320.0, 1250.0, 20)])
    df = _ohlc(pd.date_range("2015-01-01", periods=70, freq="15min"), closes, spread=0.2)
    n = len(df)
    target = np.full(n, 1.0)  # always-long state (SAR)
    size = np.full(n, 1.0)
    stop = np.full(n, 5.0)  # $5 stop distance
    run = xrun(df, target, size, stop, 0, n)
    stopped = [t for t in run.trades if t.stopped]
    assert stopped, "the collapse must trigger the stop"
    first = stopped[0]
    assert first.exit_price == pytest.approx(first.entry_price - 5.0, abs=0.05)
    # after a stop, same-direction re-entry is blocked until the state changes,
    # and the state never changes here -> exactly one trade
    assert len(run.trades) == len(stopped) == 1


def test_fill_happens_at_next_open_not_signal_close() -> None:
    # single-bar plan: decide long at bar 3's close -> fill at bar 4's open
    df = _walk(20, seed=2)
    n = len(df)
    target = np.full(n, np.nan)
    target[3] = 1.0
    size = np.full(n, np.nan)
    size[3] = 1.0
    run = xrun(df, target, size, np.full(n, np.nan), 0, n)
    t = run.trades[0]
    assert t.entry_bar == 4
    assert t.entry_price == pytest.approx(float(df["open"].iloc[4]))


def test_forced_exit_closes_open_position_at_final_close() -> None:
    df = _walk(30, seed=3)
    plan = _always_long_plan(len(df))
    run = xrun(df, plan.target, plan.size, plan.stop, 0, len(df))
    t = run.trades[-1]
    assert t.forced
    assert t.exit_price == pytest.approx(float(df["close"].iloc[-1]))
    assert t.exit_bar == len(df) - 1


def test_lag_bars_delays_execution_by_exactly_one_bar() -> None:
    df = _walk(60, seed=4)
    n = len(df)
    target = np.full(n, np.nan)
    target[5] = 1.0
    size = np.full(n, np.nan)
    size[5] = 1.0
    stop = np.full(n, np.nan)
    prompt = xrun(df, target, size, stop, 0, n)
    lagged = xrun(df, target, size, stop, 0, n, lag_bars=1)
    assert prompt.trades[0].entry_bar == 6
    assert lagged.trades[0].entry_bar == 7


# ------------------------------------------------------------------ causality


@pytest.mark.parametrize("builder_name", ["ma_cross", "donchian"])
def test_signals_are_causal_under_truncation(builder_name: str) -> None:
    """A signal at bar t must not change when the future is removed."""
    df = _walk(6000, seed=7)
    for cut in (1000, 2500, 4000):
        part = df.iloc[:cut]
        if builder_name == "ma_cross":
            full = x_ma_cross(df, 16, 64, 3.0, M15_PPY, 5520)
            trunc = x_ma_cross(part, 16, 64, 3.0, M15_PPY, 5520)
        else:
            full = x_donchian(df, 96, 48, 3.0)
            trunc = x_donchian(part, 96, 48, 3.0)
        for field in ("target", "size", "stop"):
            a = np.asarray(getattr(full, field))[: cut - 1]
            b = np.asarray(getattr(trunc, field))[: cut - 1]
            both_nan = np.isnan(a) & np.isnan(b)
            ok = both_nan | np.isclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=False)
            assert ok.all(), f"{builder_name}.{field} differs at bar {int(np.argmin(ok))} for cut {cut}"


# ------------------------------------------------------------------ statistics


def test_sharpe_and_max_drawdown_known_values() -> None:
    r = np.array([0.01, -0.02, 0.03, 0.01, -0.01, 0.02] * 10)
    sr = xsharpe(r, 252)
    assert sr == pytest.approx(float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(252)))
    eq = np.array([100.0, 120.0, 90.0, 110.0, 80.0])
    assert xmaxdd(eq, 100.0) == pytest.approx(80.0 / 120.0 - 1.0)


def test_holm_step_down_matches_reference() -> None:
    adj = xholm({"a": 0.01, "b": 0.04, "c": 0.03})
    # sorted: a .01 (x3), c .03 (x2), b .04 (x1) -> running max
    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(min(1.0, 0.06))
    assert adj["b"] == 0.06


def test_dsr_is_psr_for_one_trial_and_decreases_with_trials() -> None:
    rng = np.random.default_rng(9)
    r = rng.normal(0.00008, 0.004, 20000)
    one = xdsr(r, 1, 252)["dsr"]
    forty = xdsr(r, 40, 252)["dsr"]
    hundred = xdsr(r, 100, 252)["dsr"]
    assert 0.5 < one < 1.0
    assert forty < one
    assert hundred <= forty


# ------------------------------------------------------------------ helpers


def test_window_bounds_are_inclusive_of_end_day() -> None:
    idx = pd.date_range("2020-01-01", periods=500, freq="15min")
    a, b = window_bounds(idx, "2020-01-01", "2020-01-01")
    assert a == 0
    assert b == 96  # every 15-minute bar of that day


def test_trading_day_rolls_at_22utc() -> None:
    idx = pd.DatetimeIndex(["2024-03-05 21:45", "2024-03-05 22:00", "2024-03-06 01:00"])
    days = list(trading_day(idx))
    assert days[0] == pd.Timestamp("2024-03-05")
    assert days[1] == pd.Timestamp("2024-03-06")
    assert days[2] == pd.Timestamp("2024-03-06")


def test_compare_helper_tolerances() -> None:
    assert compare("x", 10.0, 10.005, 0.001)["match"]
    assert not compare("x", 10.0, 10.2, 0.001)["match"]
    assert compare("x", "ma_32_128_atr3", "ma_32_128_atr3", 0)["match"]
    assert not compare("x", 3, 4, 0)["match"]


def test_sma_is_causal() -> None:
    s = pd.Series(np.arange(10, dtype=float))
    out = sma(s, 3)
    assert np.isnan(out.iloc[:2]).all()
    assert out.iloc[2] == pytest.approx(1.0)
    assert out.iloc[9] == pytest.approx(8.0)
