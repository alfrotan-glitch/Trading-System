"""Canonical broker result/error normalization — was the request TRANSMITTED?

Every execution-safety decision after a failed submission reduces to one
question: *could the broker have acted on this request?* If it provably could
not, the outcome is a deterministic rejection and the system may carry on. If
it might have, the outcome is UNKNOWN and the system must fail closed, suspend,
and reconcile against broker evidence before trading again.

Before this module the distinction did not exist. ``MetaTrader5.order_send``
returns ``None`` both when the client library refuses to marshal the request
(nothing leaves the process) and when the terminal/server link dies mid-send
(the broker may hold an order). Both produced ``TimeoutError``, and
:class:`~qts.execution.engine.ExecutionEngine` treated every ``TimeoutError`` as
AMBIGUOUS, which durably suspends trading.

Real incident (``demo-20260928T140630-884971d1e6``, 2026-09-28): the comment
field was rejected by the client library — ``order_send`` returned ``None`` with
``last_error() == (-2, 'Invalid "comment" argument')``. Nothing was ever
transmitted, the broker had no record, and the account was untouched. QTS
recorded AMBIGUOUS, wrote a durable reconciliation suspension, and blocked every
subsequent order. A local marshalling error took the trading system down and
left it with no evidence-based way back out.

Classification rule (conservative by construction):

* a failure code is treated as NOT transmitted only if it appears in
  :data:`CLIENT_SIDE_NOT_TRANSMITTED`, i.e. the terminal refused or could not
  begin the operation;
* **everything else is UNKNOWN**, including generic failures, IPC send/receive
  faults and timeouts. Unrecognised codes are UNKNOWN too.

The asymmetry is deliberate. Misclassifying UNKNOWN as rejected risks a
duplicate order against a live broker position; misclassifying rejected as
UNKNOWN only costs an operator-visible reconciliation. We accept the cheap
error, never the expensive one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------- error codes
# MetaTrader5 client return codes (mt5.last_error()[0]). These are library-level
# codes, distinct from server trade retcodes (10004..10019) which only exist
# once the server has answered — and therefore always imply transmission.
RES_S_OK = 1
RES_E_FAIL = -1
RES_E_INVALID_PARAMS = -2
RES_E_NO_MEMORY = -3
RES_E_NOT_FOUND = -4
RES_E_INVALID_VERSION = -5
RES_E_AUTH_FAILED = -6
RES_E_UNSUPPORTED = -7
RES_E_AUTO_TRADING_DISABLED = -8
RES_E_INTERNAL_FAIL = -10000
RES_E_INTERNAL_FAIL_SEND = -10001
RES_E_INTERNAL_FAIL_RECEIVE = -10002
RES_E_INTERNAL_FAIL_INIT = -10003
RES_E_INTERNAL_FAIL_CONNECT = -10004
RES_E_INTERNAL_FAIL_TIMEOUT = -10005

#: Codes that PROVE the request never reached the trade server. Each one is
#: raised by the client library or the terminal *before* an order can be
#: marshalled onto the wire, so no broker-side effect is possible.
CLIENT_SIDE_NOT_TRANSMITTED: dict[int, str] = {
    RES_E_INVALID_PARAMS: "the client library refused the request structure — nothing was marshalled or sent",
    RES_E_INVALID_VERSION: "incompatible terminal/library version — the call was refused before sending",
    RES_E_AUTH_FAILED: "terminal authorisation failed — no session existed to send the order on",
    RES_E_UNSUPPORTED: "the terminal does not support this call — it was refused before sending",
    RES_E_AUTO_TRADING_DISABLED: "algorithmic trading is disabled in the terminal — the order was never sent",
    RES_E_INTERNAL_FAIL_INIT: "the terminal connection was never initialised — no order could be sent",
    RES_E_INTERNAL_FAIL_CONNECT: "no IPC connection to the terminal — the order never left this process",
}

#: Codes that are explicitly UNKNOWN. Listed for documentation and testing; the
#: classifier defaults to UNKNOWN for anything not in the allowlist above, so
#: this set never needs to be exhaustive to stay safe.
KNOWN_UNKNOWN_OUTCOME: dict[int, str] = {
    RES_E_FAIL: "generic client failure — the request may or may not have been transmitted",
    RES_E_NO_MEMORY: "client out of memory — the point of failure is unknown",
    RES_E_NOT_FOUND: "client reported not-found — the point of failure is unknown",
    RES_E_INTERNAL_FAIL: "internal terminal failure — the point of failure is unknown",
    RES_E_INTERNAL_FAIL_SEND: "IPC send failed — a partially written request may still have been processed",
    RES_E_INTERNAL_FAIL_RECEIVE: "the reply was lost — the broker may have accepted the order",
    RES_E_INTERNAL_FAIL_TIMEOUT: "the call timed out — the broker may have accepted the order",
}


class BrokerRequestRejected(ValueError):
    """The broker/terminal refused the request and it was NEVER transmitted.

    Deterministic and safe: there is provably no broker-side order, deal or
    position, so the operation may be recorded REJECTED without suspending
    trading. Subclasses ``ValueError`` so existing definitive-rejection handling
    keeps working unchanged.
    """

    transmitted = False


class BrokerOutcomeUnknown(TimeoutError):
    """The request may have reached the broker; the outcome is UNKNOWN.

    Fail closed: record AMBIGUOUS, suspend trading, and resolve against broker
    evidence before any further order. Subclasses ``TimeoutError`` so existing
    ambiguity handling keeps working unchanged.
    """

    transmitted = None  # unknown — never False


@dataclass(frozen=True)
class OutcomeClassification:
    """Normalized verdict for a failed broker call."""

    transmitted: bool | None  # False = provably not sent; None = unknown
    code: int | None
    text: str
    rationale: str

    @property
    def is_unknown(self) -> bool:
        return self.transmitted is not False

    def describe(self, client_order_id: str, operation: str = "order_send") -> str:
        code = "no code" if self.code is None else f"code {self.code}"
        verdict = "OUTCOME UNKNOWN" if self.is_unknown else "NOT TRANSMITTED"
        return (
            f"MT5 {operation} failed for {client_order_id}: {verdict} — {code} "
            f"({self.text}); {self.rationale}"
        )


def normalize_last_error(last_error: Any) -> tuple[int | None, str]:
    """Best-effort ``(code, text)`` from an MT5 ``last_error()`` value."""
    code: int | None = None
    text = ""
    if isinstance(last_error, (tuple, list)) and last_error:
        raw_code = last_error[0]
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            code = None
        if len(last_error) > 1:
            text = str(last_error[1])
    elif last_error is not None:
        text = str(last_error)
    return code, (text or "no error text reported")


def classify_send_failure(last_error: Any) -> OutcomeClassification:
    """Classify a failed send. UNKNOWN unless the code proves non-transmission."""
    code, text = normalize_last_error(last_error)
    if code is not None and code in CLIENT_SIDE_NOT_TRANSMITTED:
        return OutcomeClassification(
            transmitted=False,
            code=code,
            text=text,
            rationale=CLIENT_SIDE_NOT_TRANSMITTED[code],
        )
    if code is not None and code in KNOWN_UNKNOWN_OUTCOME:
        return OutcomeClassification(
            transmitted=None, code=code, text=text, rationale=KNOWN_UNKNOWN_OUTCOME[code]
        )
    return OutcomeClassification(
        transmitted=None,
        code=code,
        text=text,
        rationale=(
            "unrecognised client error code — treated as UNKNOWN because non-transmission was not proven"
        ),
    )


def raise_for_send_failure(last_error: Any, client_order_id: str, *, operation: str = "order_send") -> None:
    """Raise the canonical exception for a failed broker call. Always raises."""
    verdict = classify_send_failure(last_error)
    message = verdict.describe(client_order_id, operation)
    if verdict.is_unknown:
        raise BrokerOutcomeUnknown(message)
    raise BrokerRequestRejected(message)
