"""Spread profiling: percentiles from usable samples only; a flaky terminal
degrades the count, it never fabricates a quote."""

from qts.execution.spread_profile import collect_spread_profile, summarize_spread_profile

SAMPLES = [
    {"bid": "100.00", "ask": "100.10"},  # 10.00 bps of mid
    {"bid": "100.00", "ask": "100.20"},  # 19.96 bps
    {"bid": "100.00", "ask": "100.30"},  # 29.91 bps
    {"unavailable": True},  # counted, never zero
    {"bid": None, "ask": None},
]


def test_summary_uses_only_usable_samples():
    p = summarize_spread_profile(SAMPLES, symbol="XAUUSD", source="test")
    assert p["samples_total"] == 5
    assert p["samples_usable"] == 3
    assert p["samples_unavailable"] == 2
    assert p["spread_bps"]["p50"] > 19.0
    assert p["spread_bps"]["max"] > 29.0


def test_empty_profile_stays_unmeasured():
    p = summarize_spread_profile([], symbol="XAUUSD", source="test")
    assert p["spread_bps"] is None
    assert p["samples_usable"] == 0


def test_collector_counts_snapshot_failures_as_unavailable():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("terminal hiccup")
        return {"bid": "100.0", "ask": "100.1"}

    p = collect_spread_profile(flaky, samples=3, interval_sec=0.0, symbol="XAUUSD", source="test",
                               sleep=lambda _s: None)
    assert p["samples_total"] == 3
    assert p["samples_usable"] == 2
    assert p["samples_unavailable"] == 1


def test_collector_rejects_zero_samples():
    try:
        collect_spread_profile(lambda: {}, samples=0, interval_sec=0.0, symbol="X", source="t")
    except ValueError:
        pass
    else:
        raise AssertionError("samples=0 must raise")
