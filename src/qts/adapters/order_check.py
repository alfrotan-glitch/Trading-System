"""Phase 18: MT5 execution correctness — order_check pre-check."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class OrderCheckResult:
    def __init__(self, ok: bool, retcode: int, comment: str, requirements: dict):
        self.ok = ok
        self.retcode = retcode
        self.comment = comment
        self.requirements = requirements


def mt5_order_check(adapter, intent) -> OrderCheckResult:
    """Emulate MT5 order_check — pre-check without execution guarantee."""
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
    # Check margin requirements via account
    try:
        acct = adapter.account()
        # margin required = notional / leverage
        price = intent.limit_price or Decimal("2000")
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
        {"spec": spec, "margin_req": margin_req if "margin_req" in locals() else None},
    )


def submit_with_order_check(adapter, intent, risk_engine, ctx) -> Any:
    """Submit only after all local risk gates pass and order_check passes, then poll/reconcile."""
    # 1. Use broker-authoritative SymbolSpec (already)
    # 2. Call order_check and verify requirements
    check = mt5_order_check(adapter, intent)
    if not check.ok:
        raise ValueError(f"order_check failed retcode {check.retcode}: {check.comment}")
    # 3. Verify risk gates already passed (caller should have called risk.pre_trade)
    decision = risk_engine.pre_trade(intent, ctx)
    if not decision.allowed:
        raise ValueError(f"risk veto {decision.veto_reason}: {decision.reason_detail}")
    # 4. Distinguish request acceptance from actual execution — submit returns ACCEPTED, not FILLED
    order = adapter.submit(intent)
    # 5. Poll/reconcile and persist ticket IDs — caller must poll
    return order, check
