"""Frozen Prior-Day Sweep follow-up on 2025 H2, leaving 2026 untouched."""
import csv
import json
from pathlib import Path
import prior_day as p
import research as r
from alternatives import Market


def sweep_only(bars):
    signals = p.signals(bars)
    return {time: [s for s in rows if s['family'] == 'previous_day_sweep']
            for time, rows in signals.items()
            if any(s['family'] == 'previous_day_sweep' for s in rows)}


def main():
    data = r.ROOT/'runtime/terminal/MQL5/Files/QTS_research'
    output = r.ROOT/'evidence/sweep_followup'
    output.mkdir(parents=True, exist_ok=True)
    protocol = Path(__file__).with_name('sweep_followup_protocol.json')
    frozen = json.loads(protocol.read_text(encoding='utf-8-sig'))
    bars = r.load_bars(data/'bars.csv')
    spec = next(csv.DictReader((data/'spec.csv').open(encoding='utf-8-sig')))
    if spec['server'] != 'WMMarkets-Demo' or spec['symbol'] != 'XAUUSD@' or float(spec['contract_size']) != 100:
        raise ValueError('Unsupported broker specification')
    (output/'run_manifest.json').write_text(json.dumps({
        'protocol_sha256': r.digest(protocol),
        'prior_day_signals_sha256': r.digest(Path(p.__file__)),
        'research_engine_sha256': r.digest(Path(r.__file__)),
        'market_execution_sha256': r.digest(Path(__file__).with_name('alternatives.py')),
        'runner_sha256': r.digest(Path(__file__)),
        'bars_sha256': r.digest(data/'bars.csv'),
        'spec_sha256': r.digest(data/'spec.csv'),
        'reserved_forward_validation_evaluated': False,
        'final_holdout_evaluated': False}, indent=2), encoding='utf-8')
    result = r.evaluate(data, bars, spec, *map(r.epoch, frozen['exploratory_independent_block']),
                        output, 'independent_2025_h2', sweep_only, Market,
                        ('previous_day_sweep',))
    print(json.dumps(result['metrics'], indent=2))


if __name__ == '__main__':
    main()
