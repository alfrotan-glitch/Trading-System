"""Costed, one-bar-delayed research replay does not invent broker fills."""

from decimal import Decimal

import numpy as np
import pytest

from qts.execution.scalp_exit import ScalpExitPlan
from qts.research.scalp_regimes import ScalpIdea
from qts.research.xauusd_broker_ml import BrokerBars
from qts.research import scalp_replay
from qts.research.scalp_replay import ReplayAssumptions, replay_scalp_bars


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


def test_replay_refuses_parameter_search_disguised_as_assumptions():
    with pytest.raises(ValueError, match="must match frozen"):
        replay_scalp_bars(
            bars(), exit_plan=PLAN,
            assumptions=ReplayAssumptions(stop_distance_price=Decimal("9")),
        )
