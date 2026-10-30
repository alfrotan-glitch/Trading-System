from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qts.research.longhistory.sahm_u3_gate import (
    InputBlocked,
    apply_sahm_gate,
    lagged_sahm_gap,
    read_eligible_u3,
)
from qts.research.longhistory.signals import Plan


def _monthly_index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="ME", name="date")


def _write_source(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["DATE", "UNRATE"])
        writer.writerows(rows)


def _base_plan(index: pd.DatetimeIndex) -> Plan:
    n = len(index)
    return Plan(
        target=np.ones(n, dtype=float),
        size=np.full(n, 0.5, dtype=float),
        stop_dist=np.full(n, np.nan, dtype=float),
        rebalance=np.zeros(n, dtype=bool),
        family="synthetic_base",
        params={},
    )


def test_loader_skips_post_1999_u3_value_without_numeric_conversion(tmp_path: Path) -> None:
    dates = pd.date_range("1948-01-01", "1999-12-01", freq="MS")
    rows = [(stamp.strftime("%Y-%m-%d"), "5.0") for stamp in dates]
    rows.append(("2000-01-01", "DO_NOT_PARSE_POST_CUTOFF"))
    path = tmp_path / "UNRATE.csv"
    _write_source(path, rows)

    u3, metadata = read_eligible_u3(
        path,
        expected_sha256=None,
        expected_git_blob_sha1=None,
        expected_months=pd.date_range("1948-01-31", "1999-12-31", freq="ME"),
    )

    assert len(u3) == 624
    assert u3.index[0] == pd.Timestamp("1948-01-31")
    assert u3.index[-1] == pd.Timestamp("1999-12-31")
    assert metadata["post_1999_rows_skipped_using_date_only"] == 1
    assert metadata["post_1999_u3_values_converted"] == 0


def test_loader_fails_on_missing_eligible_month(tmp_path: Path) -> None:
    dates = pd.date_range("1998-01-01", "1999-12-01", freq="MS").delete(4)
    rows = [(stamp.strftime("%Y-%m-%d"), "5.0") for stamp in dates]
    path = tmp_path / "UNRATE.csv"
    _write_source(path, rows)

    with pytest.raises(InputBlocked, match="coverage mismatch"):
        read_eligible_u3(
            path,
            expected_sha256=None,
            expected_git_blob_sha1=None,
            expected_months=pd.date_range("1998-01-31", "1999-12-31", freq="ME"),
        )


def test_sahm_formula_threshold_and_two_month_release_lag() -> None:
    index = _monthly_index("1990-01-31", 24)
    values = np.full(len(index), 5.0)
    values[15:18] = 5.5
    u3 = pd.Series(values, index=index, name="U3_percent")

    feature = lagged_sahm_gap(u3, index)
    source_month = index[17]
    decision_month = index[19]
    assert feature.loc[index[18]] < 0.50
    assert feature.loc[decision_month] == pytest.approx(0.50)
    rolling = u3.rolling(3, min_periods=3).mean()
    prior_minimum = rolling.shift(1).rolling(12, min_periods=12).min()
    expected_gap = rolling.loc[source_month] - prior_minimum.loc[source_month]
    assert feature.loc[decision_month] == pytest.approx(expected_gap)

    # Two future U3 observations cannot change the earlier decision feature.
    truncated = lagged_sahm_gap(u3.loc[:decision_month], index[:20])
    pd.testing.assert_series_equal(feature.loc[:decision_month], truncated.loc[:decision_month])


def test_sahm_feature_warmup_and_missing_values_fail_closed() -> None:
    index = _monthly_index("1990-01-31", 20)
    u3 = pd.Series(np.full(len(index), 5.0), index=index, name="U3_percent")
    feature = lagged_sahm_gap(u3, index)
    assert feature.iloc[:16].isna().all()
    assert np.isfinite(feature.iloc[16:].to_numpy(dtype=float)).all()

    with pytest.raises(InputBlocked, match="missing, non-finite"):
        lagged_sahm_gap(u3.mask(u3.index == index[8]), index)


def test_sahm_gate_uses_inclusive_frozen_half_point_threshold() -> None:
    index = _monthly_index("1990-01-31", 3)
    base = _base_plan(index)
    feature = pd.Series([0.499, 0.500, 0.501], index=index, name="sahm_gap_lag2_pp")

    gated = apply_sahm_gate(base, feature, index=index)

    np.testing.assert_array_equal(gated.target, np.array([0.0, 1.0, 1.0]))
    np.testing.assert_array_equal(gated.size, base.size)
    assert gated.params["sahm_threshold_percentage_points"] == 0.50
    assert gated.params["u3_release_lag_months"] == 2


def test_sahm_gate_preserves_base_flat_state_and_marks_missing_feature_invalid() -> None:
    index = _monthly_index("1990-01-31", 3)
    base = _base_plan(index)
    base.target[1] = 0.0
    feature = pd.Series([0.6, 0.6, np.nan], index=index, name="sahm_gap_lag2_pp")

    gated = apply_sahm_gate(base, feature, index=index)

    assert gated.target[0] == 1.0
    assert gated.target[1] == 0.0
    assert np.isnan(gated.target[2])
    assert np.isnan(gated.size[2])
