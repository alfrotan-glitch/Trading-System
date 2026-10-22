from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.xauusd_mt5_broker_bars import (
    _summary,
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


def test_signals_are_causal_to_future_mutations(tmp_path: Path) -> None:
    base = _bars()
    changed = base.copy()
    changed.loc[120:, ["open", "high", "low", "close"]] *= 1.4
    left = hypothesis_signals(load_broker_bars(_write(base, tmp_path / "base.csv")))
    right = hypothesis_signals(load_broker_bars(_write(changed, tmp_path / "changed.csv")))
    for name in left:
        pd.testing.assert_series_equal(left[name].iloc[:120], right[name].iloc[:120])


def test_gap_creates_a_hard_flatten_boundary(tmp_path: Path) -> None:
    frame = load_broker_bars(_write(_bars(gap_at=80), tmp_path / "gapped.csv"))
    signals = hypothesis_signals(frame)
    signal = signals["H-MT5-TREND-12"]
    position = execution_position(frame, signal)
    # The pre-gap signal can be active, but execution must be flat on the first
    # observed bar after the missing interval.
    assert signal.iloc[79] != 0
    assert position.iloc[80] == 0.0
    report = run_discovery(
        _write(frame.reset_index().rename(columns={"index": "timestamp"}), tmp_path / "gapped_report.csv")
    )
    split = report["hypotheses"]["H-MT5-TREND-12"]["splits"]["HOLDOUT_20"]
    assert all(row["cost_basis"].startswith("ASSUMED") for row in split.values())
    assert report["safety"]["orders_submitted"] == 0


def test_discovery_report_never_promotes_and_has_all_fixed_hypotheses(tmp_path: Path) -> None:
    report = run_discovery(_write(_bars(), tmp_path / "bars.csv"))
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


def test_daily_excess_compares_compounded_strategy_and_control_returns() -> None:
    index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="12h")
    strategy = pd.Series([0.10, 0.10], index=index)
    control = pd.Series([0.05, 0.05], index=index)
    summary = _summary(strategy, strategy, control, pd.Series([1.0, 1.0], index=index))
    assert summary["mean_daily_excess_vs_control"] == pytest.approx(0.21 - 0.1025)


def _write(frame: pd.DataFrame, path: Path) -> Path:
    # The tests use the real loader to pin CSV parsing and timestamp semantics.
    frame.to_csv(path, index=False)
    return path
