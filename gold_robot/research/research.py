"""Frozen broker-tick research, standard library only. No broker order API.
Candidate families are research hypotheses, not certified reproductions of the EA.
The sealed holdout is deliberately never evaluated by this program.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, random, statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FAMILIES = ('trend_pullback','range_reversion','breakout_retest','failed_breakout','compression_expansion','session_reversal')
ROOT = Path(__file__).resolve().parents[1]

def epoch(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def load_bars(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        bars=[{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]
    previous=0
    for b in bars:
        if b['time']<=previous or not all(math.isfinite(x) for x in b.values()): raise ValueError('Invalid/unsorted bars')
        if not 0<b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']: raise ValueError('Invalid OHLC')
        previous=b['time']
    return bars

def signals(bars):
    """Indicators and extrema use only already CLOSED bars; no backfilled joins."""
    output=defaultdict(list); fast=slow=atr=0.; closes=[]; trs=[]; day_bars=[]
    for i,b in enumerate(bars):
        c=b['close']; previous=bars[i-1]['close'] if i else c
        oldfast=fast
        fast=c if not i else fast+(c-fast)*2/21
        slow=c if not i else slow+(c-slow)*2/51
        tr=max(b['high']-b['low'],abs(b['high']-previous),abs(b['low']-previous))
        atr=tr if not i else atr+(tr-atr)/14
        closes.append(c); trs.append(tr)
        if not day_bars or int(day_bars[-1]['time'])//86400!=int(b['time'])//86400: day_bars=[]
        day_bars.append(b)
        if i<200 or atr<=0: continue
        recent=bars[i-7:i+1]
        if any(recent[j]['time']-recent[j-1]['time']!=900 for j in range(1,8)): continue
        prior=bars[i-20:i]
        if any(prior[j]['time']-prior[j-1]['time']!=900 for j in range(1,20)): continue
        lo=min(x['low'] for x in recent); hi=max(x['high'] for x in recent)
        priorlo=min(x['low'] for x in prior); priorhi=max(x['high'] for x in prior)
        mean=statistics.fmean(closes[-20:]); sd=statistics.pstdev(closes[-20:])
        move=sum(abs(closes[j]-closes[j-1]) for j in range(i-19,i+1))
        efficiency=abs(c-closes[i-20])/move if move else 0.
        z=(c-mean)/sd if sd else 0.
        side={k:0 for k in FAMILIES}
        side['trend_pullback']=1 if fast>slow and previous<=oldfast and c>fast else -1 if fast<slow and previous>=oldfast and c<fast else 0
        if efficiency<.25 and abs(fast-slow)<.3*atr: side['range_reversion']=1 if z<-2 else -1 if z>2 else 0
        side['breakout_retest']=1 if c>priorhi and fast>slow else -1 if c<priorlo and fast<slow else 0
        side['failed_breakout']=1 if b['low']<priorlo and c>priorlo else -1 if b['high']>priorhi and c<priorhi else 0
        if statistics.fmean(trs[-11:-1])<.7*statistics.fmean(trs[-61:-1]) and tr>1.5*atr:
            side['compression_expansion']=1 if c>priorhi else -1 if c<priorlo else 0
        hour=int(b['time'])%86400//3600
        early=[x for x in day_bars[:-1] if int(x['time'])%86400//3600<6]
        if 8<=hour<11 and len(early)>=12:
            elo=min(x['low'] for x in early); ehi=max(x['high'] for x in early)
            side['session_reversal']=1 if b['low']<elo and c>elo else -1 if b['high']>ehi and c<ehi else 0
        now=int(b['time'])+900
        if not 6<=now%86400//3600<22: continue
        for family,direction in side.items():
            if direction:
                output[now].append(dict(family=family,side=direction,atr=atr,low=lo,high=hi,time=now,regime='trend' if efficiency>=.4 else 'range' if efficiency<.25 else 'transition'))
    return output

def levels(sig,bid,ask,spec):
    spread=ask-bid; atr=sig['atr']; step=float(spec['tick_size']); point=float(spec['point'])
    if spread<=0 or spread/point>90+1e-7 or spread*10000/((ask+bid)/2)>3 or spread>atr*.2: return None
    minimum=(float(spec['stops_level'])+2)*point
    buffer=max(.2*atr,1.2*spread)
    distance=math.ceil(max(.25*atr,3*spread,minimum+2*step)/step-1e-9)*step
    if sig['side']>0:
        entry=math.floor((sig['low']-buffer)/step)*step; stop=entry-distance
        target=math.floor((sig['high']-spread)/step)*step
        if bid-entry<max(minimum,2*step) or ask-entry>1.8*atr or target-entry<1.7*distance: return None
    else:
        entry=math.ceil((sig['high']+buffer)/step)*step; stop=entry+distance
        target=math.ceil((sig['low']+spread)/step)*step
        if entry-ask<max(minimum,2*step) or entry-bid>1.8*atr or entry-target<1.7*distance: return None
    return entry,stop,target,distance

def fillable(side,entry,bid,ask,penetration):
    return ask<=entry-penetration if side>0 else bid>=entry+penetration

def exit_price(side,stop,target,bid,ask,slippage):
    quote=bid if side>0 else ask
    if side*(quote-stop)<=0: return quote-side*slippage,'stop'
    if side*(quote-target)>=0: return target,'target'
    return None

class Simulator:
    def __init__(self,family,spec):
        self.family=family; self.spec=spec; self.pending=None; self.position=None
        self.cash=10000.; self.peak=10000.; self.maxdd=0.; self.day=None; self.daystart=10000.; self.daily_stop=False; self.peak_stop=False
        self.placements=self.fills=0; self.trades=[]; self.count=defaultdict(int); self.last=None
    def equity(self,bid,ask):
        p=self.position
        return self.cash if not p else self.cash+(p['side']*((bid if p['side']>0 else ask)-p['entry'])*100-10)*p['lots']
    def close(self,t,price,reason):
        p=self.position; gross=p['side']*(price-p['entry'])*100*p['lots']; net=gross-10*p['lots']
        self.cash+=net
        self.trades.append(dict(family=self.family,entry_time=p['filled'],exit_time=t,side=p['side'],entry=p['entry'],exit=price,lots=p['lots'],net=net,gross=gross,reason=reason,r=net/p['risk_cash'],regime=p['regime']))
        self.position=None
    def tick(self,t,bid,ask):
        day=t//86400000
        if day!=self.day:
            self.day=day; self.daystart=self.equity(bid,ask); self.daily_stop=False; self.placements=self.fills=0
        if self.pending:
            p=self.pending
            if t>=p['expiry'] or (self.last is not None and t-self.last>60000):
                self.count['expired_or_quote_gap']+=1; self.pending=None
            elif t>p['submitted'] and fillable(p['side'],p['entry'],bid,ask,.01):
                p['filled']=t; self.position=p; self.pending=None; self.fills+=1; self.count['fills']+=1
        if self.position:
            p=self.position
            outcome=exit_price(p['side'],p['stop'],p['target'],bid,ask,.05)
            if outcome: self.close(t,*outcome)
            elif t-p['filled']>=180*60000: self.close(t,(bid if p['side']>0 else ask)-p['side']*.05,'time')
        eq=self.equity(bid,ask); self.peak=max(self.peak,eq); self.maxdd=max(self.maxdd,self.peak-eq)
        self.daily_stop |= eq<=self.daystart*.985
        self.peak_stop |= eq<=self.peak*.96
        if self.daily_stop or self.peak_stop:
            self.pending=None
            if self.position:
                p=self.position; self.close(t,(bid if p['side']>0 else ask)-p['side']*.05,'risk')
        self.last=t
    def submit(self,sig,t,bid,ask):
        self.count['signals']+=1
        if t>sig['time']*1000+5000: self.count['stale_signal']+=1; return
        if self.position or self.pending or self.daily_stop or self.peak_stop or self.placements>=5 or self.fills>=3:
            self.count['exposure_or_risk_veto']+=1; return
        lv=levels(sig,bid,ask,self.spec)
        if lv is None: self.count['price_or_spread_veto']+=1; return
        entry,stop,target,distance=lv
        # USD gold contract verified from export; no leverage/margin claim.
        budget=self.equity(bid,ask)*.0025
        step=float(self.spec['volume_step']); lots=math.floor(budget/(distance*100*1.35)/step+1e-9)*step
        lots=min(lots,float(self.spec['volume_max']))
        if lots<float(self.spec['volume_min']): self.count['minimum_lot_veto']+=1; return
        expiry=min(sig['time']+1800,sig['time']//86400*86400+21*3600+30*60)*1000
        if expiry<t+60000: self.count['expiry_veto']+=1; return
        self.pending=dict(sig,entry=entry,stop=stop,target=target,lots=lots,expiry=expiry,submitted=t,risk_cash=distance*100*lots)
        self.placements+=1; self.count['placements']+=1

def metrics(sim,days):
    trades=sim.trades; values=[x['net'] for x in trades]; net=sum(values)
    wins=sum(x for x in values if x>0); losses=-sum(x for x in values if x<0)
    daily={d:0. for d in days}; quarters=defaultdict(float); regimes=defaultdict(lambda:[0,0.])
    byday=defaultdict(list)
    for x in trades:
        d=x['exit_time']//86400000; daily[d]=daily.get(d,0.)+x['net']; byday[d].append(x['net'])
        dt=datetime.fromtimestamp(x['exit_time']/1000,timezone.utc); quarters[f'{dt.year}-Q{(dt.month-1)//3+1}']+=x['net']
        regimes[x['regime']][0]+=1; regimes[x['regime']][1]+=x['net']
    daily_values=list(daily.values()); sd=statistics.stdev(daily_values) if len(daily_values)>1 else 0
    rng=random.Random(6241024); blocks=[byday.get(d,[]) for d in sorted(daily)]; boot=[]
    if values:
        for _ in range(1000):
            sample=[v for block in rng.choices(blocks,k=len(blocks)) for v in block]
            if sample: boot.append(statistics.fmean(sample))
    boot.sort()
    stress=sum(x['net']-x['lots']*(10+.10*100) for x in trades)
    lower=boot[max(0,int(len(boot)*.01)-1)] if boot else None
    pf=wins/losses if losses else None
    return dict(trades=len(trades),net_usd=net,expectancy_usd=statistics.fmean(values) if values else None,profit_factor=pf,
        daily_sharpe=statistics.fmean(daily_values)/sd*math.sqrt(252) if sd else None,max_marked_drawdown_usd=sim.maxdd,
        recovery=net/sim.maxdd if sim.maxdd else None,positive_quarters=sum(x>0 for x in quarters.values()),quarters=dict(quarters),regimes=dict(regimes),
        day_block_bootstrap_99pct_lower_expectancy=lower,stress_net_usd=stress,peak_stop=sim.peak_stop,
        screen_pass=bool(len(values)>=100 and net>0 and pf and pf>=1.15 and lower and lower>0 and stress>0 and sum(x>0 for x in quarters.values())>=3),
        execution_counts=dict(sim.count))

def evaluate(data,bars,spec,start,end,out,label,signal_builder=signals,simtype=Simulator,families=FAMILIES):
    allsignals=signal_builder([b for b in bars if b['time']<end]); scheduled=sorted(t for t in allsignals if start<=t<end)
    si=0; sims={name:simtype(name,spec) for name in families}; days=set(); coverage=[]; invalid=0; tickcount=0; lastt=0
    paths=sorted(p for p in data.glob('ticks_*.csv') if start<=int(p.stem.split('_')[1])<end)
    expected={int(b['time'])//86400*86400 for b in bars if start<=b['time']<end}
    missing=sorted(expected-{int(p.stem.split('_')[1]) for p in paths})
    for path in paths:
        day=int(path.stem.split('_')[1]); days.add(day//86400); seen_buckets=set(); n=0; first=last=0
        with path.open(newline='') as f:
            next(f)
            for line in f:
                pieces=line.rstrip().split(','); t=int(pieces[0]); bid=float(pieces[1]); ask=float(pieces[2])
                if t<lastt or not (math.isfinite(bid) and math.isfinite(ask) and 0<bid<=ask): invalid+=1; continue
                lastt=t; n+=1; first=first or t; last=t; seen_buckets.add(t//900000)
                for sim in sims.values():
                    if sim.pending or sim.position: sim.tick(t,bid,ask)
                while si<len(scheduled) and scheduled[si]*1000+250<=t:
                    st=scheduled[si]
                    for sig in allsignals[st]:
                        sim=sims[sig['family']]
                        sim.tick(t,bid,ask)
                        sim.submit(sig,t,bid,ask)
                    si+=1
        wanted={int(b['time'])//900 for b in bars if day<=b['time']<day+86400}
        coverage.append(dict(file=path.name,sha256=digest(path),ticks=n,first=first,last=last,bar_intervals_without_ticks=len(wanted-seen_buckets)))
        tickcount+=n
        if len(coverage)%20==0: print(f'{label}: {len(coverage)}/{len(paths)} days, {tickcount:,} ticks',flush=True)
    # Exposure is valued and closed at the last executable observation; disclose truncation.
    if tickcount:
        for sim in sims.values():
            if sim.position:
                p=sim.position; sim.close(lastt,(bid if p['side']>0 else ask)-p['side']*.05,'sample_end')
    result=dict(label=label,start=start,end=end,ticks=tickcount,invalid_ticks=invalid,missing_tick_days=missing,coverage=coverage,
        metrics={name:metrics(sim,days) for name,sim in sims.items()},promoted_strategies=[],
        limitations=['Historical broker specifications, commission and financing not verified. Cost figures are explicit stress assumptions.',
        'No market depth/queue, partial-fill or actual broker rejection model. One-tick penetration is a conservative fill proxy, not a fill guarantee.',
        'Independent family tests; not a simultaneous portfolio. Fixed-risk stops can end a sample early.',
        'Session hours use stored timestamps; broker UTC/DST mapping unverified.',
        'Native EA parity and real-tick Strategy Tester run still required.'])
    out.mkdir(parents=True,exist_ok=True)
    (out/f'{label}.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    with (out/f'{label}_trades.csv').open('w',newline='') as f:
        fields=['family','entry_time','exit_time','side','entry','exit','lots','net','gross','reason','r','regime']; writer=csv.DictWriter(f,fields); writer.writeheader()
        for sim in sims.values(): writer.writerows(sim.trades)
    return result

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--data',type=Path,default=ROOT/'runtime/terminal/MQL5/Files/QTS_research'); parser.add_argument('--output',type=Path,default=ROOT/'evidence/research'); args=parser.parse_args()
    protocol_path=ROOT/'research/protocol.json'; protocol=json.loads(protocol_path.read_text(encoding='utf-8-sig'))
    spec=next(csv.DictReader((args.data/'spec.csv').open(encoding='utf-8-sig')))
    if spec['server']!='WMMarkets-Demo' or spec['symbol']!='XAUUSD@' or float(spec['contract_size'])!=100: raise ValueError('Unsupported broker specification')
    bars=load_bars(args.data/'bars.csv'); args.output.mkdir(parents=True,exist_ok=True)
    manifest=dict(protocol_sha256=digest(protocol_path),engine_sha256=digest(Path(__file__)),bars_sha256=digest(args.data/'bars.csv'),spec_sha256=digest(args.data/'spec.csv'),holdout_evaluated=False)
    (args.output/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
    for label in ('development','validation'):
        result=evaluate(args.data,bars,spec,*map(epoch,protocol[label]),args.output,label)
        print(json.dumps({name:{k:v for k,v in row.items() if k in ('trades','net_usd','profit_factor','screen_pass')} for name,row in result['metrics'].items()},indent=2),flush=True)
        if label=='development' and not any(row['screen_pass'] for row in result['metrics'].values()):
            print('No development survivor. Validation and final holdout remain unexamined.',flush=True); break
if __name__=='__main__': main()
