"""Measured cost model assembly: claim-eligible only when EVERY component is
broker-measured; anything missing stays UNKNOWN instead of being assumed."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from qts.execution.measured_model import build_measured_cost_model, commission_per_lot_side

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
