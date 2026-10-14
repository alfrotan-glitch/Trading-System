"""Research-only entry point for the strongest documented daily candidate.

The 2026-10-10 long-history report ranks ``ma_20_100_atr3`` as its strongest
candidate (4/7 gates), but explicitly concludes ``NO_VALIDATED_EDGE``. This
module binds that exact existing protocol candidate to a small, reproducible
backtest API. It does not add a second signal implementation or connect to any
broker/order path.

All defaults come from the frozen daily protocol. In particular the cost basis
is ASSUMED, including zero financing; it is never upgraded to measured evidence
by this wrapper. Use a new preregistration for any parameter or rule change.
"""

from __future__ import annotations

from functools import partial

import numpy as np
import pandas as pd

from qts.research.longhistory import protocol as P
from qts.research.longhistory import runner as R
from qts.research.longhistory.engine import CostModel, RunResult
from qts.research.longhistory.protocol import Candidate
from qts.research.longhistory.signals import Plan

SELECTED_PROTOCOL_ID = P.PREREG_ID
SELECTED_CANDIDATE_ID = "ma_20_100_atr3"


def selected_candidate() -> Candidate:
    """Return the existing frozen SMA(20/100), 3×ATR candidate.

    Selection is intentionally separate from the frozen candidate grid. This
    helper names the best currently documented implementation target; it does
    not change the protocol's training/holdout selection procedure or verdict.
    """
    candidate = P.candidate_by_id(SELECTED_CANDIDATE_ID)
    if candidate.role != "CANDIDATE":
        raise RuntimeError(f"{SELECTED_CANDIDATE_ID} is not a tradable research candidate")
    if not isinstance(candidate.builder, partial):
        raise RuntimeError(f"{SELECTED_CANDIDATE_ID} no longer has the registered parameterized builder")

    # Candidate is a frozen dataclass, but functools.partial exposes a mutable
    # ``keywords`` dictionary. Return an isolated copy so a caller inspecting
    # the candidate cannot mutate the protocol's process-wide frozen definition.
    copied_builder = partial(candidate.builder.func, *candidate.builder.args, **(candidate.builder.keywords or {}))
    return Candidate(
        cid=candidate.cid,
        group=candidate.group,
        role=candidate.role,
        builder=copied_builder,
        description=candidate.description,
    )


def _validate_daily_bars(bars: pd.DataFrame) -> None:
    """Fail closed on malformed input or a timeframe mismatch."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("selected daily strategy requires a DatetimeIndex")
    if len(bars) < 2:
        raise ValueError("selected daily strategy requires at least two bars")
    if bars.index.hasnans or bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("daily bars must have unique, strictly increasing timestamps")
    if bars.index.tz is not None:
        raise ValueError("daily timestamps must be normalized to naive UTC before evaluation")
    if not bars.index.equals(bars.index.normalize()):
        raise ValueError("selected candidate is daily; supply midnight-stamped UTC daily bars, not intraday bars")

    required = ("open", "high", "low", "close")
    missing = [name for name in required if name not in bars.columns]
    if missing:
        raise ValueError(f"daily bars are missing OHLC columns: {', '.join(missing)}")
    values = bars.loc[:, list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("daily OHLC prices must be finite and positive")
    open_, high, low, close = values.T
    if (high < np.maximum(open_, close)).any() or (low > np.minimum(open_, close)).any() or (high < low).any():
        raise ValueError("daily OHLC range is inconsistent with open/close")


def build_selected_plan(bars: pd.DataFrame) -> Plan:
    """Build the frozen candidate's causal signal plan from daily bars.

    The existing plan uses only current/past completed daily closes and ATR.
    The runner executes each close-time decision at the following daily open.
    """
    _validate_daily_bars(bars)
    return selected_candidate().builder(bars)


def run_selected_window(
    bars: pd.DataFrame,
    start: str,
    end: str,
    *,
    costs: CostModel | None = None,
) -> RunResult:
    """Run one inclusive calendar window through the existing costed engine.

    The default is the frozen protocol's ASSUMED XAUUSD model (3 bps full
    spread, 1 bp slippage per side, USD 7/lot/side commission, and zero
    financing). ASSUMED overrides are useful for cost sensitivity. This wrapper
    refuses a different basis: it does not bind broker cost observations, so a
    caller cannot label an unverified cost input MEASURED here.
    """
    cost_model = P.COST_BASE if costs is None else costs
    if cost_model.basis != "ASSUMED":
        raise ValueError("selected strategy wrapper only accepts ASSUMED costs; measured-cost evidence is not bound")
    plan = build_selected_plan(bars)
    return R.run_window(bars, plan, start, end, cost_model)
