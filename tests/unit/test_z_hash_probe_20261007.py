import hashlib
from pathlib import Path


def test_probe_hash():
    digest = hashlib.sha256(Path("src/qts/research/demo_trend_tsmom.py").read_bytes()).hexdigest()
    raise AssertionError(f"PROBE_CODE_HASH={digest}")
