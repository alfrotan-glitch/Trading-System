"""Long-history gold store: alignment, look-ahead and catalogue invariants.

The macro columns are the dangerous part. `real_yield` is built from *realised*
inflation and is shifted two months precisely so that no bar can see a number that
was not yet published. If that shift is ever removed, every macro hypothesis
silently becomes look-ahead — and would look excellent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab.longgold import LONG_BOUNDS, long_specs

pytestmark = pytest.mark.skipif(
    not __import__("pathlib").Path("data/research/longgold/xauusd_d1_lbma.parquet").exists(),
    reason="51-year store not built (run scripts/edgelab_prepare_longgold.py)",
)


def test_catalogue_is_small_and_labelled():
    """Trial count is a statistical cost, so the catalogue must not sprawl."""
    specs = long_specs()
    assert 10 <= len(specs) <= 20, f"{len(specs)} configurations is a fishing expedition"
    assert len({s.name for s in specs}) == len(specs), "duplicate names"
    for s in specs:
        assert s.rationale, f"{s.name} has no stated economic reason"
        assert s.family


def test_splits_are_chronological_and_disjoint():
    from qts.research.edgelab.longgold import load_long_gold, long_split

    bars = load_long_gold()
    spans = long_split(bars.index)
    assert spans["DEV"].max() < spans["VAL"].min()
    assert spans["VAL"].max() < spans["TEST"].min()
    for a in spans:
        for b in spans:
            if a != b:
                assert set(spans[a]).isdisjoint(set(spans[b]))


def test_holdout_is_not_in_the_long_store():
    """2020-2024 must not leak into a file the development code reads."""
    from qts.research.edgelab.longgold import load_long_gold

    bars = load_long_gold()
    assert bars.index.max() <= pd.Timestamp(LONG_BOUNDS["TEST"][1])


def test_macro_is_release_lagged():
    """The value on date D must come from at least two months earlier.

    Checked against the raw inputs rather than against the stored column, so a
    change to the lag constant or to the alignment code fails here.
    """
    from qts.research.edgelab.longgold import load_long_gold

    bars = load_long_gold()
    d = bars.index[-1]
    # Recompute from raw the way a *zero-lag* build would, then confirm the stored
    # value corresponds to an older month.
    gs10 = pd.read_csv("data/raw/longgold/gs10/GS10.csv", na_values=["."], parse_dates=["DATE"]).set_index("DATE")["GS10"]
    cpi = pd.read_csv("data/raw/longgold/cpi/CPIAUCSL.csv", na_values=["."], parse_dates=["DATE"]).set_index("DATE")["CPIAUCSL"]
    yoy = (cpi / cpi.shift(12) - 1.0) * 100.0
    joint = pd.concat([gs10.rename("gs10"), yoy.rename("yoy")], axis=1, sort=True).dropna()
    joint["ry"] = joint["gs10"] - joint["yoy"]
    month_of = d.normalize().replace(day=1)
    two_back = (month_of - pd.DateOffset(months=2)).normalize().replace(day=1)
    expected = float(joint.loc[:two_back, "ry"].iloc[-1])
    assert bars["real_yield"].iloc[-1] == pytest.approx(expected, abs=0.05)


def test_returns_have_no_absurd_jumps():
    from qts.research.edgelab.longgold import load_long_gold

    bars = load_long_gold()
    r = bars["close"].pct_change().abs()
    assert float(r.max()) < 0.25
    assert (bars["close"] > 0).all()


def test_signals_are_bounded_and_causal():
    """Every signal must produce values in [-1, 1] and never peek ahead."""
    from qts.research.edgelab.longgold import load_long_gold, long_split

    bars = load_long_gold()
    dev = bars.loc[long_split(bars.index)["DEV"]]
    for spec in long_specs():
        pos = spec.positions(dev)
        assert pos.index.equals(dev.index), spec.name
        assert float(np.abs(pos.to_numpy()).max()) <= 1.0 + 1e-12, spec.name
        # Truncating the sample must not change earlier values: no future leakage.
        cut = len(dev) // 2
        truncated = spec.positions(dev.iloc[:cut]).to_numpy()
        np.testing.assert_allclose(
            pos.to_numpy()[:cut], truncated, rtol=0, atol=1e-12, err_msg=spec.name
        )
