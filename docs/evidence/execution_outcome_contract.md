# Execution Outcome Contract — what happened, what is UNKNOWN, how UNKNOWN ends

*Added 2026-09-30 after the forensic audit of incident
`demo-20260928T140630-884971d1e6` (WMMarkets-Demo, login 20282400).*

This document is the authority for the section of the lifecycle that runs from
**broker request construction** to **durable resolution of the outcome**. It
complements `canonical_authorities.md` §9 (durable suspension & recovery),
which owns everything from suspension to resume.

---

## 1. The incident this contract exists to prevent

```
MT5 order_send returned None: (-2, 'Invalid "comment" argument')
```

The MetaTrader5 client library refused to marshal the request because the
`comment` field carried the full 31-character `client_order_id`. **Nothing was
transmitted.** The trade server never saw an order; no deal, no position, no
account effect.

QTS recorded the outcome as `AMBIGUOUS`, wrote a durable reconciliation
suspension, and refused every subsequent order. There was then no way out:

* `reconcile()` compares the **in-memory** order map with the venue. After a
  restart that map is empty, so the unresolved order was invisible to the only
  check that could have resolved it.
* The suspension therefore described a condition that no longer existed —
  and outlived it indefinitely.

A local string-length bug took a trading system down permanently. Three
independent contract failures had to line up, and all three are now closed.

---

## 2. Authority map for this segment

| Question | Authority | Readers |
|---|---|---|
| What exactly do we send to MT5? | `MT5Adapter.build_broker_request` (the ONLY constructor) | `submit`, the pre-trade dry run |
| Is a request well-formed? | `validate_broker_request` | called inside the constructor, so preview and send are validated identically |
| Did the broker receive it? | `qts.adapters.broker_outcome.classify_send_failure` | `MT5Adapter.submit`, `close_position` |
| What is this order's outcome? | `demo_order_journal` (§11.4) | startup health, readiness, recovery |
| Has this id been used? | `idempotency` table | duplicate guard |
| Is execution suspended? | `reconcile_state` (`load_reconcile_suspension`) | engine, LIVE gate, API, startup health |

`demo_order_journal` and `idempotency` hold overlapping outcome vocabulary for
different questions. Any resolution writes **both**
(`DemoSession._record_idempotency_status`), so they cannot disagree about
whether an order is still unresolved.

---

## 3. Broker request contract

Enforced by `validate_broker_request` **before any send**; a violation raises
`BrokerRequestRejected`, which is by construction a *not transmitted* outcome.

| Field | Contract |
|---|---|
| `action`, `type`, `type_filling`, `type_time` | integer-like (`__index__`); never `None`/str/float |
| `symbol` | non-empty printable ASCII |
| `volume` | finite, `> 0` |
| `comment` | printable ASCII, no quote characters, `1..MT5_COMMENT_MAX` (16) chars |
| `magic` | integer `>= 0` |
| `price`, `sl`, `tp`, `deviation`, `position` | finite numerics; prices non-negative |

The comment is **not** the correlation key. `mt5_comment_for(client_order_id)`
derives a short deterministic ASCII digest and the full
`client_order_id ↔ comment` mapping is persisted, so attribution survives
restarts without pushing an arbitrary-length id into a 16-char field.

---

## 4. Transmission classification (`broker_outcome.py`)

`order_send` returning `None` is **not** evidence of anything on its own. The
discriminator is `last_error()`:

* **NOT TRANSMITTED** — only for codes in `CLIENT_SIDE_NOT_TRANSMITTED`
  (`-2` invalid params, `-5` invalid version, `-6` auth failed, `-7`
  unsupported, `-8` auto-trading disabled, `-10003` init failed, `-10004` no
  IPC). The terminal refused or could not begin the operation ⇒ deterministic
  `BrokerRequestRejected`, no suspension.
* **UNKNOWN** — everything else, including generic failures, IPC send/receive
  faults, timeouts and any unrecognised code ⇒ `BrokerOutcomeUnknown`, record
  AMBIGUOUS, suspend, reconcile.

