"""Canonical explanation for a refused DEMO order.

THE authority that turns a safety refusal into something a person can act on.
Every surface — the Trading UI, the API, the CLI — renders the object this
module builds, so the operator-facing sentence is defined once, next to the
gate that produces the verdict, and can never drift from it.

Why this exists
---------------
The pre-trade gate already produced a rich verdict: 28 named predicates, each
with a status and a detail string carrying the offending value. None of that
reached the user. ``SubmissionResult`` flattened the verdict into
``reasons: ["<id>: <detail>"]``, and the browser re-derived a sentence by
splitting the FIRST reason on ``":"`` and looking the id up in a hand-written
JavaScript dictionary of eleven entries — four of which
(``stop_loss_present``, ``reconciliation_suspension``, ``identity_mismatch``,
``order_size_within_hard_max``) matched no predicate the gate can emit.

Coverage was 7 of 28. Everything else — including ``policy_execution_assumptions``,
``kill_switch_functional``, ``max_daily_loss`` and ``no_unknown_checks`` — fell
through to:

    "A safety check refused the order. See the technical details for the exact reason."

The system knew the exact predicate and told the user nothing. Worse, five of
the six refusal paths in :meth:`~qts.execution.demo_session.DemoSession.submit`
never produced a predicate id at all (stage guard, slot claim, missing stop,
engine refusal, internal error), so they could only ever hit that fallback.

Contract
--------
* Every predicate the gate can emit has an entry here. :func:`missing_explanations`
  is asserted empty by the test suite, so a new predicate cannot ship without
  its explanation.
* ``retry_when`` states the condition that must become TRUE before retrying —
  never a duration, never a guess.
* An unidentifiable refusal is reported as unidentifiable
  (``explanation_available=False``) and says so in plain language. A reason is
  never invented, and the refusal is never softened: this module only explains,
  it never decides. HTTP 409 and every gate outcome are unchanged.
"""

from __future__ import annotations

from typing import Any

