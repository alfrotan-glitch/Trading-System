import json
from pathlib import Path

from qts.lifecycle.demo_policy import policy_fingerprint


def test_probe_policy_hash():
    doc=json.loads((Path(__file__).resolve().parents[2]/"data/evidence/demo_forward_validation_registry_2026-09-23.json").read_text())
    raise AssertionError(policy_fingerprint(dict(doc["entries"][0]["policy"])))
