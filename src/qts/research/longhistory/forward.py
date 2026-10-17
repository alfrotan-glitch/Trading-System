"""Frozen forward-validation champions: exact rules and current state.

The two best candidates of the 2026-10-17 long-history series, frozen
verbatim for forward observation under
``docs/research/forward_validation_champions_2026-10-17.md``:

``ts9_lo``  9-month TSMOM sign, long-or-flat (evaluation champion).
``veto9``   9-month trend; shorts only while the USD index rose over
            the prior 12 months (decade-robustness champion).

This module only *describes* positions a paper observer would hold. It
places no orders, touches no broker, DEMO/LIVE or risk state, and its
outputs are research records, never trade instructions.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

import pandas as pd

from qts.research.longhistory import ensemble_signals as ES
from qts.research.longhistory.signals import Plan

VOL_N = 12
ANN = 12
USD_LB = 12
LOOKBACK = 9

CHAMPION_BUILDERS: dict[str, Callable[[pd.DataFrame], Plan]] = {
    "ts9_lo": partial(
        ES.tsmom_single, lookback=LOOKBACK, long_only=True, vol_n=VOL_N, ann=ANN
    ),
    "veto9": partial(
        ES.ensemble_usd_veto, lookbacks=(LOOKBACK,), usd_lb=USD_LB, vol_n=VOL_N, ann=ANN
    ),
}


def _state_name(target: float) -> str:
    if target > 0:
        return "LONG"
    if target < 0:
        return "SHORT"
    return "FLAT"


def current_states(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Would-be state of each frozen champion at the frame's last bar.

    ``df`` is the monthly research frame (OHLC + ``usd`` index,
    month-end stamps). Returns, per champion: the state at the last
    valid bar, the vol-target size fraction, the month the current
    state began, and the rule inputs (trailing gold return, USD change)
    so a reader can verify the state by hand.
    """
    if "usd" not in df.columns:
        raise ValueError("forward states require the monthly 'usd' column")
    out: dict[str, dict[str, object]] = {}
    close = df["close"]
    gold_lb = float(close.iloc[-1] / close.shift(LOOKBACK).iloc[-1] - 1.0)
    usd_change = float(df["usd"].iloc[-1] / df["usd"].shift(USD_LB).iloc[-1] - 1.0)
    for cid, builder in CHAMPION_BUILDERS.items():
        plan = builder(df)
        target = pd.Series(plan.target, index=df.index)
        size = pd.Series(plan.size, index=df.index)
        valid = target.dropna()
        if valid.empty:
            raise ValueError(f"{cid}: no valid state in frame")
        as_of = valid.index[-1]
        current = float(valid.iloc[-1])
        changes = valid[valid.diff().fillna(1.0) != 0.0]
        out[cid] = {
            "as_of": str(as_of.date()),
            "state": _state_name(current),
            "target": current,
            "size_fraction": round(float(size.loc[as_of]), 4),
            "in_state_since": str(changes.index[-1].date()) if len(changes) else None,
            "gold_close": float(close.loc[as_of]),
            "gold_trailing_9m_return": round(gold_lb, 4),
            "usd_trailing_12m_change": round(usd_change, 4),
        }
    return out