#: ``predicate id -> (plain language, condition that must become true)``.
#: Written for a person who does not know what a "gate" or a "stage" is.
REFUSAL_EXPLANATIONS: dict[str, tuple[str, str]] = {
    # --- permission and mode -------------------------------------------------
    "mode_is_demo_execution": (
        "QTS is not in demo trading mode, so it will not place any order.",
        "The application is started in demo execution mode.",
    ),
    "execution_permission": (
        "Demo trading has not been switched on for this account yet.",
        "Demo execution is authorised and switched on.",
    ),
    "authorization_valid": (
        "The signed demo trading authorisation is missing, expired or does not match this setup.",
        "A valid demo execution authorisation is in place.",
    ),
    "autonomous_allowed": (
        "This plan is not allowed to trade on its own.",
        "The plan is approved for autonomous trading, or the order is placed manually.",
    ),
    "stage_allows_order": (
        "The demo account has not been prepared for trading yet.",
        "You complete the preparation steps, which move trading out of the halted stage.",
    ),
    "account_is_demo": (
        "The connected account is not a practice account. QTS only trades demo accounts.",
        "MetaTrader 5 is signed in to the demo account.",
    ),
    "broker_identity_verified": (
        "The connected account does not match the account you confirmed earlier.",
        "You sign in to the confirmed demo account, or confirm the new account identity.",
    ),
    # --- the trading plan ----------------------------------------------------
    "strategy_registered_frozen": (
        "No approved, frozen trading plan is registered, so there is nothing authorised to trade.",
        "An approved trading plan is registered and frozen.",
    ),
    "policy_complete": (
        "The trading plan is incomplete, so QTS cannot tell what it is allowed to do.",
        "The registered plan contains every required setting.",
    ),
    "policy_execution_assumptions": (
        "Current market conditions are outside what this trading plan assumed, so the plan is not valid right now.",
        "Market conditions (spread, cost or slippage) return inside the plan's assumptions.",
    ),
    "symbol_allowed_by_policy": (
        "This trading plan is not allowed to trade this instrument.",
        "You trade the instrument the plan was approved for.",
    ),
    "symbol_provenance": (
        "QTS cannot confirm where this instrument's definition came from.",
        "The instrument is resolved from the confirmed broker setup.",
    ),
    "broker_symbol_matches_registry": (
        "The broker's symbol does not match the one in the approved plan.",
        "The broker symbol matches the registered experiment.",
    ),
    # --- market conditions ---------------------------------------------------
    "trading_hours_allowed": (
        "Trading session is outside the permitted trading hours.",
        "The market/trading window is open.",
    ),
    "market_data_fresh": (
        "There is no fresh price for this instrument right now.",
        "The broker sends a current price again (the market is open and the feed is live).",
    ),
    "spread_available": (
        "The current spread is wider than this demo plan allows.",
        "The spread narrows back inside the plan's limit.",
    ),
    # --- risk ----------------------------------------------------------------
    "risk_limits_resolved": (
        "QTS could not read the risk limits, so it will not risk anything.",
        "The risk limits load correctly.",
    ),
    "max_daily_loss": (
        "Today's loss has reached the limit set for this demo account.",
        "The next trading day starts, or the limit is reviewed by an operator.",
    ),
    "max_drawdown_within_policy": (
        "The account is further down from its peak than this plan allows.",
        "The account recovers above the drawdown limit.",
    ),
    "max_simultaneous_positions": (
        "There are already as many open positions as this plan allows.",
        "One of the open positions is closed.",
    ),
    "order_frequency_within_policy": (
        "Orders are being placed faster than this plan allows.",
        "Enough time passes since the last order.",
    ),
    "duplicate_order_protection": (
        "An order for this request is already on its way, so a second one was not sent.",
        "The order already in flight finishes and its outcome is recorded.",
    ),
    # --- safety state --------------------------------------------------------
    "kill_switch_functional": (
        "Trading is stopped by the safety stop.",
        "The stop is reviewed and cleared through Resume.",
    ),
    "reconciliation_ready": (
        "QTS and the broker disagree about open positions. Trading stays off until they agree.",
        "A fresh check finds QTS and the broker in agreement, and the stop is cleared.",
    ),
    "no_unknown_checks": (
        "At least one safety check could not reach a definite answer, so the order was refused.",
        "Every safety check returns a definite yes or no.",
    ),
    # --- the broker request --------------------------------------------------
    "broker_order_check": (
        "The broker refused the order request.",
        "The broker accepts the request (see the technical details for its reply).",
    ),
    "broker_reference_capture": (
        "QTS could not record the broker's reference for this order, so it did not send it.",
        "The broker's price reference can be captured again.",
    ),
    "execution_record_fields": (
        "QTS cannot record everything it must about this order, so it will not place it.",
        "The order journal can store the full execution record.",
    ),
    # --- predicates emitted through helper functions -------------------------
    # These reach `record()` as `record(*_helper(...))`, so no static scan of
    # this package can see them. They were invisible to the first completeness
    # test and uncovered until `record()` began enforcing the registry.
    "symbol_mapping_canonical": (
        "The instrument could not be matched to the broker's own symbol.",
        "The broker symbol for this instrument resolves from the confirmed setup.",
    ),
    "order_size_within_hard_max": (
        "The order size is above the hard limit for a single demo order.",
        "The size is reduced to the plan's maximum for one order.",
    ),
    "stop_loss_present": (
        "This demo plan requires a protective stop on every order. Enter a stop-loss price.",
        "A stop-loss price is set for the order.",
    ),
    "stop_within_policy_distance": (
        "The stop-loss is too close to or too far from the current price for this plan.",
        "The stop-loss is moved inside the distance the plan allows.",
    ),
    "max_total_exposure": (
        "This order would push total open exposure past the demo limit.",
        "Existing exposure is reduced, or a smaller size is used.",
    ),
    # --- position-close refusals ---------------------------------------------
    "broker_state_unavailable": (
        "The broker could not be asked which positions are open, so the close was not sent.",
        "The broker connection answers again and the position list can be read.",
    ),
    "ticket_not_owned": (
        "That position is not open on this demo account, so there is nothing to close.",
        "The ticket appears in the broker's open positions for this account.",
    ),
    "close_volume_invalid": (
        "The requested close size does not fit the open position or the broker's size rules.",
        "The close size is at most the open volume and matches the broker's minimum and step.",
    ),
    "close_not_authorized": (
        "This close was not authorized for the current account, broker or instrument.",
        "The account, broker identity and instrument checks pass for this session.",
    ),
    # --- refusals raised outside the gate ------------------------------------
    "stop_loss_required": (
        "This demo plan requires a protective stop on every order, and none could be worked out.",
        "A stop-loss price is provided or can be derived from the plan.",
    ),
    "execution_engine_refused": (
        "The execution engine refused the order (risk veto, safety stop or suspension).",
        "The blocking condition named in the technical details is cleared.",
    ),
    "submission_error": (
        "The order could not be completed because of an internal error, so nothing was sent.",
        "The internal error in the technical details is resolved.",
    ),
}

