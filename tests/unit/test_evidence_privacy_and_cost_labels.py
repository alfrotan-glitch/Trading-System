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
    d = json.loads((EVIDENCE / "measured_broker_costs.json").read_text(encoding="utf-8"))
    assert d["basis"] == "ASSUMED"
    assert d["claim_eligible"] is False
    assert d["applies_to_configured_broker"] is False
    assert d["spread"]["basis"] == "ASSUMED" and d["commission"]["basis"] == "ASSUMED"
    assert "MEASURED_FROM_DOCUMENTATION" not in json.dumps(d)
