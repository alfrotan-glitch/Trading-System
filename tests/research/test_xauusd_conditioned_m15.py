from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.xauusd_conditioned_m15 import (
    HYPOTHESES,
    execution_position,
    hypothesis_signals,
    load_broker_bars,
    run_discovery,
)


def _bars(n: int = 420, gap_at: int | None = None) -> pd.DataFrame:
    stamps = pd.date_range("2026-01-01 00:00:00Z", periods=n, freq="15min")
    if gap_at is not None:
        shifted = stamps.to_series()
        shifted.iloc[gap_at:] += pd.Timedelta(hours=2)
        stamps = pd.DatetimeIndex(shifted)
    close = 2000.0 + np.linspace(0, 40, n)
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close + 0.25,
            "tick_volume": np.full(n, 100),
            "spread": np.full(n, 22),
        }
    )


def _write(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False)
    return path


def test_conditioned_loader_requires_tick_volume(tmp_path: Path) -> None:
    frame = _bars().drop(columns="tick_volume")
    with pytest.raises(ValueError, match="tick_volume"):
        hypothesis_signals(load_broker_bars(_write(frame, tmp_path / "bars.csv")))


def test_signals_are_causal_to_future_mutations(tmp_path: Path) -> None:
    base = _bars()
    changed = base.copy()
    changed.loc[300:, ["open", "high", "low", "close", "tick_volume"]] *= 1.4
    left = hypothesis_signals(load_broker_bars(_write(base, tmp_path / "base.csv")))
    right = hypothesis_signals(load_broker_bars(_write(changed, tmp_path / "changed.csv")))
    for name in left:
        pd.testing.assert_series_equal(left[name].iloc[:300], right[name].iloc[:300])


def test_fixed_hold_and_gap_boundary(tmp_path: Path) -> None:
    frame = load_broker_bars(_write(_bars(gap_at=200), tmp_path / "gapped.csv"))
    signal = pd.Series(0.0, index=frame.index)
    signal.iloc[100] = 1.0
    position = execution_position(frame, signal, hold_bars=4)
    assert position.iloc[100] == 0.0
    assert position.iloc[101:105].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert position.iloc[105] == 0.0
    signal.iloc[198] = 1.0
    position = execution_position(frame, signal, hold_bars=4)
    assert position.iloc[199] == 1.0
    assert position.iloc[200] == 0.0


def test_discovery_is_never_promoted(tmp_path: Path) -> None:
    report = run_discovery(_write(_bars(), tmp_path / "bars.csv"))
    assert report["status"] == "DISCOVERY_ONLY"
    assert report["validated_edge"] is False
    assert report["strategy_promoted"] is False
    assert set(report["hypotheses"]) == set(HYPOTHESES)
    assert report["safety"]["orders_submitted"] == 0
