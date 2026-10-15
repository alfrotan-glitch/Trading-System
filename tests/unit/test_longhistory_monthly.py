"""Unit tests for the monthly long-history XAUUSD extension.

Synthetic series only, so they run in the fast suite. The frozen protocol
values are pinned by the protocol-level tests; market evaluation has not run
at the time these tests were written (preregistration
``docs/research/preregistration_longhistory_monthly_2026-10-15.md``,
``LH-XAUUSD-MON-2026-10-15``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory import checks as C
from qts.research.longhistory import intraday_protocol as I
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import protocol as D
from qts.research.longhistory import reversal_protocol as RV
from qts.research.longhistory import runner as R
from qts.research.longhistory import seasonal_protocol as SES
from qts.research.longhistory.engine import CostModel, run_plan
from qts.research.longhistory.signals import Plan

# ------------------------------------------------------------------ fixtures


def _monthly_frame(
    n: int = 150,
    start: str = "2000-01-31",
    gold_ret: np.ndarray | None = None,
    usd_ret: np.ndarray | None = None,
    seed: int = 7,
) -> pd.DataFrame:
    """Month-end bars with open=high=low=close (the preregistered convention)."""
    idx = pd.date_range(start, periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    g = gold_ret if gold_ret is not None else rng.normal(0.004, 0.035, n)
    u = usd_ret if usd_ret is not None else rng.normal(0.000, 0.015, n)
    gold = 1000.0 * np.cumprod(1.0 + np.concatenate([[0.0], g[1:]]))
    usd = 1.0 * np.cumprod(1.0 + np.concatenate([[0.0], u[1:]]))
    return pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd},
        index=idx,
    )


# -------------------------------------------------------------------- signals


def test_signal_shapes_and_target_domain() -> None:
    df = _monthly_frame()
    for cand in MON.CANDIDATES:
        plan = cand.builder(df)
        assert len(plan.target) == len(df)
        assert len(plan.size) == len(df)
        finite = np.isfinite(plan.target)
        assert set(np.unique(plan.target[finite])) <= {-1.0, 0.0, 1.0}
        # The engine must never see a finite target with undefined size
        # (that would close a position it cannot re-enter).
        assert bool(np.isfinite(plan.size[finite]).all())
        assert bool((plan.size[np.isfinite(plan.size)] <= 1.0).all())
        assert bool((plan.size[np.isfinite(plan.size)] >= 0.0).all())


def test_truncation_causality_all_candidates() -> None:
    df = _monthly_frame(180)
    cuts = sorted({int(len(df) * f) for f in (0.25, 0.5, 0.75)})
    for cand in MON.CANDIDATES:
        rep = C.truncation_check(cand.builder, df, cuts)
        assert rep.passed, f"{cand.cid}: {rep.as_dict()}"


def test_usd_veto_rule_on_hand_built_frame() -> None:
    idx = pd.date_range("2001-01-31", periods=30, freq="ME")
    n = len(idx)
    gold = np.full(n, 1000.0)
    usd = np.full(n, 1.0)
    # persistent gold decline from month 10; persistent dollar rise from month 12
    for i in range(10, n):
        gold[i] = gold[i - 1] * 0.97
    for i in range(12, n):
        usd[i] = usd[i - 1] * 1.005
    df = pd.DataFrame({"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd}, index=idx)
    from qts.research.longhistory import monthly_signals as MS

    plan = MS.usd_veto_tsmom(df, gold_lb=6, usd_lb=6, vol_n=6)
    t = plan.target
    tail = t[20:28]
    assert np.all(np.isfinite(tail))
    # gold is DOWN over 6 months and the dollar rose over 6 months -> short
    assert np.all(tail == -1.0)
    # flip the dollar to a persistent decline from month 24 -> veto forces flat
    usd2 = usd.copy()
    for i in range(25, n):
        usd2[i] = usd2[i - 1] * 0.97
    df2 = df.copy()
    df2["usd"] = usd2
    plan2 = MS.usd_veto_tsmom(df2, gold_lb=6, usd_lb=6, vol_n=6)
    assert np.all(plan2.target[28:] == 0.0)


def test_usd_agreement_disagreement_is_flat() -> None:
    # Non-constant steps so the 6-month vol is strictly positive (a perfectly
    # constant synthetic return produces exact-zero rolling std -> NaN size).
    idx = pd.date_range("2001-01-31", periods=30, freq="ME")
    steps = np.where(np.arange(29) % 2 == 0, 1.02, 1.015)  # gold always rising
    gold = 1000.0 * np.cumprod(np.concatenate([[1.0], steps]))
    usd = np.cumprod(np.concatenate([[1.0], np.where(np.arange(29) % 2 == 0, 1.01, 1.005)]))
    df = pd.DataFrame({"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd}, index=idx)
    from qts.research.longhistory import monthly_signals as MS

    plan = MS.usd_agreement(df, gold_lb=6, usd_lb=6, vol_n=6)
    # gold trend up, dollar strengthening => disagreement => flat
    assert np.all(plan.target[15:] == 0.0)
    # gold trend up, dollar weakening => agreement => long
    usd2 = np.cumprod(np.concatenate([[1.0], np.where(np.arange(29) % 2 == 0, 0.99, 0.985)]))
    df2 = df.copy()
    df2["usd"] = usd2
    plan2 = MS.usd_agreement(df2, gold_lb=6, usd_lb=6, vol_n=6)
    assert np.all(plan2.target[15:] == 1.0)


def test_masked_target_warmup() -> None:
    df = _monthly_frame()
    for cid in ("m_tsmom_6", "m_tsmom_12", "m_usdveto_6_12", "m_agree_6_12"):
        cand = MON.candidate_by_id(cid)
        plan = cand.builder(df)
        warmup = ~np.isfinite(plan.size)
        assert bool(np.isnan(plan.target[warmup]).all())


# -------------------------------------------------------------------- engine


def test_engine_next_month_fill_and_ledger_identity() -> None:
    df = _monthly_frame(60)
    n = len(df)
    target = np.full(n, np.nan)
    size = np.full(n, np.nan)
    target[19] = 1.0  # decision at month 19 close -> fill at month 20 open
    size[19] = 0.5
    plan = Plan(
        target=target,
        size=size,
        stop_dist=np.full(n, np.nan),
        rebalance=np.zeros(n, dtype=bool),
        family="test",
        params={},
    )
    costs = CostModel(spread_bps=3.0, slippage_bps=1.0, commission_usd_per_lot_side=7.0, basis="TEST")
    run = run_plan(df, plan, 0, n, costs, initial_equity=10_000.0, force_close_end=True)
    assert len(run.trades) == 1
    trade = run.trades[0]
    # Entry at the open (monthly average) of bar 20, exit forced at final close.
    assert trade.entry_day == df.index[20]
    assert trade.entry_price == pytest.approx(df["close"].iloc[20])
    assert trade.exit_day == df.index[-1]
    # Accounting identity: equity change equals the trade ledger.
    assert run.final_equity - run.initial_equity == pytest.approx(
        sum(t.net_usd for t in run.trades), abs=1e-9
    )
    # P&L for a fixed unit count: gap marks use prev close -> this open.
    # The engine sizes units from notional before the fill cost is deducted.
    held_units = 0.5 * 10_000.0 / trade.entry_price
    expected_gross = held_units * (df["close"].iloc[-1] - df["close"].iloc[20])
    assert trade.gross_usd == pytest.approx(expected_gross, rel=1e-9)


def test_financing_regime_charges_more_than_base() -> None:
    df = _monthly_frame(80)
    n = len(df)
    target = np.full(n, np.nan)
    size = np.full(n, np.nan)
    target[19] = 1.0
    size[19] = 0.5
    plan = Plan(
        target=target,
        size=size,
        stop_dist=np.full(n, np.nan),
        rebalance=np.zeros(n, dtype=bool),
        family="test",
        params={},
    )
    base = run_plan(df, plan, 0, n, MON.COST_BASE, initial_equity=10_000.0)
    fin = run_plan(df, plan, 0, n, MON.COST_FINANCING, initial_equity=10_000.0)
    assert fin.financing_usd > 0.0
    assert fin.net_usd < base.net_usd
    assert MON.COST_FINANCING.financing_bps_per_day == MON.FINANCING_BPS_PER_DAY
    assert MON.COST_FINANCING.basis == MON.COST_BASE.basis


# ------------------------------------------------------------------ protocol


def test_protocol_windows_and_counts() -> None:
    assert MON.PREREG_ID == "LH-XAUUSD-MON-2026-10-15"
    assert MON.N_TRIALS_INHERITED == RV.N_TRIALS == 50
    assert MON.DISCOVERY_TRIALS == 22
    assert MON.N_TRIALS == 72
    assert len(MON.CANDIDATES) == 7
    assert len([c for c in MON.CANDIDATES if c.role == "CANDIDATE"]) == 6
    assert MON.FAMILY_GROUPS == ("gold_trend", "usd_veto", "usd_agreement")
    assert MON.CONTROL_GROUPS == ("monthly_reversion",)
    assert MON.DEV_END == "1999-12-31"
    assert MON.HOLDOUT_START == "2000-01-01"
    assert pd.Timestamp(MON.RESEARCH_START) < pd.Timestamp(MON.DEV_END)
    assert pd.Timestamp(MON.HOLDOUT_START) <= pd.Timestamp(MON.RESEARCH_END)
    assert tuple(range(1990, 2000)) == MON.WF_TEST_YEARS
    assert all(int(str(y)[:4]) <= 1999 for y in MON.WF_TEST_YEARS)
    assert MON.PERIODS_PER_YEAR == 12
    assert MON.VOL_BARS == 12
    assert MON.GATE_BREAK_EVEN_MIN == 2.0
    assert MON.GATE_FINANCING_CHARGED_POSITIVE is True


def test_parent_protocols_do_not_gain_cycle_gates() -> None:
    """The monthly-only gates (G8/G9 financing) must not leak into parents."""
    for proto in (D, I, SES, RV):
        assert not hasattr(proto, "GATE_FINANCING_CHARGED_POSITIVE")
        assert not hasattr(proto, "COST_FINANCING")
    assert hasattr(D, "GATE_DSR_MIN")
    assert not hasattr(D, "GATE_BREAK_EVEN_MIN")


def test_cost_base_shared_with_parents() -> None:
    assert MON.COST_BASE is D.COST_BASE
    assert MON.COST_STRESS_MULTIPLIERS == D.COST_STRESS_MULTIPLIERS
    assert MON.INITIAL_EQUITY == D.INITIAL_EQUITY
    assert MON.MIN_TRAIN_ROUND_TURNS == D.MIN_TRAIN_ROUND_TURNS


# --------------------------------------------------------------------- gates


class _SyntheticProto:
    """Windows compressed onto a synthetic frame so gates() can be exercised."""

    PREREG_ID = "SYNTHETIC-MON"
    PERIODS_PER_YEAR = 12
    VOL_BARS = 12
    REGIME_TREND_BARS = 12
    REGIME_MIN_BARS = 12
    RESEARCH_START = "2000-01-01"
    RESEARCH_END = "2009-12-31"
    DEV_END = "2004-12-31"
    HOLDOUT_START = "2005-01-01"
    WF_TEST_YEARS = (2002, 2003, 2004)
    REPLICATE_START = "2005-01-01"
    REPLICATE_END = "2005-12-31"
    COST_BASE = MON.COST_BASE
    COST_FINANCING = MON.COST_FINANCING
    COST_STRESS_MULTIPLIERS = (2.0,)
    INITIAL_EQUITY = 10_000.0
    MIN_TRAIN_ROUND_TURNS = 1
    MIN_TRADES_OOS_GATE = 1
    N_TRIALS = 6
    GATE_DSR_MIN = -1.0  # synthetic data cannot pass real DSR gates
    GATE_HOLM_ALPHA = 1.0
    GATE_WF_MIN_POSITIVE_YEARS = 1
    GATE_REGIMES_MIN_POSITIVE = 1
    GATE_BREAK_EVEN_MIN = 2.0
    GATE_FINANCING_CHARGED_POSITIVE = True
    FAMILY_GROUPS = MON.FAMILY_GROUPS
    CANDIDATES = tuple(
        c for c in MON.CANDIDATES if c.role == "CANDIDATE"
    )  # control excluded; diagnostics cover it
    candidates_in = staticmethod(lambda group: tuple(c for c in MON.CANDIDATES if c.group == group))
    candidate_by_id = staticmethod(MON.candidate_by_id)


def test_evaluate_dev_never_touches_holdout() -> None:
    df = _monthly_frame(120, start="2000-01-31")
    plans = R.build_plans(df, _SyntheticProto)
    result = R.evaluate(df, plans, "dev", replicate_df=None, proto=_SyntheticProto)
    assert result["verdict"]["status"] == "NOT_EVALUATED"
    assert result["gates"]["status"] == "NOT_EVALUATED_DEV_STAGE"
    assert "holdout" not in result


def test_evaluate_final_gates_include_all_cycle_gates() -> None:
    # A trending synthetic series so selections exist.
    drift = np.concatenate([[0.0], np.full(119, 0.01)])
    df = _monthly_frame(120, gold_ret=drift, usd_ret=np.full(120, -0.004))
    plans = R.build_plans(df, _SyntheticProto)
    result = R.evaluate(df, plans, "final", replicate_df=None, proto=_SyntheticProto)
    gates = result["gates"]
    assert isinstance(gates, dict)
    for group in _SyntheticProto.FAMILY_GROUPS:
        rec = gates[group]
        keys = set(rec["checks"])
        assert any(k.startswith("G8_") for k in keys)
        assert any(k.startswith("G9_") for k in keys)
        assert "financing_charged" in result["holdout"]["groups"][group]
    assert result["verdict"]["claim"] != ""


def test_regime_labels_present_on_monthly_frame() -> None:
    g = np.concatenate([[0.0], np.full(44, 0.02), np.full(45, -0.02)])
    df = _monthly_frame(90, gold_ret=g, usd_ret=np.full(90, 0.0))
    labels = R.regime_labels(df, _SyntheticProto)
    present = set(labels.dropna().unique())
    assert present  # labels exist
    assert present <= {"UP_HIVOL", "UP_LOWVOL", "DOWN_HIVOL", "DOWN_LOWVOL"}


# ------------------------------------------------------------- dataset build


def test_quote_probe_rejects_inverted_reading() -> None:
    import scripts.build_longhistory_monthly_dataset as build

    rows = []
    for date, checks in build.QUOTE_PROBES.items():
        for country, (lo, hi) in checks.items():
            rows.append(
                {"Country": country, "date": pd.Timestamp(date), "Exchange rate": 1.0 / ((lo + hi) / 2)}
            )
    fake = pd.DataFrame(rows)
    # Inverting the mid of the accepted range must fail the probe.
    with pytest.raises(SystemExit):
        build.quote_probes(fake)


def test_quote_probe_accepts_correct_reading() -> None:
    import scripts.build_longhistory_monthly_dataset as build

    rows = []
    for date, checks in build.QUOTE_PROBES.items():
        for country, (lo, hi) in checks.items():
            rows.append({"Country": country, "date": pd.Timestamp(date), "Exchange rate": (lo + hi) / 2})
    probes = build.quote_probes(pd.DataFrame(rows))
    assert len(probes) == sum(len(v) for v in build.QUOTE_PROBES.values())


def test_gold_month_gap_fails_closed(tmp_path) -> None:
    import scripts.build_longhistory_monthly_dataset as build

    # Write into pytest's tmp_path: data/raw/ is fully gitignored and does
    # not exist in a fresh CI checkout.
    tmp = tmp_path / "gold_monthly_gap_test.csv"
    # 2026-02 is missing between the three rows.
    pd.DataFrame({"Date": ["2026-01", "2026-03", "2026-04"], "Price": [100.0, 101.0, 103.0]}).to_csv(
        tmp, index=False
    )
    orig_csv, orig_start, orig_end = build.GOLD_CSV, build.START, build.END
    try:
        build.GOLD_CSV = tmp
        build.START = pd.Timestamp("2026-01-01")
        build.END = pd.Timestamp("2026-04-30")
        with pytest.raises(SystemExit):
            build.load_gold()
        # A complete month range passes.
        pd.DataFrame(
            {"Date": ["2026-01", "2026-02", "2026-03", "2026-04"], "Price": [100.0, 101.0, 101.0, 103.0]}
        ).to_csv(tmp, index=False)
        frame = build.load_gold()
        assert len(frame) == 4
    finally:
        build.GOLD_CSV, build.START, build.END = orig_csv, orig_start, orig_end
        tmp.unlink(missing_ok=True)
