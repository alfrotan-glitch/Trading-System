"""Tests for the cross-market miners signal (round 18)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import miners as M

_HAS_DATA = (Path(__file__).resolve().parents[2] / "data" / "raw" / "longgold").exists()
needs_data = pytest.mark.skipif(not _HAS_DATA, reason="raw data not present (gitignored)")


@needs_data
def test_loader_is_positive_and_sorted():
    s = M.load_miners()
    assert s.index.is_monotonic_increasing
    assert (s > 0).all()
    assert len(s) > 4000


@needs_data
def test_tz_alignment_is_enforced_not_silent():
    """A tz mismatch must never degrade into an all-zero signal.

    ``miner_dip`` on a tz-naive bar index has to produce actual positions; an empty
    reindex used to yield zero everywhere, which looks like a valid "never trades"
    result rather than a bug.
    """
    idx = pd.bdate_range("2010-01-04", "2020-12-31")
    close = pd.Series(np.linspace(1000, 1800, len(idx)), index=idx)
    bars = pd.DataFrame({"close": close}, index=idx)
    assert bars.index.tz is None
    sig = M.miner_dip(bars)
    assert sig.index.equals(idx)
    assert float(sig.abs().sum()) > 0, "signal collapsed to zero — alignment failed silently"


@needs_data
def test_signals_are_binary_and_disagree_by_construction():
    idx = pd.bdate_range("2010-01-04", "2020-12-31")
    close = pd.Series(np.linspace(1000, 1800, len(idx)), index=idx)
    bars = pd.DataFrame({"close": close}, index=idx)
    dip, mom = M.miner_dip(bars), M.miner_momentum(bars)
    for s in (dip, mom):
        assert s.isin([0.0, 1.0]).all()
    # Declared in advance as opposite signs; if both were long the round would be a
    # one-sided bet rather than a test.
    assert (dip * mom).sum() == 0.0


@needs_data
def test_signals_do_not_peek():
    idx = pd.bdate_range("2010-01-04", "2020-12-31")
    close = pd.Series(np.linspace(1000, 1800, len(idx)), index=idx)
    bars = pd.DataFrame({"close": close}, index=idx)
    cut = idx[int(len(idx) * 0.7)]
    for _name, fn in M.miner_specs().items():
        pd.testing.assert_series_equal(fn(bars).loc[:cut], fn(bars.loc[:cut]), check_names=False)


def test_timing_guardrail_requires_a_lag_against_the_gold_fix():
    """The whole point of round 18: miners close after the fix, so lag must be 1."""
    from qts.research.edgelab.timing import audit_required_lag

    out = audit_required_lag("lbma_am_fix", ("miners_equity_close",))
    assert out["required_lag"] == 1
