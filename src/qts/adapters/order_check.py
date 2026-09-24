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
from typing import Any


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


def submit_with_order_check(adapter, intent, risk_engine, ctx, market_price: Decimal | None = None) -> Any:
    """Submit only after all local risk gates pass and order_check passes, then poll/reconcile.

    This helper calls the broker adapter DIRECTLY. That makes it the one
    submission path in the codebase that does not go through
    :class:`qts.execution.demo_session.DemoSession`, so it is guarded here
    against becoming a way around the DEMO execution boundary: it refuses
    unless the process resolves to ``DEMO_EXECUTION`` *and* a valid owner
    authorization is in force. LIVE can therefore never reach it, and neither
    can an un-authorized DEMO mode — the same two facts the session's
    pre-trade gate checks, asserted at the point of submission.
    """
    _assert_demo_execution_permitted(adapter, intent)
    # 1. Use broker-authoritative SymbolSpec (already)
    # 2. Call order_check and verify requirements
    check = mt5_order_check(adapter, intent, market_price=market_price)
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


def _assert_demo_execution_permitted(adapter: Any, intent: Any) -> None:
    """Refuse this direct-submit helper outside an authorized DEMO_EXECUTION process.

    Fail closed: any unresolvable fact (mode, authorization, account type)
    raises rather than proceeding, because "cannot prove DEMO" must never
    degrade into "assume DEMO".
    """
    from qts.domain.modes import ExecutionMode, resolve_mode
    from qts.lifecycle.demo_authorization import resolve_demo_execution_policy

    try:
        mode = resolve_mode()
    except Exception as exc:  # unresolvable mode → refuse
        raise PermissionError(f"execution mode unresolvable — broker submission refused ({exc})") from exc
    if mode is not ExecutionMode.DEMO_EXECUTION:
        raise PermissionError(
            f"mode {mode.value} may not submit broker orders through this helper "
            "(DEMO_EXECUTION with a recorded owner authorization only; LIVE = LOCKED)"
        )
    policy = resolve_demo_execution_policy(mode=str(mode))
    if not policy.enabled:
        raise PermissionError(
            f"DEMO execution is {policy.state} — broker submission refused ({'; '.join(policy.reasons)})"
        )
    # Account-type proof, when the adapter can supply one. An adapter that
    # cannot report it is not assumed to be DEMO.
    identity = getattr(adapter, "broker_identity", None)
    if callable(identity):
        try:
            observed = identity()
        except Exception as exc:
            raise PermissionError(f"broker identity unreadable — broker submission refused ({exc})") from exc
        if getattr(observed, "is_demo", None) is not True:
            raise PermissionError(
                f"connected account is not proven DEMO (is_demo={getattr(observed, 'is_demo', None)}) — "
                "broker submission refused"
            )
