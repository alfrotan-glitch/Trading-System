import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
import pytest
from edge_gate import evaluate_trades


def row(d, gross, fee=0.10, slip=0.05):
    return {'date': d, 'gross_usd': gross, 'commission_usd': fee, 'slippage_usd': slip}


def test_no_trades_do_not_validate():
    r = evaluate_trades([], 20)
    assert r['status'] == 'REJECTED_OR_INSUFFICIENT_EVIDENCE'
    assert r['trades_per_active_day'] == 0


def test_many_trades_but_negative_net_cannot_validate():
    x = [row(f'2026-08-{1+i//5:02d}', 0.1) for i in range(100)]
    r = evaluate_trades(x, 20)
    assert r['trades'] == 100
    assert r['net_usd'] < 0
    assert r['status'] == 'REJECTED_OR_INSUFFICIENT_EVIDENCE'


def test_fees_count_once_from_gross():
    r = evaluate_trades([row('2026-08-01', 2, 0.2, 0.1)], 1)
    assert r['net_usd'] == 1.7


def test_reject_negative_commission():
    with pytest.raises(ValueError):
        evaluate_trades([row('2026-08-01', 2, -1)], 1)


def test_reproducible_block_bootstrap():
    rows = [row(f'2026-08-{i+1:02d}', 1 if i % 2 else -1) for i in range(20)]
    assert evaluate_trades(rows, 20) == evaluate_trades(rows, 20)
