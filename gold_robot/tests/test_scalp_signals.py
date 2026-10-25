import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
from scalp_signals import Bar, generate_signals
import pytest


def sample(n=80, seconds=300):
    # Deliberate impulses ensure both long/short filters can be exercised.
    return [Bar(i*seconds, 3000+i*.15, 3000+i*.15+0.3,
                3000+i*.15-0.3, 3000+i*.15) for i in range(n)]


def test_no_lookahead_on_historical_prefixes():
    candles=sample(80)
    full=generate_signals(candles,start_hour=0,end_hour=24)
    for k in range(45,80,5):
        prefix=generate_signals(candles[:k],start_hour=0,end_hour=24)
        assert prefix==[x for x in full if x.decision_time <= candles[k-1].time+300]


def test_signals_only_after_bar_closed():
    candles=sample()
    assert all(x.decision_time in {b.time+300 for b in candles}
               for x in generate_signals(candles,start_hour=0,end_hour=24))


def test_gaps_reset_history_without_lookahead():
    left=sample(30)
    right=[Bar(b.time+100000,b.open,b.high,b.low,b.close) for b in sample(20)]
    assert generate_signals(left+right,start_hour=0,end_hour=24)==[]


def test_reject_invalid_bar_or_duplicate_time():
    b=sample(2)
    with pytest.raises(ValueError):
        generate_signals([b[0],b[0]])
    with pytest.raises(ValueError):
        generate_signals([Bar(0,10,9,8,10)])


def test_session_filter_cannot_introduce_early_signals():
    c=sample()
    everything=generate_signals(c,start_hour=0,end_hour=24)
    during=generate_signals(c,start_hour=6,end_hour=22)
    assert set(during).issubset(set(everything))
