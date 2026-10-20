"""Panel loader behaviour.

The cross-section is only meaningful if each instrument's series is clean and
scale-invariant. Prices in this export are scaled by 100 or 1000 depending on the
instrument; that is fine for returns and bps costs, but a loader that silently
mis-orders or duplicates timestamps would corrupt every measurement built on it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qts.research.edgelab.crosssection import (
    INSTRUMENTS,
    PANEL_END,
    PANEL_START,
    load_instrument,
    load_panel,
)


def _panel_available() -> bool:
    try:
        load_instrument("XAUUSD", end="2018-12-31")
        return True
    except (FileNotFoundError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _panel_available(), reason="cross-section panel not downloaded (gitignored)"
)


def test_panel_has_the_expected_universe():
    assert "XAUUSD" in INSTRUMENTS
    assert len(INSTRUMENTS) == 12
    assert len(set(INSTRUMENTS)) == 12


def test_bars_are_sorted_and_unique():
    df = load_instrument("XAUUSD", end="2018-12-31")
    assert df.index.is_monotonic_increasing
    assert not df.index.has_duplicates
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_ohlc_is_internally_consistent():
    df = load_instrument("EURUSD", end="2018-12-31")
    assert (df["high"] >= df["low"]).all()
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
    assert (df["close"] > 0).all()


def test_window_is_clipped_to_pre_holdout():
    """The cross-section must never read past DEV to answer a rule-family question."""
    df = load_instrument("XAUUSD", end="2018-12-31")
    assert df.index.max() <= pd.Timestamp("2018-12-31")


def test_panel_loader_clips_every_instrument():
    panel = load_panel(end="2018-12-31")
    assert panel, "panel should not be empty when data is present"
    for name, df in panel.items():
        assert df.index.max() <= pd.Timestamp("2018-12-31"), name
        assert len(df) > 0, name


def test_declared_window_is_covered_by_every_instrument():
    """PANEL_START/END describe the *shared* window, not any one instrument's span.

    Gold starts earlier than 2012-11-14; the contract is that every instrument
    covers the declared common window, which is what makes cross-comparison valid.
    """
    start, end = pd.Timestamp(PANEL_START).date(), pd.Timestamp(PANEL_END).date()
    for name in ("XAUUSD", "EURUSD", "USDJPY"):
        df = load_instrument(name)
        # Compare dates, not instants: instruments open at different times of day.
        assert df.index.min().date() <= start, name
        assert df.index.max().date() >= end, name
