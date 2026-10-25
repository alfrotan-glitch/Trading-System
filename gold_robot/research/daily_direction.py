"""Prior-day direction continuation/reversal with same-day exits, tick replay."""
from __future__ import annotations
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
import research as r

NAMES=('daily_direction_continuation','daily_direction_reversal')


def signals(bars):
    output=defaultdict(list)
    day=None
    current=[]
    finished=[]
    for bar in bars:
        today=int(bar['time'])//86400
        if today!=day:
            if current:
                first=current[0];last=current[-1]
                finished.append(dict(open=first['open'],close=last['close'],
                                     high=max(x['high'] for x in current),
                                     low=min(x['low'] for x in current),count=len(current)))
            current=[]
            day=today
            if len(finished)>=20:
                prev=finished[-1]
                width=prev['high']-prev['low']
                body=prev['close']-prev['open']
                if prev['count']>=40 and width>0 and abs(body)>=0.4*width:
                    direction=1 if body>0 else -1
                    typical=statistics.median(x['high']-x['low'] for x in finished[-20:])
                    regime='wide_prior_day' if width>typical else 'narrow_prior_day'
                    now=today*86400+6*3600
                    for name,side in ((NAMES[0],direction),(NAMES[1],-direction)):
                        output[now].append(dict(family=name,side=side,range=width,
                                                time=now,regime=regime))
        current.append(bar)
    return output


class DailyMarket(r.Simulator):
    def tick(self,t,bid,ask):
        day=t//86400000
        if day!=self.day:
            self.day=day;self.daystart=self.equity(bid,ask);self.daily_stop=False
            self.placements=self.fills=0
        if self.position:
            p=self.position
            outcome=r.exit_price(p['side'],p['stop'],p['target'],bid,ask,.05)
            if outcome:self.close(t,*outcome)
            elif t-p['filled']>=15*3600000:
                side=p['side']
                self.close(t,(bid if side>0 else ask)-side*.05,'time')
        eq=self.equity(bid,ask)
        self.peak=max(self.peak,eq)
        self.maxdd=max(self.maxdd,self.peak-eq)
        self.daily_stop |= eq<=self.daystart*.985
        self.peak_stop |= eq<=self.peak*.96
        if (self.daily_stop or self.peak_stop) and self.position:
            side=self.position['side']
            self.close(t,(bid if side>0 else ask)-side*.05,'risk')
        self.last=t

    def submit(self,sig,t,bid,ask):
        self.count['signals']+=1
        if t>sig['time']*1000+5000:
            self.count['stale_signal']+=1;return
        if self.position or self.daily_stop or self.peak_stop or self.placements>=5 or self.fills>=3:
            self.count['exposure_or_risk_veto']+=1;return
        width=sig['range'];spread=ask-bid
        mid=(ask+bid)/2
        point=float(self.spec['point']);step=float(self.spec['tick_size'])
        if spread<=0 or spread/point>90+1e-7 or spread*10000/mid>3 or spread>0.2*width:
            self.count['price_or_spread_veto']+=1;return
        minimum=(float(self.spec['stops_level'])+2)*point+2*step
        distance=math.ceil(max(0.75*width,3*spread,minimum)/step-1e-9)*step
        side=sig['side']
        entry=(ask if side>0 else bid)+side*.05
        stop=entry-side*distance
        target=entry+side*1.5*distance
        budget=self.equity(bid,ask)*.0025
        volume_step=float(self.spec['volume_step']);contract=float(self.spec['contract_size'])
        lots=min(float(self.spec['volume_max']),
                 math.floor(budget/(distance*contract*1.35)/volume_step+1e-9)*volume_step)
        if lots<float(self.spec['volume_min']):
            self.count['minimum_lot_veto']+=1;return
        self.position=dict(sig,entry=entry,stop=stop,target=target,lots=lots,
                           filled=t,risk_cash=distance*contract*lots)
        self.placements+=1;self.fills+=1
        self.count['placements']+=1;self.count['fills']+=1


def main():
    data=r.ROOT/'runtime/terminal/MQL5/Files/QTS_research'
    out=r.ROOT/'evidence/daily_direction';out.mkdir(parents=True,exist_ok=True)
    protocol=Path(__file__).with_name('daily_direction_protocol.json')
    frozen=json.loads(protocol.read_text(encoding='utf-8-sig'))
    bars=r.load_bars(data/'bars.csv')
    with (data/'spec.csv').open(encoding='utf-8-sig') as stream:spec=next(csv.DictReader(stream))
    if spec['server']!='WMMarkets-Demo' or spec['symbol']!='XAUUSD@' or float(spec['contract_size'])!=100:
        raise ValueError('Unsupported broker specification')
    (out/'run_manifest.json').write_text(json.dumps({
        'protocol_sha256':r.digest(protocol),'hypotheses_sha256':r.digest(Path(__file__)),
        'engine_sha256':r.digest(Path(r.__file__)),'bars_sha256':r.digest(data/'bars.csv'),
        'spec_sha256':r.digest(data/'spec.csv'),'validation_evaluated':False,
        'holdout_evaluated':False},indent=2),encoding='utf-8')
    result=r.evaluate(data,bars,spec,*map(r.epoch,frozen['development']),out,
                      'development',signals,DailyMarket,NAMES)
    print(json.dumps(result['metrics'],indent=2),flush=True)

if __name__=='__main__':main()
