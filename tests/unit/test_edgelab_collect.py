"""Forward-observation collection: forward-only, complete, and idempotent.

The rules that matter are all about not manufacturing evidence:

* a date at or before registration is *holdout*, never forward;
* a date whose drivers are stale is not an observation;
* re-logging the same date is a no-op, and re-logging it with a different signal
  is refused.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import forward
from qts.research.edgelab.collect import (
    align_drivers,
    complete_dates,
    plan_observations,
    staleness,
)
from qts.research.edgelab.forward import Candidate


@pytest.fixture()
def frame():
    idx = pd.bdate_range("2026-01-01", periods=80, tz="UTC")
    bars = pd.DataFrame({"close": np.linspace(2000, 2100, 80)}, index=idx)
    drivers = pd.DataFrame(
        {"dxy": np.linspace(100, 95, 80), "y10": np.linspace(4.5, 4.0, 80)}, index=idx
    )
    signal = pd.Series(np.linspace(0.0, 1.0, 80), index=idx)
    return bars, drivers, signal


def test_plan_excludes_dates_on_or_before_registration(frame):
    bars, _, signal = frame
    registered = bars.index[60].date()
    plan = plan_observations("C", registered, bars, signal, "m15_utc_close")
    assert plan.observations, "expected some forward observations"
    for o in plan.observations:
        assert date.fromisoformat(o["date"]) > registered
    # Everything up to and including registration is reported as skipped, not lost.
    assert len(plan.skipped) == 61
    assert all("not forward" in s["reason"] for s in plan.skipped)


def test_plan_with_registration_after_the_data_yields_nothing(frame):
    bars, _, signal = frame
    plan = plan_observations("C", date(2030, 1, 1), bars, signal, "m15_utc_close")
    assert plan.empty
    assert "not forward" in plan.reason
    assert plan.as_of is None


def test_plan_skips_dates_already_recorded(frame):
    bars, _, signal = frame
    have = {bars.index[70].date()}
    plan = plan_observations("C", date(2025, 1, 1), bars, signal, "m15_utc_close", existing_dates=have)
    assert bars.index[70].date().isoformat() not in {o["date"] for o in plan.observations}


def test_plan_skips_dates_where_the_signal_is_undefined(frame):
    bars, _, signal = frame
    s = signal.copy()
    s.iloc[65:70] = np.nan
    plan = plan_observations("C", date(2025, 1, 1), bars, s, "m15_utc_close")
    recorded = {o["date"] for o in plan.observations}
    for ts in bars.index[65:70]:
        assert ts.date().isoformat() not in recorded


def test_plan_rejects_an_unknown_price_basis(frame):
    bars, _, signal = frame
    with pytest.raises(ValueError, match="price_basis"):
        plan_observations("C", date(2025, 1, 1), bars, signal, "some_intraday_high")


def test_align_drivers_localises_naive_index():
    drivers = pd.DataFrame({"dxy": [1.0, 2.0]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    idx = pd.bdate_range("2026-01-01", periods=3, tz="UTC")
    out = align_drivers(drivers, idx)
    assert out.index.tz is not None
    assert len(out) == 3
    assert out["dxy"].notna().all()


def test_complete_dates_requires_fresh_drivers():
    """Stale drivers must not be scored as observations.

    The raw frame stops half-way; an earlier implementation forward-filled first and
    then checked freshness, which always passed. The contract is now that the raw,
    unfilled frame is what gets passed, and this test pins it.
    """
    idx = pd.bdate_range("2026-01-01", periods=40, tz="UTC")
    gold = pd.Series(2000.0, index=idx)
    drivers = pd.DataFrame(
        {"dxy": np.linspace(100, 99, 20).tolist() + [np.nan] * 20,
         "y10": np.linspace(4, 3, 20).tolist() + [np.nan] * 20},
        index=idx,
    )
    usable = complete_dates(gold, drivers, idx)
    # The rule is "at most max_age_days past the last real observation", so the
    # window extends a week beyond the final driver print and then stops dead.
    assert usable.max() == idx[19] + pd.Timedelta(days=7)
    assert len(usable) == 25
    assert idx[26] not in usable


def test_complete_dates_tolerates_a_short_holiday_gap():
    """A five-day closure is bridged; the data after it is still accepted."""
    idx = pd.bdate_range("2026-01-01", periods=40, tz="UTC")
    gold = pd.Series(2000.0, index=idx)
    drivers = pd.DataFrame({"dxy": np.r_[np.linspace(100, 99, 20), [np.nan] * 5, np.full(15, 98.5)],
                            "y10": np.r_[np.linspace(4, 3, 20), [np.nan] * 5, np.full(15, 2.9)]}, index=idx)
    usable = complete_dates(gold, drivers, idx)
    assert len(usable) == 40, "observations on both sides of the gap are usable"


def test_complete_dates_returns_empty_when_nothing_is_complete():
    idx = pd.bdate_range("2026-01-01", periods=10, tz="UTC")
    gold = pd.Series(np.nan, index=idx)
    drivers = pd.DataFrame({"dxy": np.nan, "y10": np.nan}, index=idx)
    assert len(complete_dates(gold, drivers, idx)) == 0


def test_staleness_flags_old_drivers():
    assert staleness(date(2026, 1, 20), date(2026, 1, 1), limit_days=7) is not None
    assert staleness(date(2026, 1, 3), date(2026, 1, 1), limit_days=7) is None


def test_ledger_is_idempotent_and_refuses_revision(tmp_path):
    idx = pd.bdate_range("2026-01-01", periods=5, tz="UTC")
    bars = pd.DataFrame({"close": np.linspace(2000, 2010, 5)}, index=idx)

    def sig(b):
        return pd.Series(0.5, index=b.index)

    cand = Candidate(id="T-1", name="t", family="t", rationale="t", params={}, signal=sig)
    led = tmp_path / "l.jsonl"
    plan = plan_observations("T-1", date(2025, 12, 1), bars, sig(bars), "m15_utc_close")
    assert len(plan.observations) == 5
    for o in plan.observations:
        forward.log_observation(cand, o["date"], o["signal"], o["gold_close"], path=led)
    assert len(forward.load_ledger(path=led)) == 5
    # Same date, same signal: a no-op.
    first = plan.observations[0]
    forward.log_observation(cand, first["date"], first["signal"], first["gold_close"], path=led)
    assert len(forward.load_ledger(path=led)) == 5
    # Same date, different signal: refused.
    with pytest.raises(ValueError, match="refusing to revise"):
        forward.log_observation(cand, first["date"], 0.9, first["gold_close"], path=led)
