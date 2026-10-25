"""Count post-removal quote revisits for unfilled native LIMIT orders."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sys
sys.path.insert(0,str(Path(__file__).parent))
from parse_native_report import cells

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'evidence/native/native_development_2025.htm'
DATA=ROOT/'runtime/terminal/MQL5/Files/QTS_research'


def epoch(text):
    return int(datetime.strptime(text,'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp())


def main():
    html=REPORT.read_text(encoding='utf-16')
    section=html.split('>Orders</b>',1)[1].split('>Deals</b>',1)[0]
    orders=[]
    for row in re.findall(r'<tr\s+bgcolor=[^>]+>(.*?)</tr>',section,re.I|re.S):
        x=cells(row)
        if len(x)<11 or not x[3].endswith('limit') or x[9]=='filled': continue
        closed=epoch(x[8])*1000
        orders.append(dict(ticket=x[1],side=1 if x[3].startswith('buy') else -1,
                           level=float(x[5]),closed=closed,state=x[9],
                           first_touch_ms=None))
    grouped=defaultdict(list)
    for o in orders: grouped[o['closed']//86400000*86400].append(o)
    for day,items in grouped.items():
        path=DATA/f'ticks_{day}.csv'
        if not path.exists(): raise FileNotFoundError(path)
        with path.open() as stream:
            next(stream)
            for line in stream:
                time_s,bid_s,ask_s=line.rstrip().split(',')
                t=int(time_s);bid=float(bid_s);ask=float(ask_s)
                for order in items:
                    if order['first_touch_ms'] is not None or t<=order['closed']+250 or t>order['closed']+120*60000:
                        continue
                    touch=(ask<=order['level']-.01 if order['side']>0 else bid>=order['level']+.01)
                    if touch: order['first_touch_ms']=t-order['closed']
    first30=[x for x in orders if x['first_touch_ms'] is not None and x['first_touch_ms']<=30*60000]
    first120=[x for x in orders if x['first_touch_ms'] is not None]
    result={'unfilled_orders':len(orders),'quote_revisited_within_30_minutes':len(first30),
            'quote_revisited_within_120_minutes':len(first120),
            'by_state':{state:{'orders':sum(o['state']==state for o in orders),
                               'revisited_30m':sum(o['state']==state for o in first30),
                               'revisited_120m':sum(o['state']==state for o in first120)}
                        for state in sorted({x['state'] for x in orders})},
            'definition':'First later executable ask <= old BUY LIMIT minus one tick, or bid >= old SELL LIMIT plus one tick; observations start >250 ms after order removal.',
            'limitation':'A later quote touch is not an executable or profitable counterfactual. Original order expired/canceled; other signals, position limits, risk state, queue, adverse selection and costs would change.'}
    target=ROOT/'evidence/native/post_removal_quote_revisits.json'
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
