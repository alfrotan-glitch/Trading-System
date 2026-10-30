from __future__ import annotations

import numpy as np
import pandas as pd

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory import hybrid_protocol as HYB
from qts.research.longhistory.sahm_u3_gate import U3_SOURCE_COMMIT, apply_sahm_gate
from qts.research.longhistory.yield_curve_gate import MODEL_MONTHS
from scripts import run_longhistory_sahm_unemployment_gate as runner


def test_source_revision_erratum_uses_resolvable_commit() -> None:
    assert U3_SOURCE_COMMIT == "23d5e7795325ce1a69d02bd52e20ad075983082a"


def test_screen_runner_completes_on_synthetic_only_monthly_data() -> None:
    rng = np.random.default_rng(20_102_020)
    monthly_returns = 0.006 + rng.normal(0.0, 0.035, len(MODEL_MONTHS))
    gold = pd.Series(1_000.0 * np.exp(np.cumsum(monthly_returns)), index=MODEL_MONTHS)
    usd = pd.Series(np.exp(np.cumsum(rng.normal(0.0, 0.02, len(MODEL_MONTHS)))), index=MODEL_MONTHS)
    frame = pd.DataFrame(
        {"open": gold, "high": gold, "low": gold, "close": gold, "usd": usd},
        index=MODEL_MONTHS,
    )
    frame.index.name = "date"

    base = ES.tsmom_single(frame, lookback=9, long_only=True, vol_n=12, ann=12)
    feature = pd.Series(0.50, index=MODEL_MONTHS, name="sahm_gap_lag2_pp")
    candidate = apply_sahm_gate(base, feature, index=MODEL_MONTHS)
    veto9 = HYB.candidate_by_id("veto9").builder(frame)
    result = runner._screen(
        frame,
        {"sahm_u3_ts9_longflat": candidate, "ts9_lo": base, "veto9": veto9},
        feature,
    )

    assert result["candidate_outcomes_calculated"] is True
    assert result["cumulative_trials_before"] == 361
    assert result["cumulative_trials"] == 362
    assert set(result["windows"]) == set(runner.WINDOWS)
    assert len(result["development_paired_bootstrap"]["ts9_lo"]["monthly_return_differences"]) == 120
