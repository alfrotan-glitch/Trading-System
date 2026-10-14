"""Unit tests for the calendar-seasonality (session / weekday / NFP) extension.

Synthetic series only, so they run in the fast suite. Frozen knobs are
overridden with small warm-ups where the test needs decisions to fire; the
protocol-level test pins the frozen values themselves.

Preregistration: ``docs/research/preregistration_longhistory_seasonal_2026-10-14.md``
(``LH-XAUUSD-SES-2026-10-14``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory import checks as C
from qts.research.longhistory import daily as D
from qts.research.longhistory import intraday_protocol as I
from qts.research.longhistory import protocol as P
from qts.research.longhistory import runner as R
from qts.research.longhistory import seasonal_protocol as SES
from qts.research.longhistory import seasonal_signals as SS

# ------------------------------------------------------------------ fixtures


def _frame(idx: pd.DatetimeIndex, ret_per_bar: np.ndarray) -> pd.DataFrame:
    """OHLCV bars with a per-bar simple return applied to the close."""
    n = len(idx)
    close = 1000.0 * np.cumprod(1.0 + ret_per_bar)
    opens = np.concatenate([[1000.0], close[:-1]])
    spread = np.full(n, 0.2)
    high = np.maximum(opens, close) + spread
    low = np.minimum(opens, close) - spread
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": 1.0},
        index=idx,
    )


def _session_frame(days: int = 14, start: str = "2005-01-03 00:00") -> pd.DataFrame:
    """Continuous M15 grid, uniform positive drift: every window occurrence > 0."""
    idx = pd.date_range(start, periods=days * 96, freq="15min")
    return _frame(idx, np.full(len(idx), 0.0005))


def _weekday_frame(weeks: int = 7, start: str = "2005-01-02 22:00") -> pd.DataFrame:
    """FX week: Sun 22:00 -> Fri 21:45, no weekend bars. Returns by label weekday:
    Friday-labelled days drift up, Mon-Thu down."""
    idx = pd.date_range(start, periods=weeks * 7 * 96, freq="15min")
    keep = ~(
        (idx.dayofweek == 5)
        | ((idx.dayofweek == 6) & (idx.hour < 22))
        | ((idx.dayofweek == 4) & (idx.hour >= 22))
    )
    idx = idx[keep]
    labels = D.trading_day_label(idx)
    wd = pd.DatetimeIndex(labels).dayofweek.to_numpy()
    r = np.where(wd == 4, 0.001, -0.0003)  # Friday up, Mon-Thu down
    return _frame(idx, r)


def _nfp_frame(year_end: int = 2008) -> pd.DataFrame:
    """Short contiguous bursts around each NFP release; reaction bars rally +0.1%."""
    bursts: list[pd.DataFrame] = []
    for rel in SS.nfp_release_index(2005, year_end):
        idx = pd.date_range(
            rel - pd.Timedelta(minutes=45), rel + pd.Timedelta(minutes=90), freq="15min"
        )
        r = np.where(idx >= rel, 0.001, 0.0)
        bursts.append(_frame(idx, r))
    return pd.concat(bursts).sort_index()


def _equal_with_nan(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a == b) | (np.isnan(a) & np.isnan(b))


# ------------------------------------------------------------------- session


def test_session_chain_decision_hold_end_and_flat():
    df = _session_frame()
    plan = SS.session_drift(df, strongest=False, t_floor=0.0, min_occ=3)
    idx = pd.DatetimeIndex(df.index)
    at = lambda ts: int(idx.get_loc(pd.Timestamp(ts)))  # noqa: E731

    # warm-up: decisions stay flat until 3 completed occurrences exist
    assert plan.target[at("2005-01-03 06:45")] == 0.0  # europe, no history yet
    # mature day: every decision bar fires the direction of the upcoming window
    assert plan.target[at("2005-01-06 06:45")] == 1.0  # europe decision
    assert np.isnan(plan.target[at("2005-01-06 07:00")])  # europe hold
    assert np.isnan(plan.target[at("2005-01-06 10:30")])
    assert plan.target[at("2005-01-06 12:45")] == 1.0  # us decision (last europe bar)
    assert np.isnan(plan.target[at("2005-01-06 13:00")])  # us hold
    assert plan.target[at("2005-01-06 20:45")] == 0.0  # scheduled window end -> flat
    assert plan.target[at("2005-01-06 21:00")] == 0.0  # halt/rollover hours
    assert plan.target[at("2005-01-06 23:30")] == 0.0
    assert plan.target[at("2005-01-06 23:45")] == 1.0  # asia decision for next day
    assert np.isnan(plan.target[at("2005-01-06 00:00")])  # asia hold
    # targets are only ever position states or NaN
    vals = set(np.unique(plan.target[~np.isnan(plan.target)]))
    assert vals <= {-1.0, 0.0, 1.0}


def test_session_strongest_smoke_and_params():
    df = _session_frame()
    plan = SS.session_drift(df, strongest=True, t_floor=0.0, min_occ=3)
    assert len(plan.target) == len(df)
    assert plan.params["strongest"] is True
    assert plan.params["windows_utc"] == "asia:0-7,europe:7-13,us:13-21"


def test_session_placebo_control_chain():
    df = _session_frame()
    plan = SS.session_drift(
        df, strongest=False, t_floor=0.0, min_occ=3, windows=SS.PLACEBO_WINDOWS
    )
    idx = pd.DatetimeIndex(df.index)
    at = lambda ts: int(idx.get_loc(pd.Timestamp(ts)))  # noqa: E731

    assert plan.target[at("2005-01-06 02:45")] == 1.0  # decision for [03,10)
    assert np.isnan(plan.target[at("2005-01-06 03:00")])
    # 09:45 is both the end of [03,10) and the decision bar for [10,16);
    # the decision wins so adjacent placebo windows rotate at the boundary
    assert plan.target[at("2005-01-06 09:45")] == 1.0
    assert np.isnan(plan.target[at("2005-01-06 10:00")])
    assert plan.target[at("2005-01-06 20:45")] == 0.0  # [16,21) end
    assert plan.target[at("2005-01-06 00:00")] == 0.0  # outside placebo windows


def test_session_truncation_is_prefix_identical():
    df = _session_frame()
    cuts = [int(0.4 * len(df)), int(0.63 * len(df))]
    rep = C.truncation_check(
        lambda d: SS.session_drift(d, strongest=False, t_floor=0.0, min_occ=3),
        df,
        cuts,
    )
    assert rep.passed, rep.as_dict()


def test_session_truncation_with_strongest_and_placebo():
    df = _session_frame()
    cuts = [int(0.5 * len(df))]
    for build in (
        lambda d: SS.session_drift(d, strongest=True, t_floor=0.0, min_occ=3),
        lambda d: SS.session_drift(
            d, strongest=False, t_floor=0.0, min_occ=3, windows=SS.PLACEBO_WINDOWS
        ),
    ):
        rep = C.truncation_check(build, df, cuts)
        assert rep.passed, rep.as_dict()


def test_session_gap_first_bar_invalidates_only_that_occurrence():
    """If a window's first bar is missing on one day, that day contributes no
    occurrence; every other day's statistics (and decisions) are unchanged."""
    df = _session_frame()
    idx = pd.DatetimeIndex(df.index)
    cut_ts = pd.Timestamp("2005-01-05 00:00")  # drop Asia's first bar on Jan 5
    gapped = df.drop(index=[cut_ts])
    w_full = SS._session_occurrences(idx, df, SS.SESSION_WINDOWS)
    idx_g = pd.DatetimeIndex(gapped.index)
    w_gap = SS._session_occurrences(idx_g, gapped, SS.SESSION_WINDOWS)
    n_full, n_gap = len(w_full["asia"]), len(w_gap["asia"])
    # the table itself drops the occurrence only when the window start is missing
    keys_full = list(w_full["asia"].keys)
    keys_gap = list(w_gap["asia"].keys)
    assert pd.Timestamp(cut_ts) in [pd.Timestamp(k) for k in keys_full]
    assert pd.Timestamp(cut_ts) not in [pd.Timestamp(k) for k in keys_gap]
    assert n_gap == n_full - 1
    # decisions after the gap still fire (prefix statistics)
    plan_gap = SS.session_drift(gapped, strongest=False, t_floor=0.0, min_occ=3)
    pos = int(pd.DatetimeIndex(gapped.index).get_loc(pd.Timestamp("2005-01-06 06:45")))
    assert plan_gap.target[pos] == 1.0


