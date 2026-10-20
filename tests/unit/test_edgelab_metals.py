"""Gold/silver ratio construction and signal sanity.

The ratio is built from two separate vendor files. A silent date misalignment
would produce a ratio that mixes one day's gold with another day's silver — a
series that still looks plausible and is entirely fictional.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab.metals import (
    attach_ratio,
    gold_bars,
    gold_silver_ratio,
    gsr_specs,
    load_metals,
)

pytestmark = pytest.mark.skipif(
    not Path("data/raw/longgold/metals/AU.csv").exists(),
    reason="metals CSVs not downloaded (gitignored)",
)


def test_metals_are_aligned_and_positive():
    df = load_metals()
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()
    assert not df.isna().any().any()
    assert (df > 0).all().all()


def test_ratio_matches_the_hand_computation():
    df = load_metals().head(50)
    expected = df["gold"] / df["silver"]
    pd.testing.assert_series_equal(gold_silver_ratio(df), expected, check_names=False)


def test_ratio_is_attached_on_the_same_date():
    df = load_metals()
    bars = gold_bars(df).head(200)
    out = attach_ratio(bars, df)
    assert out["gsr"].notna().all()
    np.testing.assert_allclose(
        out["gsr"].to_numpy(), (df["gold"] / df["silver"]).reindex(bars.index).to_numpy()
    )


def test_ratio_level_is_historically_plausible():
    """Gold/silver has stayed roughly within 10-130; a wider range means bad data."""
    gsr = gold_silver_ratio(load_metals())
    assert 10.0 < float(gsr.min()) < 20.0
    assert 100.0 < float(gsr.max()) < 140.0


def test_signals_require_the_ratio_column():
    bars = gold_bars(load_metals()).head(100)
    for spec in gsr_specs():
        with pytest.raises(ValueError, match="gsr"):
            spec.positions(bars)


def test_signals_bounded_after_attach():
    df = load_metals()
    bars = attach_ratio(gold_bars(df), df)
    for spec in gsr_specs():
        pos = spec.positions(bars)
        assert pos.index.equals(bars.index)
        assert float(np.abs(pos.to_numpy()).max()) <= 1.0 + 1e-12
