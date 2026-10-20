"""Pre-registered acceptance gate for an XAUUSD edge.

The thresholds are fixed constants, not arguments, because a gate whose
parameters can be tuned after seeing results is not a gate. Changing them is a
deliberate decision that must be visible as a diff, and any result produced
before the change is invalidated by it.

Why alpha rather than Sharpe: the underlying rose ~7% a year with a Sharpe of
0.49 on DEV. Any strategy that is long most of the time inherits that, so a good
Sharpe is evidence of *exposure*, not of skill. The gate therefore asks whether
returns survive a regression on buy-and-hold, which is a strictly harder test
than a Sharpe ranking.
"""

from __future__ import annotations

import pandas as pd

# Frozen 2026-10-20, before the first result was read. Do not tune.
MIN_ALPHA_T_DEV = 2.5
MIN_DSR = 0.95
MAX_COST_STRESS_FACTOR = 2.0


def survivors(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that clear every DEV-side criterion.

    ``df`` must carry ``alpha_t``, ``dsr`` and ``alpha_ann_stress`` (alpha measured
    under doubled costs). Missing columns raise rather than silently passing: a
    gate that degrades to "everything passes" when a column is absent is worse
    than no gate.
    """
    required = {"alpha_t", "dsr", "alpha_ann_stress"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"gate requires columns {sorted(missing)}")
    return df[
        (df["alpha_t"] >= MIN_ALPHA_T_DEV)
        & (df["dsr"] >= MIN_DSR)
        & (df["alpha_ann_stress"] > 0)
    ]


def val_confirms(val: pd.DataFrame) -> pd.DataFrame:
    """DEV survivors must keep a positive alpha on the validation period.

    A sign flip is the signature of a fitted artefact: real effects decay, they do
    not reverse. This rejects on direction, not magnitude, because three years is
    too short to estimate the size of an edge reliably.
    """
    required = {"alpha_t", "alpha_ann"}
    missing = required - set(val.columns)
    if missing:
        raise ValueError(f"gate requires columns {sorted(missing)}")
    return val[(val["alpha_t"] > 0) & (val["alpha_ann"] > 0)]