# ------------------------------------------------------------------- weekday


def test_weekday_decisions_labels_and_rebalance_flags():
    df = _weekday_frame()
    plan = SS.weekday_drift(df, permuted=False, t_floor=0.0, min_occ=2)
    idx = pd.DatetimeIndex(df.index)
    labels = np.asarray(D.trading_day_label(idx))

    # decisions fire exactly at label changes; every other bar is a hold
    decision = np.zeros(len(idx), dtype=bool)
    decision[:-1] = labels[:-1] != labels[1:]
    assert np.all(np.isnan(plan.target[~decision]))
    assert np.all(plan.rebalance[~decision] == 0)
    assert np.all(plan.rebalance[decision] == 1)
    assert np.isnan(plan.target[-1]) and plan.rebalance[-1] == 0

    at = lambda ts: int(idx.get_loc(pd.Timestamp(ts)))  # noqa: E731
    # mature decisions: Friday-labelled days drift up, Mon-Thu down
    assert plan.target[at("2005-01-20 21:45")] == 1.0  # decides Friday
    assert plan.target[at("2005-01-17 21:45")] == -1.0  # decides Tuesday
    # the weekly gap: Friday's close is the last bar before Sunday 22:00
    # (labelled Monday), so Monday trading days ARE decided and traded
    assert plan.target[at("2005-01-21 21:45")] == -1.0  # decides Monday
    # mid-day bars never decide
    assert np.isnan(plan.target[at("2005-01-18 10:00")])
    assert np.isnan(plan.target[at("2005-01-19 22:00")])


