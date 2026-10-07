from qts.lifecycle.demo_registry import load_registry, resolve_entry


def test_public_trend_demo_policy_is_resolvable():
    registry = load_registry()
    entry, reasons = resolve_entry(registry, "DEMO-XAUUSD-TREND-TSMOM-V1")
    assert entry is not None, reasons
    assert entry.status == "ELIGIBLE_DIAGNOSTIC"
    assert entry.validated_edge is False
    assert entry.policy_id == "DEMOPOL-TSMOM-XAUUSD-2026-10-07-V1"
