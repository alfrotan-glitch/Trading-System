"""Unit tests for the M15 intraday extension of the long-history XAUUSD research.

Synthetic series only, so they run in the fast suite. The real-data complete-day
loader is exercised only when the gitignored processed inputs are present.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory import checks as C
from qts.research.longhistory import daily as D
from qts.research.longhistory import engine as E
from qts.research.longhistory import intraday_protocol as I
from qts.research.longhistory import intraday_signals as IS
from qts.research.longhistory import protocol as P
from qts.research.longhistory import runner as R
from qts.research.longhistory import signals as G
from qts.research.longhistory import stats as ST

REPO = Path(__file__).resolve().parents[2]
ZERO_COST = E.CostModel(spread_bps=0.0, slippage_bps=0.0, commission_usd_per_lot_side=0.0, basis="TEST")


def _m15(days: int, seed: int = 11, start: str = "2015-03-02 22:00") -> pd.DataFrame:
    """Continuous 15-minute bars, 96 per calendar day, random walk with a daily drift."""
    rng = np.random.default_rng(seed)
    n = days * 96
    idx = pd.date_range(start, periods=n, freq="15min")
    close = 1500.0 * np.exp(np.cumsum(rng.normal(0.00002, 0.0015, n)))
    opens = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0.4, 0.2, n))
    high = np.maximum(opens, close) + spread
    low = np.minimum(opens, close) - spread
    return pd.DataFrame({"open": opens, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


# ----------------------------------------------------------------- calendar and protocol


def test_intraday_protocol_is_consistent_with_daily_and_counts_trials():
    assert I.PERIODS_PER_YEAR == I.BARS_PER_DAY * I.TRADING_DAYS_PER_YEAR == 23184
    assert I.N_TRIALS == P.N_TRIALS + I.N_TRIALS_THIS_CYCLE == 26 + 14
    assert I.N_TRIALS_THIS_CYCLE == len(I.CANDIDATES) == 14
    # shared experiment definition must not drift from the daily protocol
    assert (I.HOLDOUT_START, I.DEV_END, I.RESEARCH_END) == (P.HOLDOUT_START, P.DEV_END, P.RESEARCH_END)
    assert I.COST_BASE == P.COST_BASE and I.COST_BASE.basis == "ASSUMED"
    assert (I.GATE_DSR_MIN, I.GATE_HOLM_ALPHA, I.MIN_TRADES_OOS_GATE) == (
        P.GATE_DSR_MIN,
        P.GATE_HOLM_ALPHA,
        P.MIN_TRADES_OOS_GATE,
    )
    cids = [c.cid for c in I.CANDIDATES]
    assert len(set(cids)) == len(cids)
    assert [c.cid for c in I.CANDIDATES if c.role == "CONTROL"] == ["bollinger_20_2_control"]
    assert set(I.FAMILY_GROUPS) == {"ma_cross", "donchian", "volatility_expansion", "session_breakout"}


def test_daily_protocol_defaults_still_mean_one_bar_per_day():
    assert P.PERIODS_PER_YEAR == 252
    assert P.VOL_BARS == G.VOL_WINDOW == 60
    assert P.REGIME_TREND_BARS == P.REGIME_MIN_BARS == 252


def test_sharpe_and_cagr_default_to_daily_and_scale_with_periods():
    r = np.random.default_rng(0).normal(0.0005, 0.01, 500)
    assert ST.sharpe(r) == pytest.approx(ST.sharpe(r, 252))
    assert ST.sharpe(r, 23184) == pytest.approx(ST.sharpe(r, 252) * np.sqrt(23184 / 252))
    assert ST.cagr(100.0, 110.0, 252) == pytest.approx(0.1)
    assert ST.cagr(100.0, 110.0, 23184, 23184) == pytest.approx(0.1)


def test_window_includes_every_bar_stamped_on_the_end_day():
    bars = _m15(4)
    i0, i1 = R.window_positions(bars, "2015-03-03", "2015-03-03")
    stamps = bars.index[i0:i1]
    assert stamps.min().date() == pd.Timestamp("2015-03-03").date()
    assert stamps.max() == pd.Timestamp("2015-03-03 23:45")
    assert i1 - i0 == 96
    # daily (midnight-stamped) index: identical to the original right-side search
    daily = pd.DatetimeIndex(pd.date_range("2010-01-01", periods=400, freq="B"))
    frame = pd.DataFrame({"close": 1.0}, index=daily)
    a0, a1 = R.window_positions(frame, "2010-03-01", "2010-06-30")
    assert a0 == int(daily.searchsorted(pd.Timestamp("2010-03-01"), side="left"))
    assert a1 == int(daily.searchsorted(pd.Timestamp("2010-06-30"), side="right"))


def test_regime_attribution_vectorised_matches_per_day_lookup():
    idx = pd.date_range("2020-01-01", periods=6, freq="D")
    labels = pd.Series(["UP_HIVOL", None, "DOWN_LOWVOL", "UP_HIVOL", "UP_LOWVOL", None], index=idx, dtype=object)
    pnl = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    out = R.regime_attribution([(idx, pnl)], labels)
    assert out["UP_HIVOL"] == {"days": 2, "net_usd": 5.0}
    assert out["DOWN_LOWVOL"] == {"days": 1, "net_usd": 3.0}
    assert out["UP_LOWVOL"] == {"days": 1, "net_usd": 5.0}
    assert out["DOWN_HIVOL"] == {"days": 0, "net_usd": 0.0}


# ----------------------------------------------------------------- session breakout


def _ranged_day_frame() -> pd.DataFrame:
    """One trading day: Asian range 1990-2010, then a breakout above 2010 at 08:00."""
    idx = pd.date_range("2015-03-02 22:00", periods=96, freq="15min")  # trading day 2015-03-03
    close = np.full(96, 2000.0)
    high = np.full(96, 2010.0)
    low = np.full(96, 1990.0)
    opens = np.full(96, 2000.0)
    frame = pd.DataFrame({"open": opens, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)
    # bars index: 22:00 is position 0, so 00:00 is position 8, 07:00 is 36, 08:00 is 40
    frame.loc[idx[40], ["close", "high"]] = [2015.0, 2016.0]  # close above range high at 08:00
    return frame


def test_session_breakout_enters_on_first_close_outside_asian_range_only():
    frame = _ranged_day_frame()
    plan = IS.session_breakout(frame, buffer_atr=0.0)
    assert plan.family == "session_breakout"
    tgt = plan.target
    # no state before the range is complete (ATR warm-up is NaN) or before 07:00 decisions
    assert np.all(tgt[:36] != 1.0) and np.all(tgt[:36] != -1.0)
    # the entry decision is the 08:00 bar (position 40), executed next open
    assert tgt[40] == 1.0 and tgt[39] != 1.0
    # stop at the opposite range boundary: close - range_low
    assert plan.stop_dist[40] == pytest.approx(2015.0 - 1990.0)
    # persists through the session; position 84 is 19:00 (22:00 + 21 h), the first flat decision
    assert tgt[83] == 1.0  # 18:45 still held
    assert tgt[84] == 0.0


def test_session_breakout_is_flat_outside_entry_hours_and_one_entry_per_session():
    bars = _m15(20, seed=5)
    plan = IS.session_breakout(bars, buffer_atr=0.0)
    hour = np.asarray(bars.index.hour)
    t = plan.target
    live = np.isfinite(t)
    # any non-zero state is held only inside 07:00 <= hour < 19:00 decision hours
    active = live & (t != 0.0)
    assert np.all((hour[active] >= 7) & (hour[active] < 19))
    # at most one entry (0 -> +/-1 transition) per trading day
    days = np.asarray(D.trading_day_label(pd.DatetimeIndex(bars.index)))
    entries = np.zeros(len(bars), dtype=bool)
    prev = 0.0
    for k in range(len(bars)):
        if np.isfinite(t[k]):
            entries[k] = t[k] != 0.0 and prev == 0.0
            prev = t[k]
    per_day = pd.Series(entries.astype(int)).groupby(days).sum()
    assert per_day.max() <= 1


def test_session_breakout_is_causal_under_truncation_at_every_session_phase():
    bars = _m15(12, seed=21)
    # cuts at every hour of the first three trading days, including the 07:00 range completion
    cuts = list(range(1, 3 * 96, 4))
    rep = C.truncation_check(lambda d: IS.session_breakout(d, buffer_atr=0.25), bars, cuts)
    assert rep.passed, rep.mismatches[:3]
    rep0 = C.truncation_check(lambda d: IS.session_breakout(d, buffer_atr=0.0), bars, cuts)
    assert rep0.passed, rep0.mismatches[:3]


def test_intraday_candidates_all_causal_on_a_random_walk():
    bars = _m15(30, seed=8)
    cuts = [len(bars) // 3, len(bars) // 2 + 17, len(bars) - 200]
    for cand in I.CANDIDATES:
        rep = C.truncation_check(cand.builder, bars, cuts)
        assert rep.passed, (cand.cid, rep.mismatches[:2])


# ----------------------------------------------------------------- engine on intraday bars


def test_intraday_ledger_reconciles_to_equity_under_costs():
    bars = _m15(60, seed=13)
    costs = I.COST_BASE
    for cid in ["session_brk_b0", "ma_16_64_atr3", "donchian_96_48_atr2"]:
        plan = I.candidate_by_id(cid).builder(bars)
        run = E.run_plan(bars, plan, 0, len(bars), costs, initial_equity=10_000.0)
        ident = (run.final_equity - run.initial_equity) - sum(t.net_usd for t in run.trades)
        assert abs(ident) < 1e-6, (cid, ident)


# ----------------------------------------------------------------- real data (skips when absent)


def test_complete_day_loader_keeps_only_complete_trading_days():
    sys.path.insert(0, str(REPO / "scripts"))
    import run_longhistory_intraday as X

    if not X.RESEARCH_FILE.exists():
        pytest.skip("raw long-history inputs not present (gitignored; fetch with the pinned script)")
    df = X.load_complete_m15(X.RESEARCH_FILE, last_label=I.RESEARCH_END)
    labels = D.trading_day_label(pd.DatetimeIndex(df.index))
    counts = pd.Series(1, index=labels).groupby(level=0).sum()
    assert counts.min() >= D.DEFAULT_MIN_BARS
    assert pd.Timestamp(labels.max()) <= pd.Timestamp(I.RESEARCH_END)
    per_complete_day = counts.median()
    assert per_complete_day == I.BARS_PER_DAY
