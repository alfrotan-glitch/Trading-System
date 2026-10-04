# Demo Readiness Gate — Execution Record — 2026-10-04

**Gate ID:** DEMO-READY-02
**Executed from:** HEAD `ec3d788` (DEMO-READY-01 report commit), tree clean, reconciled with origin.
**Procedure:** the 10-step Demo Readiness Gate (start → connect/identify → clean safety state → controlled order → broker ack → safe close → final reconcile → stop at blockers → never weaken a gate → record result).

---

## FINAL RESULT: **ENVIRONMENT BLOCKED**

The gate was executed literally on this host. It halted at **step 2** on a single root cause that the product named identically at every surface, and that cause is **not fixable on this machine without violating step 9**:

> **The MetaTrader 5 terminal and the `MetaTrader5` Python package cannot exist on this host.**
> Host: `Linux 6.1.158+ x86_64` (this sandbox). Evidence:
> `pip install MetaTrader5` → `ERROR: Could not find a version that satisfies the requirement MetaTrader5 (from versions: none)` — the package publishes **no Linux distribution at any version**. The only fix is a different machine (the Windows host), not a different configuration.

**No gate was weakened, bypassed, or disabled** (step 9 honored). The only lawful "fix" available here — injecting a mock broker — is itself a gate violation, and the product says so explicitly in its own health output: *"mock-based connectivity evidence is not valid."*

---

## Per-step record

| Step | Instruction | Result | Evidence |
|---|---|---|---|
| 1 | Start QTS with the approved DEMO configuration | **PASS** | Server started with `QTS_MODE=demo_execution`; `/api/demo/config` records `mode: DEMO_EXECUTION`, `mode_source: QTS_MODE=demo_execution`, state root pinned cwd-independent. Mode gate flipped honestly: `mode_ok: true`. Owner authorization honored: `authorization_ok: true — ENABLED_AUTHORIZED` (artifact DEMO-AUTH-2026-09-23-01, fingerprint-checked). |
| 2 | Verify MT5 connection, account identity, XAUUSD@ mapping, fresh market data | **HALT — first actual blocker** | Connection: `connected: false`, `BrokerIdentityError: MetaTrader5 package not installed — DEMO identity cannot be verified (fail closed)`. Identity: not recorded (pin artifact `data/evidence/demo_broker_identity_pin.json` exists=false — correct: identity may only be pinned against a live terminal). Symbol mapping: config declares XAUUSD → `XAUUSD@` (session binding verified in DEMO-READY-01 §2.13). Market data: `quote.fresh: false`, bid/ask `null` — no tick is invented. Readiness: `mt5_installed: false — "MetaTrader5 not installed — install MT5 terminal and pip install MetaTrader5"`. |
| 3 | Verify safety gates and durable risk/reconcile state are clean | **NOT CLEAN — correctly** | Durable kill switch ACTIVE (`source: durable:risk_state`, policy DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1 kill conditions). Reconcile suspension ACTIVE (`broker disconnect: MetaTrader5 package not installed…`). Both blockers state their recovery authority: kill → *operator decision recorded with a reason (resume)*; reconcile → *a fresh broker-authoritative reconciliation reporting no drift*. The second is impossible without a broker — so the durable state **cannot and must not** be cleaned on this host. Resume correctly refuses (verified: 409, `failed_predicates: ["reconciliation_verified_clean"]`, nothing cleared). |
| 4 | Execute one controlled DEMO order through the canonical UI/API path | **ATTEMPTED → REFUSED (correct)** | `POST /api/demo/order` with full intent (`confirmed`, `risk_ack`, stop-loss, rationale) → **409, `allowed: false`, `state: NO_TRADE`**, every blocking gate named: `execution_permission` (never enabled), `stage_allows_order` (HALTED), `broker_order_check` (MetaTrader5 not installed), `kill_switch_functional` (ACTIVE), `reconciliation_ready` (BROKER_DISCONNECT), `broker_reference_capture`. The canonical path was used; the canonical path refused; nothing was retried around it. |
| 5 | Confirm broker acknowledgement and position state | **NOT REACHABLE** | No order exists (step 4 refused). Position surface answers honestly: `GET /api/demo/positions` → **503 `broker positions UNAVAILABLE`** — never a fabricated flat book (DEMO-READY-01 fix, regression-pinned). |
| 6 | Safely close through the canonical close authority | **NOT REACHABLE** | No position exists. Close authority verified fail-closed in DEMO-READY-01 (§2.14: no blind close path). |
| 7 | Verify final broker state, journal, reconciliation | **NOT REACHABLE** | No broker. Journal and reconcile authorities verified contract-accurate in the 148-test lifecycle suite (DEMO-READY-01 §4). |
| 8 | If any gate blocks, stop and fix only the actual blocker | **STOPPED** | Actual blocker identified and proven singular: the OS. `pip index versions MetaTrader5` → *No matching distribution found* on Linux. Not fixable here. Nothing else was "fixed". |
| 9 | Do not weaken, bypass, or disable any safety gate | **HONORED** | Zero code changes this gate run. Zero state edits. Every probe went through the canonical API path and accepted its refusal. |
| 10 | Record DEMO READY or ENVIRONMENT BLOCKED | **ENVIRONMENT BLOCKED** | This document. |

