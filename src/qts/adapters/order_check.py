"""Phase 18: MT5 execution correctness — order_check pre-check.

Fail-closed rules (regression-pinned):
* Margin math NEVER guesses a price. Without an authoritative price
  (intent limit/stop or an explicit ``market_price``) the check fails with
  ``MISSING_MARKET_PRICE`` — the previous ``Decimal("2000")`` fallback
  fabricated margin requirements.
* Unknown account leverage/currency is ``UNAVAILABLE`` — the check fails
  closed rather than dividing by a guessed leverage.
"""

from __future__ import annotations

from decimal import Decimal


class OrderCheckResult:
    def __init__(self, ok: bool, retcode: int, comment: str, requirements: dict):
        self.ok = ok
        self.retcode = retcode
        self.comment = comment
        self.requirements = requirements


def mt5_order_check(adapter, intent, market_price: Decimal | None = None) -> OrderCheckResult:
    """Emulate MT5 order_check — pre-check without execution guarantee.

    ``market_price``: authoritative executable price from MarketDataProvider
    (BUY→ask, SELL→bid). Required for market orders; limit/stop orders use
    their own price.
    """
    # Use adapter.get_symbol_spec and validation
    spec = adapter.get_symbol_spec(intent.instrument.symbol)
    # Validate quantity, price
    try:
        adapter.validate_and_normalize_quantity(intent.quantity, spec)
    except Exception as e:
        return OrderCheckResult(False, 10014, f"invalid volume: {e}", {"spec": spec})
    if intent.limit_price:
        try:
            adapter.validate_price_precision(intent.limit_price, spec)
        except Exception as e:
            return OrderCheckResult(False, 10015, f"invalid price: {e}", {"spec": spec})
    # Authoritative price only — never a fabricated default
    price = intent.limit_price or intent.stop_price or market_price
    if price is None:
        return OrderCheckResult(
            False,
            10018,  # TRADE_RETCODE_INVALID_PRICE family: no price to validate against
            "MISSING_MARKET_PRICE: no limit/stop price on intent and no authoritative market price supplied",
            {},
        )
    # Check margin requirements via account
    margin_req: Decimal | None = None
    try:
        acct = adapter.account()
        if acct.leverage is None or acct.leverage <= 0:
            return OrderCheckResult(
                False,
                10006,
                f"UNAVAILABLE: broker leverage unknown ({acct.leverage}) — margin requirement not computable, fail closed",
                {"leverage": acct.leverage},
            )
        # margin required = notional / leverage
        notional = intent.quantity * spec.contract_size * price
        margin_req = notional / acct.leverage
        if margin_req > acct.free_margin:
            return OrderCheckResult(
                False, 10019, "no money", {"margin_req": margin_req, "free_margin": acct.free_margin}
            )
    except Exception as e:
        return OrderCheckResult(False, 10006, f"account check failed: {e}", {})
    # All local gates passed — but MT5 docs: order_check is pre-check, not execution guarantee
    return OrderCheckResult(
        True,
        0,
        "order_check passed (not execution guarantee)",
        {"spec": spec, "margin_req": margin_req, "price": price},
    )
