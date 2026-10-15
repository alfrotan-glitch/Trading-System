"""Unit tests for the long-history XAUUSD research modules.

These use small synthetic series so they run in the fast suite. Real-data
provenance (SHA-256 of the processed files) is checked separately and skips
cleanly when the gitignored raw inputs are absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory import checks as C
from qts.research.longhistory import daily as D
from qts.research.longhistory import engine as E
from qts.research.longhistory import protocol as P
from qts.research.longhistory import signals as G
from qts.research.longhistory import sources as S
from qts.research.longhistory import stats as ST

REPO = Path(__file__).resolve().parents[2]


def _ohlc(index: pd.DatetimeIndex, close: np.ndarray, spread: float = 0.5) -> pd.DataFrame:
    opens = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(opens, close) + spread
    low = np.minimum(opens, close) - spread
    return pd.DataFrame({"open": opens, "high": high, "low": low, "close": close, "volume": 1.0}, index=index)


def _walk(n: int, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-04", periods=n)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    return _ohlc(idx, close)


ZERO_COST = E.CostModel(spread_bps=0.0, slippage_bps=0.0, commission_usd_per_lot_side=0.0, basis="TEST")


# ----------------------------------------------------------------------- clock


def test_server_clock_is_gmt3_in_us_dst_and_gmt2_otherwise():
    stamps = pd.DatetimeIndex(["2024-07-01 12:00", "2024-01-15 12:00"])
    utc = S.server_gmt23_to_utc(stamps)
    assert list(utc) == [pd.Timestamp("2024-07-01 09:00"), pd.Timestamp("2024-01-15 10:00")]


def test_server_clock_offset_follows_us_dst_and_only_spring_switch_is_ambiguous():
    stamps = pd.date_range("2023-01-01", "2024-12-31 23:45", freq="15min")
    utc = S.server_gmt23_to_utc(stamps)
    offset_h = (pd.Series(stamps) - pd.Series(utc)).dt.total_seconds() / 3600.0
    months = pd.Series(stamps).dt.month.to_numpy()
    assert set(offset_h[(months == 1)].unique()) == {2.0}
    assert set(offset_h[(months == 7)].unique()) == {3.0}
    # On a dense grid the spring switch repeats one UTC hour (a backward step, two in two years).
    # Real BaseMax stamps skip that local hour, and any source that does not will be flagged by
    # quality_report (duplicate/non-monotonic steps) rather than silently repaired.
    steps = pd.Series(utc).diff().dropna()
    assert int((steps < pd.Timedelta(0)).sum()) == 2


def test_to_utc_rejects_unknown_basis():
    frame = _walk(3)
    with pytest.raises(ValueError):
        S.to_utc(frame, "mystery")


def test_clock_fit_recovers_known_shift():
    base = _walk(400)
    shifted = base.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=2)
    fit = S.clock_fit(base, shifted, hours=range(-3, 4))
    assert fit["best_shift_hours"] == -2


# ----------------------------------------------------------------------- daily


def test_session_rolls_at_22_utc():
    stamps = pd.DatetimeIndex(["2024-03-04 21:45", "2024-03-04 22:00", "2024-03-05 21:45"])
    labels = D.trading_day_label(stamps)
    assert list(labels) == [pd.Timestamp("2024-03-04"), pd.Timestamp("2024-03-05"), pd.Timestamp("2024-03-05")]


def test_partial_days_are_excluded_from_daily_bars():
    idx = pd.date_range("2024-03-04 22:00", periods=200, freq="15min")
    frame = _ohlc(idx, np.linspace(100, 110, 200))
    # keep only 10 bars of the second session: partial
    frame = pd.concat([frame.iloc[:96], frame.iloc[96:106]])
    daily, cov = D.to_daily(frame, min_bars=40)
    assert cov.days_partial == 1
    assert len(daily) == 1
    assert daily["n_bars"].iloc[0] == 96


def test_daily_ohlc_definition():
    idx = pd.date_range("2024-03-04 22:00", periods=96, freq="15min")
    close = np.linspace(100, 101, 96)
    frame = _ohlc(idx, close, spread=1.0)
    daily, _ = D.to_daily(frame, min_bars=40)
    row = daily.iloc[0]
    assert row["open"] == frame["open"].iloc[0]
    assert row["close"] == frame["close"].iloc[-1]
    assert row["high"] == frame["high"].max()
    assert row["low"] == frame["low"].min()


# ----------------------------------------------------------------------- causality


def test_every_candidate_is_causal_on_a_random_walk():
    df = _walk(900, seed=11)
    for cand in P.CANDIDATES:
        report = C.truncation_check(cand.builder, df, cuts=[300, 560, 780])
        assert report.passed, (cand.cid, report.mismatches[:2])


def test_truncation_check_catches_lookahead():
    df = _walk(300, seed=5)

    def leaky(frame: pd.DataFrame) -> G.Plan:
        future = frame["close"].shift(-1)  # uses the NEXT bar's close: forbidden
        target = np.where(future > frame["close"], 1.0, -1.0)
        n = len(frame)
        return G._plan(frame, "leaky", {}, target, np.full(n, 0.5), np.full(n, np.nan))

    # a leak at bar t shows only where the truncation removes bar t+1, so use many cut points
    report = C.truncation_check(leaky, df, cuts=list(range(40, 280, 12)))
    assert not report.passed


def test_warmup_check_converges_for_recursive_indicators():
    df = _walk(1200, seed=2)
    report = C.warmup_check(G.atr, df, burn_in=300, offset=400)
    assert report.passed
    report = C.warmup_check(lambda d: G.rsi(d["close"], 2), df, burn_in=300, offset=400)
    assert report.passed


def test_regime_label_at_t_does_not_change_with_future_data():
    df = _walk(700, seed=9)
    from qts.research.longhistory.runner import regime_labels

    full = regime_labels(df)
    part = regime_labels(df.iloc[:500])
    common = part.dropna()
    assert (full.loc[common.index] == common).all()


# ----------------------------------------------------------------------- stop-based sizing


def test_stop_based_risk_override_is_opt_in_and_preserves_frozen_defaults():
    df = _walk(450, seed=31)
    legacy_ma = P.candidate_by_id("ma_20_100_atr3").builder(df)
    default_ma = G.ma_cross(df, 20, 100, 3.0, risk_fraction=G.RISK_PER_TRADE)
    reduced_ma = G.ma_cross(df, 20, 100, 3.0, risk_fraction=0.005)
    legacy_donchian = P.candidate_by_id("donchian_55_20_atr2").builder(df)
    default_donchian = G.donchian(df, 55, 20, 2.0, risk_fraction=G.RISK_PER_TRADE)
    reduced_donchian = G.donchian(df, 55, 20, 2.0, risk_fraction=0.005)

    for legacy, explicit_default, reduced in (
        (legacy_ma, default_ma, reduced_ma),
        (legacy_donchian, default_donchian, reduced_donchian),
    ):
        np.testing.assert_allclose(legacy.target, explicit_default.target, equal_nan=True)
        np.testing.assert_allclose(legacy.size, explicit_default.size, equal_nan=True)
        np.testing.assert_allclose(legacy.stop_dist, explicit_default.stop_dist, equal_nan=True)
        np.testing.assert_array_equal(legacy.rebalance, explicit_default.rebalance)
        np.testing.assert_allclose(reduced.target, legacy.target, equal_nan=True)
        np.testing.assert_allclose(reduced.stop_dist, legacy.stop_dist, equal_nan=True)
        valid_size = np.isfinite(legacy.size)
        assert valid_size.any()
        np.testing.assert_allclose(reduced.size[valid_size], legacy.size[valid_size] * 0.5)
        assert "risk_fraction" not in legacy.params  # preserves frozen result metadata
        assert reduced.params["risk_fraction"] == pytest.approx(0.005)


def test_stop_based_sizing_rejects_invalid_or_increased_risk_budgets():
    df = _walk(40)
    for risk_fraction in (0.0, -0.001, np.nan, np.inf, G.RISK_PER_TRADE + 1e-6):
        with pytest.raises(ValueError, match="risk_fraction"):
            G.size_stop_based(df, 2.0, risk_fraction=risk_fraction)
    with pytest.raises(ValueError, match="only to stop-based"):
        G.ma_cross(df, 20, 100, None, risk_fraction=0.005)


# ----------------------------------------------------------------------- engine


def _plan_at(df: pd.DataFrame, target_at: int, sd: float | None = None, size: float = 0.5) -> G.Plan:
    n = len(df)
    target = np.full(n, np.nan)
    target[target_at] = 1.0
    stop = np.full(n, np.nan)
    if sd is not None:
        stop[target_at] = sd
    return G._plan(df, "test", {}, target, np.full(n, size), stop)


def test_decision_at_close_fills_at_next_open():
    df = _walk(40, seed=1)
    run = E.run_plan(df, _plan_at(df, 5), 0, 40, ZERO_COST)
    assert len(run.trades) == 1
    assert run.trades[0].entry_price == pytest.approx(df["open"].iloc[6])
    assert run.trades[0].entry_day == df.index[6]


def test_position_quantity_stays_fixed_until_an_explicit_rebalance():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    prices = np.array([100.0, 100.0, 110.0, 121.0])
    bars = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices}, index=idx
    )
    n = len(bars)
    target = np.full(n, np.nan)
    target[0] = 1.0
    size = np.full(n, np.nan)
    size[0] = 0.5
    no_rebalance = G._plan(
        bars, "fixed_units", {}, target.copy(), size.copy(), np.full(n, np.nan)
    )

    fixed = E.run_plan(bars, no_rebalance, 0, n, ZERO_COST)
    assert fixed.gross_usd == pytest.approx(1_050.0)  # 50 oz x ($121 - $100)
    assert fixed.final_equity == pytest.approx(11_050.0)
    assert fixed.accounting_model_version == "fixed_units.v2"

    target[1] = 1.0
    size[1] = 1.0
    rebalance = np.zeros(n, dtype=bool)
    rebalance[1] = True
    explicit_rebalance = G._plan(bars, "fixed_units", {}, target, size, np.full(n, np.nan), rebalance)
    resized = E.run_plan(bars, explicit_rebalance, 0, n, ZERO_COST)
    assert resized.gross_usd == pytest.approx(1_550.0)  # explicit resize occurs at the $110 open
    assert resized.final_equity == pytest.approx(11_550.0)
    assert resized.turnover_fraction > fixed.turnover_fraction


def test_explicit_rebalance_charges_only_the_actual_quantity_delta():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    price = np.full(4, 100.0)
    bars = pd.DataFrame({"open": price, "high": price, "low": price, "close": price}, index=idx)
    target = np.full(4, np.nan)
    target[0:2] = 1.0
    size = np.full(4, np.nan)
    size[0:2] = [0.5, 1.0]
    rebalance = np.zeros(4, dtype=bool)
    rebalance[1] = True
    plan = G._plan(bars, "rebalance_cost", {}, target, size, np.full(4, np.nan), rebalance)
    costs = E.CostModel(spread_bps=3.0, slippage_bps=1.0, commission_usd_per_lot_side=7.0, basis="TEST")
    run = E.run_plan(bars, plan, 0, len(bars), costs)

    rate = costs.side_rate(100.0)
    entry_notional = 5_000.0
    entry_cost = entry_notional * rate
    equity_after_entry = 10_000.0 - entry_cost
    target_notional = equity_after_entry
    rebalance_cost = (target_notional - entry_notional) * rate
    exit_cost = target_notional * rate
    assert run.cost_usd == pytest.approx(entry_cost + rebalance_cost + exit_cost)
    assert run.final_equity == pytest.approx(10_000.0 - run.cost_usd)
    assert run.trades[0].net_usd == pytest.approx(run.net_usd)


def test_zero_cap_skips_entry_and_zero_size_explicit_rebalance_closes():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    price = np.full(4, 100.0)
    bars = pd.DataFrame({"open": price, "high": price, "low": price, "close": price}, index=idx)
    target = np.full(4, np.nan)
    target[:2] = 1.0
    size = np.full(4, np.nan)
    size[:2] = [0.5, 0.0]
    rebalance = np.zeros(4, dtype=bool)
    rebalance[1] = True
    plan = G._plan(bars, "zero_size_rebalance", {}, target, size, np.full(4, np.nan), rebalance)
    costs = E.CostModel(spread_bps=3.0, slippage_bps=1.0, commission_usd_per_lot_side=7.0, basis="TEST")

    no_capacity = E.run_plan(bars, plan, 0, len(bars), costs, cap=0.0)
    assert no_capacity.trades == []
    assert not no_capacity.held.any()
    assert no_capacity.turnover_fraction == 0.0
    assert no_capacity.cost_usd == 0.0

    closed = E.run_plan(bars, plan, 0, len(bars), costs)
    entry_notional = 5_000.0
    side_rate = costs.side_rate(100.0)
    assert len(closed.trades) == 1
    assert closed.trades[0].exit_day == idx[2]
    assert not closed.trades[0].forced_exit
    assert closed.trades[0].gross_usd == pytest.approx(0.0)
    assert closed.cost_usd == pytest.approx(2.0 * entry_notional * side_rate)
    assert closed.final_equity == pytest.approx(10_000.0 - closed.cost_usd)


def test_zero_cost_identity_trades_equal_equity_change():
    df = _walk(200, seed=4)
    plan = _plan_at(df, 10, sd=None)
    run = E.run_plan(df, plan, 0, 200, ZERO_COST)
    assert sum(t.net_usd for t in run.trades) == pytest.approx(run.net_usd, abs=1e-6)


def test_costs_match_hand_calculation_on_flat_price():
    idx = pd.bdate_range("2020-01-01", periods=30)
    df = _ohlc(idx, np.full(30, 100.0), spread=0.0)
    costs = E.CostModel(spread_bps=3.0, slippage_bps=1.0, commission_usd_per_lot_side=7.0, basis="TEST")
    run = E.run_plan(df, _plan_at(df, 5, size=0.5), 0, 30, costs)
    rate = costs.side_rate(100.0)
    entry_notional = 0.5 * 10_000.0
    e1 = 10_000.0 - entry_notional * rate  # entry cost
    e2 = e1 - entry_notional * rate  # fixed 50 oz exit at the same price
    assert run.final_equity == pytest.approx(e2, rel=1e-12)
    assert run.cost_usd == pytest.approx(2 * entry_notional * rate, rel=1e-9)


def test_stop_fills_at_stop_level_when_range_crosses_it():
    idx = pd.bdate_range("2020-01-01", periods=20)
    close = np.full(20, 100.0)
    df = _ohlc(idx, close, spread=0.1)
    df.loc[df.index[7], "low"] = 97.0
    df.loc[df.index[7], "open"] = 99.5
    df.loc[df.index[7], "close"] = 98.0
    run = E.run_plan(df, _plan_at(df, 5, sd=2.0), 0, 20, ZERO_COST)
    stopped = [t for t in run.trades if t.stopped]
    assert stopped and stopped[0].exit_price == pytest.approx(98.0)


def test_stop_gap_fills_at_open_not_at_stop():
    idx = pd.bdate_range("2020-01-01", periods=20)
    df = _ohlc(idx, np.full(20, 100.0), spread=0.1)
    df.loc[df.index[7], "open"] = 95.0  # gapped through the 98 stop
    df.loc[df.index[7], "high"] = 95.5
    df.loc[df.index[7], "low"] = 94.0
    df.loc[df.index[7], "close"] = 94.5
    run = E.run_plan(df, _plan_at(df, 5, sd=2.0), 0, 20, ZERO_COST)
    stopped = [t for t in run.trades if t.stopped]
    assert stopped and stopped[0].exit_price == pytest.approx(95.0)


def test_blocked_reentry_until_state_changes():
    idx = pd.bdate_range("2020-01-01", periods=30)
    df = _ohlc(idx, np.full(30, 100.0), spread=0.1)
    df.loc[df.index[7], "low"] = 97.0  # stop-out on bar 7
    n = 30
    target = np.full(n, np.nan)
    target[5:] = 1.0  # decision at bar 5 enters at bar 6 with a stop; the state then stays long
    stop = np.full(n, np.nan)
    stop[5] = 2.0
    plan = G._plan(df, "t", {}, target, np.full(n, 0.5), stop)
    run = E.run_plan(df, plan, 0, n, ZERO_COST)
    assert sum(1 for t in run.trades if t.stopped) == 1
    assert len(run.trades) == 1  # no immediate re-entry while the state remains long


def test_window_end_forces_flat_and_marks_trade():
    df = _walk(60, seed=8)
    run = E.run_plan(df, _plan_at(df, 3), 0, 60, ZERO_COST, force_close_end=True)
    assert run.trades[-1].forced_exit
    assert not run.held[-1]


def test_cost_model_commission_scales_with_price():
    cheap = E.CostModel(spread_bps=0, slippage_bps=0, commission_usd_per_lot_side=7.0)
    assert cheap.side_rate(1000.0) > cheap.side_rate(4000.0)
    assert cheap.scaled(2.0).side_rate(1000.0) == pytest.approx(2 * cheap.side_rate(1000.0))


def test_cost_model_rejects_non_finite_negative_and_invalid_price_inputs():
    invalid_models = (
        {"spread_bps": -0.1},
        {"slippage_bps": np.nan},
        {"commission_usd_per_lot_side": np.inf},
        {"financing_bps_per_day": -0.1},
        {"multiplier": -1.0},
        {"spread_usd_per_oz": np.inf},
        {"slippage_usd_per_oz_side": -0.1},
    )
    for values in invalid_models:
        with pytest.raises(ValueError):
            E.CostModel(**values)
    for price in (0.0, -1.0, np.nan, np.inf):
        with pytest.raises(ValueError, match="fill price"):
            E.CostModel().side_rate(price)
    with pytest.raises(ValueError):
        E.CostModel().scaled(-1.0)


def test_run_plan_refuses_invalid_risk_or_ohlc_inputs():
    bars = _walk(10)
    plan = _plan_at(bars, 2)
    for equity in (0.0, -1.0, np.nan, np.inf):
        with pytest.raises(ValueError, match="initial_equity"):
            E.run_plan(bars, plan, 0, len(bars), ZERO_COST, initial_equity=equity)
    with pytest.raises(ValueError, match="no leverage"):
        E.run_plan(bars, plan, 0, len(bars), ZERO_COST, cap=1.01)
    malformed = bars.copy()
    malformed.iloc[4, malformed.columns.get_loc("low")] = malformed["high"].iloc[4] + 1.0
    with pytest.raises(ValueError, match="OHLC ranges"):
        E.run_plan(malformed, _plan_at(malformed, 2), 0, len(malformed), ZERO_COST)
    bad_target = np.full(len(bars), np.nan)
    bad_target[2] = 2.0
    bad_plan = G._plan(bars, "bad", {}, bad_target, np.ones(len(bars)), np.full(len(bars), np.nan))
    with pytest.raises(ValueError, match="targets must be"):
        E.run_plan(bars, bad_plan, 0, len(bars), ZERO_COST)


def test_financing_is_time_prorated_and_includes_calendar_gaps():
    costs = E.CostModel(
        spread_bps=0.0,
        slippage_bps=0.0,
        commission_usd_per_lot_side=0.0,
        financing_bps_per_day=24.0,
        basis="ASSUMED_TEST",
    )
    # Four 15-minute holding intervals equal one hour: 24 bps/day on $5,000
    # is $12/day, hence $0.50 for one hour (not 96x the daily rate).
    idx = pd.date_range("2024-01-01", periods=7, freq="15min")
    flat = np.full(len(idx), 100.0)
    bars = pd.DataFrame({"open": flat, "high": flat, "low": flat, "close": flat}, index=idx)
    target = np.full(len(idx), np.nan)
    target[0], target[4] = 1.0, 0.0
    size = np.full(len(idx), np.nan)
    size[0] = 0.5
    plan = G._plan(bars, "carry", {}, target, size, np.full(len(idx), np.nan))
    intraday = E.run_plan(bars, plan, 0, len(bars), costs)
    assert intraday.financing_usd == pytest.approx(0.5)
    assert intraday.net_usd == pytest.approx(-intraday.financing_usd)

    # Friday-to-Monday is three calendar days in this continuous-rate model;
    # this is not a broker-specific weekday/triple-swap convention.
    daily_idx = pd.DatetimeIndex(["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])
    daily = pd.DataFrame(
        {"open": flat[:4], "high": flat[:4], "low": flat[:4], "close": flat[:4]}, index=daily_idx
    )
    daily_target = np.full(4, np.nan)
    daily_target[0], daily_target[1] = 1.0, 0.0
    daily_size = np.full(4, np.nan)
    daily_size[0] = 0.5
    daily_plan = G._plan(daily, "carry", {}, daily_target, daily_size, np.full(4, np.nan))
    weekend = E.run_plan(daily, daily_plan, 0, len(daily), costs)
    assert weekend.financing_usd == pytest.approx(36.0)  # $12/day x three calendar days

    # The terminal estimate uses only intervals inside this run window. Large
    # gaps after its end must not leak into the final in-window carry charge.
    partial_idx = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-12", "2024-01-22"])
    partial = pd.DataFrame(
        {"open": flat[:4], "high": flat[:4], "low": flat[:4], "close": flat[:4]}, index=partial_idx
    )
    partial_target = np.full(4, np.nan)
    partial_target[0] = 1.0
    partial_size = np.full(4, np.nan)
    partial_size[0] = 0.5
    partial_plan = G._plan(partial, "carry_window", {}, partial_target, partial_size, np.full(4, np.nan))
    windowed = E.run_plan(partial, partial_plan, 0, 2, costs)
    assert windowed.financing_usd == pytest.approx(12.0)  # one in-window day, not a future ten-day gap


# ----------------------------------------------------------------------- statistics


def test_holm_is_monotone_and_capped():
    adj = ST.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})
    assert adj["a"] == pytest.approx(0.04)
    assert adj["d"] == pytest.approx(0.5)
    assert all(v <= 1.0 for v in adj.values())
    assert adj["a"] <= adj["c"] <= adj["b"] <= adj["d"]


def test_max_drawdown_and_sharpe_edge_cases():
    assert ST.max_drawdown(np.array([100.0, 120.0, 90.0, 110.0])) == pytest.approx(-0.25)
    assert ST.sharpe(np.zeros(50)) == 0.0


def test_bootstrap_p_value_is_not_significant_for_pure_noise():
    rng = np.random.default_rng(0)
    p = ST.mean_p_value_one_sided(rng.normal(0.0, 0.01, 1500), n_boot=500)
    assert p > 0.05


def test_deflated_sharpe_decreases_with_more_trials():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0008, 0.01, 2000)
    few = ST.deflated_sharpe(r, num_trials=1)["dsr"]
    many = ST.deflated_sharpe(r, num_trials=26)["dsr"]
    assert many < few


# ----------------------------------------------------------------------- protocol


def test_protocol_is_internally_consistent():
    cids = [c.cid for c in P.CANDIDATES]
    assert len(cids) == len(set(cids)) == P.N_TRIALS
    assert set(P.FAMILY_GROUPS) == {c.group for c in P.CANDIDATES if c.role == "CANDIDATE"}
    assert [c.cid for c in P.CANDIDATES if c.role == "CONTROL"] == ["bollinger_20_2_control"]
    assert pd.Timestamp(P.DEV_END) < pd.Timestamp(P.HOLDOUT_START) <= pd.Timestamp(P.RESEARCH_END)
    assert P.COST_BASE.basis == "ASSUMED"
    assert max(P.WF_TEST_YEARS) < 2020  # walk-forward never touches the holdout years


def test_cost_stress_multipliers_are_at_least_base():
    assert min(P.COST_STRESS_MULTIPLIERS) >= 1.0


def test_research_end_precedes_partial_months():
    assert P.RESEARCH_END == "2025-02-28"


# ----------------------------------------------------------------------- provenance


def test_processed_files_match_recorded_hashes_when_present():
    evidence = REPO / "data" / "evidence" / "longhistory" / "data_quality.json"
    processed = REPO / "data" / "raw" / "longhistory" / "processed"
    if not evidence.is_file() or not processed.is_dir():
        pytest.skip("long-history raw inputs not built in this checkout")
    record = json.loads(evidence.read_text(encoding="utf-8"))
    for name, meta in record["processed_files"].items():
        path = processed / name
        if not path.is_file():
            pytest.skip(f"{name} not present")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == meta["sha256"], name


def test_buy_and_hold_matches_closed_form_at_zero_cost():
    from qts.research.longhistory import runner as R

    df = _walk(120, seed=6)
    start, end = df.index[30].strftime("%Y-%m-%d"), df.index[100].strftime("%Y-%m-%d")
    run = R.buy_and_hold(df, start, end, ZERO_COST)
    expected = P.INITIAL_EQUITY * (df["close"].iloc[100] / df["open"].iloc[30])
    assert run.final_equity == pytest.approx(expected, rel=1e-12)
    assert len(run.trades) == 1


def test_server_clock_eu_dst_switches_in_late_october_before_us_dst():
    # On 2025-10-28, EU DST has ended (ended 2025-10-26 -> UTC+2), whereas US DST
    # is still active until 2025-11-02 (UTC+3).
    stamps = pd.DatetimeIndex(["2025-07-01 12:00", "2025-10-28 12:00", "2025-11-10 12:00"])
    utc_eu = S.server_gmt23_eu_dst_to_utc(stamps)
    utc_us = S.server_gmt23_to_utc(stamps)
    assert list(utc_eu) == [
        pd.Timestamp("2025-07-01 09:00"),
        pd.Timestamp("2025-10-28 10:00"),
        pd.Timestamp("2025-11-10 10:00"),
    ]
    assert list(utc_us) == [
        pd.Timestamp("2025-07-01 09:00"),
        pd.Timestamp("2025-10-28 09:00"),
        pd.Timestamp("2025-11-10 10:00"),
    ]
    frame = _ohlc(stamps, np.array([2500.0, 2600.0, 2700.0]))
    out = S.to_utc(frame, "server_gmt23_eu_dst")
    assert list(out.index) == list(utc_eu)


def test_bar_integrity_diagnostics_flags_non_integer_volumes_and_zero_weekend_gaps():
    idx = pd.DatetimeIndex(
        [
            "2026-03-27 20:30",
            "2026-03-27 20:45",
            "2026-03-29 22:00",  # > 24h weekend gap
            "2026-03-29 22:15",
        ]
    )
    frame = pd.DataFrame(
        {
            "open": [4500.0, 4501.0, 4502.0, 4505.0],
            "high": [4502.0, 4503.0, 4506.0, 4507.0],
            "low": [4499.0, 4500.0, 4501.0, 4503.0],
            "close": [4501.0, 4502.0, 4505.0, 4506.0],
            "volume": [100.0, 200.0, 19649.951518, 150.0],
        },
        index=idx,
    )
    diag = S.bar_integrity_diagnostics(frame)
    assert diag["rows"] == 4
    assert diag["non_integer_volume_bars"] == 1
    assert diag["open_equals_prev_close_share"] == pytest.approx(1.0)
    assert diag["weekend_reopen_bars"] == 1
    assert diag["weekend_reopen_zero_gap_bars"] == 1


def test_cost_model_from_price_units_and_scaling():
    cm = E.CostModel.from_price_units(
        spread_usd_per_oz=0.24,
        slippage_usd_per_oz_side=0.10,
        commission_usd_per_lot_side=7.0,
        basis="MIXED_MEASURED_SPREAD_ASSUMED_SLIPPAGE",
    )
    # At $2,000/oz: half_spread = $0.12 / 2000 = 0.6 bps; slip = $0.10 / 2000 = 0.5 bps;
    # commission = $7 / (100 * 2000) = 0.35 bps -> side_rate = 1.45 bps (2.90 bps round-turn).
    assert cm.side_rate(2000.0) == pytest.approx(1.45e-4, rel=1e-12)
    scaled = cm.scaled(2.0)
    assert scaled.side_rate(2000.0) == pytest.approx(2.90e-4, rel=1e-12)
    desc = cm.describe()
    assert desc["spread_usd_per_oz"] == 0.24
    assert desc["slippage_usd_per_oz_side"] == 0.10
    assert desc["round_turn_bps_at_2000"] == pytest.approx(2.9, rel=1e-6)
    with pytest.raises(ValueError, match="non-negative"):
        E.CostModel.from_price_units(spread_usd_per_oz=-0.01, slippage_usd_per_oz_side=0.0)

