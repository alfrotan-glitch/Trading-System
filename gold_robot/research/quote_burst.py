"""Causal tick-event research for short-horizon XAUUSD burst hypotheses."""
from __future__ import annotations
import csv
import json
import math
from collections import defaultdict, deque
from pathlib import Path
import research as r

NAMES = ('quote_burst_momentum', 'quote_burst_reversion')


class ScalpMarket(r.Simulator):
    def tick(self, t, bid, ask):
        super().tick(t, bid, ask)
        if self.position and t-self.position['filled'] >= 20*60000:
            side = self.position['side']
            self.close(t, (bid if side > 0 else ask)-side*0.05, 'time')

    def submit(self, sig, t, bid, ask):
        self.count['signals'] += 1
        if t > sig['time_msc']+5000:
            self.count['stale_signal'] += 1
            return
        if self.position or self.pending or self.daily_stop or self.peak_stop or self.placements >= 5 or self.fills >= 3:
            self.count['exposure_or_risk_veto'] += 1
            return
        spread = ask-bid
        atr = sig['atr']
        step = float(self.spec['tick_size'])
        point = float(self.spec['point'])
        mid = (ask+bid)/2
        if spread <= 0 or spread/point > 90+1e-7 or spread*10000/mid > 3 or spread > 0.2*atr:
            self.count['price_or_spread_veto'] += 1
            return
        floor = (float(self.spec['stops_level'])+2)*point+2*step
        distance = math.ceil(max(0.6*atr,3*spread,floor)/step-1e-9)*step
        side = sig['side']
        entry = (ask if side > 0 else bid)+side*0.05
        stop = entry-side*distance
        target = entry+side*2*distance
        budget = self.equity(bid,ask)*0.0025
        volume_step = float(self.spec['volume_step'])
        lots = min(float(self.spec['volume_max']),
                   math.floor(budget/(distance*float(self.spec['contract_size'])*1.35)/volume_step+1e-9)*volume_step)
        if lots < float(self.spec['volume_min']):
            self.count['minimum_lot_veto'] += 1
            return
        self.position = dict(sig, entry=entry, stop=stop, target=target, lots=lots,
                             filled=t, risk_cash=distance*float(self.spec['contract_size'])*lots)
        self.placements += 1
        self.fills += 1
        self.count['placements'] += 1
        self.count['fills'] += 1


def atr_rows(bars, end):
    output = []
    atr = 0.0
    previous = None
    for i,bar in enumerate(b for b in bars if b['time'] < end):
        close = bar['close']
        prev = previous if previous is not None else close
        tr = max(bar['high']-bar['low'],abs(bar['high']-prev),abs(bar['low']-prev))
        atr = tr if i == 0 else atr+(tr-atr)/14
        if i >= 200:
            output.append((int(bar['time']+900)*1000,atr))
        previous = close
    return output


