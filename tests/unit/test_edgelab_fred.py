"""FRED-mirrored drivers: provenance checks and the alignment that broke once.

``align_to_index`` exists because an earlier version of the holdout script
forward-filled a naive-index driver frame onto a tz-aware bar index and got a
*constant* column. Nothing raised: the strategy simply never took a position and
reported a flat line. That is the worst class of bug in this project — a silent
zero that looks like a result — so it gets a test that fails loudly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import fred_drivers as F


def test_align_to_index_fills_forward_without_flattening():
    """The regression test: a naive driver frame onto a tz-aware index."""
    drv = pd.DataFrame(
        {"dxy": [100.0, 101.0, 102.0, 103.0], "y10": [4.0, 4.1, 4.2, 4.3]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    bars = pd.DatetimeIndex(
        pd.to_datetime(["2024-01-02", "2024-01-04", "2024-01-05"]).tz_localize("UTC")
    )
    out = F.align_to_index(drv, bars)
    assert list(out.index) == list(bars)
    # Values must vary — a constant column is the bug this guards against.
    assert out["dxy"].nunique() == 2
    assert out["dxy"].iloc[0] == pytest.approx(101.0)
    assert out["dxy"].iloc[1] == pytest.approx(103.0)
    assert out["dxy"].iloc[2] == pytest.approx(103.0)  # forward-filled, not dropped


def test_align_to_index_rejects_an_empty_frame():
    with pytest.raises(ValueError, match="empty"):
        F.align_to_index(pd.DataFrame({"dxy": [], "y10": []}), pd.DatetimeIndex([]))


def test_validate_series_reports_identity_and_drift():
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
    same = F.validate_series(a, a.copy(), "same")
    assert same["identical"] and same["max_abs_diff"] == 0.0
    shifted = F.validate_series(a, a + 0.5, "shifted")
    assert not shifted["identical"]
    assert shifted["max_abs_diff"] == pytest.approx(0.5)


def test_validate_series_handles_disjoint_ranges():
    a = pd.Series([1.0, 2.0], index=pd.date_range("2020-01-01", periods=2, freq="D"))
    b = pd.Series([1.0, 2.0], index=pd.date_range("2021-01-01", periods=2, freq="D"))
    out = F.validate_series(a, b, "disjoint")
    assert out["overlap_obs"] == 0
    assert out["identical"] is False


def test_index_agreement_is_perfect_for_identical_series():
    idx = pd.bdate_range("2010-01-01", periods=600)
    px = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(5).normal(0, 0.01, 600))), index=idx)
    out = F.index_agreement(px, px)
    assert out["level_corr"] == pytest.approx(1.0)
    assert out["flag_agreement"] == pytest.approx(1.0)


def test_index_agreement_reads_the_flag_not_the_level():
    """Two inversely-related indices disagree on flags while correlating -1."""
    idx = pd.bdate_range("2010-01-01", periods=600)
    a = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(9).normal(0, 0.01, 600))), index=idx)
    out = F.index_agreement(a, 1.0 / a)
    assert out["level_corr"] < -0.9
    assert out["flag_agreement"] == pytest.approx(0.0, abs=0.05)


@pytest.mark.parametrize("loader", ["load_treasury_10y", "load_broad_dollar"])
def test_loaders_raise_a_useful_error_when_data_is_absent(loader, tmp_path, monkeypatch):
    """Missing raw data must name the file, not fail with a bare FileNotFoundError."""
    monkeypatch.setattr(F, "FRED_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="sgdividends"):
        getattr(F, loader)()


def test_real_yield_loader_accepts_negative_yields(tmp_path, monkeypatch):
    """Real yields were negative for most of 2011-2021.

    The positivity guard is correct for a price level and wrong for a yield; it
    rejected the actual DFII10 history and broke `scripts/edgelab_realyield_run.py`.
    """
    p = tmp_path / "treasury_10y_real.csv"
    p.write_text("date,value\n2020-01-02,-0.15\n2020-01-03,-0.20\n2020-01-06,0.02\n", encoding="utf-8")
    monkeypatch.setattr(F, "FRED_DIR", tmp_path)
    s = F.load_treasury_10y_real()
    assert s.min() == pytest.approx(-0.20)
    assert len(s) == 3


def test_price_level_loader_still_rejects_non_positive(tmp_path, monkeypatch):
    p = tmp_path / "treasury_10y.csv"
    p.write_text("date,value\n2020-01-02,1.5\n2020-01-03,0\n", encoding="utf-8")
    monkeypatch.setattr(F, "FRED_DIR", tmp_path)
    with pytest.raises(ValueError, match="non-positive"):
        F.load_treasury_10y()
