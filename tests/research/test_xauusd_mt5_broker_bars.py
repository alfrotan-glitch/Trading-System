from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.xauusd_mt5_broker_bars import (
    execution_position,
    hypothesis_signals,
    load_broker_bars,
    run_discovery,
)


def _bars(n: int = 180, gap_at: int | None = None) -> pd.DataFrame:
    stamps = pd.date_range("2026-01-01 00:00:00Z", periods=n, freq="15min")
    if gap_at is not None:
        stamps = stamps.to_series()
        stamps.iloc[gap_at:] += pd.Timedelta(hours=2)
        stamps = pd.DatetimeIndex(stamps)
    close = 2000.0 + np.linspace(0, 20, n)
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close + 0.25,
            "spread": np.full(n, 22),
        }
    )


def test_loader_refuses_to_repair_invalid_bars(tmp_path: Path) -> None:
    bad = _bars(20)
    bad.loc[5, "high"] = bad.loc[5, "open"] - 1.0
    path = tmp_path / "bad.csv"
    bad.to_csv(path, index=False)
    with pytest.raises(ValueError, match="high invariant"):
        load_broker_bars(path)


def test_signals_are_causal_to_future_mutations() -> None:
    base = _bars()
    changed = base.copy()
    changed.loc[120:, ["open", "high", "low", "close"]] *= 1.4
    left = hypothesis_signals(load_broker_bars(_write(base)))
    right = hypothesis_signals(load_broker_bars(_write(changed)))
    for name in left:
        pd.testing.assert_series_equal(left[name].iloc[:120], right[name].iloc[:120])


def test_gap_creates_a_hard_flatten_boundary() -> None:
    frame = load_broker_bars(_write(_bars(gap_at=80)))
    signals = hypothesis_signals(frame)
    signal = signals["H-MT5-TREND-12"]
    position = execution_position(frame, signal)
    # The pre-gap signal can be active, but execution must be flat on the first
    # observed bar after the missing interval.
    assert signal.iloc[79] != 0
    assert position.iloc[80] == 0.0
    report = run_discovery(_write(frame.reset_index().rename(columns={"index": "timestamp"})))
    split = report["hypotheses"]["H-MT5-TREND-12"]["splits"]["HOLDOUT_20"]
    assert all(row["cost_basis"].startswith("ASSUMED") for row in split.values())
    assert report["safety"]["orders_submitted"] == 0


def test_discovery_report_never_promotes_and_has_all_fixed_hypotheses() -> None:
    report = run_discovery(_write(_bars()))
    assert report["status"] == "DISCOVERY_ONLY"
    assert report["validated_edge"] is False
    assert report["strategy_promoted"] is False
    assert set(report["hypotheses"]) == {
        "H-MT5-TREND-12",
        "H-MT5-REVERT-4",
        "H-MT5-BREAKOUT-32",
        "H-MT5-SESSION-MOM-4",
    }
    for payload in report["hypotheses"].values():
        assert payload["status"] == "DISCOVERY_ONLY"


def _write(frame: pd.DataFrame) -> Path:
    # The tests use the real loader to pin CSV parsing and timestamp semantics.
    import tempfile

    path = Path(tempfile.gettempdir()) / "qts_mt5_broker_bars_test.csv"
    frame.to_csv(path, index=False)
    return path
