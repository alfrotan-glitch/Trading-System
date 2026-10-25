"""Aggregate tester-only closed-bar coverage telemetry."""
from collections import Counter
from pathlib import Path
import json
import re
import sys

PATTERN=re.compile(r'QTS_COVER bar=(.*?) session=(\d) indicator=(\d) adx=(\d) raw=(-?\d) h1=(\d) status=(.*)$')

def parse(path):
    text=Path(path).read_text(encoding='utf-8')
    counts=Counter();statuses=Counter();raws=Counter()
    for line in text.splitlines():
        match=PATTERN.search(line)
        if not match:continue
        _,session,indicator,adx,raw,h1,status=match.groups()
        session=int(session);indicator=int(indicator);adx=int(adx);raw=int(raw);h1=int(h1)
        counts['closed_bars']+=1
        counts['session_open' if session else 'session_closed']+=1
        counts['indicator_values_ready']+=indicator
        counts['adx_gate_passed']+=adx
        counts['ema_pullback_cross_after_adx']+=raw!=0
        counts['h1_gate_passed']+=h1
        counts['signal_evaluation_attempted']+=int(status=='No closed-bar signal' or raw!=0)
        counts['raw_h1_veto']+=int(raw!=0 and h1==0)
        statuses[status]+=1
        if raw:raws['buy' if raw>0 else 'sell']+=1
    if not counts['closed_bars']:raise ValueError('No probe bars found')
    return {'funnel':dict(counts),'final_status_per_closed_bar':dict(statuses),
            'ema_cross_direction_after_adx':dict(raws),
            'note':'Counts are from a diagnostic copy of the canonical EA with logging only. No filter or risk rule was relaxed. A status can represent exposure or safety gating before signal evaluation.'}

if __name__=='__main__':
    result=parse(sys.argv[1])
    target=Path(sys.argv[2]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