def test_weekday_permuted_control_rotates_the_anchor():
    df = _weekday_frame()
    aligned = SS.weekday_drift(df, permuted=False, t_floor=0.0, min_occ=2)
    perm = SS.weekday_drift(df, permuted=True, t_floor=0.0, min_occ=2)
    idx = pd.DatetimeIndex(df.index)
    i = int(idx.get_loc(pd.Timestamp("2005-01-20 21:45")))  # decides Friday
    assert aligned.target[i] == 1.0
    # control takes Monday's statistics for the Friday decision -> Monday is down
    assert perm.target[i] == -1.0
    assert perm.params["permuted_control"] is True
    assert aligned.params["permuted_control"] is False


def test_weekday_truncation_is_prefix_identical():
    df = _weekday_frame()
    cuts = [int(0.45 * len(df)), int(0.7 * len(df))]
    rep = C.truncation_check(
        lambda d: SS.weekday_drift(d, permuted=False, t_floor=0.0, min_occ=2),
        df,
        cuts,
    )
    assert rep.passed, rep.as_dict()
    rep_p = C.truncation_check(
        lambda d: SS.weekday_drift(d, permuted=True, t_floor=0.0, min_occ=2),
        df,
        cuts,
    )
    assert rep_p.passed, rep_p.as_dict()


