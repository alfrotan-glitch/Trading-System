from __future__ import annotations

import json
from pathlib import Path


def test_documentation_reference_is_not_presented_as_account_measurement() -> None:
    root = Path(__file__).resolve().parents[2]
    reference_path = root / "data/evidence/broker_cost_reference_documented_2026-10-20.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))

    assert reference["schema"] == "qts.broker_cost_reference.documented.v2"
    assert reference["status"] == "DOCUMENTED_REFERENCE_ONLY"
    assert reference["account_specific"] is False
    assert reference["deal_level_measurement"] is False
    assert reference["actual_account_cost_status"] == "UNMEASURED"
    assert reference["claim_eligible"] is False
    assert reference["spread"]["basis"] == "DOCUMENTED_REFERENCE_ONLY"
    assert reference["commission"]["basis"] == "DOCUMENTED_REFERENCE_ONLY"
    assert reference["legacy_unverified_spread_stat"]["status"] == "QUARANTINED"


def test_legacy_measured_filename_points_to_correction() -> None:
    root = Path(__file__).resolve().parents[2]
    legacy_path = root / "data/evidence/measured_broker_costs.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))

    assert legacy["status"] == "SUPERSEDED_FILENAME_CORRECTION"
    assert legacy["actual_account_cost_status"] == "UNMEASURED"
    assert legacy["superseded_by"] == "broker_cost_reference_documented_2026-10-20.json"
