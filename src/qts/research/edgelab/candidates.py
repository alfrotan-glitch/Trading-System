"""The frozen candidate catalogue.

Only strategies that have cleared the pre-registered gate on development data
belong here. Registration freezes the definition by hash, so the forward record
attached to a candidate cannot be transferred to a modified rule.

Why one candidate rather than several: this is the only configuration in the
project that passed every criterion, and presenting a menu of half-validated
signals invites the reader to pick the one that looks best in hindsight — the
exact selection effect the gate exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab.forward import Candidate

BARS_PER_MONTH = 21
MACRO_DIR = Path("data/raw/longgold/macro_daily")


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
)


def candidates() -> list[Candidate]:
    return [EASING_6M]


def build_signal_frame(bars: pd.DataFrame | None = None) -> pd.DataFrame:
    """Gold bars with DXY and the 10-year yield attached, for signal computation."""
    from qts.research.edgelab.macro_daily import attach_macro_daily
    from qts.research.edgelab.metals import gold_bars, load_metals

    if bars is None:
        bars = gold_bars(load_metals())
    return attach_macro_daily(bars).dropna(subset=["dxy", "y10"])