def test_weekday_occurrence_is_open_to_open_across_the_weekend():
    df = _weekday_frame()
    idx = pd.DatetimeIndex(df.index)
    labels = D.trading_day_label(idx)
    opens = df["open"].to_numpy()
    tables = SS._weekday_expanding(idx, labels, opens)
    first: dict[pd.Timestamp, int] = {}
    for i, lab in enumerate(labels):
        first.setdefault(pd.Timestamp(lab), i)
    days = sorted(first)
    # Friday's return = open(first Monday bar) / open(first Friday bar) - 1
    fri_days = [d for d in days if d.dayofweek == 4]
    assert fri_days, "expected Friday trading-day labels"
    fri = tables[4]
    keys = [pd.Timestamp(k) for k in fri.keys]
    assert fri_days[0] in keys
    pos_f = keys.index(fri_days[0])
    nxt = next(d for d in days if d > fri_days[0])
    expected = opens[first[nxt]] / opens[first[fri_days[0]]] - 1.0
    assert fri.values[pos_f] == pytest.approx(expected)


# ----------------------------------------------------------------------- nfp


def test_nfp_lag_one_decision_and_hold_shape():
    df = _nfp_frame()
    plan = SS.nfp_drift(df, hold_bars=4, t_floor=0.0, min_events=2)
    idx = pd.DatetimeIndex(df.index)
    releases = [r for r in SS.nfp_release_index(2005, 2008) if r in idx]
    assert len(releases) >= 3
    pos = {r: int(idx.get_loc(r)) for r in releases}

    # lag-one: event 0 has no history; event 1 has one occurrence (< min_events);
    # event 2 uses events 0..1 and fires
    assert plan.target[pos[releases[0]]] == 0.0
    assert plan.target[pos[releases[1]]] == 0.0
    r2 = pos[releases[2]]
    assert plan.target[r2] == 1.0
    # hold shape: enter at R+1, hold 4 bars, exit decision at R+4
    assert np.isnan(plan.target[r2 + 1])
    assert np.isnan(plan.target[r2 + 2])
    assert np.isnan(plan.target[r2 + 3])
    assert plan.target[r2 + 4] == 0.0
    # every later event also fires (all prior reactions were positive)
    fired = int(np.nansum(plan.target == 1.0))
    assert fired == len(releases) - 2
    # non-event bars stay explicitly flat
    assert plan.target[0] == 0.0
    assert plan.params["hold_bars"] == 4


def test_nfp_missing_release_bar_skips_event():
    df = _nfp_frame()
    idx = pd.DatetimeIndex(df.index)
    present = [r for r in SS.nfp_release_index(2005, 2008) if r in idx]
    drop = present[2]
    gapped = df.drop(index=[drop])
    # min_events=3: with the third release absent, event 3 has only 2 valid
    # earlier occurrences, so its decision must stay flat (lag-one, no invention)
    plan = SS.nfp_drift(gapped, hold_bars=4, t_floor=0.0, min_events=3)
    assert plan.target[0] == 0.0
    gidx = pd.DatetimeIndex(gapped.index)
    ev3 = [r for r in present if r != drop][2]  # fourth release overall
    assert plan.target[int(gidx.get_loc(ev3))] == 0.0
    ev4 = [r for r in present if r != drop][3]
    assert plan.target[int(gidx.get_loc(ev4))] == 1.0
    fired = int(np.nansum(plan.target == 1.0))
    assert fired == len(present) - 4  # ev0, ev1, ev3 flat; ev2 has no bar


