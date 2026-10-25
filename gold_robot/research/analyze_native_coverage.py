"""Explain native pending-order coverage without changing EA execution rules."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import bisect
import json
import re
import statistics
import sys
sys.path.insert(0,str(Path(__file__).parent))
import research as r
from parse_native_report import cells

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'evidence/native/native_development_2025.htm'
LOG=ROOT/'evidence/native/native_development_fixed_agent.log'
BARS=ROOT/'runtime/terminal/MQL5/Files/QTS_research/bars.csv'


def parse_time(value):
    return datetime.strptime(value,'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()


def main():
    html=REPORT.read_text(encoding='utf-16')
    section=html.split('>Orders</b>',1)[1].split('>Deals</b>',1)[0]
    rows=[cells(x) for x in re.findall(r'<tr\s+bgcolor=[^>]+>(.*?)</tr>',section,re.I|re.S)]
    orders=[dict(open=x[0],ticket=x[1],side=x[3],volume=x[4],price=float(x[5]),
                 closed=x[8],state=x[9]) for x in rows if len(x)>=11 and x[3].endswith('limit')]
    bars=r.load_bars(BARS)
    times=[];atrs=[];atr=0.0;previous=0.0
    for i,b in enumerate(bars):
        close=b['close'];prev=previous if i else close
        tr=max(b['high']-b['low'],abs(b['high']-prev),abs(b['low']-prev))
        atr=tr if i==0 else atr+(tr-atr)/14
        times.append(int(b['time']+900));atrs.append(atr)
        previous=close
    quotes=defaultdict(list)
    pattern=re.compile(r'(\d{4}\.\d\d\.\d\d \d\d:\d\d:\d\d)\s+(buy|sell) limit [\d.]+ XAUUSD_QTS_AUDIT at ([\d.]+) sl: [\d.]+ tp: [\d.]+ \(([\d.]+) / ([\d.]+)\)')
    for line in LOG.read_text(encoding='utf-8').splitlines():
        if '\tTrade\t' not in line: continue
        match=pattern.search(line)
        if match:
            stamp,side,price,bid,ask=match.groups()
            quotes[(stamp,side,round(float(price),2))].append((float(bid),float(ask)))
    bins=defaultdict(lambda:Counter())
    distance_ratios=[];spreads=[];latencies=[];unmatched=0
    for order in orders:
        side='buy' if order['side'].startswith('buy') else 'sell'
        key=(order['open'],side,round(order['price'],2))
        match=quotes.get(key)
        if not match:
            unmatched+=1;continue
        bid,ask=match.pop(0)
        stamp=int(parse_time(order['open']))
        index=bisect.bisect_right(times,stamp)-1
        if index<0: unmatched+=1;continue
        atr=atrs[index]
        distance=(ask-order['price']) if side=='buy' else (order['price']-bid)
        ratio=distance/atr if atr>0 else None
        if ratio is None: unmatched+=1;continue
        label='<0.5 ATR' if ratio<.5 else '0.5-1 ATR' if ratio<1 else '1-1.8 ATR' if ratio<=1.8 else '>1.8 ATR'
        bins[label][order['state']]+=1
        distance_ratios.append(ratio)
        spreads.append(ask-bid)
        if order['state']=='filled':
            latencies.append((parse_time(order['closed'])-parse_time(order['open']))/60)
    result={'native_pending_orders':len(orders),'states':dict(Counter(x['state'] for x in orders)),
            'by_side_state':{str(k):v for k,v in Counter((x['side'],x['state']) for x in orders).items()},
            'filled_fraction':round(sum(x['state']=='filled' for x in orders)/len(orders),4),
            'initial_distance_atr_bins':{key:dict(val) for key,val in sorted(bins.items())},
            'initial_distance_atr_median':round(statistics.median(distance_ratios),3),
            'initial_spread_price_median':round(statistics.median(spreads),3),
            'fill_latency_min_median':round(statistics.median(latencies),2),
            'fill_latency_min_max':round(max(latencies),2),
            'unmatched_quote_rows':unmatched,'ticks_tested':28969323,
            'limitation':'Unfilled LIMIT orders are missed fills, not proven profitable missed opportunities. ATR is a causal Python proxy, not exact MT5 initialization.'}
    target=ROOT/'evidence/native/native_order_coverage.json'
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
