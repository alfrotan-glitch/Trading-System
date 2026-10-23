"""Costed, one-bar-delayed research replay does not invent broker fills."""

from dataclasses import replace
from decimal import Decimal

import numpy as np
import pytest

from qts.execution.scalp_exit import ScalpExitPlan
from qts.research import scalp_replay
from qts.research.scalp_regimes import ScalpIdea, propose_anticipatory_entry
from qts.research.scalp_replay import ReplayAssumptions, replay_scalp_bars
from qts.research.xauusd_broker_ml import BrokerBars

PLAN = ScalpExitPlan.from_mapping({
    "take_profit_net_bps": "5", "extra_cost_reserve_bps": "2",
    "max_loss_net_bps": "12", "max_spread_bps": "3", "max_tick_age_s": "3",
})


def bars(*, gap: bool = False, rise: float = 0.0, wide: bool = False) -> BrokerBars:
    times = np.arange(40, dtype=np.int64) * 60_000
    if gap:
        times[37:] += 120_000
    close = np.full(40, 2000.0)
    close[36:] = 2000.0 + rise
    spread = 2.0 if wide else 0.2
    return BrokerBars(
        time_msc=times,
        open_bid=close - spread / 2,
        open_ask=close + spread / 2,
        close_bid=close - spread / 2,
        close_ask=close + spread / 2,
        high_mid=close + 0.05,
        low_mid=close - 0.05,
        mean_spread=np.full(40, spread),
    )


def test_replay_enters_next_bar_and_has_costed_exit(monkeypatch):
    monkeypatch.setattr(
        scalp_replay, "propose_scalp_entry",
        lambda closes: ScalpIdea("BUY", "breakout", "UP", Decimal("6"))
        if len(closes) == 34 else None,
    )
    result = replay_scalp_bars(bars(rise=2.0), exit_plan=PLAN)
    assert result["status"] == "RESEARCH_ONLY_NOT_VALIDATED"
    assert result["orders_submitted"] == 0
    assert result["metrics"]["trades"] >= 1
    assert all(t["entry_time_msc"] > t["signal_time_msc"] for t in result["trades"])
    assert result["strategy_promoted"] is False
    assert result["metrics"]["mean_net_bps"] is not None


def test_replay_rejects_nonmonotonic_and_crossed_broker_quotes():
    b = bars()
    b.time_msc[4] = b.time_msc[3]
    with pytest.raises(ValueError, match="strictly ordered"):
        replay_scalp_bars(b, exit_plan=PLAN)
    bad = bars()
    bad.open_ask[0] = bad.open_bid[0] - 0.1
    with pytest.raises(ValueError, match="bid-ask spreads"):
        replay_scalp_bars(bad, exit_plan=PLAN)


def test_replay_abstains_when_spread_exceeds_executable_cost_gate(monkeypatch):
    monkeypatch.setattr(
        scalp_replay, "propose_scalp_entry",
        lambda closes: ScalpIdea("BUY", "breakout", "UP", Decimal("6"))
        if len(closes) == 34 else None,
    )
    outcome = replay_scalp_bars(bars(wide=True), exit_plan=PLAN)
    assert outcome["metrics"]["trades"] == 0
    assert outcome["entry_refusals_cost_gate"] > 0


def test_gapped_quote_bar_never_reuses_stale_signal(monkeypatch):
    monkeypatch.setattr(
        scalp_replay, "propose_scalp_entry",
        lambda closes: ScalpIdea("BUY", "breakout", "UP", Decimal("6"))
        if len(closes) == 34 else None,
    )
    output = replay_scalp_bars(bars(gap=True), exit_plan=PLAN)
    assert output["observed_bar_gaps"] == 1
    assert output["LIVE"] == "LOCKED"


