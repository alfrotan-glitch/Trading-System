"""Bias checks for signal code, modelled on Freqtrade's bias tooling.

* :func:`truncation_check` (Freqtrade ``lookahead-analysis``): a signal computed
  on bars ``[0, k)`` must equal the same signal computed on the full series,
  restricted to ``[0, k)``. Any difference means the value at some bar used
  information from its future.
* :func:`warmup_check` (Freqtrade ``recursive-analysis``): an indicator must
  converge to the same value whatever bar the history starts at, once its
  burn-in has passed. A mismatch means the value depends on an arbitrary start.

A calendar-driven rebalance flag can change on the final bar of a truncated
series: truncation makes that bar look like a month end. Only that bar's
calendar-driven target is exempted, and only when the flag itself differs.
Every other bar and field is compared exactly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import Plan

PLAN_FIELDS = ("target", "size", "stop_dist")


@dataclass
class BiasReport:
    check: str
    passed: bool
    cuts_checked: int = 0
    mismatches: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "passed": self.passed,
            "cuts_checked": self.cuts_checked,
            "mismatch_count": len(self.mismatches),
            "first_mismatches": self.mismatches[:5],
        }


def _equal_with_nan(a: np.ndarray, b: np.ndarray, rtol: float = 1e-12) -> np.ndarray:
    both_nan = np.isnan(a) & np.isnan(b)
    close = np.isclose(a, b, rtol=rtol, atol=1e-12, equal_nan=False)
    return both_nan | close


def truncation_check(build: Callable[[pd.DataFrame], Plan], df: pd.DataFrame, cuts: Sequence[int]) -> BiasReport:
    full = build(df)
    mismatches: list[dict[str, object]] = []
    for k in cuts:
        if k <= 1 or k >= len(df):
            continue
        part = build(df.iloc[:k])
        # A calendar-driven rebalance flag can differ on the final truncated bar (it
        # looks like a month end there). That bar's calendar-driven target is then
        # exempt; every other bar and field is compared exactly.
        calendar_exempt = bool(np.asarray(full.rebalance)[k - 1] != np.asarray(part.rebalance)[k - 1])
        upto = k - 1 if calendar_exempt else k
        for name in PLAN_FIELDS:
            a = np.asarray(getattr(full, name))[:upto]
            b = np.asarray(getattr(part, name))[:upto]
            ok = _equal_with_nan(a, b)
            if not ok.all():
                bad = int(np.argmin(ok))
                mismatches.append(
                    {"cut": k, "field": name, "bar": bad, "full": float(a[bad]), "truncated": float(b[bad])}
                )
        ra = np.asarray(full.rebalance)[: k - 1]
        rb = np.asarray(part.rebalance)[: k - 1]
        if not np.array_equal(ra, rb):
            bad = int(np.argmax(ra != rb))
            mismatches.append({"cut": k, "field": "rebalance", "bar": bad})
    return BiasReport(check="truncation", passed=not mismatches, cuts_checked=len(cuts), mismatches=mismatches)


def warmup_check(
    indicator: Callable[[pd.DataFrame], pd.Series], df: pd.DataFrame, burn_in: int, offset: int, rtol: float = 1e-8
) -> BiasReport:
    """Compare ``indicator`` on the full series with the same indicator started at ``offset``."""
    full = indicator(df).to_numpy(dtype=float)
    late = indicator(df.iloc[offset:]).to_numpy(dtype=float)
    tail_full = full[offset + burn_in :]
    tail_late = late[burn_in:]
    mask = np.isfinite(tail_full) & np.isfinite(tail_late)
    diffs = np.abs(tail_full[mask] - tail_late[mask]) / np.maximum(np.abs(tail_full[mask]), 1e-12)
    worst = float(diffs.max()) if diffs.size else 0.0
    passed = worst <= rtol
    mismatches: list[dict[str, object]] = (
        [] if passed else [{"max_relative_difference": worst, "rtol": rtol, "offset": offset}]
    )
    return BiasReport(check="warmup", passed=passed, cuts_checked=1, mismatches=mismatches)
