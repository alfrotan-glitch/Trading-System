"""Unit tests for the M15 impulse-fade (reversal) cycle ``LH-XAUUSD-M15-REV-2026-10-14``.

Synthetic series only. The protocol test pins the frozen values, so a silent edit
to the candidates, trial count or gates fails the fast suite.

Preregistration: ``docs/research/preregistration_longhistory_m15_reversal_2026-10-14.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory import reversal_protocol as RV
from qts.research.longhistory import seasonal_protocol as SES
from qts.research.longhistory import signals as G


def _impulse_frame(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """Random-walk M15 bars with a few deliberately large single-bar impulses."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-04 00:00", periods=n, freq="15min")
    ret = rng.normal(0.0, 0.0005, n)
    for t in range(200, n, 97):
        ret[t] = 0.02  # a large up impulse
    close = 1000.0 * np.cumprod(1.0 + ret)
    opens = np.concatenate([[1000.0], close[:-1]])
    spread = 0.2
    high = np.maximum(opens, close) + spread
    low = np.minimum(opens, close) - spread
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": 1.0},
        index=idx,
    )


def test_fade_is_exact_sign_inverse_of_continuation_state():
    """Fade and continuation share thresholds, timing and stops; only the sign differs."""
    df = _impulse_frame()
    cont = G.range_expansion(df, k=1.0, hold=4)
    fade = G.impulse_fade(df, k=1.0, hold=4)
    c = np.nan_to_num(cont.target, nan=0.0)
    f = np.nan_to_num(fade.target, nan=0.0)
    # Wherever the continuation is active the fade is the opposite, and vice versa.
    assert np.array_equal(f, -c)
    assert np.any(f != 0.0), "test series must contain fade trades"


def test_fade_reads_only_prior_atr_and_current_body():
    """Causality: the decision at t depends only on bars <= t (truncation invariance)."""
    df = _impulse_frame()
    full = G.impulse_fade(df, k=2.0, hold=16).target
    cut = len(df) // 2
    part = G.impulse_fade(df.iloc[:cut], k=2.0, hold=16).target
    assert np.allclose(np.nan_to_num(part, nan=-9), np.nan_to_num(full[:cut], nan=-9))


def test_protocol_is_frozen_and_counts_trials():
    names = [c.cid for c in RV.CANDIDATES]
    assert names == ["fade_k20_h4", "fade_k20_h16", "fade_k10_h4"]
    assert all(c.role == "CANDIDATE" for c in RV.CANDIDATES)
    assert RV.FAMILY_GROUPS == ("impulse_fade",)
    # Cumulative trials: seasonal's 47 plus this cycle's three.
    assert RV.N_TRIALS == SES.N_TRIALS + 3 == 50
    assert RV.GATE_BREAK_EVEN_MIN == 2.0
    assert RV.PREREG_ID == "LH-XAUUSD-M15-REV-2026-10-14"
    # Holdout and replicate windows are inherited, not redefined here.
    assert RV.HOLDOUT_START == "2020-01-01"
    assert RV.RESEARCH_END == "2025-02-28"
