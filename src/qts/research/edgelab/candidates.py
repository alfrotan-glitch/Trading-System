"""The frozen candidate catalogue.

Only strategies that have cleared the pre-registered gate on development data are
listed as ``candidate``. Rejected definitions are kept, not deleted: the hash and
the rejection reason are what make the decision auditable, and deleting them would
make the project's history look better than it was.

Why the list is short. Two families are currently *credible but unvalidated*
(XL-001's macro easing premise, and the real-yield residual from round 9). Neither
is registered as a candidate: XL-001's gate pass has been withdrawn by the round-10
audit, and the real-yield residual never cleared the 2.5 gate (DEV t 2.20). A
catalogue of half-validated signals invites the reader to pick the one that looks
best in hindsight, which is the selection effect the gate exists to prevent.

``DRIVERS`` names, per candidate, the driver columns its signal reads. The
collector uses that to decide which dates have complete, fresh inputs — a signal
computed from a stale forward-filled driver is a guess, not an observation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab.forward import Candidate

BARS_PER_MONTH = 21
MACRO_DIR = Path("data/raw/longgold/macro_daily")

#: Driver columns each candidate requires to be fresh.
DRIVERS: dict[str, tuple[str, ...]] = {
    "XL-001": ("dxy", "y10"),
}


def _falling(series: pd.Series, months: int) -> pd.Series:
    ch = series - series.shift(months * BARS_PER_MONTH)
    return pd.Series(np.where(ch < 0, 1.0, 0.0), index=series.index).where(ch.notna(), np.nan)


def easing_score_6m(bars: pd.DataFrame) -> pd.Series:
    """Average of two easing indicators: dollar falling, and yields falling.

    Each is a binary "direction of travel" test over six months. Averaging rather
    than requiring agreement was fixed by reasoning, not by fitting: the two series
    measure the same underlying factor (loosening financial conditions) with
    independent noise, so the average should have a better signal-to-noise ratio
    than either part. Requiring both to agree was tested and was *worse*, which is
    the honest outcome to report.

    Returns exposure in [0, 1]; 0.5 means exactly one of the two is falling.

    **Known defect (round-10 audit, 2026-10-21).** This rule was scored on the LBMA
    AM fix (10:30 London) while its drivers settle at 22:00 London, so the backtest
    earned roughly eleven hours of return before the inputs existed. The definition
    is preserved unchanged because the hash is the audit trail; the status is
    ``rejected`` and no forward observation is collected for it.
    """
    if "dxy" not in bars.columns or "y10" not in bars.columns:
        raise ValueError("bars must carry 'dxy' and 'y10'")
    usd = _falling(bars["dxy"], 6)
    yld = _falling(bars["y10"], 6)
    return ((usd + yld) / 2.0).fillna(0.0).clip(0.0, 1.0)


#: Registered candidate. Ids are stable and must never be reused for a new rule.
EASING_6M = Candidate(
    id="XL-001",
    name="easing_conditions_6m",
    family="macro",
    rationale=(
        "Gold is a zero-coupon asset quoted in dollars. Its two opportunity-cost "
        "proxies are the dollar (its numeraire) and the nominal 10-year yield (the "
        "competing risk-free return). When both are trending down, financial "
        "conditions are loosening and the cost of holding gold is falling. Averaging "
        "the two indicators diversifies their independent noise."
    ),
    params={"usd_lookback_months": 6, "yield_lookback_months": 6, "combination": "mean"},
    signal=easing_score_6m,
    status="rejected",
    rejected_reason=(
        "Round-10 audit (2026-10-21): the gate pass was a price-snapshot artifact. "
        "Every macro round measured gold on the LBMA AM fix (10:30 London) while the "
        "drivers settle at the close (22:00 London), so the harness earned roughly "
        "11 hours of return before the signal existed. With the decision lagged to "
        "the next fix, VAL flips sign (-1.09%) and TEST falls to 1.75; on genuinely "
        "tradable 24-hour M15 closes over 2005-2025 the alpha is +1.6%/yr, t 1.34. "
        "See docs/research/audit_xl001_2026-10-21.md."
    ),
)


def candidates() -> list[Candidate]:
    return [EASING_6M]


def active_candidates() -> list[Candidate]:
    """Candidates still eligible to accumulate forward evidence."""
    return [c for c in candidates() if c.status == "candidate"]


def build_signal_frame(bars: pd.DataFrame | None = None) -> pd.DataFrame:
    """Gold bars with DXY and the 10-year yield attached, for signal computation."""
    from qts.research.edgelab.macro_daily import attach_macro_daily
    from qts.research.edgelab.metals import gold_bars, load_metals

    if bars is None:
        bars = gold_bars(load_metals())
    return attach_macro_daily(bars).dropna(subset=["dxy", "y10"])
