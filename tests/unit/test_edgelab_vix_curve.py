"""Integrity properties for a genuinely new, still UNVALIDATED research channel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab.vix_curve import align_to_gold, curve_frame, fixed_cadence_signal, read_cboe_history


def test_cboe_csv_parser_does_not_invent_dates_or_prices():
    text = 'Cboe history\nDATE,OPEN,HIGH,LOW,CLOSE\n01/02/2024,18,20,17,19\n01/03/2024,20,22,18,21\n'
    s = read_cboe_history(text, name="VIX")
    assert s.index.tz is not None
    assert len(s) == 2
    assert s.iloc[1] == 21
    assert s.index[0] == pd.Timestamp("2024-01-02", tz="UTC")


@pytest.mark.parametrize("bad", [
    "date,close\n2024-01-02,18\n2024-01-02,21",
    "DATE,CLOSE\n2024-01-02,-1",
    "DATE,CLOSE\n2024-01-02,n/a",
    "not a CSV",
])
def test_cboe_csv_rejects_corrupt_history(bad):
    with pytest.raises(ValueError):
        read_cboe_history(bad, name="VIX")


def _curve(size: int = 150) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-02", periods=size, tz="UTC")
    return pd.DataFrame(
        {"VIX": np.full(size, 20.0), "VIX3M": np.full(size, 24.0)}, index=idx
    )


def test_curve_signal_is_causal_and_uses_one_extra_publication_delay():
    curve = _curve()
    full = fixed_cadence_signal(curve, direction="contango")
    cut = 100
    truncated = fixed_cadence_signal(curve.iloc[:cut], direction="contango")
    pd.testing.assert_series_equal(full.iloc[:cut], truncated)
    # Before the first 21-day rebalance plus a full publication delay, no trade.
    assert (full.iloc[:22] == 0.0).all()
    assert full.iloc[23] == 1.0
    # Editing prices from the FUTURE cannot affect the position already taken.
    changed = curve.copy()
    changed.loc[changed.index[120]:, "VIX3M"] = 5.0
    altered = fixed_cadence_signal(changed, direction="contango")
    pd.testing.assert_series_equal(full.iloc[:120], altered.iloc[:120])


def test_both_directions_declared_and_complementary_after_warmup():
    curve = _curve()
    c = fixed_cadence_signal(curve, direction="contango")
    b = fixed_cadence_signal(curve, direction="backwardation")
    assert c.iloc[-1] == 1.0 and b.iloc[-1] == 0.0
    with pytest.raises(ValueError, match="direction"):
        fixed_cadence_signal(curve, direction="invented")


def test_align_uses_only_past_cboe_data_and_refuses_stale_days():
    curve = _curve(60)
    pos = fixed_cadence_signal(curve, direction="contango")
    date = curve.index[-1]
    gold_idx = pd.DatetimeIndex(
        [date - pd.Timedelta(days=1), date + pd.Timedelta(days=2), date + pd.Timedelta(days=8)]
    )
    out = align_to_gold(pos, gold_idx)
    assert out.iloc[0] == 1.0
    assert out.iloc[1] == 1.0
    assert out.iloc[2] == 0.0  # 8 days old -> no position


def test_merge_requires_common_observations():
    a = read_cboe_history("DATE,CLOSE\n2024-01-02,20\n2024-01-03,21", name="VIX")
    b = read_cboe_history("DATE,CLOSE\n2024-01-03,23\n2024-01-04,24", name="VIX3M")
    combined = curve_frame(a, b)
    assert len(combined) == 1
    assert combined.iloc[0]["VIX"] == 21
    assert combined.iloc[0]["VIX3M"] == 23
