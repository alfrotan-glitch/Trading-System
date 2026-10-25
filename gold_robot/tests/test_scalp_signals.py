from gold_robot.research.scalp_signals import Bar, generate_signals
import pytest


def sample(n=80, seconds=300):
    return [
        Bar(i*seconds, 3000+i*.15, 3000+i*.15+.3,
            3000+i*.15-.3, 3000+i*.15) for i in range(n)
    ]


def test_signals_are_causal_across_prefixes():
    candles = sample()
    full = generate_signals(candles, start_hour=0, end_hour=24)
    for k in range(45, 80, 5):
        prefix = generate_signals(candles[:k], start_hour=0, end_hour=24)
        assert prefix == [
            s for s in full if s.decision_time <= candles[k-1].time+300
        ]


def test_decision_after_bar_close():
    candles = sample()
    known = {b.time+300 for b in candles}
    assert all(s.decision_time in known for s in
               generate_signals(candles, start_hour=0, end_hour=24))


def test_gap_invalidates_warmup():
    first = sample(30)
    second = [Bar(b.time+100000, b.open, b.high, b.low, b.close)
              for b in sample(20)]
    assert generate_signals(first+second, start_hour=0, end_hour=24) == []


def test_duplicate_or_invalid_ohlc_refused():
    bars = sample(2)
    with pytest.raises(ValueError):
        generate_signals([bars[0], bars[0]])
    with pytest.raises(ValueError):
        generate_signals([Bar(0, 10, 9, 8, 10)])
