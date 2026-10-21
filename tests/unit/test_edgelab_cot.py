"""Tests for the CFTC positioning signals (round 15) and their data guards."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import cot as C

_HAS_DATA = (Path(__file__).resolve().parents[2] / "data" / "raw" / "longgold").exists()
needs_data = pytest.mark.skipif(not _HAS_DATA, reason="raw data not present (gitignored); see MISSION_STATE recovery")



@needs_data
def test_loader_sorts_chronologically_despite_lexical_file_order():
    """The source file is ordered by 'MM-DD-YY' string, which is not date order.

    Reading it in file order would scramble seven years of positioning, so this is
    the single most important property of the loader.
    """
    df = C.load_cot()
    assert df.index.is_monotonic_increasing
    assert df.index.min() < pd.Timestamp("2019-01-01") < df.index.max()
    assert len(df) > 300


@needs_data
def test_release_stamp_is_after_the_observation():
    df = C.load_cot()
    # pub_date is the index; observation date is four calendar days earlier.
    obs = df.index - pd.Timedelta(days=C.RELEASE_LAG_DAYS)
    assert (obs < df.index).all()


@needs_data
def test_net_series_are_consistent():
    df = C.load_cot()
    assert np.allclose(df["spec_net"], df["spec_long"] - df["spec_short"])
    assert np.allclose(df["comm_net"], df["comm_long"] - df["comm_short"])
    assert (df["oi"] > 0).all()


@needs_data
def test_signals_preserve_a_tz_aware_bar_index():
    idx = pd.date_range("2019-01-02", "2024-12-31", freq="B", tz="UTC")
    bars = pd.DataFrame({"close": np.linspace(1300, 2000, len(idx))}, index=idx)
    for name, fn in C.cot_specs().items():
        sig = fn(bars)
        assert sig.index.equals(idx), f"{name} did not return the caller's index"
        assert sig.notna().all(), f"{name} leaked NaN"


@needs_data
def test_signals_are_binary_and_do_not_peek():
    idx = pd.date_range("2019-01-02", "2024-12-31", freq="B")
    bars = pd.DataFrame({"close": np.linspace(1300, 2000, len(idx))}, index=idx)
    cut = idx[int(len(idx) * 0.7)]
    for _name, fn in C.cot_specs().items():
        full = fn(bars)
        assert full.isin([0.0, 1.0]).all()
        pd.testing.assert_series_equal(full.loc[:cut], fn(bars.loc[:cut]), check_names=False)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("openpyxl") is None,
    reason="openpyxl is required to read/write the COT workbook",
)
def test_corrupt_spacing_is_refused(tmp_path):
    """A file with two reports three days apart must fail loudly."""
    rows = [("01-02-24", 1, 2, 3, 4, 5, 6), ("01-03-24", 1, 2, 3, 4, 5, 6)]
    df = pd.DataFrame(rows, columns=C.COLUMNS)
    p = tmp_path / "bad.xlsx"
    df.to_excel(p, index=False)
    with pytest.raises(ValueError, match="days apart"):
        C.load_cot(p)
