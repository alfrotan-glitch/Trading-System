# DEMO Execution — Authorization and Safety Contract (2026-09-23)

**Status:** `DEMO_EXECUTION = ENABLED_AUTHORIZED` · `LIVE = LOCKED` · `REAL_CAPITAL_EXPOSURE = 0` ·
**Trading state: `TRADING_ELIGIBLE_DIAGNOSTIC`** (2026-09-24) — a registered, **non-validated** DEMO
forward research policy may trade to *measure*; no strategy has a validated edge.
**Branch:** `arena/01a0ce9f-trading-system`
**Authorization artifact:** `data/evidence/demo_execution_authorization_2026-09-23.json` (`DEMO-AUTH-2026-09-23-01`)
**Strategy registry:** `data/evidence/demo_forward_validation_registry_2026-09-23.json` (1 entry, see §12a)
**Registered policy:** `DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1` · preregistration
`docs/preregistration_demo_execution_probe_2026-09-24.md`

> **One-line summary.** The owner has authorized real order submission on the configured **MT5 DEMO**
> account for forward-validation research. The authorization is a recorded, hashed, revocable artifact —
> not a source-code switch — and it opens a path in which **every pre-existing gate still applies**.
> No strategy has passed the research gates, so instead of inventing one, a `DEMO_FORWARD_RESEARCH_POLICY`
> was preregistered to **measure the execution path** (§12a). It claims no edge, and its observation
> records may never be used to re-fit it or to select a strategy.

---

## 1. Why DEMO execution was locked — the exact reason

The lock was **policy, not capability**. Every broker-facing component already existed:

| Capability | Where | State before this change |
|---|---|---|
| `order_send` / order lifecycle | `qts/adapters/mt5_adapter.py` (`submit`, `cancel`, `positions`, `history_deals`) | implemented, unused by any product path |
| Order manager, idempotency, reconciliation, fill polling | `qts/execution/engine.py` | implemented |
| Risk veto, durable kill switch, exposure/daily-loss limits | `qts/risk/engine.py`, `qts/risk/authority.py` | implemented |
| DEMO readiness (14 checks) | `qts/lifecycle/demo_gate.py` | implemented |
| Live gate | `qts/lifecycle/live_gate.py` | implemented (and still locking LIVE) |

The single thing standing between `DEMO_FORWARD` (observation) and `DEMO_EXECUTION` (orders) was one
module constant:

```python
# src/qts/lifecycle/demo_authority.py  (before)
DEMO_EXECUTION_POLICY = "DISABLED BY POLICY"
DEMO_EXECUTION_DISABLED = True
```

and its three consumers:

* `DemoExecutionAuthority.current()` — short-circuits to `execution_permitted=False`;
* `DemoExecutionAuthority.enable()` — returns a **durable refusal** (records a `enabled=0` row and emits
  `demo_execution_refused`) before evaluating any other gate;
* `POST /api/demo/enable` — returned **HTTP 409** with `execution_permitted=false` plus the diagnostic
  readiness probe (`src/qts/api/server.py`), and `GET /api/demo/state` always reported
  `execution_permitted=false`.

So `/api/demo/enable -> 409` was **not** a failure of readiness, configuration, or the terminal: it was the
product policy answering "no order path exists" — by design, to keep DEMO_FORWARD observation provably
order-free while research gates were unmet.

**Nothing was bypassed to change that answer.** The constant was not deleted or weakened; it was
re-interpreted as *the shipped default of a checkout with no owner authorization*, and the effective
policy is now resolved from a recorded authorization artifact (`§3`).

---

## 2. New authorization

### 2.1 The artifact

`data/evidence/demo_execution_authorization_2026-09-23.json`, schema
`qts.demo_execution_authorization.v1`, authorization id `DEMO-AUTH-2026-09-23-01`, containing the
owner's written authorization verbatim (`statement`), its scope, the risk ceiling, the research-integrity
covenants, and an `integrity.content_sha256` over the canonical JSON of the document **excluding** the
`integrity` block.

Validation is fail-closed (`qts.lifecycle.demo_authorization._validate`). Any of the following makes the
artifact invalid, which resolves the policy back to `DISABLED BY POLICY`:

* missing file, unreadable file, or wrong `schema`;
* **hash mismatch** (the artifact was edited after signing);
* a revocation record exists (`…revocation.json`);
* `expires_at` in the past;
* `scope.account_type != "demo"`, `scope.live_locked != true`, `real_capital_exposure_usd != 0`,
  `funds_transfer_permitted == true`, `broker_switch_permitted == true`;
* `modes_allowed` includes `LIVE` or omits `DEMO_EXECUTION`;
* `research_integrity.no_forward_optimization != true` or `strategy_registry_required != true`;
* `risk_ceiling` **loosens** any canonical DEMO limit (it may only tighten) or names an unknown key.

### 2.2 What the artifact does *not* do

* It is **not** an override switch: the artifact cannot widen a risk limit, cannot enable LIVE, and
  cannot skip a gate.
* It is **not** environment-controlled: `QTS_DEMO_AUTHORIZATION` only *selects* the file; the file must
  still validate.
* It is **not** implicit: a clean clone with no artifact is `DISABLED BY POLICY`, and the source constant
  `DEMO_EXECUTION_DISABLED = True` still states that default (pinned by
  `test_shipped_default_constant_remains_disabled`).

### 2.3 Revocation (reversibility)

`qts demo revoke --reason …` writes `<artifact>.revocation.json` (`qts.demo_execution_revocation.v1`).
The artifact itself is **never edited or deleted**, so both the authorization and its withdrawal remain
in the audit trail. Revocation immediately resolves the policy to `DISABLED BY POLICY`.

### 2.4 Resolved policy

```
resolve_demo_execution_policy(mode=…)
  no valid artifact                    -> DISABLED BY POLICY          (shipped default)
  valid artifact + mode=DEMO_EXECUTION -> ENABLED_AUTHORIZED
  mode=LIVE                            -> DISABLED BY POLICY (LIVE = LOCKED, always)
  mode=DEMO_FORWARD/PAPER/SHADOW/DEV   -> DISABLED BY POLICY for orders + explicit reason
```

---

## 3. Account verification (safeguard #1)

`qts/execution/demo_identity.py` reads the connected account **from the terminal**
(`account_info()` / `terminal_info()`), never from configuration:

* `trade_mode == 0` (`ACCOUNT_TRADE_MODE_DEMO`) → `is_demo = True` — the only accepted value;
* `trade_mode == 1` (CONTEST) or `2` (REAL) → refused;
* **absent `trade_mode` → `None` → UNKNOWN → refused** (never "probably demo");
* `trade_allowed=false` or `trade_expert=false` → refused;
* `account_info()` returning `None`, or `initialize()` failing → `BrokerIdentityError`, refused.

