"""Tests for the stress-complex signals (round 12) and their data guards."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab import stress as S

INDEX = pd.bdate_range("2005-01-03", "2008-12-31")

_HAS_DATA = (Path(__file__).resolve().parents[2] / "data" / "raw" / "longgold").exists()
needs_data = pytest.mark.skipif(not _HAS_DATA, reason="raw data not present (gitignored); see MISSION_STATE recovery")



@needs_data
def test_stress_frame_rejects_a_truncated_mirror(monkeypatch):
    """A rolling-window CSV must fail loudly, not quietly shorten the backtest."""
    short = pd.Series(1.0, index=pd.date_range("2023-01-02", periods=400, tz="UTC"))
    real = S.load_fred

    def fake_load(name: str, *, positive: bool = False):
        return short if name == "vix" else real(name, positive=positive)

    monkeypatch.setattr(S, "load_fred", fake_load)
    with pytest.raises(ValueError, match="rolling window"):
        S.stress_frame(INDEX)


def test_trend_flags_only_rising_indicators():
    idx = pd.bdate_range("2005-01-03", periods=300)
    up = pd.Series(np.linspace(10, 40, 300), index=idx)
    down = pd.Series(np.linspace(40, 10, 300), index=idx)
    assert S._trend(up, 21).iloc[-1] == 1.0
    assert S._trend(down, 21).iloc[-1] == 0.0
    # NaN before the window is complete, never a silent 0 that would look like a view.
    assert S._trend(up, 21).iloc[:21].isna().all()


def test_regime_flags_only_above_median():
    idx = pd.bdate_range("2005-01-03", periods=400)
    s = pd.Series(np.sin(np.arange(400) / 12) + 5, index=idx)
    out = S._regime(s, window=100).dropna()
    assert set(np.unique(out.to_numpy())) <= {0.0, 1.0}
    assert out.mean() == pytest.approx(0.5, abs=0.08)


def test_composite_is_the_mean_of_its_four_legs(monkeypatch):
    """The composite must be exactly the average of the four declared legs."""
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        rng.normal(0, 1, (len(INDEX), 4)).cumsum(axis=0) / 10,
        index=INDEX,
        columns=["vix", "baa10y", "nfci", "stress"],
    )
    monkeypatch.setattr(S, "stress_frame", lambda index: frame)
    comp = S.stress_composite(INDEX)
    legs = pd.concat(
        [
            S._trend(frame["vix"], S.LOOKBACK_DAYS["short"]),
            S._trend(frame["baa10y"], S.LOOKBACK_DAYS["medium"]),
            S._trend(frame["nfci"], S.LOOKBACK_DAYS["medium"]),
            S._trend(frame["stress"], S.LOOKBACK_DAYS["medium"]),
        ],
        axis=1,
    )
    expected = legs.mean(axis=1).fillna(0.0).clip(0.0, 1.0)
    pd.testing.assert_series_equal(comp, expected.rename("stress_composite"))
    assert comp.between(0.0, 1.0).all()


@needs_data
def test_tradable_gold_is_utc_positive_and_monotonic():
    g = S.tradable_gold()
    assert g.index.is_monotonic_increasing
    assert g.index.tz is not None, "a tz-naive index silently breaks joins against FRED"
    assert (g > 0).all()
    assert len(g) > 5000
    if g.attrs.get("splice_at"):
        splice = pd.Timestamp(g.attrs["splice_at"], tz="UTC")
        assert g.index.min() < splice < g.index.max()


@needs_data
def test_signals_are_defensive_on_short_history():
    """With fewer bars than the lookback, signals must return zeros, not NaN."""
    short_idx = pd.bdate_range("2005-01-03", periods=5)
    for fn in (S.vix_trend, S.vix_regime, S.credit_trend, S.credit_regime):
        out = fn(short_idx)
        assert out.notna().all(), f"{fn.__name__} leaked NaN on short history"
        assert (out == 0.0).all(), f"{fn.__name__} took a view without enough history"
