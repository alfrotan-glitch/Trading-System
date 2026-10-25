import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
from small_account_risk import Contract, QuoteRisk, size_trade


def _sample(equity, stop_distance, pct, margin_per_lot=100):
    c = Contract(margin_per_lot_usd=margin_per_lot)
    r = QuoteRisk(
        equity_usd=equity, free_margin_usd=equity, side=1,
        entry=3000, stop=3000-stop_distance, requested_risk_pct=pct
    )
    return size_trade(c, r)


def test_cannot_round_up_unaffordable_min_lot():
    d = _sample(100, 3, 2)
    assert d.lots == 0 and d.reason == 'min_lot_exceeds_risk'


def test_cost_and_slippage_count_toward_cap():
    d = _sample(200, 3, 2)
    assert d.lots == 0.01 and 3 < d.estimated_loss_usd <= 4


def test_not_forced_to_risk_two_percent():
    d = _sample(200, 3, 1)
    assert d.lots == 0 and d.reason == 'min_lot_exceeds_risk'


def test_reject_unknown_margin():
    c = Contract()
    r = QuoteRisk(200, 200, 1, 3000, 2998)
    assert size_trade(c,r).reason == 'invalid_or_unverified_input'


def test_reject_over_two_percent():
    c = Contract(margin_per_lot_usd=100)
    r = QuoteRisk(200, 200, 1, 3000, 2998, requested_risk_pct=3)
    assert size_trade(c,r).reason == 'risk_cap_exceeded'


def test_margin_cannot_be_assumed():
    d = _sample(200, 1, 2, margin_per_lot=2000)
    assert d.reason == 'insufficient_margin'
