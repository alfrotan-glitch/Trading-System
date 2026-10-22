"""CFTC official Managed Money research: real-publication causal invariants."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qts.research.edgelab.cot_disaggregated import (
    ASSUMED_PUBLICATION_LAG_DAYS,
    align_published_positions,
    fixed_positioning_hypotheses,
    parse_official_gold,
)


def rows(n=700):
    dates = pd.date_range("2006-07-04", periods=n, freq="W-TUE", tz="UTC")
    return [
        {
            "cftc_contract_market_code": "088691",
            "report_date_as_yyyy_mm_dd": str(day.date()),
            "open_interest_all": "300000",
            "m_money_positions_long_all": str(110000 + int(i * 30) % 20000),
            "m_money_positions_short_all": str(32000 + int(i * 17) % 8000),
        }
        for i, day in enumerate(dates)
    ]


def test_parse_direct_official_data_requires_identity_and_history():
    data = parse_official_gold(rows())
    assert len(data) == 700
    assert data.index.tz is not None
    assert data.index.is_monotonic_increasing
    assert data.iloc[0]["managed_money_net_oi"] == pytest.approx((110000 - 32000) / 300000)
    invalid = rows()
    invalid[-1]["cftc_contract_market_code"] = "WRONG"
    with pytest.raises(ValueError, match="non-GOLD"):
        parse_official_gold(invalid)


def test_invalid_values_and_duplicate_report_dates_refused():
    cases = (
        ("open_interest_all", "-1"),
        ("m_money_positions_long_all", "garbage"),
        ("m_money_positions_short_all", "-5"),
    )
    for field, invalid_value in cases:
        sample = rows()
        sample[-1][field] = invalid_value
        with pytest.raises(ValueError):
            parse_official_gold(sample)
    dups = rows()
    dups[-1]["report_date_as_yyyy_mm_dd"] = dups[-2]["report_date_as_yyyy_mm_dd"]
    with pytest.raises(ValueError, match="duplicate"):
        parse_official_gold(dups)


def test_no_position_decision_before_delayed_official_release():
    data = parse_official_gold(rows())
    signal = fixed_positioning_hypotheses(data)
    assert signal.index[0] == data.index[0] + pd.Timedelta(days=ASSUMED_PUBLICATION_LAG_DAYS)
    assert set(np.unique(signal.values)) <= {0.0, 1.0}
    cut = data.index[400]
    # Mutating reports AFTER a given date cannot change earlier published signals.
    changed = data.copy()
    changed.loc[changed.index > cut, "managed_money_net_oi"] = -0.8
    altered = fixed_positioning_hypotheses(changed)
    pd.testing.assert_frame_equal(signal.loc[:cut], altered.loc[:cut])


def test_daily_target_is_past_only_and_fails_closed_when_stale():
    data = parse_official_gold(rows())
    signals = fixed_positioning_hypotheses(data)
    source_last = signals.index[-1]
    idx = pd.DatetimeIndex(
        [
            source_last - pd.Timedelta(days=7),
            source_last + pd.Timedelta(days=3),
            source_last + pd.Timedelta(days=20),
        ]
    )
    out = align_published_positions(signals, idx)
    assert out.iloc[-1].eq(0.0).all()
    assert out.iloc[1].equals(signals.iloc[-1]) or out.iloc[1].eq(0.0).all()
    with pytest.raises(ValueError, match="timezone"):
        align_published_positions(signals, idx.tz_localize(None))
