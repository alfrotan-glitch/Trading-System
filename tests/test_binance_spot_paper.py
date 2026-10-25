"""Offline deterministic security and arithmetic tests; never call an exchange."""
from decimal import Decimal as D

import pytest

from qts.research.binance_spot_paper import (
    BinancePublicSpot,
    Quote,
    Rules,
    SpotPaperAccount,
    SpotPaperError,
    floor_step,
)


def rules(min_notional="10", step="0.001"):
    return Rules.from_exchange_info({"symbols": [{
        "symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True,
        "baseAsset": "BTC", "quoteAsset": "USDT",
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": step},
            {"filterType": "NOTIONAL", "minNotional": min_notional},
        ],
    }]}, "BTCUSDT")


def test_buy_sell_spot_200_usdt_costs_and_no_short():
    p = SpotPaperAccount()
    r = rules()
    q = Quote(D("10000"), D("10001"))
    with pytest.raises(SpotPaperError):
        p.sell(r, q)
    buy = p.buy(r, q, D("9900"))
    assert buy.qty == D("0.003")
    assert buy.qty * buy.price + buy.fee_usdt <= D("40")
    assert p.cash > D("160")
    assert p.equity(q) < D("200")
    with pytest.raises(SpotPaperError):
        p.buy(r, q, D("9900"))
    sale = p.sell(r, q)
    assert sale.qty == buy.qty and p.units == 0
    assert p.cash < D("200")
    with pytest.raises(SpotPaperError):
        p.sell(r, q)


def test_risk_cap_refuses_size_too_small_for_filters():
    p = SpotPaperAccount(max_risk_usdt=D("0.05"))
    with pytest.raises(SpotPaperError):
        p.buy(rules(), Quote(D("10000"), D("10001")), D("9900"))
    assert p.cash == D(200) and not p.journal


def test_zero_fees_and_step_round_down():
    assert floor_step(D("5.79"), D("0.2")) == D("5.6")
    assert floor_step(D("0.00097"), D("0.001")) == D("0.000")
    p = SpotPaperAccount(fee_rate=D("0"))
    p.buy(rules(), Quote(D("10000"), D("10001")), D("9990"))
    assert p.equity(Quote(D("10000"), D("10001"))) <= D("200")


def test_symbol_metadata_and_quote_validate_fail_closed():
    with pytest.raises(SpotPaperError):
        Quote.from_book_ticker({"symbol": "BTCUSDT", "bidPrice": "101", "askPrice": "100"}, "BTCUSDT")
    with pytest.raises(SpotPaperError):
        Rules.from_exchange_info({"symbols": []}, "BTCUSDT")
    with pytest.raises(SpotPaperError):
        BinancePublicSpot("https://api.binance.com")
    with pytest.raises(SpotPaperError):
        BinancePublicSpot._validate_symbol("BTCUSDT&another=1")


def test_notional_fails_without_exposure():
    p = SpotPaperAccount(max_buy_usdt=D(10))
    with pytest.raises(SpotPaperError):
        p.buy(rules(min_notional="25"), Quote(D("10000"), D("10001")), D("9900"))
    assert p.cash == D(200) and p.units == 0
