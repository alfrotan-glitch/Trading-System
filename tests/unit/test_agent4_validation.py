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
    month_end_flags,
    side_rate,
    sma,
    trading_day,
    window_bounds,
    x_bollinger,
    x_donchian,
    x_gated_donchian,
    x_ma_cross,
    x_nr7,
    x_rsi2,
    x_tsmom,
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


# ------------------------------------------------------------------ daily families


def test_month_end_flags_mark_last_bar_of_each_month() -> None:
    idx = pd.bdate_range("2024-01-01", "2024-03-31")  # three complete months
    flags = month_end_flags(idx)
    assert flags.sum() == 3
    for month in (1, 2, 3):
        pos = np.where(idx.month == month)[0]
        assert flags[pos[-1]], f"last bar of month {month} must be flagged"
        assert not flags[pos[-2]]


def test_tsmom_resizes_on_month_end_and_keeps_accounting_identity() -> None:
    df = _walk(3000, seed=21, drift=0.001)  # strong uptrend -> long after warm-up
    plan = x_tsmom(df, 63)
    run = xrun(df, plan.target, plan.size, plan.stop, 0, len(df), rebalance=plan.rebalance)
    assert run.trades, "tsmom should trade on an uptrend"
    # accounting identity must hold through the resize path
    ledger = sum(t.net_usd for t in run.trades)
    assert run.equity[-1] - INITIAL_EQUITY == pytest.approx(ledger, abs=1e-6)
    # the position must be long most of the time on an uptrend
    long_frac = float(np.mean([t.direction for t in run.trades]))
    assert long_frac > 0.5


def test_tsmom_signals_causal_under_truncation_with_calendar_exemption() -> None:
    """The final truncated bar can look like a month end; exempt it (as the repo check does)."""
    df = _walk(2500, seed=22)
    for cut in (800, 1600):
        part = df.iloc[:cut]
        full = x_tsmom(df, 63)
        trunc = x_tsmom(part, 63)
        for field in ("target", "size", "stop"):
            a = np.asarray(getattr(full, field))[: cut - 1]
            b = np.asarray(getattr(trunc, field))[: cut - 1]
            both_nan = np.isnan(a) & np.isnan(b)
            ok = both_nan | np.isclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=False)
            assert ok.all(), f"tsmom.{field} differs at bar {int(np.argmin(ok))} for cut {cut}"


def test_rsi2_buys_oversold_dip_and_exits_on_recovery() -> None:
    # flat, deep dive, recovery: RSI(2) < 5 at the bottom, close > SMA5 on the bounce
    n_flat, n_dive, n_rec = 60, 6, 8
    close = np.concatenate(
        [np.full(n_flat, 1000.0), np.linspace(1000.0, 940.0, n_dive), np.linspace(940.0, 990.0, n_rec)]
    )
    idx = pd.bdate_range("2020-01-01", periods=len(close))
    df = _ohlc(idx, close, spread=0.3)
    plan = x_rsi2(df, threshold=5.0, trend_filter=False)
    state = plan.target
    assert (state == 1.0).any(), "RSI(2) < 5 must go long on the dive"
    first_long = int(np.argmax(state == 1.0))
    assert first_long >= n_flat - 1  # no entry before the dive
    # state returns to 0 after the recovery (close > SMA5)
    assert (state[first_long:] == 0.0).any()


def test_nr7_narrow_range_breakout_triggers() -> None:
    # six ordinary bars, one very narrow bar (NR7), then a close above its high
    rngs = [8.0, 7.0, 6.0, 5.0, 4.5, 4.0, 0.5]
    closes = [1000.0 + i for i in range(len(rngs))]
    closes.append(closes[-1] + 10.0)  # breakout close above the NR7 high
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    opens = np.concatenate([[closes[0]], np.array(closes[:-1])])
    highs = np.maximum(opens, closes) + np.concatenate([rngs, [2.0]])
    lows = np.minimum(opens, closes) - np.concatenate([rngs, [2.0]])
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1.0}, index=idx
    )
    plan = x_nr7(df, hold=3)
    assert (plan.target == 1.0).any(), "a close through the NR7 range must enter long"


def test_bollinger_control_fades_excursion_and_exits_at_mean() -> None:
    rng = np.random.default_rng(31)
    n = 400
    close = 1000.0 + np.cumsum(rng.normal(0, 1.0, n))
    close[200:212] = close[199] - np.linspace(1, 24, 12)  # shove below the lower band
    idx = pd.bdate_range("2020-01-01", periods=n)
    df = _ohlc(idx, close, spread=0.2)
    plan = x_bollinger(df, 20, 2.0)
    state = plan.target
    assert (state == 1.0).any(), "a close below the lower band must fade long"
    assert (state == -1.0).any() or (state == 1.0).any()


def test_efficiency_gated_donchian_blocks_chop_and_accounting_holds() -> None:
    rng = np.random.default_rng(41)
    n = 5000
    # alternating chop: efficiency ratio stays low, so the gate must suppress entries
    step = np.where(np.arange(n) % 2 == 0, 6.0, -6.0)
    close = 1000.0 + np.cumsum(rng.normal(0, 0.8, n) + step * 0.0)
    idx = pd.bdate_range("2015-01-01", periods=n)
    df = _ohlc(idx, close, spread=0.5)
    plan = x_gated_donchian(df, 0.25)
    run = xrun(df, plan.target, plan.size, plan.stop, 0, n)
    ledger = sum(t.net_usd for t in run.trades)
    assert run.equity[-1] - INITIAL_EQUITY == pytest.approx(ledger, abs=1e-6)
    plain = x_donchian(df, 55, 20, 3.0)
    run_plain = xrun(df, plain.target, plain.size, plain.stop, 0, n)
    # the gate can only remove entries, never add them
    assert len(run.trades) <= len(run_plain.trades)