The asymmetry is deliberate: misreading UNKNOWN as rejected risks a duplicate
order against real exposure; misreading rejected as UNKNOWN costs only an
operator-visible reconciliation. **Unrecognised codes are UNKNOWN.**

A *server* retcode (10004–10019) always implies transmission — the server
answered — so those are definitive rejections regardless of the wording in the
broker's `comment` field.

### What this replaced

`ExecutionEngine` classified ambiguity by substring-matching the exception
message for `timeout`/`connection`/`network`/`unknown`/`disconnected`. That was
wrong in both directions: a locally refused request became a durable
suspension, and a definitive rejection whose broker comment merely contained
the word "connection" was treated as ambiguous. Classification is now by
exception **type**, derived from broker evidence; the text heuristic survives
only as a fallback for third-party adapters that raise bare exceptions.

---

## 5. Resolution contract — how UNKNOWN ends

`DemoSession.resolve_unresolved_executions()` is the only resolver, and it runs
as a predicate *inside* the one canonical recovery transition
(`resume_from_suspension`) — never as a second recovery path. Unresolved means
a durable journal row in `AMBIGUOUS`, `NEW` or `SUBMITTED`.

```
durable journal row (UNKNOWN outcome)
        |
        v
broker liveness proven?  --no-->  UNVERIFIABLE: nothing decided, nothing cleared
        | yes
        v
positions / working orders / deal history carry this order's comment?
        |                                   |
       yes                                  no
        v                                   v
   EXECUTED                            NO_EXECUTION
   adopt broker record onto            close the row REJECTED, recording the
   the journal row; DO NOT             evidence; the durable suspension may
   clear the suspension —              now be cleared by the canonical
   real exposure needs an              transition
   operator
```

**Absence of evidence counts as evidence of absence only when the broker
positively answered.** `positions()` and `orders()` raise on a dead link, and
`history_deals(..., strict=True)` distinguishes "no deals" from "query failed"
— previously it swallowed exceptions and returned `[]`, which would have let a
broken lookup masquerade as proof that nothing executed.

Nothing is reported resolved unless the durable write succeeded: a failed
journal write downgrades the entry to UNVERIFIABLE rather than being suppressed.

---

## 6. Idempotency

* One `client_order_id` ⇒ one broker submission. The journal's
  `claim_order_slot` refuses a second in-flight row, and the idempotency table
  blocks a re-used id.
* Resolution **never** re-submits. Adopting broker evidence is a local write;
  the recovery path issues no order (the regression suite asserts
  `terminal.requests == []`).
* A resolved-as-`REJECTED` id stays used. Retrying the business intent requires
  a new `client_order_id`, so a resolution can never create duplicate exposure.

---

## 7. Resume semantics (HTTP)

`POST /api/demo/guide/resume` returns the outcome of the *operation*:

| Status | Meaning |
|---|---|
| **200** | every active durable suspension was recovered (or none was active). Trading is **not** resumed: the stage machine is untouched and the body says so. |
| **409** | a recovery predicate failed. **Nothing was cleared.** `recovery.active_blockers` and `recovery.failed_predicates` name what blocked it. |
| **400** | the request itself was invalid (no `confirmed`, no reason). |

A `200` never implies readiness. `200 resume` followed by `409 order` is
coherent and expected when a *current* predicate (stale quote, unprepared
stage) refuses the order — the two endpoints answer different questions, and
the order refusal names its own blocker.

`recovery.failed_predicates` is part of the contract, alongside `recovered`,
`changed`, `cleared`, `active_blockers`, `recovery_checks`,
`unresolved_executions`, `stage`, `orders_permitted` and `next`.

---

## 8. Market-data clock (unchanged, restated)

`qts.lifecycle.demo_gate.evaluate_tick_epoch_freshness` is the single freshness
authority for every consumer. Rule 2 rejects any quote with
`raw_age > MAX_TICK_AGE_S` because `true_age = raw_age + offset ≥ raw_age` for
any non-negative server offset — so a reading such as the observed
`age 3833.7s > 60s` is a **true positive on any clock basis**, not an artefact.
Thresholds were not touched by this work.

