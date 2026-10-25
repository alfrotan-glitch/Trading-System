"""Causal previous-day level hypotheses; development data only."""
from collections import defaultdict
from pathlib import Path
import csv
import json
import research as r
from alternatives import Market

NAMES = ('previous_day_sweep', 'previous_day_acceptance')


def signals(bars):
    output = defaultdict(list)
    day = None
    current = []
    previous = None
    fired = set()
    atr = 0.0
    for i, b in enumerate(bars):
        stamp = int(b['time'])
        today = stamp // 86400
        if today != day:
            if current:
                previous = dict(high=max(x['high'] for x in current),
                                low=min(x['low'] for x in current), count=len(current))
            current = []
            fired = set()
            day = today
        current.append(b)
        prior_close = bars[i-1]['close'] if i else b['close']
        tr = max(b['high']-b['low'], abs(b['high']-prior_close), abs(b['low']-prior_close))
        atr = tr if i == 0 else atr + (tr-atr)/14
        if i < 200 or previous is None or previous['count'] < 40 or atr <= 0:
            continue
        if stamp-bars[i-1]['time'] != 900:
            continue
        now = stamp+900
        if not 6 <= now % 86400 // 3600 < 22:
            continue
        hi, lo = previous['high'], previous['low']
        proposals = []
        if lo <= b['open'] <= hi and b['high'] > hi+0.15*atr and b['close'] < hi:
            proposals.append(('previous_day_sweep', -1))
        if lo <= b['open'] <= hi and b['low'] < lo-0.15*atr and b['close'] > lo:
            proposals.append(('previous_day_sweep', 1))
        if lo <= prior_close <= hi and b['close'] > hi+0.25*atr:
            proposals.append(('previous_day_acceptance', 1))
        if lo <= prior_close <= hi and b['close'] < lo-0.25*atr:
            proposals.append(('previous_day_acceptance', -1))
        recent = bars[i-20:i+1]
        changes = [recent[j]['close']-recent[j-1]['close'] for j in range(1,len(recent))]
        movement = sum(abs(x) for x in changes)
        efficiency = abs(b['close']-recent[0]['close'])/movement if movement else 0.0
        regime = 'trend' if efficiency >= 0.4 else 'range' if efficiency < 0.25 else 'transition'
        for family, side in proposals:
            key = family, side
            if key not in fired:
                output[now].append(dict(family=family, side=side, atr=atr, time=now,
                                        regime=regime))
                fired.add(key)
    return output


def main():
    data = r.ROOT/'runtime/terminal/MQL5/Files/QTS_research'
    out = r.ROOT/'evidence/prior_day'
    out.mkdir(parents=True, exist_ok=True)
    protocol = Path(__file__).with_name('prior_day_protocol.json')
    frozen = json.loads(protocol.read_text(encoding='utf-8-sig'))
    bars = r.load_bars(data/'bars.csv')
    spec = next(csv.DictReader((data/'spec.csv').open(encoding='utf-8-sig')))
    if spec['server'] != 'WMMarkets-Demo' or spec['symbol'] != 'XAUUSD@' or float(spec['contract_size']) != 100:
        raise ValueError('Unsupported broker specification')
    (out/'run_manifest.json').write_text(json.dumps({
        'protocol_sha256': r.digest(protocol), 'engine_sha256': r.digest(Path(r.__file__)),
        'hypotheses_sha256': r.digest(Path(__file__)), 'validation_evaluated': False,
        'holdout_evaluated': False}, indent=2), encoding='utf-8')
    result = r.evaluate(data, bars, spec, *map(r.epoch, frozen['development']),
                        out, 'development', signals, Market, NAMES)
    print(json.dumps(result['metrics'], indent=2), flush=True)


if __name__ == '__main__':
    main()
