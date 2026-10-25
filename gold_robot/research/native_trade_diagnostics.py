"""Cost-adjusted native MT5 exit diagnostics with zero-trade day blocks."""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json
import random
import re
import statistics
import research as r
from parse_native_report import cells,number,value

DATA=r.ROOT/'runtime/terminal/MQL5/Files/QTS_research'


def summarize(report,start,end):
    document=Path(report).read_text(encoding='utf-16')
    section=document.split('>Deals</b>',1)[1]
    exits=[]
    for row in re.findall(r'<tr\s+bgcolor=[^>]+>(.*?)</tr>',section,re.I|re.S):
        x=cells(row)
        if len(x)<13 or x[4].lower() not in ('out','out by','in/out'):
            continue
        dt=datetime.strptime(x[0],'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc)
        lots=number(x[5]);native=number(x[10]);commission=number(x[8]);swap=number(x[9])
        after=native+commission+swap-15*lots
        exits.append(dict(time=x[0],day=int(dt.timestamp())//86400,
                          week=(dt.isocalendar().year,dt.isocalendar().week),
                          quarter=f'{dt.year}-Q{(dt.month-1)//3+1}',
                          side='long' if x[3]=='sell' else 'short',lots=lots,
                          native_pnl=native,after_cost_pnl=after,
                          reason=x[12]))
    days=sorted(int(p.stem.split('_')[1])//86400 for p in DATA.glob('ticks_*.csv')
                if start<=int(p.stem.split('_')[1])<end)
    byday=defaultdict(list);byweek=defaultdict(list);byquarter=defaultdict(list);byreason=defaultdict(list)
    for x in exits:
        byday[x['day']].append(x['after_cost_pnl'])
        byweek[x['week']].append(x['after_cost_pnl'])
        byquarter[x['quarter']].append(x['after_cost_pnl'])
        reason='stop' if x['reason'].startswith('sl ') else 'target' if x['reason'].startswith('tp ') else 'other'
        byreason[reason].append(x['after_cost_pnl'])
    values=[x['after_cost_pnl'] for x in exits]
    wins=sum(v for v in values if v>0);losses=-sum(v for v in values if v<0)
    weeks=sorted({(datetime.fromtimestamp(day*86400,timezone.utc).isocalendar().year,
                   datetime.fromtimestamp(day*86400,timezone.utc).isocalendar().week) for day in days})
    rng=random.Random(6242025);bounds={}
    for name,blocks in [('day',[byday.get(d,[]) for d in days]),('week',[byweek.get(w,[]) for w in weeks])]:
        means=[]
        for _ in range(20000):
            sample=[v for block in rng.choices(blocks,k=len(blocks)) for v in block]
            if sample:means.append(statistics.fmean(sample))
        means.sort()
        bounds[name]={'99pct_lower_expectancy':round(means[int(.01*len(means))],2) if means else None,
                      '99_9pct_lower_expectancy':round(means[int(.001*len(means))],2) if means else None}
    native_total=number(value(document,'Total Net Profit:'))
    after_total=sum(values)
    return {'report':str(report),'report_sha256':r.digest(Path(report)),
            'trading_days':len(days),'trades':len(exits),
            'native_net_usd':round(native_total,2),
            'native_exit_profit_sum_usd':round(sum(x['native_pnl'] for x in exits),2),
            'after_extra_cost_net_usd':round(after_total,2),
            'stress_net_usd':round(after_total-20*sum(x['lots'] for x in exits),2),
            'after_extra_cost_profit_factor':round(wins/losses,3) if losses else None,
            'after_extra_cost_expectancy_usd':round(statistics.fmean(values),2) if values else None,
            'after_extra_cost_by_quarter':{k:round(sum(v),2) for k,v in sorted(byquarter.items())},
            'after_extra_cost_by_exit_reason':{k:dict(trades=len(v),net_usd=round(sum(v),2)) for k,v in sorted(byreason.items())},
            'day_week_block_bootstrap_seed':6242025,'bootstrap_resamples':20000,
            'bootstrap_lower_expectancy_usd':bounds,
            'exited_lots':round(sum(x['lots'] for x in exits),8),
            'extra_cost_model':'Add USD10 per roundtrip lot plus USD5/lot equivalent of 0.05 adverse exit price units, on top of native quote spread and any native fees. Historical tariff and slippage are unverified.',
            'limitation':'Assumed costs are deducted at exit; risk path/drawdown after costs is not fully reconstructed. Bootstrap bounds on selected samples are not independent proof.'}

if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('report',type=Path)
    cli.add_argument('start')
    cli.add_argument('end')
    cli.add_argument('output',type=Path)
    a=cli.parse_args()
    result=summarize(a.report,r.epoch(a.start),r.epoch(a.end))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
