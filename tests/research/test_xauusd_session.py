"""Fixed UTC session assay contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from qts.research.xauusd_session import Bar, _event, _stats, _verdict


def _bars() -> list[Bar]:
    start = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
    bars: list[Bar] = []
    for index in range(40):
        stamp = start + index * 15 * 60 * 1000
        price = 100.0 + index * 0.10
        bars.append(Bar(stamp, stamp, price, price + 0.02, stamp + 1, price, price + 0.02))
    return bars


def test_session_event_uses_bid_ask_sides_and_fixed_boundaries() -> None:
    event = _event(_bars(), datetime(2026, 1, 2, tzinfo=UTC).date(), {"id": "X", "start_minute": 480, "end_minute": 720, "sign": 1})
    assert event is not None
    assert event["position"] == "LONG"
    assert event["exit_time_msc"] > event["entry_time_msc"]
    assert event["quote_only_return_bps"] > 0


def test_cost_stress_is_subtracted_without_changing_events() -> None:
    events = [{"quote_only_return_bps": 2.0}, {"quote_only_return_bps": 4.0}]
    free = _stats(events, 0.0)
    stressed = _stats(events, 1.0)
    assert free["mean_net_bps"] == 3.0
    assert stressed["mean_net_bps"] == 2.0


def test_verdict_requires_all_chronological_splits() -> None:
    good = {"n": 20, "mean_net_bps": 1.0, "t_stat": 2.0}
    assert _verdict({"discovery": good, "validation": good, "holdout": good}) == "PROMISING"
    underpowered = {"discovery": good, "validation": good, "holdout": {"n": 19, "mean_net_bps": 1.0, "t_stat": 3.0}}
    assert _verdict(underpowered) == "INCONCLUSIVE"