## What this run positively established (beyond DEMO-READY-01)

1. **The approved DEMO configuration works.** `QTS_MODE=demo_execution` is accepted, recorded with its source, and flips exactly two gates — mode and owner-authorization — while every broker-dependent gate stays shut. The product does not conflate "allowed to trade" with "able to trade".
2. **The blocker chain is honest end-to-end.** In demo-execution mode, every surface (health, guide, readiness, order refusal, resume refusal) names the same root cause with the same remedy string: *install the MT5 terminal + `pip install MetaTrader5`*.
3. **Durable safety state refuses to be cleaned without a broker.** The resume path demands a broker-authoritative clean reconciliation and cannot be satisfied by any local action — which is precisely the guarantee the Windows host will rely on.

## Hand-off: the identical procedure on the Windows host

**Executable form:** `python scripts/demo_readiness_gate.py` runs steps 1–3 read-only;
add `--execute --quantity ... --stop-loss ...` for steps 4–7. The runner is a pure
sequencer over the canonical API — every PASS criterion is read from the product's
responses, it halts at the first blocker with the server's reasons verbatim, writes a
machine-readable record (`qts.demo_readiness_gate_record.v1`, timestamped under
`data/evidence/`), and exits 2 on any block. Self-tested on this host: step 1 PASS
under the approved configuration, step 2 HALT → ENVIRONMENT BLOCKED, exit 2 — the
runner itself fails closed. Unit-pinned in `tests/test_demo_readiness_gate_runner.py`
(halt-at-first-failure, 503-positions-is-a-halt-not-a-retry, missing broker IDs block
an "allowed" order, verify mode touches no mutating endpoint).

The manual equivalent, for auditing the runner against the procedure:

```
# 0. Prereqs (once): install MetaTrader 5 terminal, log the approved DEMO
#    account into it, then in the QTS venv:
pip install MetaTrader5 -c constraints.txt

# 1. Start (approved DEMO configuration)
set QTS_MODE=demo_execution           (PowerShell: $env:QTS_MODE="demo_execution")
qts desktop launch                     # or: python -m uvicorn qts.api.server:app

# 2. Connection / identity / symbol / data    → all must be measured, none invented
GET /api/mt5            PASS: connected=true, real broker/server/login shown
GET /api/demo/readiness PASS: all 14 checks true (mt5_installed … spread_acceptable)
POST /api/demo/guide/record-identity, then confirm-identity
                        PASS: identity recorded+confirmed+verified, pin artifact written
GET /api/demo/guide     PASS: quote.fresh=true with real bid/ask; symbol XAUUSD→XAUUSD@

# 3. Clean durable state — through recovery authority only, never by editing state
POST /api/demo/guide/prepare   (runs reconciliation against the live broker)
POST /api/demo/guide/resume    PASS only when recovery_checks.reconciliation_verified_clean
                               is satisfied; kill cleared with recorded operator reason;
                               stage advanced to STAGE_2_MIN_SIZE_ORDER by the guide

# 4. One controlled order (canonical path, minimum size, stop-loss required)
POST /api/demo/order {side, quantity=min, stop_loss, confirmed:true, risk_ack:true, rationale}
                        PASS: HTTP 200, allowed=true, broker_order_id AND
                              broker_position_id captured (never null on success)

# 5. Broker ack + position
GET /api/demo/positions PASS: 200, count=1, ticket matches broker_position_id,
                              journal_id correlated
                        (503 here means the terminal link dropped — that is a halt, not a retry)

# 6. Safe close (canonical close authority)
POST /api/demo/close {ticket, confirmed:true, risk_ack:true, reason}
                        PASS: success=true, realized P/L reported,
                              reconciliation.requires_suspend=false

# 7. Final state
GET /api/demo/positions PASS: 200, count=0 (verified flat, not assumed)
GET /api/demo/journal   PASS: order row state CLOSED with broker references
GET /api/demo/guide     PASS: reconciliation.clean=true, no active blockers

# 8-9. Any refusal: read reasons[], fix ONLY the named cause, re-run that step.
#       Never edit data/sqlite state, never mock, never lower a limit to pass.

# 10. Record: DEMO READY (attach the four PASS payloads from steps 4-7)
#            or ENVIRONMENT BLOCKED (attach the refusal payload naming the blocker).
```

---

*Prepared under DEMO-READY-02. No code or durable state changed by this gate run; the session branch carries only this record.*