The gate records an unknown DEMO state as `UNKNOWN` (distinct from `FAIL`) so the operator can tell
"cannot prove" from "proved not-DEMO"; **both block the order**.

## 4. Broker / server verification (safeguard #2)

Identity is **pinned** so the terminal cannot be silently repointed:

1. `qts demo connectivity --pin` writes `data/evidence/demo_broker_identity_pin.json`
   (`qts.demo_broker_identity_pin.v1`) with status `PENDING_REVIEW`;
2. the owner reviews and confirms it: `qts demo connectivity --confirm-pin` → `CONFIRMED`;
3. every order compares the live identity against the pin: **login, server, company, trade_mode and
   fingerprint must all match**, and the pin must be `CONFIRMED`.

A first-run probe can therefore never authorize whatever account it happened to find.

## 5. Symbol verification (safeguard #3)

The canonical symbol (`XAUUSD`) must map to a broker symbol (`XAUUSD@` or as configured), which must be
visible, tradable, and resolve a broker-authoritative `SymbolSpec` (contract size, volume min/max/step,
digits, point, stops_level, filling mode) — `get_symbol_spec` fails closed on any missing field.

---

## 6. Pre-trade gate — all 17 required safeguards

`qts/execution/demo_pretrade.py::run_pretrade_gate` runs **31 checks** per order as of 2026-09-24: the
17 required safeguards, contract-level checks (authorization, permission, mode, stage, autonomy, risk
limit provenance), the registered-policy checks added in §12a (`policy_complete`,
`symbol_allowed_by_policy`, `trading_hours_allowed`, `order_frequency_within_policy`,
`max_drawdown_within_policy`, `policy_execution_assumptions`) and the two symbol-binding checks added
by the §16.10 lifecycle audit (`broker_symbol_matches_registry`, `symbol_provenance`). It passes only when **every** check is
`PASS`; any unresolved fact is `UNKNOWN` and blocks. The exact count moves as safeguards are added —
the invariant is the completeness rule, not the number.

| # | Required safeguard | Check | Fail-closed behaviour |
|---|---|---|---|
| 1 | account is actually DEMO | `account_is_demo` | unknown `trade_mode` blocks |
| 2 | broker/server identity | `broker_identity_verified` | unpinned / pending / mismatched blocks |
| 3 | canonical symbol mapping | `symbol_mapping_canonical` + `broker_symbol_matches_registry` + `symbol_provenance` | no mapping, untradable, a venue alias the registry never pinned, or a pin whose symbol provenance disagrees all block |
| 4 | market data freshness | `market_data_fresh` | age > 60 s or unmeasurable blocks |
| 5 | spread available | `spread_available` | invalid quote or spread > 30 bps blocks |
| 6 | order size within hard maximum | `order_size_within_hard_max` + `broker_order_check` | > min(demo cap, broker max), off-step, or failing broker `order_check` blocks |
| 7 | stop-loss present | `stop_loss_present` | missing / wrong side / inside `stops_level` / off-tick / risking more than the policy's daily budget blocks |
| 8 | maximum simultaneous positions | `max_simultaneous_positions` | > 3 positions blocks |
| 9 | maximum daily loss | `max_daily_loss` | ≥ $50 realized loss, or unknown P&L, blocks |
| 10 | maximum total demo exposure | `max_total_exposure` | > 0.3 lots (and notional cap) blocks |
| 11 | duplicate-order protection | `duplicate_order_protection` | seen `client_order_id` or orders inside the interval block |
| 12 | kill-switch functionality | `kill_switch_functional` | active, unreadable, or **un-exercised** switch blocks |
| 13 | reconciliation after every order | `reconciliation_ready` | suspended, drifted, stale or never-run blocks |
| 14 | broker order/position id recorded | `broker_reference_capture` | adapter/journal that cannot capture ids blocks |
| 15 | price/spread/slippage/timestamps recorded | `execution_record_fields` | any missing record field blocks |
| 16 | strategy/configuration hash recorded | `strategy_registered_frozen` | unregistered strategy or **parameter drift** blocks |
| 17 | fail closed on uncertainty | `no_unknown_checks` | any `UNKNOWN` blocks |

Contract-level checks: `authorization_valid`, `execution_permission` (durable authority, ≤120 s evidence
TTL), `mode_is_demo_execution`, `stage_allows_order`, `risk_limits_resolved`, `autonomous_allowed`.

### Hard risk limits (DEMO_EXECUTION)

Resolved from the single canonical risk authority (`qts.risk.authority`, mode `DEMO_EXECUTION`); the
authorization's `risk_ceiling` may only tighten them:

| Limit | Value |
|---|---|
| max order size | 0.10 lots (and ≤ broker `volume_max`, on-step, ≥ `volume_min`) |
| max total exposure | 0.30 lots |
| max simultaneous positions / orders | 3 |
| max orders per minute | 4 |
| daily loss limit | $50 |
| max drawdown | $100 / 5 % |
| max spread | 30 bps |
| max slippage | 20 bps |
| kill switch | always armed (`flatten_on_kill=false` — halts new orders, no forced flattening) |

---

## 7. Execution state machine

`qts/lifecycle/demo_stage.py` — persisted, refusal-recording, no shortcuts:

```
DISABLED ──► STAGE_1_CONNECTIVITY ──► STAGE_2_MIN_SIZE_ORDER ──► STAGE_3_FORWARD_OBSERVATION
   ▲                  ▲                        │                          │
   └──────────────────┴────────────────────────┴──────────────────────────┘
                        (any stage) ──► HALTED
```

* Only `STAGE_2` and `STAGE_3` permit orders (`ORDER_STAGES`).
* Each transition records actor, reason and the prerequisite evidence; a refused transition is recorded
  too (durable negative evidence, never a silent no-op).
* `HALTED` is reachable from anywhere and leaves only through an explicit re-arm (`DISABLED`).

Stage prerequisites:

* **Stage 1** — readiness passed, account is DEMO, symbol OK, quote fresh.
* **Stage 2** — policy authorized, identity pinned **and confirmed**, operator `confirmed` + `risk_ack`,
  durable authority enabled with a fresh readiness report.
* **Stage 3** — ≥ 1 journaled/reconciled Stage-2 order and an explicit strategy selection.

## 8. Kill switch

* Durable flag in `risk_state` (shared with `qts risk kill`), re-read on access; a read failure is treated
  as **killed**.
* `qts demo kill` / `POST /api/demo/kill` raise the durable flag **and** halt the stage machine.
* The pre-trade gate requires a **self-test each cycle**, executed on a scratch database
  (`data/sqlite/demo_killswitch_selftest.db`) so proving the switch never disturbs the production flag:
  arm → read back `killed=True` → clear → read back `False`. An unproven switch blocks every order.

