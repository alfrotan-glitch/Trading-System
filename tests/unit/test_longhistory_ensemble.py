"""Unit tests for the ensemble/weekly long-history extension (synthetic only)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory import checks as C
from qts.research.longhistory import ensemble_protocol as ENS
from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import hybrid_protocol as HYB
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import weekly_protocol as WK


def _frame(n: int = 180, freq: str = "ME", seed: int = 7) -> pd.DataFrame:
    idx = pd.date_range("2000-01-31", periods=n, freq=freq)
    rng = np.random.default_rng(seed)
    gold = 1000.0 * np.cumprod(1.0 + rng.normal(0.004, 0.035, n))
    return pd.DataFrame(
        {"open": gold, "high": gold * 1.001, "low": gold * 0.999, "close": gold,
         "usd": np.cumprod(1.0 + rng.normal(0.0, 0.015, n))},
        index=idx,
    )


def test_trial_counts_are_cumulative() -> None:
    assert ENS.N_TRIALS == MON.N_TRIALS + ENS.DISCOVERY_TRIALS
    assert WK.N_TRIALS == ENS.N_TRIALS + WK.DISCOVERY_TRIALS
    assert HYB.N_TRIALS == WK.N_TRIALS + HYB.DISCOVERY_TRIALS


def test_signal_shapes_and_target_domain() -> None:
    df = _frame()
    for proto in (ENS, WK, HYB):
        for cand in proto.CANDIDATES:
            plan = cand.builder(df)
            assert len(plan.target) == len(df)
            finite = np.isfinite(plan.target)
            assert set(np.unique(plan.target[finite])) <= {-1.0, 0.0, 1.0}
            assert bool(np.isfinite(plan.size[finite]).all())
            assert bool((plan.size[np.isfinite(plan.size)] <= 1.0).all())
            assert bool((plan.size[np.isfinite(plan.size)] >= 0.0).all())


def test_truncation_causality_all_candidates() -> None:
    df = _frame(200)
    cuts = sorted({int(len(df) * f) for f in (0.25, 0.5, 0.75)})
    for proto in (ENS, WK, HYB):
        for cand in proto.CANDIDATES:
            rep = C.truncation_check(cand.builder, df, cuts)
            assert rep.passed, f"{cand.cid}: {rep.as_dict()}"


def test_long_only_never_shorts() -> None:
    df = _frame()
    for builder in (
        lambda d: ES.ensemble_tsmom(d, (2, 4, 8), long_only=True, vol_n=12, ann=12),
        lambda d: ES.ma_trend(d, 3, 12, long_only=True, vol_n=12, ann=12),
        lambda d: ES.tsmom_single(d, 9, long_only=True, vol_n=12, ann=12),
    ):
        plan = builder(df)
        finite = np.isfinite(plan.target)
        assert set(np.unique(plan.target[finite])) <= {0.0, 1.0}


def test_graded_size_never_exceeds_ungraded() -> None:
    df = _frame()
    plain = ES.ensemble_tsmom(df, (1, 3, 6, 12), vol_n=12, ann=12)
    graded = ES.ensemble_tsmom(df, (1, 3, 6, 12), graded=True, vol_n=12, ann=12)
    mask = np.isfinite(plain.size) & np.isfinite(graded.size)
    assert bool((graded.size[mask] <= plain.size[mask] + 1e-12).all())
    assert np.allclose(
        np.sign(graded.target[np.isfinite(graded.target)]),
        np.sign(plain.target[np.isfinite(plain.target)]),
    )


def test_ensemble_hand_built_direction() -> None:
    # Steadily rising gold: every horizon votes long once warm.
    n = 60
    idx = pd.date_range("2001-01-31", periods=n, freq="ME")
    gold = 1000.0 * (1.02 ** np.arange(n))
    df = pd.DataFrame({"open": gold, "high": gold, "low": gold, "close": gold}, index=idx)
    plan = ES.ensemble_tsmom(df, (2, 4, 8), vol_n=12, ann=12)
    tail = plan.target[-10:]
    assert bool((tail[np.isfinite(tail)] == 1.0).all())
