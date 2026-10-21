"""Price-snapshot timing: the guardrail that XL-001 should have had.

XL-001 cleared every pre-registered gate and was still wrong. The defect was not
statistical — it was that the gold series and the driver series were sampled at
different times of day, and the backtest quietly combined them as if they were
simultaneous.

Concretely:

* ``AU.csv`` is the **LBMA gold price at 10:30 London** (the source dataset states
  this explicitly; it is the FRED ``GOLDAMGBD228NLBM`` AM fix).
* DXY and the 10-year yield are **close-of-day** series, settling around 22:00
  London.

So a decision made from "today's" DXY close is being filled at a gold price
observed 11.5 hours *earlier*. The harness's close-to-close convention then credits
the position with the move from that earlier fix into the next one — roughly half
of which happened before the information existed. On XL-001 that inflated the DEV
alpha_t from 2.70 to an honest 1.0-1.3 depending on the price basis.

This module makes the relationship explicit and testable:

* every price source declares the UTC hour at which its daily value is struck;
* every driver declares the UTC hour at which it becomes known;
* :func:`required_lag` derives how many bars a decision must be delayed for the
  fill to be executable;
* :func:`timing_robustness` re-runs a signal at lags 0..n so an artifact shows up
  as a collapse rather than hiding behind a single number.

The rule is one line: **a position may only be taken at a price struck after its
inputs were knowable.**
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Snapshot:
    """A daily value and the UTC hour at which it is struck or published."""

    name: str
    utc_hour: float

    def __str__(self) -> str:
        h = int(self.utc_hour)
        m = int(round((self.utc_hour - h) * 60))
        return f"{self.name} @ {h:02d}:{m:02d} UTC"


#: Where a daily gold value comes from, and when it is struck.
GOLD_PRICE_SNAPSHOTS: dict[str, Snapshot] = {
    # LBMA AM auction, 10:30 London == 09:30 UTC in winter, 10:30 UTC under BST.
    # The later (BST) reading is used so the requirement is never understated.
    "lbma_am_fix": Snapshot("LBMA AM fix", 10.5),
    # A 24-hour bar's close: the last tick of the UTC day.
    "m15_utc_close": Snapshot("M15 UTC close", 24.0),
}

#: When a daily macro driver becomes knowable.
DRIVER_SNAPSHOTS: dict[str, Snapshot] = {
    "dxy_close": Snapshot("DXY close", 22.0),
    "y10_close": Snapshot("10y close", 22.0),
    # FRED stamps an observation with its observation date but publishes later;
    # one full day is the conservative assumption.
    "fred_observation_date": Snapshot("FRED observation", 24.0),
    # A US equity close is 16:00 New York == 21:00 London under EDT, 22:00 under
    # EST. Registered in round 18 after a miners-relative signal produced DEV alpha
    # t 5.57 at lag 0 and exactly zero at lag 1 — the third occurrence of the
    # snapshot artifact, and the reason this table exists.
    "miners_equity_close": Snapshot("US equity close", 21.0),
}


def required_lag(price: Snapshot, driver: Snapshot) -> int:
    """Bars a decision must be delayed so the fill is executable.

    Returns 0 when the fill price is struck after the driver is known (the
    information is available before the trade), and 1 otherwise — with daily bars,
    one bar is the smallest executable delay.

    Note the direction: the *fill* must come after the *information*. A driver
    known at 22:00 cannot be acted on at a price struck at 10:30 the same day.
    """
    if price.utc_hour > driver.utc_hour:
        return 0
    return 1


def audit_required_lag(price_key: str, driver_keys: tuple[str, ...]) -> dict:
    """Required lag for a price source against several drivers, with reasoning."""
    price = GOLD_PRICE_SNAPSHOTS[price_key]
    lags = {}
    for k in driver_keys:
        d = DRIVER_SNAPSHOTS[k]
        lags[k] = required_lag(price, d)
    worst = max(lags.values()) if lags else 0
    return {
        "price": str(price),
        "drivers": {k: {"snapshot": str(DRIVER_SNAPSHOTS[k]), "required_lag": v} for k, v in lags.items()},
        "required_lag": worst,
        "explanation": (
            "the fill price precedes the latest driver observation"
            if worst
            else "every driver is knowable before the fill price is struck"
        ),
    }


def apply_lag(signal: pd.Series, lag: int) -> pd.Series:
    """Delay a position by ``lag`` bars; negative lags are refused, not reversed."""
    if lag < 0:
        raise ValueError("lag must be >= 0 — a negative lag is look-ahead by definition")
    return signal.shift(lag) if lag else signal


def timing_robustness(
    evaluate: Callable[[int], dict],
    lags: tuple[int, ...] = (0, 1, 2, 3),
) -> pd.DataFrame:
    """Run a caller-supplied evaluator at several lags and tabulate the effect.

    ``evaluate`` must accept ``lag`` and return a mapping containing at least
    ``alpha_ann`` and ``alpha_t``. Kept as a callback so this module does not
    depend on the backtest engine and can be tested in isolation.
    """
    rows = []
    for lag in lags:
        m = evaluate(lag)
        rows.append({"lag": lag, "alpha_ann": m["alpha_ann"], "alpha_t": m["alpha_t"]})
    df = pd.DataFrame(rows).set_index("lag")
    return df


def verdict_at_lag(table: pd.DataFrame, required: int, threshold: float) -> dict:
    """Whether the effect survives at the lag the data actually permits."""
    if required not in table.index:
        raise ValueError(f"required lag {required} not present in {list(table.index)}")
    row = table.loc[required]
    ok = bool(row["alpha_ann"] > 0 and row["alpha_t"] >= threshold)
    base = table.loc[0]
    # Row values arrive as numpy scalars; ``np.asarray(...).item()`` states the
    # intent and satisfies the type stubs, which float() alone does not.
    def _f(v: object) -> float:
        return float(np.asarray(v, dtype=float).item())

    return {
        "required_lag": required,
        "alpha_ann": _f(row["alpha_ann"]),
        "alpha_t": _f(row["alpha_t"]),
        "lag0_alpha_ann": _f(base["alpha_ann"]),
        "lag0_alpha_t": _f(base["alpha_t"]),
        "survives": ok,
        "decay": _f(base["alpha_t"]) - _f(row["alpha_t"]),
    }


def detect_misaligned_index(drivers: pd.DataFrame, prices: pd.DatetimeIndex) -> dict:
    """Cheap pre-flight check for the failure mode that produced a flat signal.

    A driver frame whose dates do not overlap the price index at all, or whose
    forward-fill collapsed to a constant, produces a strategy that never trades and
    reports a flat line with no error. Both are caught here.
    """
    if drivers.empty:
        raise ValueError("driver frame is empty")
    idx = pd.DatetimeIndex(prices)
    overlap = drivers.index.intersection(idx)
    zero_variance = {c: bool(pd.Series(drivers[c]).nunique() <= 1) for c in drivers.columns}
    return {
        "driver_rows": int(len(drivers)),
        "price_rows": int(len(idx)),
        "overlapping_dates": int(len(overlap)),
        "constant_columns": [c for c, v in zero_variance.items() if v],
        "ok": bool(len(overlap) > 0 and not any(zero_variance.values())),
    }


__all__ = [
    "DRIVER_SNAPSHOTS",
    "GOLD_PRICE_SNAPSHOTS",
    "Snapshot",
    "apply_lag",
    "audit_required_lag",
    "detect_misaligned_index",
    "required_lag",
    "timing_robustness",
    "verdict_at_lag",
]
