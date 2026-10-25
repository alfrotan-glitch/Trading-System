import importlib.util
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('qts_research',ROOT/'research/research.py')
r=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=r
spec.loader.exec_module(r)
SPEC={'tick_size':'.01','point':'.01','stops_level':'25','volume_step':'.01','volume_max':'20','volume_min':'.01'}

def test_limit_requires_executable_side_and_penetration():
    assert not r.fillable(1,100,99.8,100.1,.01)
    assert not r.fillable(1,100,99.8,100,.01)
    assert r.fillable(1,100,99.8,99.98,.01)
    assert not r.fillable(-1,100,99.9,100.2,.01)
    assert r.fillable(-1,100,100.02,100.3,.01)

def test_gap_stop_uses_next_quote_and_adverse_slippage():
    assert r.exit_price(1,99,103,98,98.2,.05)==(97.95,'stop')
    assert r.exit_price(-1,101,97,102,102.2,.05)==(102.25,'stop')
    assert r.exit_price(1,99,103,104,104.2,.05)==(103,'target')

def test_duplicate_tick_cannot_double_fill_or_double_close():
    sim=r.Simulator('trend_pullback',SPEC)
    sim.pending=dict(side=1,entry=100,stop=99,target=102,lots=.1,expiry=5000,submitted=1000,risk_cash=10,regime='range')
    sim.tick(2000,99.8,99.9)
    sim.tick(2000,99.8,99.9)
    assert sim.count['fills']==1
    sim.tick(3000,102,102.2)
    sim.tick(3000,102,102.2)
    assert len(sim.trades)==1
    assert sim.trades[0]['net']==19

def test_expired_order_cannot_fill_on_same_tick():
    sim=r.Simulator('trend_pullback',SPEC)
    sim.pending=dict(side=1,entry=100,stop=99,target=102,lots=.1,expiry=2000,submitted=1000,risk_cash=10,regime='range')
    sim.tick(2000,99.8,99.9)
    assert sim.position is None and sim.count['fills']==0

def test_partial_history_gap_cancels_pending_without_synthetic_fill():
    sim=r.Simulator('trend_pullback',SPEC); sim.last=1000
    sim.pending=dict(side=1,entry=100,stop=99,target=102,lots=.1,expiry=200000,submitted=1000,risk_cash=10,regime='range')
    sim.tick(100000,99.8,99.9)
    assert sim.position is None and sim.pending is None

def test_future_bar_mutation_cannot_change_previous_signals():
    import math
    bars=[]
    for i in range(500):
        c=3000+math.sin(i/5)*10+i*.01
        bars.append(dict(time=1725238800+i*900,open=c-.1,close=c,low=c-1,high=c+1,spread=22,tick_volume=100))
    cutoff=bars[350]['time']
    first={t:s for t,s in r.signals(bars).items() if t<cutoff}
    assert first
    for b in bars[350:]:
        for k in ('open','close','high','low'): b[k]+=1000
    second={t:s for t,s in r.signals(bars).items() if t<cutoff}
    assert first==second

def test_former_stop_levels_preserve_tick_and_risk_floors():
    s=dict(side=1,atr=8,low=3000,high=3010)
    entry,stop,target,distance=r.levels(s,3004,3004.22,SPEC)
    assert abs(entry-2998.4)<1e-6
    assert abs(stop-2996.4)<1e-6
    assert target>entry and distance>=2

def test_alternative_market_entry_uses_executable_quote_and_cost():
    sys.path.insert(0,str(ROOT/'research'))
    import alternatives
    sim=alternatives.Market('channel_momentum',SPEC)
    sim.tick(100000,3000,3000.22)
    sim.submit(dict(family='channel_momentum',side=1,atr=5,time=100,regime='trend'),100250,3000,3000.22)
    assert abs(sim.position['entry']-3000.27)<1e-8
    assert sim.position['stop']<sim.position['entry']<sim.position['target']
    assert sim.position['lots']*sim.position['risk_cash']/sim.position['lots']<=25


def test_market_hypothesis_still_honors_latched_risk():
    import alternatives
    sim=alternatives.Market('channel_momentum',SPEC)
    sim.peak_stop=True
    sim.submit(dict(family='channel_momentum',side=1,atr=5,time=100,regime='trend'),100250,3000,3000.22)
    assert sim.position is None