## 9. Reconciliation

* Performed by `ExecutionEngine.reconcile()` (broker positions/orders vs internal state).
* Runs **after every submitted order**; the result (drift, details, suspension) is written to the journal
  row (`reconciled`, `reconcile_note`).
* Any `requires_suspend` also halts the stage machine. A pre-trade check additionally requires a
  reconciliation result fresher than 300 s; "never reconciled" blocks.

## 10. Audit trail

`qts/execution/demo_journal.py` (SQLite `demo_order_journal`, exportable with `qts demo journal --export`)
records for every order:

* `label = RESEARCH_DEMO_ORDER` (immutable, so a DEMO research order can never be replayed or reported as
  a LIVE order), authorization id, client order id;
* strategy id, **frozen configuration hash**, hypothesis id, registry hash;
* signal snapshot, order request, requested price / lots / SL / TP;
* broker order id, **position/deal id**, retcode, executed price/volume;
* spread (bps), slippage (bps vs requested price), latency (ms), timestamps (signal → requested →
  submitted → closed);
* lifecycle state, exit reason, realized and unrealized P&L, fees;
* market state at entry and at exit, reconciliation outcome.

`demo_signal_journal` records **every** decision, including `NO_TRADE`, so "the system stayed flat" is as
auditable as "the system traded". Domain events (lifecycle, order, fill, risk veto, reconcile, kill) go
through the existing audit sink; every authority transition emits
`demo_execution_enabled` / `demo_execution_refused` / `demo_execution_disabled`.

---

## 11. First-order conditions (what must be true before the first DEMO order)

1. Valid, un-revoked authorization artifact → `ENABLED_AUTHORIZED` (✔ in this checkout).
2. Process running in `QTS_MODE=demo_execution` (a `DEMO_FORWARD` process can never hold permission).
3. Stage advanced to `STAGE_2_MIN_SIZE_ORDER` (requires pinned + confirmed identity and a fresh
   readiness pass) — **not yet done**.
4. Broker identity verified against the pin (§4) — **not yet done** (no terminal reachable from this
   sandbox, see §14).
5. An **eligible, preregistered strategy** in the forward-validation registry — **not satisfied**
   (registry empty).
6. All 22 pre-trade checks `PASS` in the same cycle as the order.
7. A broker `order_check` dry-run passes for the exact request.
8. Size is the **broker minimum** for the first order (`size_policy.mode = "broker_minimum"`), unless the
   registry specifies otherwise.
9. A stop-loss is attached to the order itself (never added after the fill).

**Current verdict: conditions 3–5 are unmet → `NO_TRADE`. No DEMO order has been submitted
(`orders_submitted = 0`).**

## 12. Strategy status — no validated strategy (deliberate)

On 2026-09-23 every preregistered XAUUSD family is REJECTED or INCONCLUSIVE after realistic costs
(`spread+2c`, 1-quote delay, Holm α0.01, block-bootstrap): H-DIR-02, H-DIR-03a/b, H-TEMP-01, H-ST-02WF,
H-XF-01, H-XF-02, H-MM-01 (fails absolute-net), H-MM-02 WF (fails 4/5 folds), H-1M-01, 15m impulse.
`strategy_promoted=false` in every `reports/xauusd_*_state.json`; the 69 M-row held-out prefix was never
opened. See `docs/evidence/final_best_strategy_2026-09-23.md` and `docs/evidence/best_edge_strategy_2026-09-23.md`.

Therefore: **`DEMO_EXECUTION = ENABLED` and `TRADING_STATE = NO_TRADE` coexist**, exactly as the owner's
instructions require. No strategy was invented to make the new capability look useful.

To trade, a hypothesis must be preregistered and registered in
`data/evidence/demo_forward_validation_registry_2026-09-23.json` with:

```json
{"strategy_id": "...", "status": "ELIGIBLE", "hypothesis_id": "H-...-NN",
 "preregistration_artifact": "docs/preregistration_....json",
 "signal_provider": "qts.research.<module>:<Provider>",
 "params": {...}, "params_hash": "<sha256 of canonical params>",
 "size_policy": {"mode": "broker_minimum"}, "stop_policy": {"required": true},
 "exit_policy": {"max_hold_seconds": 0}, "allowed_symbols": ["XAUUSD"], "max_orders_per_day": 1}
```

Research-integrity enforcement while trading:

* parameters are frozen — any change breaks `params_hash` and halts the run (`PARAMETER_DRIFT`);
* providers exposing `optimize`/`fit`/`tune`/`search`/`calibrate` hooks are refused while the registry
  forbids optimization;
* forward DEMO results are recorded as observation evidence only and are never fed back into research,
  parameter selection, or promotion decisions.

**Update 2026-09-24.** The registry is no longer empty: one *diagnostic* forward research policy is
registered so the DEMO path can be measured without inventing an edge. It uses status
`ELIGIBLE_DIAGNOSTIC`, not `ELIGIBLE`. See **§12a**.

## 12a. The registered DEMO research/execution policy (2026-09-24)

The registry is no longer empty. One **diagnostic** research policy is registered, under a status that
cannot be confused with a validated strategy:

| Field | Value |
|---|---|
| `strategy_id` | `DEMO-EXECPROBE-XAUUSD-V1` |
| `status` | `ELIGIBLE_DIAGNOSTIC` (not `ELIGIBLE` — that status is reserved for a strategy with a validation artifact) |
| `policy_class` | `DEMO_FORWARD_RESEARCH_POLICY` |
| `policy_id` / `version` | `DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1` / `1.0.0` |
| `hypothesis_id` | `H-EXEC-01` (execution-cost probe — a *measurement* hypothesis, not a directional one) |
| Preregistration | `docs/preregistration_demo_execution_probe_2026-09-24.md` |
| Provider | `qts.research.demo_execution_probe:ExecutionCostProbe` |
| `validated_edge` | `false` |
| Session | Mon–Fri 08:00–16:00 UTC (London–New York overlap) |
| Size / exposure | 0.01 lots (broker minimum) · `max_simultaneous_exposure_lots` 0.01 · one position |
| Loss limits | `max_daily_loss` 5.00 USD · `max_drawdown` 10.00 USD |
| Frequency | 2 orders/day · 900 s minimum interval · 900 s maximum hold |
| Costs | `max_spread_bps` 3.0 · `max_slippage_bps` 2.0 · `execution_delay_assumption_ms` 1500 |
| Pinned hashes | `code_hash` (provider source) · `config_hash` (= `params_hash`) · `data_hash` null (no historical dataset is consumed) |

