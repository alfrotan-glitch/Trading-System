"""Daily macro drivers: alignment and causality.

DXY and the 10-year yield trade on calendars that do not match gold's. A forward
fill across a mismatched calendar is the right choice, but only if it is applied
per column and never shifts a value backwards in time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qts.research.edgelab.macro_daily import (
    attach_macro_daily,
    load_macro_daily,
    macro_daily_specs,
    usd_trend,
    yield_trend,
)
from qts.research.edgelab.metals import gold_bars, load_metals

pytestmark = pytest.mark.skipif(
    not Path("data/raw/longgold/macro_daily/DXY.csv").exists(),
    reason="daily macro CSVs not downloaded (gitignored)",
)


def test_macro_series_are_clean_and_long():
    df = load_macro_daily()
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()
    assert not df.isna().any().any()
    assert df.index.min().year <= 1971
    assert (df > 0).all().all()


def test_dxy_range_is_historically_plausible():
    dxy = load_macro_daily()["dxy"]
    assert 70.0 < float(dxy.min()) < 100.0
    assert 100.0 < float(dxy.max()) < 170.0


def test_attach_forward_fills_without_lookahead():
    """A bar must never carry a macro value from a later date."""
    metals = load_metals()
    bars = attach_macro_daily(gold_bars(metals))
    m = load_macro_daily()
    assert {"dxy", "y10"}.issubset(bars.columns)
    # Every attached value must exist in the source at or before that date.
    sample = bars.dropna(subset=["dxy"]).index[::500]
    for d in sample:
        assert d >= m.index[0]
        prior = m.loc[:d, "dxy"]
        assert not prior.empty
        assert bars.loc[d, "dxy"] == pytest.approx(float(prior.iloc[-1]))


def test_signals_require_their_columns():
    metals = load_metals()
    plain = gold_bars(metals)
    with pytest.raises(ValueError, match="dxy"):
        usd_trend(plain)
    with pytest.raises(ValueError, match="y10"):
        yield_trend(plain)


def test_signals_are_bounded_and_reproducible():
    metals = load_metals()
    bars = attach_macro_daily(gold_bars(metals)).dropna(subset=["dxy", "y10"])
    for spec in macro_daily_specs():
        pos = spec.positions(bars)
        assert pos.index.equals(bars.index)
        assert float(np.abs(pos.to_numpy()).max()) <= 1.0 + 1e-12
        # Truncation must not change history: no future leakage.
        cut = len(bars) // 2
        truncated = spec.positions(bars.iloc[:cut]).to_numpy()
        np.testing.assert_allclose(pos.to_numpy()[:cut], truncated, rtol=0, atol=1e-12, err_msg=spec.name)
