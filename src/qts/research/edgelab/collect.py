"""Planning and recording forward observations.

The forward ledger only has value if every entry is genuinely out-of-sample, so
the collection step is where discipline is easiest to lose and hardest to notice.
Three rules are enforced here rather than left to the caller:

1. **Forward means forward.** An observation counts as forward only if its date is
   strictly later than the candidate's registration date. Anything at or before
   that is a holdout reading, not forward evidence, and this module refuses to
   label it otherwise.
2. **Complete bars only.** An observation is planned only for a date where the
   gold price and *every* driver used by the signal are present. A signal computed
   from a forward-filled stale driver is not an observation, it is a guess.
3. **The price basis is recorded.** Each entry carries whether gold was measured
   at an AM fix or a 24-hour close, so a later scorer cannot silently combine a
   look-ahead-free series with one that is not.

Networking lives in ``scripts/edgelab_collect_observations.py``; everything here
is pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from qts.research.edgelab.timing import detect_misaligned_index

#: Price bases this package knows how to reason about.
PRICE_BASES = ("m15_utc_close", "lbma_am_fix")


@dataclass(frozen=True)
class CollectionPlan:
    """What a collection run would record, before anything is written."""

    as_of: date | None
    observations: list[dict]
    skipped: list[dict]
    reason: str

    @property
    def empty(self) -> bool:
        return not self.observations


def align_drivers(drivers: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill drivers onto a bar index, preserving timezone handling."""
    f = drivers.copy()
    f.index = pd.DatetimeIndex(f.index)
    if f.index.tz is None:
        f.index = f.index.tz_localize("UTC")
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    f = f.sort_index()
    f = f[~f.index.duplicated(keep="first")]
    out = f.reindex(f.index.union(idx)).ffill().reindex(idx)
    check = detect_misaligned_index(out.dropna(), idx)
    if not check["ok"]:
        raise ValueError(f"driver alignment failed its pre-flight check: {check}")
    return out


def complete_dates(
    gold: pd.Series,
    drivers_raw: pd.DataFrame,
    index: pd.DatetimeIndex,
    max_age_days: int = 7,
) -> pd.DatetimeIndex:
    """Dates where gold has a bar and every driver has a *fresh real* observation.

    ``drivers_raw`` must be the un-filled driver frame. An earlier version of this
    function measured freshness on the forward-filled frame, where every row is
    non-null by construction, so the recency test always passed and stale drivers
    were silently scored as observations. Taking the raw frame as the argument makes
    that mistake impossible to make by accident.
    """
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    raw = drivers_raw.copy()
    raw.index = pd.DatetimeIndex(raw.index)
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC")
    raw = raw.sort_index()
    raw = raw[~raw.index.duplicated(keep="first")]
    if raw.empty or not raw.columns.size:
        return idx[:0]

    g = gold.reindex(idx)
    if g.notna().sum() == 0:
        return idx[:0]

    ok = g.notna()
    for c in raw.columns:
        observed = raw[c].dropna()
        if observed.empty:
            return idx[:0]
        # Age, in days, of the most recent real observation at or before each date.
        pos = observed.index.searchsorted(idx, side="right") - 1
        ages = np.full(len(idx), np.inf)
        has = pos >= 0
        ages[has] = (idx.values[has] - observed.index.values[pos[has]]) / np.timedelta64(1, "D")
        ok &= pd.Series(ages <= max_age_days, index=idx)
    return idx[ok.to_numpy()]


def plan_observations(
    candidate_id: str,
    registered_on: date,
    bars: pd.DataFrame,
    signal: pd.Series,
    price_basis: str,
    existing_dates: set[date] | None = None,
    forward_only: bool = True,
) -> CollectionPlan:
    """Decide which dates to record for one candidate.

    ``registered_on`` is the freeze date. With ``forward_only`` the plan contains
    only dates strictly after it — the definition of forward evidence.
    """
    if price_basis not in PRICE_BASES:
        raise ValueError(f"price_basis must be one of {PRICE_BASES}")
    already = existing_dates or set()
    idx = pd.DatetimeIndex(bars.index)
    sig = signal.reindex(idx)
    valid = sig.notna() & bars["close"].notna()

    observations: list[dict] = []
    skipped: list[dict] = []
    for ts, ok, s in zip(idx, valid.to_numpy(), sig.to_numpy(), strict=True):
        d = ts.date()
        if not ok:
            continue
        if d in already:
            continue
        if forward_only and d <= registered_on:
            skipped.append({"date": d.isoformat(), "reason": "not forward (on or before registration)"})
            continue
        observations.append(
            {
                "date": d.isoformat(),
                "candidate_id": candidate_id,
                "signal": float(s),
                "gold_close": float(bars["close"].loc[ts]),
                "price_basis": price_basis,
            }
        )

    if observations:
        reason = f"{len(observations)} observation(s) ready, latest {observations[-1]['date']}"
        as_of = date.fromisoformat(observations[-1]["date"])
    elif skipped:
        reason = (
            f"no forward observations yet; {len(skipped)} date(s) are at or before "
            "registration and are holdout data, not forward evidence"
        )
        as_of = None
    else:
        reason = "no new complete dates in the data"
        as_of = None
    return CollectionPlan(as_of=as_of, observations=observations, skipped=skipped, reason=reason)


def staleness(as_of: date, last_driver: date, limit_days: int = 7) -> str | None:
    gap = (as_of - last_driver).days
    if gap > limit_days:
        return f"drivers are {gap} days stale on {as_of} (limit {limit_days}); signal would be a guess"
    return None