**Why a probe and not a strategy.** The ledger is closed with `NO_VALIDATED_EDGE`
(`reports/research_cycle_closure_2026-09-23.json`); every magnitude survivor is *process structure, not a
directional trade* ("mean signed move ~0.8 cent, P(up)~0.506 at 256q; not executable — no volatility
instrument, no side"). Inventing a signal to make the DEMO account trade would be the exact
research-integrity failure this project forbids. What *can* be measured honestly — and what every future
hypothesis needs first — is the cost and behaviour of the execution path itself: spread at entry,
slippage, submission latency, protective-stop behaviour, time-exit behaviour, round-turn cost, and
reconciliation agreement.

**The rules are deterministic and frozen.** At most one round turn per UTC hour; direction alternates
by parity of the UTC hour (`BUY` on even hours, `SELL` on odd) so the sample set carries **no net
directional exposure**; entry is gated only on data quality and cost (quote age ≤ 5 s, spread within the
policy cap); the protective stop (± 2.00 USD) is attached to the order itself; exit at 900 s or on the
stop, with the reason and the venue's realized P&L recorded either way. There is no indicator, no
prediction, and no parameter search.

**How the policy is enforced, not just stored.** Registration alone proves nothing, so every declared
limit is a live constraint:

* `policy_complete`, `symbol_allowed_by_policy`, `trading_hours_allowed`,
  `order_frequency_within_policy`, `max_drawdown_within_policy` and `policy_execution_assumptions` are
  pre-trade gate checks; a policy check that cannot be evaluated is `UNKNOWN` and fails the order;
* the policy can only **tighten** the canonical DEMO limits — spread, tick age, order interval,
  reconcile age, per-order size, exposure and daily loss are combined with `min`/`max`, never replaced
  (`src/qts/execution/demo_pretrade.py::_cap`);
* `code_hash` is verified against the provider's source file on every autopilot cycle — a provider that
  no longer matches its registration halts the loop (`code drift`);
* kill conditions named by the policy (daily loss, drawdown, reconciliation drift, parameter drift, code
  drift, identity mismatch, revoked authorization, stale data, stage) **raise the kill switch and halt
  the stage** on the refusal, rather than letting the loop retry (`DemoSession._enforce_policy_kill_conditions`).

**Change control.** Any change is a new policy version with a new preregistration and a new
`config_hash`, never an edit in response to a result. `scripts/register_demo_research_policy.py`
recomputes the hashes from disk and re-seals the entry (the procedure is in git either way, which is
exactly why the preregistration rule is a rule and not a convention).

**What success looks like.** Measurement completeness — complete spread/slippage/latency/stop/reconciliation
records with the controls clean — **not** profit. A run that loses money and produces complete
measurements succeeded; a run that makes money without an explanation did not.

## 13. What this authorization does not permit

* **LIVE trading** — `LIVE = LOCKED`; the live gate is untouched and the authorization refuses any
  artifact that mentions LIVE or unlocks it.
* **Real capital exposure** — `REAL_CAPITAL_EXPOSURE = 0`; any non-zero value invalidates the artifact.
* **Funds transfers, withdrawals, deposits** — explicitly forbidden in scope.
* **Broker/account switching** — forbidden; enforced by the identity pin.
* **Weakening risk controls to obtain trades** — the risk ceiling may only tighten; the gate cannot be
  partially disabled.
* **Bypassing authentication or broker safeguards** — no credential handling was added or changed; the
  terminal session and the broker's own checks remain authoritative.

## 14. Environment limitation (honest boundary)

This work was implemented and tested in a **Linux sandbox without a MetaTrader5 terminal**
(`import MetaTrader5` → `ModuleNotFoundError`). Consequently:

* Stage 1 connectivity, identity pinning and Stage 2 order submission **cannot be executed here**; they
  must run on the Windows workstation where the MT5 DEMO terminal is installed
  (see `docs/mt5_demo_setup.md`).
* In this environment the pre-trade gate reports the honest result: `UNKNOWN` for identity, pin, quote
  and symbol → **order refused** (verified: `/api/demo/preflight` → HTTP 409).
* No order was submitted from this sandbox and none could be.

## 15. Operating procedure (Windows terminal, DEMO account)

```bash
set QTS_MODE=demo_execution                  # the DEMO order path exists ONLY in this mode
qts demo verify                              # START HERE: what's blocking, and the one next command
qts demo authorization                       # artifact + resolved policy
qts demo connectivity                        # Stage 1 (no orders)
qts demo connectivity --pin                  # record observed identity + symbol provenance (PENDING_REVIEW)
qts demo connectivity --confirm-pin          # owner confirms the pin
qts demo arm --stage 1                       # prove Stage 1 prerequisites
qts demo preflight --side BUY                # full-gate dry run (derives the policy stop; no order)
qts demo arm --stage 2 --confirm --risk-ack  # open the order path
qts demo reverify --confirm --risk-ack       # refresh permission when its 120 s evidence expires
qts demo order --side BUY                    # ONE RESEARCH_DEMO_ORDER (SL derived unless given)
qts demo run --strategy <id> --confirm --risk-ack   # autonomous DEMO trading (refreshes permission)
qts demo journal --export data/evidence/demo_forward_observations.jsonl
qts demo kill --reason "..."                 # halt immediately (durable; halts the stage)
qts demo clear-kill --reason "..." --confirm # lift the halt (stage stays HALTED — re-arm)
qts demo revoke --reason "..."               # withdraw authorization
python scripts/demo_static_validation.py     # offline check: LIVE lock, scope, policy, hashes
```

**Readiness evidence expires every 120 s — that is normal, not a failure.**
Permission is proven against the live terminal rather than inherited from an old
pass, so a long session must refresh it:

* `qts demo reverify --confirm --risk-ack` re-proves readiness and re-enables the
  durable authority **at the current stage**; it is recorded as
  `demo_execution_reverified` and never touches the stage machine.
* `qts demo arm --stage 2 --confirm --risk-ack` while already at Stage 2 does the
  same thing (it is a re-verification, not a transition — the state machine has
  no `STAGE_2 → STAGE_2` edge, by design).
* `qts demo verify` names whichever of the two applies, so the suggested command
  always runs. Neither changes `REVERIFY_TTL_S`.
* `qts demo run --confirm --risk-ack` refreshes automatically inside the loop
  (once per cycle, only when permission has decayed); without those flags the
  loop stops when the window closes instead of refreshing it.

**`QTS_MODE` is not decoration.** A `DemoSession` resolves its mode from the process (or from an explicit
`DemoSessionConfig.mode`), so the DEMO order path cannot be reached by merely constructing a DEMO session
in a process that is running in another mode — `mode_is_demo_execution` fails, the authority refuses
permission, and `qts demo verify` says so first. Every other mode, **including LIVE**, has no DEMO order
path at all.

`qts demo verify` is the operator's entry point: a read-only triage that touches nothing (no order, no
stage change, no enablement) and answers one question — *where am I, and which single command comes next?*
It prints authorization, account/identity/pin state, symbol mapping, the fresh 14-check readiness result,
registry state, stage, a minimum-size pre-trade dry run, kill-switch and reconciliation health, then
`READY: True/False` and `NEXT: <the one command>`. Exit code **0** = every checkable gate passes, **2** =
something is blocking (each blocker is printed). `--json <path>` writes the full triage report. The next
action follows the order the gates actually require — for example a raised kill switch is reported before
arming, because arming cannot succeed until the halt is lifted.