#: Shown only when no predicate can be identified. It must say so, plainly.
UNIDENTIFIED_PLAIN = (
    "The order was refused by a safety check, but QTS could not identify which one. "
    "It has NOT been sent."
)
UNIDENTIFIED_RETRY = "The exact reason is unavailable — see the technical details below."

HEADLINE = "Order blocked"
SUMMARY = "Trading is not ready yet."


def missing_explanations(predicate_ids: list[str] | tuple[str, ...]) -> list[str]:
    """Predicate ids with no plain-language entry. The test suite pins this empty."""
    return sorted(p for p in predicate_ids if p not in REFUSAL_EXPLANATIONS)


def _entry(check_id: str, technical: str, current: str | None = None) -> dict[str, Any]:
    known = REFUSAL_EXPLANATIONS.get(check_id)
    return {
        "id": check_id,
        "plain": known[0] if known else UNIDENTIFIED_PLAIN,
        "retry_when": known[1] if known else UNIDENTIFIED_RETRY,
        "technical": technical,
        "current": current if current is not None else technical,
        "explained": known is not None,
    }


def explain_refusal(
    *,
    verdict: dict[str, Any] | None = None,
    reasons: list[str] | None = None,
    blocked_by: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Build the structured, user-facing refusal.

    ``verdict`` is the pre-trade gate's own output and is preferred: it names
    every failed predicate and carries each one's current value. ``blocked_by``
    covers refusals raised outside the gate, which have no verdict. ``reasons``
    is the flat list and is used for the technical text.

    The primary blocker is the first failed predicate in gate evaluation order
    — deterministic, and the same one the flat ``reasons`` list has always led
    with.
    """
    reasons = list(reasons or [])
    blockers: list[dict[str, Any]] = []
    unknown_checks: list[str] = []

    checks = (verdict or {}).get("checks") or {}
    failed_ids = list((verdict or {}).get("failed") or [])
    unknown_checks = list((verdict or {}).get("unknown") or [])

    for check_id in failed_ids:
        check = checks.get(check_id) or {}
        detail = str(check.get("detail") or "")
        blockers.append(_entry(check_id, technical=f"{check_id}: {detail}" if detail else check_id, current=detail))

    if not blockers and blocked_by:
        detail = reasons[0] if reasons else ""
        blockers.append(_entry(blocked_by, technical=detail or blocked_by, current=detail or None))

    if not blockers and reasons:
        # No verdict and no id: keep the raw reason as the technical text and
        # say honestly that the predicate could not be identified.
        blockers.append(_entry("unidentified", technical="; ".join(reasons), current=None))

    if not blockers:
        blockers.append(_entry("unidentified", technical="no refusal detail was recorded", current=None))

    primary = blockers[0]
    return {
        "allowed": False,
        "headline": HEADLINE,
        "summary": SUMMARY,
        "state": state or "NO_TRADE",
        "explanation_available": bool(primary["explained"]),
        "primary": primary,
        "blockers": blockers,
        "blocker_ids": [b["id"] for b in blockers],
        "unknown_checks": unknown_checks,
        "reasons": reasons,
    }
