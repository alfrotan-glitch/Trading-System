import hashlib
import json
from pathlib import Path

from qts.lifecycle.demo_registry import policy_fingerprint


def test_probe_hash():
    source_hash = hashlib.sha256(Path("src/qts/research/demo_trend_tsmom.py").read_bytes()).hexdigest()
    doc = json.loads(Path("data/evidence/demo_forward_validation_registry_2026-09-23.json").read_text())
    entry = next(e for e in doc["entries"] if e["strategy_id"] == "DEMO-XAUUSD-TREND-TSMOM-V1")
    policy = dict(entry["policy"])
    policy["code_hash"] = source_hash
    policy.pop("policy_hash", None)
    raise AssertionError(f"PROBE_CODE_HASH={source_hash} PROBE_POLICY_HASH={policy_fingerprint(policy)}")
