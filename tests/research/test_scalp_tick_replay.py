"""Causal tick-sequenced scalp backtest: no lookahead, independent later entries."""

from decimal import Decimal

import numpy as np
import pytest

from qts.execution.scalp_exit import ScalpExitPlan
from qts.research import scalp_tick_replay
from qts.research.scalp_regimes import ScalpIdea
from qts.research.scalp_tick_replay import TickScalpReplay


PLAN = ScalpExitPlan.from_mapping({
    "take_profit_net_bps": "5", "extra_cost_reserve_bps": "2",
    "max_loss_net_bps": "12", "max_spread_bps": "3", "max_tick_age_s": "3",
})


def engine(mode="confirmed", cutoff=45 * 60000):
    return TickScalpReplay(mode=mode, exit_plan=PLAN, end_exclusive_time_msc=cutoff)


def series(*, stop=False):
    times = np.arange(40, dtype=np.int64) * 60000
    bid = np.full(40, 1999.9)
    ask = np.full(40, 2000.1)
    # One distinct completed-bar close triggers a SINGLE synthetic signal.
    bid[33] = 2000.4
    ask[33] = 2000.6
    event_time = np.array([34 * 60000 + 500], dtype=np.int64)
    event_bid = np.array([1995.0 if stop else 2002.0], dtype=np.float64)
    event_ask = event_bid + 0.2
    t = np.insert(times, 35, event_time)
    b = np.insert(bid, 35, event_bid)
    a = np.insert(ask, 35, event_ask)
    return t, b, a


def fake_signal(closes):
    if len(closes) == 34 and closes[-1] == Decimal("2000.5"):
        return ScalpIdea("BUY", "breakout", "UP", Decimal("8"))
    return None


def test_enter_only_after_34_completed_bars_then_exit_on_first_eligible_tick(monkeypatch):
    monkeypatch.setattr(scalp_tick_replay, "propose_scalp_entry", fake_signal)
    t, b, a = series()
    result = engine()
    result.consume(t, b, a)
    report = result.report()
    assert report["signals"] == 1 and report["metrics"]["trades"] == 1
    tr = report["trades"][0]
    assert tr["signal_time_msc"] == 33 * 60000
    assert tr["entry_time_msc"] == 34 * 60000
    assert tr["exit_time_msc"] == 34 * 60000 + 500
    assert tr["exit_reason"] == "scalp_take_profit"
    assert report["LIVE"] == "LOCKED" and report["orders_submitted"] == 0


def test_split_batch_boundaries_dont_change_decisions(monkeypatch):
    monkeypatch.setattr(scalp_tick_replay, "propose_scalp_entry", fake_signal)
    t, b, a = series()
    whole = engine()
    whole.consume(t, b, a)
    pieces = engine()
    for left, right in ((0, 20), (20, 35), (35, len(t))):
        pieces.consume(t[left:right], b[left:right], a[left:right])
    assert whole.report()["trades"] == pieces.report()["trades"]


def test_stop_quote_is_first_and_no_future_profitable_tick(monkeypatch):
    monkeypatch.setattr(scalp_tick_replay, "propose_scalp_entry", fake_signal)
    t, b, a = series(stop=True)
    t = np.insert(t, 36, 34 * 60000 + 700)
    b = np.insert(b, 36, 2004.0)
    a = np.insert(a, 36, 2004.2)
    e = engine()
    e.consume(t, b, a)
    r = e.report()
    assert r["metrics"]["trades"] == 1
    assert r["trades"][0]["exit_reason"] == "tick_stop_quote_crossing"
    assert r["trades"][0]["exit_time_msc"] == 34 * 60000 + 500
    assert r["metrics"]["mean_net_bps"] < 0


def test_refuse_bad_quote_chronology():
    e = engine()
    e.consume(np.array([10, 20]), np.array([2000.0, 2000.0]), np.array([2000.2, 2000.2]))
    with pytest.raises(ValueError, match="ordering"):
        e.consume(np.array([19]), np.array([2000.0]), np.array([2000.2]))
    with pytest.raises(ValueError, match="executable"):
        engine().consume(np.array([10]), np.array([2001.0]), np.array([2000.0]))


def test_cutoff_excludes_future_ticks(monkeypatch):
    monkeypatch.setattr(scalp_tick_replay, "propose_scalp_entry", fake_signal)
    t, b, a = series()
    e = engine(cutoff=34 * 60000)
    e.consume(t, b, a)
    r = e.report()
    assert r["metrics"]["trades"] == 0
    assert r["raw_quote_rows"] == 34


def test_inconsistent_frozen_strategy_assumptions_refused():
    from qts.research.scalp_replay import ReplayAssumptions

    with pytest.raises(ValueError, match="frozen"):
        TickScalpReplay(
            mode="confirmed", exit_plan=PLAN,
            assumptions=ReplayAssumptions(stop_distance_price=Decimal("9")),
            end_exclusive_time_msc=60_000,
        )


def test_replay_does_not_bridge_missing_minutes(monkeypatch):
    monkeypatch.setattr(scalp_tick_replay, "propose_scalp_entry", fake_signal)
    t, b, a = series()
    t[36:] += 60000
    e = engine()
    e.consume(t, b, a)
    r = e.report()
    assert r["minute_gaps"] == 1
    assert r["metrics"]["trades"] == 1
