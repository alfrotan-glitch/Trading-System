def test_probe():
    import hashlib
    from pathlib import Path
    print('PROBE_CODE_HASH='+hashlib.sha256(Path('src/qts/research/demo_trend_tsmom.py').read_bytes()).hexdigest())
    assert False, 'PROBE_HASH'
