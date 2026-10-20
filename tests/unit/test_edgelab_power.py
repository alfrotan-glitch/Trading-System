"""Detection-floor tests.

A gate that reports "no evidence" without saying what evidence it *could* have
detected overstates its own conclusion. These tests pin the arithmetic that
converts "we saw nothing" into "we could not have seen anything smaller than X".
"""

from __future__ import annotations

import pytest

from qts.research.edgelab.power import (
    detection_summary,
    min_detectable_sr,
    years_for,
    years_needed,
)


def test_years_for_is_calendar_equivalent():
    assert years_for(2520, 252) == pytest.approx(10.0)


def test_detection_floor_matches_the_dev_sample():
    """17.8 years at a 2.5 t-stat means nothing below SR ~0.59 was detectable.

    This is the number the verdict must quote: a real SR 0.3 edge — a good
    strategy in live terms — is invisible on this sample.
    """
    assert min_detectable_sr(17.8, 2.5) == pytest.approx(0.593, abs=0.005)


def test_years_needed_quadruples_when_the_effect_halves():
    """Evidence scales with the square of the effect size."""
    assert years_needed(0.6, 2.5) == pytest.approx(17.4, abs=0.2)
    assert years_needed(0.3, 2.5) == pytest.approx(4 * years_needed(0.6, 2.5), rel=1e-9)


def test_resampling_does_not_add_evidence():
    """Daily and hourly bars over the same period must give the same floor.

    t = SR * sqrt(years) is independent of bar frequency, which is why an
    apparent confirmation at a second timeframe is not a second observation.
    """
    daily = detection_summary(n_obs=4481, bars_per_year=252, t_stat=2.5)
    hourly = detection_summary(n_obs=4481 * 24, bars_per_year=252 * 24, t_stat=2.5)
    assert daily["years"] == pytest.approx(hourly["years"])
    assert daily["min_detectable_sr"] == pytest.approx(hourly["min_detectable_sr"])


def test_rejects_degenerate_inputs():
    with pytest.raises(ValueError):
        years_for(100, 0)
    with pytest.raises(ValueError):
        min_detectable_sr(0)
    with pytest.raises(ValueError):
        years_needed(0)
