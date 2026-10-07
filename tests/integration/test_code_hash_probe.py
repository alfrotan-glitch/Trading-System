import hashlib
from pathlib import Path


def test_probe_provider_hash():
    source=Path(__file__).resolve().parents[2]/"src/qts/research/demo_trend_tsmom.py"
    raise AssertionError(hashlib.sha256(source.read_bytes()).hexdigest())