---

## 9. Regression coverage

`tests/integration/test_execution_outcome_contract.py` — 12 tests, 9 of which
fail against the pre-fix code:

| Property | Test |
|---|---|
| `-2` is a rejection, not an ambiguity | `test_a_request_the_broker_never_received_is_rejected_not_ambiguous` |
| a lost reply stays UNKNOWN | `test_a_lost_reply_stays_unknown_and_fails_closed` |
| unknown codes fail closed | `test_an_unrecognised_error_code_is_treated_as_unknown` |
| classification by evidence, not text | `test_the_engine_classifies_by_evidence_not_by_error_text` |
| one request construction | `test_submit_sends_exactly_what_the_dry_run_builder_produced` |
| the incident's comment is refused | `test_the_request_contract_refuses_the_comment_that_caused_the_incident` |
| proven-not-executed resolves | `test_broker_evidence_that_nothing_executed_resolves_the_ambiguity` |
| proven-executed is adopted, never duplicated | `test_an_order_that_did_execute_is_adopted_and_never_duplicated` |
| unreadable history resolves nothing | `test_an_unreadable_broker_history_resolves_nothing` |
| both outcome stores stay in step | `test_resolution_keeps_the_journal_and_the_duplicate_guard_in_step` |
| in-flight rows are unresolved too | `test_an_in_flight_submission_is_unresolved_too` |
| API reports failed predicates | `test_the_resume_api_reports_failed_predicates_and_never_fakes_success` |

---

## 10. Refusal explanation contract

**Authority:** `qts.execution.demo_refusal`. It lives beside the gate that
produces the verdict, so the operator-facing wording cannot drift from the
predicate it describes.

Every refusal — from the 28-check pre-trade gate or from any guard around it —
leaves the system carrying a `refusal` block:

```jsonc
{
  "allowed": false,
  "headline": "Order blocked",
  "summary":  "Trading is not ready yet.",
  "explanation_available": true,
  "primary":  { "id": "trading_hours_allowed",
                "plain": "Trading session is outside the permitted trading hours.",
                "retry_when": "The market/trading window is open.",
                "current": "now 03:14 UTC is outside the policy window 07:00-20:00 UTC",
                "technical": "trading_hours_allowed: now 03:14 UTC is outside ...",
                "explained": true },
  "blockers": [ ... every failed predicate, same shape ... ],
  "blocker_ids": ["trading_hours_allowed", ...],
  "unknown_checks": [],
  "reasons": ["trading_hours_allowed: ..."]
}
```

Rules:

1. **Completeness.** Every predicate `demo_pretrade` can `record()` has an
   entry in `REFUSAL_EXPLANATIONS`. `missing_explanations()` is asserted empty
   by the suite, so a new safeguard cannot ship without its sentence.
2. **One chokepoint.** `SubmissionResult.as_dict()` attaches the block
   whenever `allowed is False`, so no refusal path can forget to explain
   itself. Refusals raised outside the gate carry `blocked_by` and use the
   *same* predicate vocabulary (`stage_allows_order`,
   `duplicate_order_protection`, `stop_loss_required`, `submission_error`,
   `execution_engine_refused`, `strategy_registered_frozen`).
3. **Never invent.** An unidentifiable refusal sets
   `explanation_available: false` and says the exact reason is unavailable.
   Fail-closed is unchanged: the order is still refused.
4. **Separation.** `plain` and `retry_when` are for the normal Trading view;
   `id`, `current`, `technical` and the raw `verdict` are for Advanced.
5. **The UI renders, it does not decide.** `trading.js` prints what the server
   built. It previously kept its own dictionary of 11 sentences for 28
   predicates — 4 of its keys matched no predicate the gate can emit — so
   coverage was 7/28 and everything else became a generic line.
6. **HTTP unchanged.** 409 still means refused; only the explanation improved.
   A `dry_run` preview that fails now renders as a refusal too, instead of
   "Preview passed the safety checks".
