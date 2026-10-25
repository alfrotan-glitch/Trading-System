"""Second, distinct hypothesis set. Development only; no EA order capability."""
import json, math, statistics
from collections import defaultdict
from pathlib import Path
import research as r
NAMES=('channel_momentum','opening_range_breakout','exhaustion_reversal')
def signals(bars):
    output=defaultdict(list); atr=0.; daybars=[]
    for i,b in enumerate(bars):
        c=b['close']; prev=bars[i-1]['close'] if i else c
        tr=max(b['high']-b['low'],abs(b['high']-prev),abs(b['low']-prev)); atr=tr if not i else atr+(tr-atr)/14
        if not daybars or daybars[-1]['time']//86400!=b['time']//86400: daybars=[]
        daybars.append(b)
        if i<200 or atr<=0: continue
        prior=bars[i-20:i]
        if any(prior[j]['time']-prior[j-1]['time']!=900 for j in range(1,20)) or b['time']-prior[-1]['time']!=900: continue
        changes=[bars[j]['close']-bars[j-1]['close'] for j in range(i-19,i+1)]
        efficiency=abs(c-bars[i-20]['close'])/sum(map(abs,changes)) if sum(map(abs,changes)) else 0.
        side={n:0 for n in NAMES}; now=int(b['time'])+900; hour=now%86400//3600
        if not 6<=hour<22: continue
        if efficiency>.4:
            side['channel_momentum']=1 if c>max(x['high'] for x in prior) else -1 if c<min(x['low'] for x in prior) else 0
        early=[x for x in daybars[:-1] if int(x['time'])%86400//3600<6]
        if 8<=hour<12 and len(early)>=12:
            hi=max(x['high'] for x in early); lo=min(x['low'] for x in early)
            side['opening_range_breakout']=1 if prev<=hi<c else -1 if prev>=lo>c else 0
        old=[bars[j]['close']-bars[j-1]['close'] for j in range(i-3,i)]
        if sum(old)>2*atr and all(x>0 for x in old) and c<b['open']: side['exhaustion_reversal']=-1
        if sum(old)<-2*atr and all(x<0 for x in old) and c>b['open']: side['exhaustion_reversal']=1
        for name,d in side.items():
            if d: output[now].append(dict(family=name,side=d,atr=atr,time=now,regime='trend' if efficiency>=.4 else 'range' if efficiency<.25 else 'transition'))
    return output

class Market(r.Simulator):
    def submit(self,sig,t,bid,ask):
        self.count['signals']+=1
        if t>sig['time']*1000+5000: self.count['stale_signal']+=1; return
        if self.position or self.pending or self.daily_stop or self.peak_stop or self.placements>=5 or self.fills>=3:
            self.count['exposure_or_risk_veto']+=1; return
        spread=ask-bid; atr=sig['atr']; point=float(self.spec['point']); step=float(self.spec['tick_size'])
        if spread<=0 or spread/point>90+1e-7 or spread*10000/((ask+bid)/2)>3 or spread>atr*.2:
            self.count['price_or_spread_veto']+=1; return
        distance=math.ceil(max(atr*(1 if sig['family']=='exhaustion_reversal' else 1.5),3*spread,(float(self.spec['stops_level'])+2)*point+2*step)/step)*step
        rr=1.5 if sig['family']=='exhaustion_reversal' else 2
        side=sig['side']; entry=(ask if side>0 else bid)+side*.05
        budget=self.equity(bid,ask)*.0025; vstep=float(self.spec['volume_step'])
        lots=min(float(self.spec['volume_max']),math.floor(budget/(distance*100*1.35)/vstep+1e-9)*vstep)
        if lots<float(self.spec['volume_min']): self.count['minimum_lot_veto']+=1; return
        self.position=dict(sig,entry=entry,stop=entry-side*distance,target=entry+side*distance*rr,lots=lots,filled=t,risk_cash=distance*100*lots)
        self.placements+=1; self.fills+=1; self.count['placements']+=1; self.count['fills']+=1

def main():
    data=r.ROOT/'runtime/terminal/MQL5/Files/QTS_research'; out=r.ROOT/'evidence/alternatives'; out.mkdir(parents=True,exist_ok=True)
    protocol=Path(__file__).with_name('alternative_protocol.json')
    p=json.loads(protocol.read_text(encoding='utf-8-sig')); bars=r.load_bars(data/'bars.csv')
    spec=next(r.csv.DictReader((data/'spec.csv').open()))
    (out/'run_manifest.json').write_text(json.dumps(dict(protocol_sha256=r.digest(protocol),engine_sha256=r.digest(Path(r.__file__)),hypotheses_sha256=r.digest(Path(__file__)),holdout_evaluated=False,validation_evaluated=False),indent=2))
    result=r.evaluate(data,bars,spec,*map(r.epoch,p['development']),out,'development',signals,Market,NAMES)
    print(json.dumps(result['metrics'],indent=2),flush=True)
if __name__=='__main__': main()