def test_nfp_noncontiguous_window_contributes_no_occurrence():
    df = _nfp_frame()
    idx = pd.DatetimeIndex(df.index)
    present = [r for r in SS.nfp_release_index(2005, 2008) if r in idx]
    third = present[2]
    # remove one bar from the third event's hold window (release bar stays)
    gapped = df.drop(index=[third + pd.Timedelta(minutes=15)])
    # min_events=3: decision at event 3 reads occurrences {0, 1} only (event 2's
    # window is broken, so it contributes no occurrence) -> flat; the aligned
    # full frame would have n=3 and fire.
    plan = SS.nfp_drift(gapped, hold_bars=4, t_floor=0.0, min_events=3)
    gidx = pd.DatetimeIndex(gapped.index)
    assert plan.target[int(gidx.get_loc(third))] == 0.0  # n=2 < 3 before the break
    ev3 = present[3]
    assert plan.target[int(gidx.get_loc(ev3))] == 0.0  # occurrence 2 invalid -> n stays 2
    ev4 = present[4]
    assert plan.target[int(gidx.get_loc(ev4))] == 1.0  # n=3 by then
    full = SS.nfp_drift(df, hold_bars=4, t_floor=0.0, min_events=3)
    assert full.target[int(idx.get_loc(ev3))] == 1.0  # contrast: full frame fires
    fired = int(np.nansum(plan.target == 1.0))
    assert fired == len(present) - 4


def test_nfp_truncation_is_prefix_identical():
    df = _nfp_frame()
    cuts = [int(0.35 * len(df)), int(0.6 * len(df))]
    rep = C.truncation_check(
        lambda d: SS.nfp_drift(d, hold_bars=4, t_floor=0.0, min_events=2), df, cuts
    )
    assert rep.passed, rep.as_dict()
    rep16 = C.truncation_check(
        lambda d: SS.nfp_drift(d, hold_bars=16, t_floor=0.0, min_events=2), df, cuts
    )
    assert rep16.passed, rep16.as_dict()


def test_nfp_release_index_uses_first_friday_et_dst():
    # Jan 2006: first Friday is Jan 6, 08:30 EST = 13:30 UTC
    assert pd.Timestamp("2006-01-06 13:30") in SS.nfp_release_index(2006, 2007)
    # Jul 2006: first Friday is Jul 7, 08:30 EDT = 12:30 UTC
    assert pd.Timestamp("2006-07-07 12:30") in SS.nfp_release_index(2006, 2007)


# ------------------------------------------------------------------- protocol


def test_seasonal_protocol_counts_groups_and_shares_parents():
    assert SES.PREREG_ID == "LH-XAUUSD-SES-2026-10-14"
    assert SES.N_TRIALS_THIS_CYCLE == len(SES.CANDIDATES) == 7
    assert SES.N_TRIALS == I.N_TRIALS + SES.N_TRIALS_THIS_CYCLE == 40 + 7 == 47
    assert SES.FAMILY_GROUPS == ("session_drift", "weekday_drift", "nfp_drift")
    assert set(SES.CONTROL_GROUPS) == {"weekday_drift_control", "session_drift_control"}
    assert [c.cid for c in SES.CANDIDATES if c.role == "CONTROL"] == [
        "wd_perm1_control",
        "sd_placebo_h3_control",
    ]
    cids = [c.cid for c in SES.CANDIDATES]
    assert len(set(cids)) == len(cids)
    assert [c.cid for c in SES.candidates_in("session_drift")] == ["sd_all", "sd_strongest"]
    assert [c.cid for c in SES.candidates_in("weekday_drift")] == ["wd_all"]
    assert [c.cid for c in SES.candidates_in("nfp_drift")] == ["nfp_h4", "nfp_h16"]
    # controls never enter selection
    for group in SES.FAMILY_GROUPS:
        assert all(c.role == "CANDIDATE" for c in SES.candidates_in(group))
    with pytest.raises(KeyError):
        SES.candidate_by_id("nope")
    # shared experiment definition must not drift from the parent protocols
    assert (SES.HOLDOUT_START, SES.DEV_END, SES.RESEARCH_END) == (
        P.HOLDOUT_START,
        P.DEV_END,
        P.RESEARCH_END,
    )
    assert SES.COST_BASE == P.COST_BASE and SES.COST_BASE.basis == "ASSUMED"
    assert (SES.GATE_DSR_MIN, SES.GATE_HOLM_ALPHA, SES.MIN_TRADES_OOS_GATE) == (
        P.GATE_DSR_MIN,
        P.GATE_HOLM_ALPHA,
        P.MIN_TRADES_OOS_GATE,
    )
    assert SES.PERIODS_PER_YEAR == I.PERIODS_PER_YEAR == 23184
    assert (SES.T_FLOOR, SES.MIN_OCCURRENCES, SES.MIN_NFP_EVENTS) == (2.0, 250, 48)
    assert SES.GATE_BREAK_EVEN_MIN == 2.0
    assert SES.SWAP_USD_PER_LOT_ROLLOVER == 3.5


