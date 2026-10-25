from gold_robot.research.small_account_risk import Contract, QuoteRisk, size_trade


def sample(equity, stop_distance, pct, margin_per_lot=100):
    contract = Contract(margin_per_lot_usd=margin_per_lot)
    risk = QuoteRisk(equity, equity, 1, 3000, 3000-stop_distance,
                     requested_risk_pct=pct)
    return size_trade(contract, risk)


def test_reject_unaffordable_min_lot():
    x = sample(100, 3, 2)
    assert x.lots == 0 and x.reason == "min_lot_exceeds_risk"


def test_include_costs_and_slippage():
    x = sample(200, 3, 2)
    assert x.lots == 0.01 and 3 < x.estimated_loss_usd <= 4


def test_risk_not_forced_to_maximum():
    x = sample(200, 3, 1)
    assert x.lots == 0


def test_reject_unknown_margin():
    x = size_trade(Contract(), QuoteRisk(200, 200, 1, 3000, 2998))
    assert x.reason == "invalid_or_unverified_input"


def test_reject_more_than_two_percent():
    x = size_trade(Contract(margin_per_lot_usd=100),
                   QuoteRisk(200, 200, 1, 3000, 2998, requested_risk_pct=3))
    assert x.reason == "risk_cap_exceeded"


def test_margin_requirement_blocks_trade():
    x = sample(200, 1, 2, margin_per_lot=2000)
    assert x.reason == "insufficient_margin"
