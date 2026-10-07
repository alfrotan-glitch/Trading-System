"""Bar-time semantics of the DEMO trend benchmark (completed 15m bars only).

These tests pin the *strategy clock* contract:

* the first quote opens the current bar;
* intra-bar quotes only move the current bar's close — they never advance history;
* the first quote of a new bar completes exactly one previous bar, once;
* only completed bar closes enter the EMA history and only a completed bar can
  produce a signal (no partial-bar signals, no lookahead);
* signals are identified by the completed-bar boundary, deterministically;
* restart warmup reconstructs exactly the state a continuous run would hold and
  cannot re-emit a boundary that already signalled;
* seeding refuses anything that is not a validated, completed, clock-proven bar.

The execution polling clock is deliberately absent from the strategy: every
assertion below drives the strategy with quote timestamps only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qts.research.demo_trend_tsmom import DEFAULT_PARAMS, TrendTimeSeriesMomentum

T0 = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def _quote(t: datetime, price: str, *, spread: str = "0.10", basis: str | None = "measured-m1-bar") -> dict:
    bid = Decimal(price)
    quote = {
        "symbol": "XAUUSD",
        "bid": bid,
        "ask": bid + Decimal(spread),
        "spread_bps": 1.0,
        "age_s": 0.5,
        "event_time": t.isoformat(),
    }
    if basis is not None:
        quote["timestamp_basis"] = basis
    return quote


def _params(**overrides) -> dict:
    return {**DEFAULT_PARAMS, **overrides}


def _boundary(signal) -> datetime:
    """The completed-bar boundary a signal id is bound to."""
    assert signal.signal_id.startswith(f"tsmom-{signal.side.lower()}-")
    stamp = signal.signal_id.rsplit("-", 1)[-1]
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _feed(strategy: TrendTimeSeriesMomentum, t0: datetime, prices: list[str]) -> list:
    """Feed one quote per 15m bar; each quote opens the next bar."""
    signals = []
    for i, price in enumerate(prices):
        signal = strategy.generate(_quote(t0 + STEP * i, price))
        if signal is not None:
            signals.append(signal)
    return signals


# --------------------------------------------------------------- bar building


def test_first_quote_opens_the_current_bar_without_advancing_history():
    strategy = TrendTimeSeriesMomentum()

    assert strategy.generate(_quote(T0, "4000")) is None

    assert strategy.completed_bars == 0
    assert strategy._bar_start == T0
    assert strategy._bar_close == Decimal("4000.05")


def test_intra_bar_quotes_only_move_the_current_close():
    strategy = TrendTimeSeriesMomentum()
    strategy.generate(_quote(T0, "4000"))

    for offset in (timedelta(minutes=1), timedelta(minutes=7, seconds=30), timedelta(minutes=14, seconds=59)):
        assert strategy.generate(_quote(T0 + offset, "4005")) is None

    assert strategy.completed_bars == 0
    assert strategy._bar_start == T0
    assert strategy._bar_close == Decimal("4005.05")


def test_new_bar_completes_exactly_one_previous_bar():
    strategy = TrendTimeSeriesMomentum()
    strategy.generate(_quote(T0, "4000"))
    strategy.generate(_quote(T0 + timedelta(minutes=10), "4010"))

    strategy.generate(_quote(T0 + STEP, "4020"))

    assert strategy.completed_bars == 1
    assert list(strategy._closes) == [Decimal("4010.05")]
    assert strategy._bar_start == T0 + STEP
    assert strategy._bar_close == Decimal("4020.05")

    # A second quote inside the new bar must not complete another bar.
    strategy.generate(_quote(T0 + STEP + timedelta(seconds=30), "4030"))
    assert strategy.completed_bars == 1


def test_partial_bars_never_produce_a_signal():
    """A violent intra-bar move is not a crossover until the bar completes."""
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    _feed(strategy, T0, ["4000", "3990"])  # bar 08:00 completed; bar 08:15 is forming
    assert strategy.completed_bars == 1

    for price in ("4100", "4200", "4300"):
        assert strategy.generate(_quote(T0 + STEP + timedelta(minutes=5), price)) is None

    assert strategy.completed_bars == 1  # nothing partial entered the history
    assert strategy.signals_emitted == 0
    assert strategy._bar_close == Decimal("4300.05")

    # The forming bar completes with the close it actually saw intra-bar — the
    # first quote of the next bar is the completion trigger, never the close.
    strategy.generate(_quote(T0 + STEP * 2, "4400"))

    assert strategy.completed_bars == 2
    assert list(strategy._closes)[-1] == Decimal("4300.05")
    assert strategy._bar_close == Decimal("4400.05")


def test_signals_are_bound_to_the_completed_bar_boundary():
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    prices = ["4000", "3990", "4000", "4060", "4100", "4140"]
    signals = _feed(strategy, T0, prices)

    assert signals, "a rising series after a dip must cross EMA2 above EMA3"
    for signal in signals:
        boundary = _boundary(signal)
        assert boundary.minute % 15 == 0
        assert boundary.second == 0
        assert signal.take_profit is None
        assert signal.lots == Decimal("0.01")
    # One signal per completed boundary: no duplicate ids.
    ids = [s.signal_id for s in signals]
    assert len(ids) == len(set(ids))


def test_identical_quote_sequences_produce_identical_signals():
    prices = ["4000", "3990", "4000", "4060", "4100", "4140", "4120", "4100", "4140"]
    first = _feed(TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3)), T0, prices)
    second = _feed(TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3)), T0, prices)

    assert [(s.side, s.signal_id, s.stop_loss) for s in first] == [
        (s.side, s.signal_id, s.stop_loss) for s in second
    ]


def test_a_completed_boundary_is_never_signalled_twice(monkeypatch):
    """Belt and braces: even a replayed boundary cannot become a second order."""
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    signals = _feed(strategy, T0, ["4000", "3990", "4000", "4060", "4100"])
    assert signals

    boundary = _boundary(signals[0])
    replayed = strategy._signal(
        side=signals[0].side,
        boundary=boundary,
        bid=Decimal("4100"),
        ask=Decimal("4100.10"),
        basis="measured-m1-bar",
    )
    assert replayed is None
    assert strategy.signals_emitted == len(signals)


def test_out_of_order_quote_is_refused_without_touching_state():
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    _feed(strategy, T0, ["4000", "3990", "4000"])
    before = (list(strategy._closes), strategy._bar_start, strategy._bar_close)

    assert strategy.generate(_quote(T0, "9999")) is None

    assert (list(strategy._closes), strategy._bar_start, strategy._bar_close) == before
    assert "out-of-order" in strategy.last_rationale()


def test_bar_gaps_are_counted_never_fabricated():
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    _feed(strategy, T0, ["4000"])

    # Next quote arrives three bars later: the two unobserved bars do not exist.
    strategy.generate(_quote(T0 + STEP * 3, "4010"))

    assert strategy.completed_bars == 1
    assert strategy.history_provenance()["bar_gaps"] == 1


# ----------------------------------------------------------- quote validation


@pytest.mark.parametrize(
    "market_state",
    [
        {"bid": None, "ask": "4000.10", "age_s": 0.0},
        {"bid": "4000", "ask": None, "age_s": 0.0},
        {"bid": "4000", "ask": "4000.10", "age_s": 0.0, "event_time": "2026-10-07T08:00:00"},
        {"bid": "4000", "ask": "4000.10", "age_s": 0.0},
        {"bid": "4000", "ask": "4000.10", "age_s": 99.0, "event_time": T0.isoformat()},
        {"bid": "4000", "ask": "4000.10", "age_s": 0.0, "spread_bps": None, "event_time": T0.isoformat()},
        {"bid": "0", "ask": "4000.10", "age_s": 0.0, "event_time": T0.isoformat()},
    ],
)
def test_unusable_quotes_never_advance_history(market_state):
    strategy = TrendTimeSeriesMomentum()

    assert strategy.generate(market_state) is None

    assert strategy.completed_bars == 0
    assert strategy._bar_start is None


def test_strategy_clock_is_the_quote_clock_not_the_wall_clock():
    """A historical-looking quote stream is processed exactly as-is."""
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    old = datetime(2020, 3, 16, 2, 0, tzinfo=UTC)

    signals = _feed(strategy, old, ["1500", "1490", "1500", "1550", "1600"])

    assert strategy.completed_bars == 4
    assert signals
    assert all(_boundary(s).year == 2020 for s in signals)


# ------------------------------------------------------------------- warmup


def test_seeding_a_full_window_reconstructs_a_continuous_run(monkeypatch):
    """Seeded state is identical to the state of a continuously fed strategy."""
    continuous = TrendTimeSeriesMomentum()
    seeded = TrendTimeSeriesMomentum()
    prices = [str(4000 + (i % 7) * 3 - (i % 11) * 2) for i in range(120)]

    # Continuous: one quote per bar, so completed bars are prices[:-1].
    _feed(continuous, T0, prices)

    boundaries = [T0 + STEP * i for i in range(len(prices) - 1)]
    outcome = seeded.seed_completed_bars(
        list(zip(boundaries, [Decimal(p) + Decimal("0.05") for p in prices[:-1]], strict=True)),
        source="test-window",
    )

    assert outcome["accepted"] is True
    assert seeded.completed_bars == continuous.completed_bars == seeded.warmup_plan()["bars"]
    assert list(seeded._closes) == list(continuous._closes)
    assert seeded.history_provenance()["source"] == "test-window"
    assert seeded.history_provenance()["completed_only"] is True
    # Seeding is history reconstruction: it never evaluates a boundary.
    assert seeded.signals_emitted == 0

    # ...and the continuation is seamless: identical signals, identical EMA state.
    continuation = [str(4010 + i * 2) for i in range(12)]
    continuous_signals = _feed(continuous, T0 + STEP * (len(prices) - 1), continuation)
    seeded_signals = _feed(seeded, T0 + STEP * (len(prices) - 1), continuation)

    assert [(s.side, s.signal_id) for s in seeded_signals] == [
        (s.side, s.signal_id) for s in continuous_signals
    ]
    assert seeded._last_fast == continuous._last_fast
    assert seeded._last_slow == continuous._last_slow
    assert list(seeded._closes) == list(continuous._closes)


def test_restart_after_a_signal_does_not_repeat_it():
    """The whole point of the completed-only contract: no duplicated signal."""
    prices = [
        "4000", "3990", "4000", "4060", "4100", "4140",
        "4120", "4080", "4020", "4000", "3990", "4010", "4090",
    ]
    continuous = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    signals = _feed(continuous, T0, prices)
    assert len(signals) >= 2, "the fixture series must signal before and after the restart"
    first_signal = signals[0]
    restart_boundary = _boundary(first_signal)  # the bar that was forming when it fired
    restart_index = int((restart_boundary - T0) // STEP)

    # The restarted process seeds the bars that had completed by then and
    # continues from the bar that was forming at restart time.
    restarted = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    completed = [
        (T0 + STEP * i, Decimal(prices[i]) + Decimal("0.05"))
        for i in range(restart_index)
    ]
    assert restarted.seed_completed_bars(completed, source="restart-window")["accepted"] is True

    resumed = _feed(restarted, restart_boundary, prices[restart_index:])

    # The pre-restart signal is not repeated, and every later signal is
    # reproduced exactly (same side, same boundary, same stop).
    assert first_signal.signal_id not in [s.signal_id for s in resumed]
    later = [s for s in signals if _boundary(s) > restart_boundary]
    assert later, "the fixture series must also signal after the restart"
    assert [(s.side, s.signal_id, s.stop_loss) for s in resumed] == [
        (s.side, s.signal_id, s.stop_loss) for s in later
    ]


def test_insufficient_history_leaves_the_strategy_warming_up():
    strategy = TrendTimeSeriesMomentum()
    bars = [(T0 + STEP * i, Decimal("4000")) for i in range(5)]

    outcome = strategy.seed_completed_bars(bars, source="short-window")

    assert outcome["accepted"] is True
    assert outcome["bars"] == 5
    assert "warming up" in strategy.last_rationale() or strategy.last_rationale().startswith("seeded")
    assert strategy.completed_bars == 5
    assert strategy.signals_emitted == 0

    # Live quotes keep filling the same bounded history.
    _feed(strategy, T0 + STEP * 5, ["4000"] * 45)
    assert strategy.completed_bars == strategy.warmup_plan()["bars"]


def test_seeding_refuses_an_invalid_window_as_a_whole():
    strategy = TrendTimeSeriesMomentum()
    good = (T0, Decimal("4000"))
    bad_windows = [
        [(T0.replace(tzinfo=None), Decimal("4000"))],
        [(T0 + timedelta(minutes=5), Decimal("4000"))],
        [(T0, Decimal("0"))],
        [(T0, "not-a-price")],
        [(T0, Decimal("4000")), (T0, Decimal("4001"))],
        [(T0 + STEP, Decimal("4000")), (T0, Decimal("4001"))],
        [(T0, Decimal("4000")), ("2026-10-07T09:00:00", Decimal("4001"))],
        ["not-a-bar"],
    ]

    for window in bad_windows:
        outcome = strategy.seed_completed_bars(window, source="bad-window")
        assert outcome["accepted"] is False, window
        assert outcome["bars"] == 0
        assert strategy.completed_bars == 0

    assert strategy.seed_completed_bars([good], source="good-window")["accepted"] is True
    assert strategy.completed_bars == 1


def test_seeding_is_a_startup_only_operation():
    strategy = TrendTimeSeriesMomentum()
    strategy.generate(_quote(T0, "4000"))

    outcome = strategy.seed_completed_bars([(T0 - STEP, Decimal("4000"))], source="late")

    assert outcome["accepted"] is False
    assert "startup-only" in outcome["reason"]


def test_live_quote_inside_the_newest_seeded_bar_is_refused():
    """The seed window must be completed-only; anything else is a contract breach."""
    strategy = TrendTimeSeriesMomentum()
    strategy.seed_completed_bars([(T0, Decimal("4000"))], source="window")

    # A quote belonging to the newest seeded bar (i.e. that bar is still open)
    # must not be treated as newer than the completed history.
    assert strategy.generate(_quote(T0, "4001")) is None
    assert strategy.completed_bars == 1
    assert strategy._bar_start is None
    assert "not newer than the newest completed bar" in strategy.last_rationale()


def test_history_then_live_quotes_complete_a_new_bar():
    strategy = TrendTimeSeriesMomentum(_params(fast_ema=2, slow_ema=3))
    assert strategy.seed_completed_bars(
        [(T0 + STEP * i, Decimal(p)) for i, p in enumerate(["4000", "3990", "4000"])],
        source="window",
    )["accepted"]

    # First live quote opens the bar after the seeded window.
    assert strategy.generate(_quote(T0 + STEP * 3, "4060")) is None
    assert strategy.completed_bars == 3

    signal = strategy.generate(_quote(T0 + STEP * 4, "4100"))
    assert strategy.completed_bars == 4
    assert signal is not None
    assert _boundary(signal) == T0 + STEP * 4
