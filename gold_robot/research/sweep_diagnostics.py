"""Fixed, descriptive Prior-Day Sweep diagnostics; never select a segment for trading."""
import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def score(rows):
    values = [float(r['net']) for r in rows]
    wins = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    return {'trades': len(values), 'net_usd': round(sum(values), 2),
            'expectancy_usd': round(statistics.fmean(values), 2) if values else None,
            'profit_factor': round(wins/losses, 3) if losses else None}


def summarize(trades_path, coverage_path):
    with Path(trades_path).open(newline='', encoding='utf-8') as stream:
        rows = [r for r in csv.DictReader(stream) if r['family'] == 'previous_day_sweep']
    result = json.loads(Path(coverage_path).read_text(encoding='utf-8'))
    days = sorted(int(x['file'].split('_')[1].split('.')[0])//86400 for x in result['coverage'])
    splits = {'side': defaultdict(list), 'efficiency_regime': defaultdict(list),
              'broker_clock_entry_bin': defaultdict(list), 'month': defaultdict(list),
              'quarter': defaultdict(list), 'exit_reason': defaultdict(list)}
    by_day = defaultdict(list)
    by_week = defaultdict(list)
    for row in rows:
        stamp = int(row['entry_time'])//1000
        dt = datetime.fromtimestamp(stamp, timezone.utc)
        hour = dt.hour
        bin_name = '06-11' if 6 <= hour < 12 else '12-17' if 12 <= hour < 18 else '18-21' if 18 <= hour < 22 else 'outside'
        period = f'{dt.year}-{dt.month:02d}'
        quarter = f'{dt.year}-Q{(dt.month-1)//3+1}'
        keys = {'side': 'long' if int(row['side']) > 0 else 'short',
                'efficiency_regime': row['regime'], 'broker_clock_entry_bin': bin_name,
                'month': period, 'quarter': quarter, 'exit_reason': row['reason']}
        for name, key in keys.items():
            splits[name][key].append(row)
        by_day[stamp//86400].append(float(row['net']))
        iso = dt.isocalendar()
        by_week[(iso.year,iso.week)].append(float(row['net']))
    diagnostics = {name: {key: score(part) for key,part in sorted(groups.items())}
                   for name,groups in splits.items()}
    rng = random.Random(6242025)
    daily_blocks = [by_day.get(day,[]) for day in days]
    weeks = sorted({(datetime.fromtimestamp(day*86400,timezone.utc).isocalendar().year,
                     datetime.fromtimestamp(day*86400,timezone.utc).isocalendar().week) for day in days})
    weekly_blocks = [by_week.get(week,[]) for week in weeks]
    lower = {}
    for name,blocks in [('day',daily_blocks),('week',weekly_blocks)]:
        outcomes=[]
        for _ in range(20000):
            sample=[v for block in rng.choices(blocks,k=len(blocks)) for v in block]
            if sample: outcomes.append(statistics.fmean(sample))
        outcomes.sort()
        lower[name]={'99pct_lower_expectancy_usd':round(outcomes[int(.01*len(outcomes))],2),
                     '99_9pct_lower_expectancy_usd':round(outcomes[int(.001*len(outcomes))],2)}
    return {'overall':score(rows),'splits_descriptive_only':diagnostics,
            'bootstrap_seed':6242025,'bootstrap_resamples':20000,
            'lower_expectancy':lower,'coverage_days':len(days),
            'note':'All splits were fixed before inspecting the independent 2025 H2 result. Never promote a favorable post-hoc segment.'}

if __name__ == '__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('trades',type=Path)
    cli.add_argument('coverage',type=Path)
    cli.add_argument('output',type=Path)
    args=cli.parse_args()
    result=summarize(args.trades,args.coverage)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'overall':result['overall'],'lower_expectancy':result['lower_expectancy']},indent=2))