def test_real_quote_extrema_detect_a_stop_hidden_by_mid_range(monkeypatch):
    """A transient adverse BID quote is visible even if the mid stays flat."""
    monkeypatch.setattr(
        scalp_replay, "propose_scalp_entry",
        lambda closes: ScalpIdea("BUY", "breakout", "UP", Decimal("6"))
        if len(closes) == 34 else None,
    )
    b = bars()
    # 1-minute simulated mid extremes alone would miss this temporary
    # executable-bid sell-off; the broker-side minimum proves a possible stop.
    low_bid = np.minimum(b.open_bid, b.close_bid).copy()
    low_bid[34] = 1995.0
    b = replace(b, low_bid=low_bid, high_ask=np.maximum(b.open_ask, b.close_ask).copy())
    outcome = replay_scalp_bars(b, exit_plan=PLAN)
    assert outcome["stop_detection_basis"] == "BROKER_BID_ASK_EXTREMA"
    assert outcome["metrics"]["uncertain_intrabar_stop_count"] >= 1
    assert outcome["trades"][0]["exit_reason"] == "intrabar_stop_touch_uncertain"


def test_replay_rejects_inconsistent_bid_ask_extrema():
    b = bars()
    b = replace(b, low_bid=np.full(40, 2001.0), high_ask=np.full(40, 2001.2))
    with pytest.raises(ValueError, match="broker-side quote extrema"):
        replay_scalp_bars(b, exit_plan=PLAN)


def test_replay_refuses_parameter_search_disguised_as_assumptions():
    with pytest.raises(ValueError, match="must match frozen"):
        replay_scalp_bars(
            bars(), exit_plan=PLAN,
            assumptions=ReplayAssumptions(stop_distance_price=Decimal("9")),
        )


def test_anticipatory_replay_uses_prior_close_not_future_bar():
    raw = [2002.0 + (3.0 if i % 2 else -3.0) for i in range(25)]
    raw += [
        2003.6, 2003.65, 2003.62, 2003.66, 2003.60,
        2003.63, 2003.64, 2003.66, 2003.72,
        2004.0, 2006.0, 2006.5, 2006.7, 2006.8, 2006.9,
    ]
    assert len(raw) == 40
    b = bars()
    mid = np.asarray(raw, dtype=np.float64)
    b = replace(
        b, open_bid=mid - 0.1, open_ask=mid + 0.1,
        close_bid=mid - 0.1, close_ask=mid + 0.1,
        high_mid=mid + 0.05, low_mid=mid - 0.05,
    )
    signal = propose_anticipatory_entry([Decimal(str(x)) for x in mid[:34]])
    assert signal is not None and signal.family == "pre_breakout"
    assert scalp_replay.propose_scalp_entry([Decimal(str(x)) for x in mid[:34]]) is None
    early = replay_scalp_bars(b, exit_plan=PLAN, entry_mode="anticipatory")
    baseline = replay_scalp_bars(b, exit_plan=PLAN, entry_mode="confirmed")
    assert early["entry_mode"] == "anticipatory"
    assert baseline["entry_mode"] == "confirmed"
    assert early["metrics"]["trades"] >= 1
    assert early["trades"][0]["entry_time_msc"] == int(mid.size - 6) * 60_000
    assert early["trades"][0]["signal_time_msc"] < early["trades"][0]["entry_time_msc"]
    assert early["trades"][0]["family"] == "pre_breakout"
    assert early["LIVE"] == "LOCKED" and early["orders_submitted"] == 0


def test_anticipatory_replay_refuses_late_gap_up_entry():
    raw = [2002.0 + (3.0 if i % 2 else -3.0) for i in range(25)]
    raw += [
        2003.6, 2003.65, 2003.62, 2003.66, 2003.60,
        2003.63, 2003.64, 2003.66, 2003.72,
        2006.5, 2006.7, 2006.9, 2007.0, 2007.2, 2007.3,
    ]
    b = bars()
    mid = np.asarray(raw)
    b = replace(
        b, open_bid=mid - 0.1, open_ask=mid + 0.1,
        close_bid=mid - 0.1, close_ask=mid + 0.1,
        high_mid=mid + 0.05, low_mid=mid - 0.05,
    )
    r = replay_scalp_bars(b, exit_plan=PLAN, entry_mode="anticipatory")
    assert r["early_chase_refusals"] >= 1
    assert r["metrics"]["trades"] == 0


def test_replay_refuses_unknown_entry_mode():
    with pytest.raises(ValueError, match="entry_mode"):
        replay_scalp_bars(bars(), exit_plan=PLAN, entry_mode="telepathic")