def test_frozen_builders_emit_well_formed_plans():
    df = _session_frame(days=6)
    for cand in SES.CANDIDATES:
        plan = cand.builder(df)
        assert len(plan.target) == len(df)
        assert len(plan.size) == len(df)
        vals = set(np.unique(plan.target[~np.isnan(plan.target)]))
        assert vals <= {-1.0, 0.0, 1.0}
        assert plan.family in {
            "session_drift",
            "weekday_drift",
            "nfp_drift",
        }


# ---------------------------------------------------------------------- gates


def _fake_final_result(
    be_value: float, family_groups: tuple[str, ...] = SES.FAMILY_GROUPS
) -> tuple[dict, dict, pd.Series]:
    regime_keys = ["trend", "range", "high_vol", "low_vol"]
    groups: dict[str, dict] = {}
    wf_summary: dict[str, dict] = {}
    for g in family_groups:
        groups[g] = {
            "cid": f"{g}_cid",
            "base": {"net_usd": 1000.0, "sharpe": 1.5, "round_turns": 300},
            "stress": {"2x": {"net_usd": 100.0}},
            "regimes_holdout": {k: {"days": 5, "net_usd": 10.0} for k in regime_keys},
            "holm_adjusted_p": 0.01,
            "break_even_multiplier": {"value": be_value, "status": "TEST"},
        }
        wf_summary[g] = {
            "wf_sharpe": 1.0,
            "wf_positive_years": 7,
            "wf_regimes": {k: {"days": 50, "net_usd": 100.0} for k in regime_keys},
        }
    folds = [
        {"selection": {g: {"round_turns": 150, "cid": "x"} for g in family_groups}}
        for _ in range(10)
    ]
    result = {
        "holdout": {"groups": groups},
        "walk_forward": {"summary": wf_summary, "folds": folds},
    }
    combined = {g: np.full(500, 0.001) for g in family_groups}
    return result, combined, pd.Series(dtype=float)


def test_g8_gate_fails_below_threshold_and_passes_at_two_x():
    for be_value, should_fail in ((1.5, True), (2.5, False)):
        result, combined, labels = _fake_final_result(be_value)
        out = R.gates(result, combined, labels, "final", proto=SES)
        for g in SES.FAMILY_GROUPS:
            rec = out[g]
            assert "G8_break_even_multiplier_ge_min" in rec["checks"]
            assert ("G8_break_even_multiplier_ge_min" in rec["failed"]) is should_fail
            assert set(rec["checks"]) == set(rec["checks"])  # sanity
            # all other gates pass in the fixture
            others = [k for k in rec["failed"] if k != "G8_break_even_multiplier_ge_min"]
            assert others == []


def test_parent_protocols_do_not_gain_a_g8_gate():
    for proto in (I, P):
        result, combined, labels = _fake_final_result(1.0, proto.FAMILY_GROUPS)
        out = R.gates(result, combined, labels, "final", proto=proto)
        for g in proto.FAMILY_GROUPS:
            assert not any(k.startswith("G8") for k in out[g]["checks"])
            assert not any(k.startswith("G8") for k in out[g]["failed"])


def test_dev_stage_still_short_circuits_before_any_gate():
    result, combined, labels = _fake_final_result(0.0)
    out = R.gates(result, combined, labels, "dev", proto=SES)
    assert out["status"] == "NOT_EVALUATED_DEV_STAGE"
