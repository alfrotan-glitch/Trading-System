"""Price-snapshot timing: the guardrail added after XL-001's gate pass was found
to be an artifact of sampling gold at 10:30 London and the drivers at 22:00.

The tests that matter encode the two failure modes actually observed:

* a rule scored at a lag the data does not permit (fixed by ``required_lag``);
* a driver frame that silently collapses to a constant (fixed by
  ``detect_misaligned_index``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import timing as T


def test_am_fix_against_close_drivers_requires_one_bar():
    """The XL-001 case: fill at 10:30, drivers known at 22:00 -> must wait a bar."""
    audit = T.audit_required_lag("lbma_am_fix", ("dxy_close", "y10_close"))
    assert audit["required_lag"] == 1
    assert "precedes" in audit["explanation"]


def test_utc_close_against_close_drivers_needs_no_lag():
    """A 24:00 UTC close is struck after the 22:00 UTC driver settles."""
    audit = T.audit_required_lag("m15_utc_close", ("dxy_close", "y10_close"))
    assert audit["required_lag"] == 0


def test_required_lag_is_about_ordering_not_magnitude():
    early = T.Snapshot("early", 8.0)
    late = T.Snapshot("late", 20.0)
    assert T.required_lag(early, late) == 1  # fill before information
    assert T.required_lag(late, early) == 0  # fill after information
    # Identical timestamps still require a bar: the close is not known before it
    # prints, so acting at the same instant is not executable.
    same = T.Snapshot("same", 20.0)
    assert T.required_lag(same, late) == 1


def test_snapshot_string_is_readable():
    assert str(T.GOLD_PRICE_SNAPSHOTS["lbma_am_fix"]) == "LBMA AM fix @ 10:30 UTC"
    assert str(T.GOLD_PRICE_SNAPSHOTS["m15_utc_close"]) == "M15 UTC close @ 24:00 UTC"


def test_apply_lag_refuses_negative_lag():
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="look-ahead"):
        T.apply_lag(s, -1)


def test_apply_lag_zero_is_identity():
    s = pd.Series([1.0, 2.0, 3.0])
    assert T.apply_lag(s, 0) is s


def test_timing_robustness_tabulates_each_lag():
    table = T.timing_robustness(lambda lag: {"alpha_ann": 0.05 / (lag + 1), "alpha_t": 3.0 / (lag + 1)}, lags=(0, 1, 2))
    assert list(table.index) == [0, 1, 2]
    assert table.loc[0, "alpha_t"] == pytest.approx(3.0)
    assert table.loc[2, "alpha_t"] == pytest.approx(1.0)


def test_verdict_reports_survival_at_the_required_lag():
    table = T.timing_robustness(lambda lag: {"alpha_ann": 0.06 if lag == 0 else 0.01, "alpha_t": 2.9 if lag == 0 else 0.8}, lags=(0, 1))
    v = T.verdict_at_lag(table, required=1, threshold=2.5)
    assert v["survives"] is False
    assert v["lag0_alpha_t"] == pytest.approx(2.9)
    assert v["alpha_t"] == pytest.approx(0.8)
    assert v["decay"] == pytest.approx(2.1)


def test_verdict_passes_when_the_effect_survives_the_required_lag():
    table = T.timing_robustness(lambda lag: {"alpha_ann": 0.04, "alpha_t": 2.8 - 0.1 * lag}, lags=(0, 1))
    assert T.verdict_at_lag(table, required=1, threshold=2.5)["survives"] is True


def test_verdict_rejects_a_missing_lag():
    table = T.timing_robustness(lambda lag: {"alpha_ann": 0.04, "alpha_t": 2.8}, lags=(0,))
    with pytest.raises(ValueError, match="required lag 1 not present"):
        T.verdict_at_lag(table, required=1, threshold=2.5)


def test_detect_misaligned_index_catches_a_constant_column():
    """The bug that produced a flat equity curve with no error anywhere."""
    idx = pd.bdate_range("2020-01-01", periods=50, tz="UTC")
    drv = pd.DataFrame({"dxy": 100.0, "y10": np.linspace(1, 2, 50)}, index=idx)
    out = T.detect_misaligned_index(drv, idx)
    assert out["constant_columns"] == ["dxy"]
    assert out["ok"] is False


def test_detect_misaligned_index_catches_no_overlap():
    drv = pd.DataFrame({"dxy": [1.0, 2.0]}, index=pd.bdate_range("2020-01-01", periods=2, tz="UTC"))
    prices = pd.bdate_range("2021-01-01", periods=5, tz="UTC")
    out = T.detect_misaligned_index(drv, prices)
    assert out["overlapping_dates"] == 0
    assert out["ok"] is False


def test_detect_misaligned_index_passes_a_healthy_frame():
    idx = pd.bdate_range("2020-01-01", periods=50, tz="UTC")
    rng = np.random.default_rng(1)
    drv = pd.DataFrame({"dxy": rng.normal(100, 1, 50), "y10": rng.normal(2, 0.1, 50)}, index=idx)
    assert T.detect_misaligned_index(drv, idx)["ok"] is True