`qts demo clear-kill` is the recovery half of the kill switch: it requires `--confirm` and a non-empty
`--reason`, records an audit event, and **deliberately leaves the stage HALTED**, so trading cannot resume
by accident — the operator must re-arm and prove the staged progression again.

API equivalents: `GET /api/demo/authorization`, `/api/demo/stage`, `/api/demo/preflight`,
`POST /api/demo/enable`, `POST /api/demo/order`, `POST /api/demo/kill`, `GET /api/demo/journal`.
`POST /api/demo/enable` now returns **200** only when the authorization is valid and every gate passes;
it still returns **409** (`execution_permitted=false`) on any refusal, with the reasons attached.

## 16. Verification performed

### 16.1 Real-terminal wiring (simulated terminal, no broker contact)

`tests/integration/test_demo_session_wiring.py` (run with `pytest --run-integration`) drives the whole
session against a deterministic fake MT5 module that behaves like a healthy DEMO terminal. After
connectivity, identity pinning + owner confirmation, reconciliation, fresh readiness, durable authority
enablement and Stage-2 arming, the pre-trade gate reports:

```
19 PASS · 0 UNKNOWN · 1 FAIL
failed = ["strategy_registered_frozen"]
       → "no registered forward-validation strategy — NO_TRADE"
```

(Recorded on 2026-09-23, when the registry was empty. With a registered policy the same wiring
evaluates 31 checks and the residual blocker is the one the policy or the venue actually raises —
e.g. `trading_hours_allowed` outside Mon–Fri 08:00–16:00 UTC.)

i.e. **every operational safeguard passes and the order is still refused**, because the binding
constraint is the research gate. The same test asserts that `submit()` returns `NO_TRADE`, records a
`NO_TRADE` signal, sends no broker order, and that the autopilot halts (0 orders) on `NO_TRADE` and on
an active kill switch.

With the operator steps *not* yet performed (the state of this checkout on a fresh terminal) the gate
reports the honest residual blockers instead of a green light:

| Check | Status | Operator action |
|---|---|---|
| `broker_identity_verified` | FAIL | `qts demo connectivity --pin` then `--confirm-pin` |
| `execution_permission` | FAIL | not yet armed: `qts demo arm --stage 2 --confirm --risk-ack`. Already at Stage 2/3 and the 120 s evidence expired: `qts demo reverify --confirm --risk-ack` (a refresh, **not** a transition — §16.10) |
| `stage_allows_order` | FAIL | advance the stage machine (Stage 1 → 2) |
| `symbol_allowed_by_policy` | FAIL | the canonical symbol the policy binds to does not match the session: declare the venue alias in `data/setup/mt5_setup.json` `symbol_map` (e.g. `{"XAUUSD": "XAUUSD@"}`) — the refusal message names the exact entry (§16.10 #1) |
| `broker_symbol_matches_registry` | FAIL | the venue symbol this session trades is not the one the registered experiment was verified against — re-register against the verified alias; never edit the entry in place |
| `symbol_provenance` | FAIL | the confirmed identity pin was taken against a different canonical/venue pair — re-pin and re-confirm (`qts demo connectivity --pin` then `--confirm-pin`) |
| `reconciliation_ready` | UNKNOWN→PASS | resolved by the pre-trade reconciliation probe |
| `strategy_registered_frozen` | FAIL | **research**: register a preregistered, eligible experiment (§12a) |

### 16.2 Autonomous loop (simulated terminal + registered test strategy)

`tests/integration/test_demo_autopilot_loop.py` (8 tests, `--run-integration`) registers an eligible,
parameter-frozen test provider (`tests/fakes_demo_provider.py`) and drives the real loop against a
stateful fake terminal. Verified end to end:

* one `RESEARCH_DEMO_ORDER` is submitted at **minimum size with its stop and target on the order**
  (`volume 0.01`, `sl 1995.00`, `tp 2010.20`), and the journal carries the full record — broker order
  and position id, requested/executed price, spread, slippage, latency, strategy config hash;
* the open position is managed: unrealized P&L is updated, and on `max_hold_seconds` it is **closed**,
  the exit reason and realized P&L are journalled, and the loop reconciles clean afterwards
  (`drift NONE`, engine not suspended);
* an **eligible strategy may decline to trade** — a provider returning no signal yields recorded
  `NO_TRADE` cycles with zero orders, not an error;
* the daily order cap stops new orders without halting the loop;
* a provider exposing an `optimize` hook is **refused** ("optimization hooks") with zero orders;
* **parameter drift** (runtime `config_hash` != registered hash) halts the loop with zero orders;
* once the DEMO daily-loss limit is consumed, `max_daily_loss` fails and no order is sent.

None of that traded real capital: the terminal is a fake, and the same code path is refused
outright in any non-DEMO mode.

### 16.3 Defects the integration tests exposed (and the fixes)

Building the loop found four real bugs in the pre-existing execution path — all of them would have
made the *first* DEMO order misbehave. They are fixed here and covered by tests:

| # | Defect | Effect | Fix |
|---|---|---|---|
| 1 | `MT5Adapter.submit()` built the broker request **without SL/TP** (only the dry-run `build_broker_request` carried them) | the gate requires a stop, but the order actually sent had none — exposure could exist unprotected | `_protective_levels()` now validates and attaches `sl`/`tp` on the request that is really sent |
| 2 | `positions()`, `orders()` and `poll_fills()` reported the **broker** symbol (`XAUUSD@`) as if it were canonical | reconciliation compared `local XAUUSD` against `venue XAUUSD@`; the first order produced phantom drift (`UNKNOWN_POSITION` / `MISSING_POSITION`) and suspended trading | `_canonical_symbol()` translates broker aliases back before the portfolio, reconciliation or fills ever see them |
| 3 | reconciliation ran **before** broker deals were polled | local portfolio still empty vs a real venue position ⇒ immediate suspend on a phantom mismatch | `DemoSession.submit()` polls live fills before reconciling; `DemoSession.sync_fills()` added for the close path |
| 4 | a position close produced an **unattributable deal** (its comment was not in the comment map) | the engine must discard unattributed fills, so the local portfolio kept a position the venue had already closed | `close_position()` registers the close comment (`close-<ticket>`) so the closing deal is attributable |

Two loop-level gaps were fixed alongside: the signal provider is instantiated **once per run**
(a fresh object every cycle would re-emit the same signal), and every cycle now re-checks
reconciliation health and halts if a suspension is required.

### 16.4 API contract (the surface the 409 lived on)

`tests/test_demo_api.py` (13 tests, always run) pins the behaviour at the HTTP layer, because the
original symptom — `POST /api/demo/enable -> 409 execution_permitted=false` — is something an operator
meets through the API:

* `GET /api/demo/authorization` — reports the artifact, `live_locked: true`, `real_capital_exposure_usd: 0`
  and the resolved policy `ENABLED_AUTHORIZED`;
* `POST /api/demo/enable` without `confirmed`/`risk_ack` → **400**;
* `POST /api/demo/enable` with **no** authorization artifact → **409** `state=DISABLED`,
  `policy="DISABLED BY POLICY"`, `demo_execution_disabled: true` — the shipped default, unchanged;
* with an artifact but a **failing fresh readiness** → **409** (authorized, still refused);
* with an artifact and a **fresh passing readiness** → **200** `execution_permitted: true`, and
  `POST /api/demo/disable` revokes it again;
* `GET /api/demo/preflight` → 409 while any check is unresolved (`no_unknown_checks` FAILs: nothing
  unknown is counted as a pass);
* `POST /api/demo/order` with no registered strategy → **409** `NO_TRADE`; with an armed session and a
  registered strategy → **200**, exactly one minimum-size `RESEARCH_DEMO_ORDER` journaled with its
  strategy config hash;
* `POST /api/demo/kill` → kill switch raised **and stage HALTED**;
* `GET /api/demo/journal` → labelled `RESEARCH_DEMO_ORDER`, `capital_class: DEMO`, empty by default;
* `GET /api/demo/stage` → `DISABLED`, `orders_permitted: false` on a fresh database.

Every durable side effect in those tests (DB, audit log, kill-switch self test, identity pin) is
redirected to `tmp_path`, so the suite never touches the operator's state.

### 16.5 Operator CLI (the documented procedure, executed)

`tests/integration/test_demo_cli.py` (9 tests, `--run-integration`) runs the §15 procedure through the
CLI with the fake terminal injected as `sys.modules["MetaTrader5"]`, so the real 14-check readiness
gate, authority, stage machine and pre-trade gate all execute:

* `qts demo connectivity` → `readiness passed: True`, `account: demo=True login=123456`,
  `XAUUSD -> XAUUSD@`, spread, `STAGE_1_READY: True`, and **zero broker requests** (Stage 1 sends nothing);
  `--json-out` writes the full report;
* `connectivity --pin` → pin `PENDING_REVIEW`; `connectivity --confirm-pin` → owner confirmation;
* `arm --stage 1` → `arm --stage 2` → `authority: ENABLED permitted=True` (each stage re-proves its
  prerequisites); `arm --stage 2` **without** `--confirm --risk-ack` is `REFUSED` (exit 2);
* `order` with no registered strategy → exit 2 `NO_TRADE`; with one → a single minimum-size
  `RESEARCH_DEMO_ORDER`, journaled and visible in `qts demo journal`;
* `journal --export` writes the forward-validation JSONL (label, broker id, strategy config hash);
* `preflight` submits nothing;
* `run --dry-run` halts on the research gate (`NO_TRADE`, 0 orders, 0 broker requests) once armed;
* `kill` raises the durable kill switch and a subsequent `arm` is `REFUSED`;
* `revoke` writes an **additive** sidecar (`…json.revocation.json`), leaves the artifact byte-identical,
  and execution is disabled again — `status` reports `DISABLED BY POLICY` and `order` refuses.

### 16.6 Failure modes and concurrency

A trading system is judged by what it does when things break. `tests/integration/test_demo_failure_modes.py`
(10 tests, `--run-integration`) injects failures and asserts the system fails closed:

| Injected failure | Required behaviour | Result |
|---|---|---|
| ambiguous retcode (10012, timeout) | record `REJECTED` with the retcode, suspend, **never resend** | 1 broker request, engine suspended, second attempt refused |
| definitive rejection (10006) | record `REJECTED` + `broker_retcode`, no retry | 1 request, 1 record, no position |
| broker disconnect mid-loop | stop the loop | halted with the reconciliation reason; no crash |
| restart with a broker-only position (crash left a position we never journaled) | refuse to trade | `UNKNOWN_POSITION` → suspend → 0 orders |
| cold start after a legitimate fill (new process, empty in-memory portfolio) | rebuild from broker deals, **don't** call it drift | `drift NONE`, position restored, trading allowed |
| stale in-flight row (process died mid-submission) | fail the abandoned row, keep trading | row → `REJECTED` ("outcome unknown — verify with the broker"), next order allowed |
| two concurrent submissions | exactly one order | 1 broker request, 1 journal row, other refused "in flight"/"duplicate" |
| second order inside the minimum interval | refuse | 1 request |
| another process holds the DB write lock | refuse, do not guess | claim returns "could not be claimed atomically", no row inserted |
| kill switch raised by another process | obey it | a brand-new session with empty in-memory state refuses |
| kill switch vs. a stage that allows orders | stop immediately | loop halts, 0 orders |

Two implementation properties make the concurrency rows true:

* **The order slot is claimed atomically.** The gate's duplicate/rate check reads the journal and the
  insert happened afterwards — a check-then-act pair that two callers (an operator CLI command during an
  autopilot cycle, or two processes) could both pass. `DemoOrderJournal.claim_order_slot()` performs the
  whole sequence — expire stale in-flight rows → duplicate/rate check → in-flight check → insert — inside a
  single `BEGIN IMMEDIATE` transaction (`qts.db.immediate`), so a concurrent caller either waits for the row
  or sees it and refuses. A locked database is an unknown state: the claim refuses instead of assuming the
  slot is free.
* **Reconciliation heals a cold start before it compares.** A fresh process has an empty portfolio, so a
  legitimate broker position would otherwise read as `UNKNOWN_POSITION` and suspend trading. `reconcile()`
  polls the broker's deal history first when local state is empty and the venue reports positions, so it
  compares like with like — while a position that genuinely cannot be attributed still suspends.
* **An abandoned submission is failed, not assumed.** Rows in `NEW`/`SUBMITTED` older than the in-flight
  budget are expired to `REJECTED` at session start, so a crash can never wedge the system — and the record
  says the outcome is unknown rather than implying the order never happened.

Two smaller corrections came out of this work: a refusal now records the **engine's own reason and broker
retcode** (safeguard #15) instead of the generic "risk/engine veto", which hid the difference between a
risk limit, a broker rejection and an ambiguous timeout; and when the loop stops because the stage is
`HALTED` it reports **why it was halted** ("halted because: reconciliation drift after …").

### 16.7 Unit / adversarial coverage

New/updated tests (all passing in this checkout):

* `tests/adversarial/test_demo_authority_gate.py` — 36 tests: the un-authorized regime still refuses
  everything (readiness, payload, direct call, restart, tampered rows), plus the authorized regime
  (confirmation, fresh evidence, LIVE locked, tampered/revoked artifact, TTL decay, audit-before-write).
* `tests/adversarial/test_demo_pretrade_gate.py` — 46 tests: one per safeguard, healthy-context-passes
  baseline, and "no silent defaults" (dropping identity/spec/limits/entry refuses).
* `tests/adversarial/test_demo_execution_authorization.py` — 23 tests: DEMO/REAL/unknown account
  detection, pin lifecycle and account-switch rejection, registry resolution, parameter drift, shipped
  registry is empty.
* `tests/unit/test_demo_stage_machine.py` — 15 tests: stage transitions, halted state, journal lifecycle,
  slippage/P&L accounting, export.
* `tests/integration/test_demo_session_wiring.py` — 9 tests (`--run-integration`): the full session
  against a simulated DEMO terminal (see §16.1).
* `tests/integration/test_demo_autopilot_loop.py` — 8 tests (`--run-integration`): autonomous loop,
  position lifecycle and research-integrity refusals (see §16.2/§16.3).
* `tests/integration/test_demo_cli.py` — 9 tests (`--run-integration`): the operator CLI procedure (§16.5).
* `tests/integration/test_demo_failure_modes.py` — 10 tests (`--run-integration`): broker faults,
  restart/concurrency and kill-switch propagation (see §16.7).
* Shared: `tests/demo_harness.py` (hermetic environment + one `armed_session` helper),
  `tests/integration/conftest.py`, `tests/fakes_mt5_demo.py`, `tests/fakes_demo_provider.py`.
* `tests/test_demo_api.py` — 13 tests: the HTTP contract above (see §16.4).
* `tests/integration/test_demo_cli.py` — 9 tests (`--run-integration`): the operator CLI procedure (§16.5).
* Shared fixtures: `tests/fakes_mt5_demo.py` (stateful fake terminal), `tests/fakes_demo_provider.py`
  (frozen deterministic provider + deliberately non-compliant variants).

Invariants stated by this document and pinned by tests:

```
DEMO_EXECUTION = ENABLED_AUTHORIZED   (with the recorded artifact)
LIVE = LOCKED                         (no artifact, mode, or request can change it)
REAL_CAPITAL_EXPOSURE = 0
orders_submitted = 0                  (as of 2026-09-23, NO_TRADE)
```

### 16.8 PR #4 review (2026-09-24) — findings and fixes

The branch was re-reviewed end to end against the two questions that matter most for this contract:
*can any path submit a LIVE order?* and *can DEMO authorization become LIVE authorization?*

| # | Finding | Disposition |
|---|---|---|
| 1 | `submit_with_order_check()` in `src/qts/adapters/order_check.py` calls the broker adapter **directly**, bypassing `DemoSession` and therefore the DEMO gate. It has no callers today, so nothing could be submitted — but it is a latent hole: the first caller would inherit a broker path with no mode check, no authorization check and no DEMO-account proof. | **Fixed.** It now asserts, before anything is sent, that the process resolves to `DEMO_EXECUTION`, that a valid owner authorization is in force, and that the connected account is provably DEMO; any unresolvable fact raises `PermissionError`. Covered by `tests/unit/test_direct_broker_submit_guard.py` (7 tests, including LIVE/DEMO_FORWARD/PAPER/DEVELOPMENT, missing authorization, non-DEMO account and unreadable identity). |
| 2 | A policy could be *carried* by the registry without being *enforced* by the gate: nothing checked the registered symbol, trading hours, daily order budget or drawdown. | **Fixed** — six new gate checks plus policy-tightened canonical caps (§12a). |
| 3 | `ResearchPolicy` wrapped its document in a mutable `dict`, so a caller could retune a limit in memory while the registered hash still matched. | **Fixed** — the parsed document is deep-frozen (read-only mappings); the test that exposed it is `test_policy_contents_cannot_be_retuned_after_registration`. |
| 4 | `DemoSession` **asserted** its own mode: `policy` resolved with `mode="DEMO_EXECUTION"` and the gate context reported `DEMO_EXECUTION` no matter what mode the process was actually in. A LIVE-mode (or merely misconfigured) process could therefore walk the DEMO path behind a gate check that claimed the right thing. | **Fixed** — the session resolves its mode from `QTS_MODE` (or an explicit, audited `DemoSessionConfig.mode`), uses it for the policy, the authority and the gate context, and rebuilds the authority when the mode changes. `qts demo verify` now reports the mode first and blocks on it. Covered by `test_a_process_in_any_other_mode_cannot_use_the_demo_order_path` (DEVELOPMENT/PAPER/SHADOW/DEMO_FORWARD/LIVE: 0 broker requests) and `test_demo_session_reports_the_mode_it_is_actually_running_in`. |

Checked and found correct (no change needed):

* **No LIVE order path.** The only production submission routes are `DemoSession.submit()` (29 gate
  checks including `mode_is_demo_execution`, `account_is_demo`, `broker_identity_verified`,
  `authorization_valid`) and the autopilot's close path, both reached only under a broker-capable DEMO
  mode with a valid authorization. `resolve_demo_execution_policy()` refuses mode `LIVE` outright — an
  authorization artifact cannot unlock it — and `DemoExecutionAuthority.current()` re-checks the
  *requesting* process's mode, not only the stored row, so a tampered `enabled=1` row cannot grant
  permission to an observation-mode process.
* **DEMO authorization cannot become LIVE authorization.** The artifact validator refuses
  `account_type != demo`, `live_locked != true`, `LIVE` in `modes_allowed`, non-zero
  `real_capital_exposure_usd`, funds transfer and broker switching; the risk ceiling may only tighten
  the canonical DEMO limits; tampering (hash mismatch), expiry and revocation all fail closed.
* **`NO_TRADE` still holds when nothing is registered.** With an empty (or policy-less) registry the
  gate fails `strategy_registered_frozen` and the autopilot records `NO_TRADE` and halts — asserted by
  `test_entry_without_a_policy_is_refused_by_the_gate` and
  `test_an_entry_without_a_complete_policy_cannot_trade`.

### 16.9 Registered-policy validation (2026-09-24)

`tests/integration/test_demo_research_policy_loop.py` (7 tests, `--run-integration`) drives the
**real registered provider and the real frozen parameters** against the stateful fake terminal:

| Property | Result |
|---|---|
| The registered policy drives a minimum-size order with its protective stop on the order | 1 request, `volume 0.01`, `sl` = reference ∓ 2.00, side by UTC-hour parity, full journal record incl. `hypothesis_id` `H-EXEC-01` |
| `max_orders_per_day` is enforced by the gate (not by the loop) | 2nd order of a 1/day policy refused with `order_frequency_within_policy`; 1 broker request |
| `max_simultaneous_exposure_lots` is a real cap | a second position is refused with `max_total_exposure`; 1 broker request |
| Trading hours are enforced | outside the declared window: 0 orders, 0 requests, loop halts naming `trading_hours` |
| **Code drift** halts the loop | a policy whose `code_hash` no longer matches the provider source: 0 orders, halted `code drift` |
| An entry without a complete policy cannot trade | registry refuses (`NO_TRADE`), loop halts, 0 requests |
| The shipped policy declares what the operator approved | Mon–Fri 08:00–16:00 UTC, 2/day, 5 USD daily loss, 10 USD drawdown, 0.01 lots, stop 2.00, hold 900 s |

Policy-schema validation is covered by `tests/unit/test_demo_research_policy.py` (45 tests): every
mandated field is required (one test per field, none defaulted), unknown kill-condition names are
refused rather than ignored, `validated_edge=true` requires an existing artifact, an `edge_statement`
that does not disclaim an edge is refused, hours/days/timezone are validated, `config_hash` must match
the registered params, and the runtime helpers (symbol authorisation, session window, kill-condition
mapping, code-hash verification) behave as specified.

### 16.10 Lifecycle audit after the first real-terminal run (2026-09-24)

Running the operator procedure against the **real MT5 DEMO terminal on Windows**
exposed defects that no simulated terminal could have shown, because they live in
the seams between configuration, stage, authority and policy. All are fixed here
and regression-tested in `tests/integration/test_demo_lifecycle_audit.py`
(17 tests) — reproduced first, then fixed.

| # | Defect (as observed on the host) | Root cause | Fix |
|---|---|---|---|
| 1 | `preflight` failed `symbol_allowed_by_policy`: broker/canonical symbol was `XAUUSD@`, the policy allows `XAUUSD` | `DemoSession` used `config.symbol` verbatim. The host's `configs/setup.json` stores the **venue alias**, so the session's "canonical" symbol was `XAUUSD@` while the registered policy (and the journal, portfolio and reconciliation) are keyed on `XAUUSD`. Nothing normalised either spelling. | One canonical spelling per instrument: `DemoSession.canonical_symbol` / `.broker_symbol` resolve any spelling through the map (`mt5_adapter.canonical_symbol`), and **every** comparison — policy, journal, gate, reconciliation — reads them. The registry entry also pins the alias it was verified against, and the new gate check `broker_symbol_matches_registry` proves the session's mapping resolves to it. |
| 2 | `execution_permission` failed once the readiness evidence passed 120 s — correctly — but there was **no way to refresh it** | Permission decay and stage progression were conflated: the only path back was `arm --stage 2`, which the state machine refuses (`STAGE_2 → STAGE_2` is not an edge). | Explicit refresh path: `DemoExecutionAuthority.refresh()` (same gates as `enable`, distinct audit action `demo_execution_reverified`), `DemoSession.reverify_authority()`, the `qts demo reverify` command, and `arm --stage N` at the current stage performing a re-verification instead of an illegal transition. `REVERIFY_TTL_S` is untouched. |
| 3 | `stop_loss_present` failed because no SL was supplied | The gate required a stop (correctly) but nothing derived one; the operator had to remember a price that the frozen policy already specifies. | `DemoSession.resolve_order_parameters()` derives the stop from the registered policy (`stop_loss_logic.distance_price`) against the executable side of the quote, rounded **away** from the entry so the derived distance is never smaller than the registered one. An operator-supplied stop is used as given. A required stop that cannot be derived is refused before the broker call (defence in depth in `submit`). |
| 4 | (found by audit, not yet observed) continuous autonomous DEMO trading stops after 120 s | The autopilot never refreshed the authority, and `execution_permission` is a control failure → the loop halts. | `AutopilotConfig.refresh_authority` (enabled only by `qts demo run --confirm --risk-ack`) re-proves readiness when permission has decayed, at most once per cycle, audited per refresh; a failed refresh halts. |
| 5 | (found by audit) the policy document itself was not pinned | `config_hash` covers the parameters and `code_hash` the provider, so a registered policy's limits, hours or kill conditions could be edited with every hash still matching. | `policy_hash` (sha256 of the policy document) is required and verified at load; `scripts/register_demo_research_policy.py` re-seals it. Editing a limit now invalidates the entry until it is re-sealed as a deliberate, preregistered change. |
| 6 | (found by audit) policy kill conditions depended on the caller passing the entry | `submit(entry=None)` skipped `_enforce_policy_kill_conditions`, so a control failure could leave the loop retrying instead of halting. | `submit()` resolves the registered entry itself, exactly as the gate does, before enforcing kill conditions. |
| 7 | (found by audit) `/api/demo/order` read a private `session._entry` stash | The entry was resolved once when the session object was built, not per request. | The endpoint resolves the registry entry per request, so a policy revoked or drifted since the last call cannot still authorise an order. |
| 8 | (test hygiene) `QTS_DEMO_REGISTRY` leaked between test modules via `os.environ` | Registry-dependent results depended on test order — a "shipped registry" assertion was inspecting another module's temporary fixture entry. | An autouse fixture in `tests/conftest.py` saves and restores the DEMO env vars around every test; helpers take `monkeypatch`. |

Additional hardening found while auditing the same surfaces:

* the stop-loss check now validates **tick alignment** (an off-tick stop is
  rejected rather than silently rounded towards the entry) and **policy maximum
  risk** (one order may not risk more than the policy's whole daily budget);
* the identity pin records **symbol provenance** (which canonical/venue pair was
  verified on that account) and the new `symbol_provenance` gate check refuses a
  session whose symbols disagree with it;
* the stop requirement is now taken from the **registered policy**, not only the
  legacy `stop_policy` field.

Re-verified after the fixes: `qts demo reverify --confirm --risk-ack` at Stage 2
restores permission with the stage unchanged; a subsequent `qts demo verify`
reports `READY: True`; a fresh process never inherits stale authority; and no
path in the test suite can reach a real MetaTrader5 module.
