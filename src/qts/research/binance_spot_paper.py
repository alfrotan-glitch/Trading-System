"""Read-only Binance Spot market data and local $200 paper-ledger reference.

There is deliberately NO authenticated Binance endpoint, API key, signing,
POST/DELETE, live order, or strategy activation in this module. A paper fill is
only a simplified hypothetical fill at the observed bid/ask, NOT a venue fill.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode
from urllib.request import Request, urlopen


D = Decimal
MARKET_DATA_HOST = "https://data-api.binance.vision"


class SpotPaperError(ValueError):
    """Fail-closed paper simulation or exchange-data validation error."""


def dec(value: object) -> Decimal:
    try:
        number = D(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise SpotPaperError("invalid numeric exchange field") from exc
    if not number.is_finite():
        raise SpotPaperError("non-finite numeric exchange field")
    return number


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise SpotPaperError("invalid exchange step size")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


@dataclass(frozen=True)
class Rules:
    symbol: str
    base: str
    quote: str
    min_qty: Decimal
    max_qty: Decimal
    step: Decimal
    min_notional: Decimal

    @classmethod
    def from_exchange_info(cls, payload: dict, symbol: str) -> "Rules":
        items = payload.get("symbols", [])
        if len(items) != 1 or items[0].get("symbol") != symbol:
            raise SpotPaperError("symbol metadata missing or inconsistent")
        item = items[0]
        if item.get("status") != "TRADING" or item.get("isSpotTradingAllowed") is not True:
            raise SpotPaperError("spot symbol is not explicitly tradeable")
        if item.get("quoteAsset") != "USDT":
            raise SpotPaperError("this paper account supports USDT quote pairs only")
        filters = {f["filterType"]: f for f in item.get("filters", [])}
        lot = filters.get("LOT_SIZE")
        if not lot:
            raise SpotPaperError("missing mandatory LOT_SIZE filter")
        min_notional = D(0)
        for name in ("MIN_NOTIONAL", "NOTIONAL"):
            if name in filters:
                min_notional = max(min_notional, dec(filters[name]["minNotional"]))
        if not any(k in filters for k in ("MIN_NOTIONAL", "NOTIONAL")):
            raise SpotPaperError("notional filter missing")
        min_qty, max_qty, step = (dec(lot[k]) for k in ("minQty", "maxQty", "stepSize"))
        if min_qty <= 0 or max_qty < min_qty or step <= 0 or min_notional <= 0:
            raise SpotPaperError("invalid lot or notional bounds")
        return cls(symbol, item["baseAsset"], item["quoteAsset"], min_qty, max_qty, step, min_notional)


@dataclass(frozen=True)
class Quote:
    bid: Decimal
    ask: Decimal

    @classmethod
    def from_book_ticker(cls, payload: dict, symbol: str) -> "Quote":
        if payload.get("symbol") != symbol:
            raise SpotPaperError("quote symbol mismatch")
        bid, ask = dec(payload["bidPrice"]), dec(payload["askPrice"])
        if bid <= 0 or ask <= bid:
            raise SpotPaperError("invalid/stale-market bid or ask; trading disabled")
        return cls(bid, ask)


class BinancePublicSpot:
    """No private account access. API key is neither accepted nor required."""

    def __init__(self, host: str = MARKET_DATA_HOST):
        if host != MARKET_DATA_HOST:
            raise SpotPaperError("only the Binance read-only market-data host is permitted")
        self.host = host

    @staticmethod
    def _validate_symbol(symbol: str) -> str:
        if not (3 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum() and symbol.isupper()):
            raise SpotPaperError("invalid spot symbol")
        return symbol

    def _get(self, endpoint: str, symbol: str) -> dict:
        # Hardcoded read-only allowlist; no arbitrary URLs or account endpoints.
        if endpoint not in ("exchangeInfo", "ticker/bookTicker"):
            raise SpotPaperError("endpoint is not a public allowlisted market-data route")
        symbol = self._validate_symbol(symbol)
        url = f"{self.host}/api/v3/{endpoint}?{urlencode({'symbol': symbol})}"
        request = Request(url, headers={"User-Agent": "QTS-Research-Spot-Paper/0.1"}, method="GET")
        with urlopen(request, timeout=6) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise SpotPaperError("unexpected exchange response")
        return result

    def rules(self, symbol: str) -> Rules:
        return Rules.from_exchange_info(self._get("exchangeInfo", symbol), symbol)

    def quote(self, symbol: str) -> Quote:
        return Quote.from_book_ticker(self._get("ticker/bookTicker", symbol), symbol)


@dataclass(frozen=True)
class PaperFill:
    side: str
    symbol: str
    qty: Decimal
    price: Decimal
    fee_usdt: Decimal
    cash_after: Decimal
    units_after: Decimal


class SpotPaperAccount:
    """In-memory spot-only reference, no leverage, market orders, or external effects.

    Fees are simplified as quote-asset charges on both sides. Actual venue
    commissions may settle in base/BNB and live fill/slippage can differ.
    """

    def __init__(self, starting_usdt: Decimal = D("200"), *,
                 max_buy_usdt: Decimal = D("40"),
                 max_risk_usdt: Decimal = D("0.50"), fee_rate: Decimal = D("0.001")):
        self.cash = dec(starting_usdt)
        self.units = D(0)
        self.max_buy_usdt = dec(max_buy_usdt)
        self.max_risk_usdt = dec(max_risk_usdt)
        self.fee_rate = dec(fee_rate)
        if (self.cash <= 0 or self.max_buy_usdt <= 0 or self.max_risk_usdt <= 0
                or not D(0) <= self.fee_rate < D("0.1")):
            raise SpotPaperError("invalid paper-account risk settings")
        self.symbol: str | None = None
        self.journal: list[PaperFill] = []

    @staticmethod
    def _check_order(qty: Decimal, price: Decimal, rules: Rules) -> None:
        if (qty < rules.min_qty or qty > rules.max_qty or
                qty != floor_step(qty, rules.step) or qty * price < rules.min_notional):
            raise SpotPaperError("order fails exchange lot/step/min-notional reference checks")

    def buy(self, rules: Rules, market: Quote, stop_price: Decimal) -> PaperFill:
        if self.units != 0 or self.symbol is not None:
            raise SpotPaperError("one paper position at a time; no doubling down")
        stop = dec(stop_price)
        if not D(0) < stop < market.bid:
            raise SpotPaperError("buy requires a protective stop below current bid")
        # Stop-risk budget includes estimated buy/sell fees at the stop. Actual
        # exchange gap or market slippage can exceed this hypothetical budget.
        risk_per_unit = market.ask - stop + self.fee_rate * (market.ask + stop)
        if risk_per_unit <= 0:
            raise SpotPaperError("invalid per-unit loss model")
        buying_power = min(self.cash, self.max_buy_usdt)
        qty = floor_step(min(buying_power / (market.ask * (D(1) + self.fee_rate)),
                             self.max_risk_usdt / risk_per_unit,
                             rules.max_qty), rules.step)
        self._check_order(qty, market.ask, rules)
        gross = qty * market.ask
        fee = gross * self.fee_rate
        if gross + fee > self.cash or gross + fee > self.max_buy_usdt:
            raise SpotPaperError("paper buy exceeds available cash/allocation")
        self.cash -= gross + fee
        self.units = qty
        self.symbol = rules.symbol
        fill = PaperFill("BUY", rules.symbol, qty, market.ask, fee, self.cash, self.units)
        self.journal.append(fill)
        return fill

    def sell(self, rules: Rules, market: Quote) -> PaperFill:
        if self.symbol != rules.symbol or self.units <= 0:
            raise SpotPaperError("spot SELL requires existing owned base asset")
        qty = self.units
        self._check_order(qty, market.bid, rules)
        gross = qty * market.bid
        fee = gross * self.fee_rate
        self.cash += gross - fee
        self.units = D(0)
        self.symbol = None
        fill = PaperFill("SELL", rules.symbol, qty, market.bid, fee, self.cash, self.units)
        self.journal.append(fill)
        return fill

    def equity(self, market: Quote | None = None) -> Decimal:
        if self.units == 0:
            return self.cash
        if market is None:
            raise SpotPaperError("bid quote required to value an owned paper position")
        return self.cash + self.units * market.bid * (D(1) - self.fee_rate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Binance SPOT public data only; no account access or orders")
    parser.add_argument("--symbol", default="BTCUSDT", help="USDT spot symbol e.g. BTCUSDT")
    args = parser.parse_args()
    client = BinancePublicSpot()
    try:
        rules = client.rules(args.symbol)
        quote = client.quote(args.symbol)
        print(json.dumps({
            "mode": "PUBLIC_DATA_ONLY", "orders_submitted": 0, "live_access": False,
            "symbol": rules.symbol, "bid": str(quote.bid), "ask": str(quote.ask),
            "min_qty": str(rules.min_qty), "step": str(rules.step),
            "min_notional_usdt": str(rules.min_notional),
            "hypothetical_paper_start_usdt": "200",
            "warning": "Data is not a real fill; strategy profitability unvalidated",
        }, indent=2))
    except (SpotPaperError, OSError, TimeoutError, ValueError) as exc:
        parser.exit(2, f"Binance public data unavailable or invalid: {exc}\n")


if __name__ == "__main__":
    main()
