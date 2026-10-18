"""Measured cost model assembly: claim-eligible only when EVERY component is
broker-measured; anything missing stays UNKNOWN instead of being assumed."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from qts.execution.measured_model import (
    assumed_vs_measured_comparison,
    build_measured_cost_model,
    commission_per_lot_side,
    reevaluate_frozen_champions,
)

TERMS = {
    "schema": "qts.broker_symbol_cost_terms.v1",
    "observed_at": "2026-10-17T00:00:00+00:00",
    "bid": "2650.10",
    "ask": "2650.45",
    "swap_long_usd_per_lot_night": "-55.3000",
    "swap_short_usd_per_lot_night": "12.1000",
    "swap_rollover3days": 3,
    "unavailable_fields": [],
}
PROFILE = {
    "schema": "qts.spread_profile.v1",
    "samples_usable": 90,
    "spread_bps": {"p50": 1.321, "p90": 2.0, "p95": 2.5, "p99": 4.0, "max": 6.0, "min": 1.0, "mean": 1.5},
}


@dataclass
class Deal:
    volume: Decimal | None
    commission: Decimal | None


def _deals():
    return [Deal(Decimal("0.10"), Decimal("-0.70")), Deal(Decimal("0.20"), Decimal("-1.40")),
            Deal(Decimal("0"), Decimal("0")), Deal(Decimal("0.10"), None)]


def test_commission_median_per_lot_side_skips_unusable():
    value, used = commission_per_lot_side(_deals())
    assert used == 2
    assert value == pytest.approx(7.0)  # |−0.70| / 0.10 lots


def test_fully_measured_model_is_claim_eligible():
    out = build_measured_cost_model(
        spread_profile=PROFILE, symbol_terms=TERMS, deals=_deals(), slippage_bps=0.75, direction="long"
    )
    assert out["claim_eligible"] is True
    bases = {c["name"]: c["basis"] for c in out["components"]}
    assert set(bases.values()) == {"MEASURED"}
    financing = next(c for c in out["components"] if c["name"] == "financing")
    assert financing["usd_per_lot_per_night"] == -55.3


def test_missing_deals_blocks_claim_eligibility():
    out = build_measured_cost_model(
        spread_profile=PROFILE, symbol_terms=TERMS, deals=[], slippage_bps=0.75, direction="long"
    )
    assert out["claim_eligible"] is False
    commission = next(c for c in out["components"] if c["name"] == "commission")
    assert commission["basis"] == "UNKNOWN"


def test_short_direction_uses_swap_short():
    out = build_measured_cost_model(
        spread_profile=PROFILE, symbol_terms=TERMS, deals=_deals(), slippage_bps=0.75, direction="short"
    )
    financing = next(c for c in out["components"] if c["name"] == "financing")
    assert financing["usd_per_lot_per_night"] == 12.1
    assert out["provenance"]["inputs"]["swap"]["direction_used"] == "short"


def test_no_inputs_means_nothing_is_measured():
    out = build_measured_cost_model()
    assert out["claim_eligible"] is False
    assert all(c["basis"] == "UNKNOWN" for c in out["components"])


def test_assumed_vs_measured_comparison_preserves_unmeasured_honesty():
    unmeasured = build_measured_cost_model()
    comp = assumed_vs_measured_comparison(unmeasured)
    assert comp["claim_eligible"] is False
    for name in ("spread", "commission", "slippage", "financing"):
        live = comp["components"][name]["live_terminal"]
        assert live["status"] == "UNMEASURED"
        assert live["value"] is None

    measured = build_measured_cost_model(
        spread_profile=PROFILE, symbol_terms=TERMS, deals=_deals(), slippage_bps=0.75, direction="long"
    )
    comp_m = assumed_vs_measured_comparison(measured)
    assert comp_m["claim_eligible"] is True
    assert comp_m["components"]["financing"]["live_terminal"]["status"] == "MEASURED"
    assert comp_m["components"]["financing"]["live_terminal"]["financing_cost_usd_per_lot_night"] == 55.3
    assert comp_m["components"]["financing"]["live_terminal"]["financing_cost_bps_per_day_at_mid"] == pytest.approx(
        2.0866, abs=1e-3
    )


def test_reevaluate_frozen_champions_unmeasured_and_measured(tmp_path):
    import numpy as np
    import pandas as pd

    unmeasured = build_measured_cost_model()
    res_unm = reevaluate_frozen_champions(unmeasured)
    assert res_unm["claim_eligible"] is False
    assert res_unm["claim_grade_measured"] is None
    assert res_unm["overall_verdict"] == "NO_VALIDATED_EDGE"
    assert set(res_unm["unmeasured_components"]) == {"spread", "commission", "slippage", "financing"}

    # Build a synthetic monthly CSV spanning 1998-01..2026-09 so 2000-01..2026-09 can run
    dates = pd.date_range("1998-01-31", "2026-09-30", freq="ME")
    n = len(dates)
    close = 300.0 * np.exp(np.linspace(0.0, 2.2, n))
    usd = 100.0 * np.exp(np.sin(np.linspace(0.0, 12.0, n)) * 0.1)
    csv_path = tmp_path / "monthly.csv"
    pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "usd": usd,
        }
    ).to_csv(csv_path, index=False, lineterminator="\n")

    measured = build_measured_cost_model(
        spread_profile=PROFILE, symbol_terms=TERMS, deals=_deals(), slippage_bps=0.75, direction="long"
    )
    res_m = reevaluate_frozen_champions(measured, monthly_csv_path=csv_path)
    assert res_m["claim_eligible"] is True
    assert res_m["unmeasured_components"] == []
    assert res_m["claim_grade_measured"] is not None
    assert res_m["claim_grade_measured"]["cost_model_used"]["financing_convention"] == (
        "directional_time_prorated_bps_per_calendar_day"
    )
    assert res_m["overall_verdict"] == "NO_VALIDATED_EDGE"
