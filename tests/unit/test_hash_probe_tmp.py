import hashlib
from pathlib import Path

def test_probe_hashes():
    p=Path("src/qts/research/demo_trend_tsmom.py")
    print("PROBE_CODE_HASH", hashlib.sha256(p.read_bytes()).hexdigest())
    import json
    from qts.lifecycle.demo_registry import policy_fingerprint
    doc=json.loads(Path("data/evidence/demo_forward_validation_registry_2026-09-23.json").read_text())
    entry=next(e for e in doc["entries"] if e["strategy_id"]=="DEMO-XAUUSD-TREND-TSMOM-V1")
    policy=dict(entry["policy"])
    policy["code_hash"]=hashlib.sha256(p.read_bytes()).hexdigest()
    policy.pop("policy_hash",None)
    print("PROBE_POLICY_HASH", policy_fingerprint(policy))
