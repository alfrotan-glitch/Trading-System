"""Guards: committed evidence must not leak broker identity, and documentation-sourced
costs must never be labelled MEASURED (only a terminal/deal observation is a measurement)."""
from __future__ import annotations

import json
import re
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[2] / "data" / "evidence"
_LOGIN = re.compile(r'"login"\s*:\s*(?!"REDACTED")\S')


def test_readiness_gate_snapshots_hold_no_account_identity():
    for p in EVIDENCE.glob("demo_readiness_gate_*.json"):
        text = p.read_text(encoding="utf-8")
        assert not _LOGIN.search(text), p.name
        assert "Allah Yar" not in text, p.name


def test_third_party_cost_file_is_assumed_and_not_claim_eligible():
    """Legacy filename is a tombstone, not a broker measurement or cost model."""
    d = json.loads((EVIDENCE / "measured_broker_costs.json").read_text(encoding="utf-8"))
    assert d["schema"] == "qts.evidence.superseded-reference.v1"
    assert d["status"] == "SUPERSEDED_FILENAME_CORRECTION"
    assert d["actual_account_cost_status"] == "UNMEASURED"
    assert d["superseded_by"] == "broker_cost_reference_documented_2026-10-20.json"
    assert "MEASURED_FROM_DOCUMENTATION" not in json.dumps(d)

    reference = json.loads(
        (EVIDENCE / d["superseded_by"]).read_text(encoding="utf-8")
    )
    assert reference["status"] == "DOCUMENTED_REFERENCE_ONLY"
    assert reference["account_specific"] is False
    assert reference["deal_level_measurement"] is False
    assert reference["actual_account_cost_status"] == "UNMEASURED"
    assert reference["claim_eligible"] is False
    assert reference["spread"]["basis"] == "DOCUMENTED_REFERENCE_ONLY"
    assert reference["commission"]["basis"] == "DOCUMENTED_REFERENCE_ONLY"
    assert "MEASURED_FROM_DOCUMENTATION" not in json.dumps(reference)