def evaluate(data, bars, spec, start, end, out):
    indicators = atr_rows(bars,end)
    index = 0
    current_atr = 0.0
    known_at = 0
    sims = {name: ScalpMarket(name,spec) for name in NAMES}
    scheduled = {}
    last_event = {name: -10**18 for name in NAMES}
    window = deque()
    previous_tick = None
    days = set()
    coverage = []
    invalid = 0
    tickcount = 0
    last_t = 0
    for path in sorted(data.glob('ticks_*.csv')):
        day = int(path.stem.split('_')[1])
        if not start <= day < end:
            continue
        days.add(day//86400)
        seen = set()
        count = 0
        first = 0
        last = 0
        with path.open(newline='') as stream:
            next(stream)
            for line in stream:
                values = line.rstrip().split(',')
                t = int(values[0]); bid = float(values[1]); ask = float(values[2])
                if t < last_t or not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
                    invalid += 1
                    continue
                last_t = t
                count += 1
                first = first or t
                last = t
                seen.add(t//900000)
                while index < len(indicators) and indicators[index][0] <= t:
                    known_at,current_atr = indicators[index]
                    index += 1
                for name,sim in sims.items():
                    if sim.position or sim.pending:
                        sim.tick(t,bid,ask)
                    if name in scheduled:
                        signal = scheduled[name]
                        if t > signal['time_msc']+5000:
                            sim.count['stale_signal'] += 1
                            del scheduled[name]
                        elif t >= signal['time_msc']+250:
                            sim.tick(t,bid,ask)
                            sim.submit(signal,t,bid,ask)
                            del scheduled[name]
                if previous_tick is not None and t-previous_tick > 2000:
                    window.clear()
                previous_tick = t
                mid = (bid+ask)/2
                window.append((t,mid))
                while window and t-window[0][0] > 20000:
                    window.popleft()
                if (current_atr <= 0 or t-known_at > 1800000 or
                    not 6 <= t//3600000%24 < 22 or len(window) < 4 or
                    t-window[0][0] < 15000):
                    continue
                spread = ask-bid
                if spread <= 0 or spread/float(spec['point']) > 90 or spread*10000/mid > 3 or spread > 0.2*current_atr:
                    continue
                delta = mid-window[0][1]
                if abs(delta) < 0.35*current_atr:
                    continue
                sign = 1 if delta > 0 else -1
                for name,side in ((NAMES[0],sign),(NAMES[1],-sign)):
                    sim = sims[name]
                    if t-last_event[name] < 15*60000 or name in scheduled or sim.position or sim.pending:
                        continue
                    scheduled[name] = dict(family=name,side=side,atr=current_atr,
                                           time_msc=t,time=t//1000,regime='burst')
                    last_event[name] = t
        wanted = {int(b['time'])//900 for b in bars if day <= b['time'] < day+86400}
        coverage.append(dict(file=path.name,sha256=r.digest(path),ticks=count,
                             first=first,last=last,bar_intervals_without_ticks=len(wanted-seen)))
        tickcount += count
        if len(coverage)%20 == 0:
            print(f'development: {len(coverage)} days, {tickcount:,} ticks',flush=True)
    if tickcount:
        for sim in sims.values():
            if sim.position:
                side = sim.position['side']
                sim.close(last_t,(bid if side > 0 else ask)-side*0.05,'sample_end')
    expected = {int(b['time'])//86400*86400 for b in bars if start <= b['time'] < end}
    actual = {int(row['file'].split('_')[1].split('.')[0]) for row in coverage}
    result = dict(start=start,end=end,ticks=tickcount,invalid_ticks=invalid,
                  missing_tick_days=sorted(expected-actual),coverage=coverage,
                  metrics={name:r.metrics(sim,days) for name,sim in sims.items()},
                  validation_evaluated=False,holdout_evaluated=False)
    out.mkdir(parents=True,exist_ok=True)
    (out/'development.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (out/'development_trades.csv').open('w',newline='') as stream:
        fields=['family','entry_time','exit_time','side','entry','exit','lots','net','gross','reason','r','regime']
        writer=csv.DictWriter(stream,fields);writer.writeheader()
        for sim in sims.values(): writer.writerows(sim.trades)
    return result


def main():
    data = r.ROOT/'runtime/terminal/MQL5/Files/QTS_research'
    out = r.ROOT/'evidence/quote_burst'
    out.mkdir(parents=True,exist_ok=True)
    source = Path(__file__)
    protocol = source.with_name('quote_burst_protocol.json')
    frozen = json.loads(protocol.read_text(encoding='utf-8-sig'))
    bars = r.load_bars(data/'bars.csv')
    with (data/'spec.csv').open(encoding='utf-8-sig') as stream:
        spec = next(csv.DictReader(stream))
    if spec['server'] != 'WMMarkets-Demo' or spec['symbol'] != 'XAUUSD@' or float(spec['contract_size']) != 100:
        raise ValueError('Unsupported broker specification')
    (out/'run_manifest.json').write_text(json.dumps({
        'protocol_sha256':r.digest(protocol),'engine_sha256':r.digest(source),
        'shared_metrics_sha256':r.digest(Path(r.__file__)),
        'bars_sha256':r.digest(data/'bars.csv'),'spec_sha256':r.digest(data/'spec.csv'),
        'validation_evaluated':False,'holdout_evaluated':False},indent=2),encoding='utf-8')
    result = evaluate(data,bars,spec,*map(r.epoch,frozen['development']),out)
    print(json.dumps(result['metrics'],indent=2),flush=True)


if __name__ == '__main__':
    main()
