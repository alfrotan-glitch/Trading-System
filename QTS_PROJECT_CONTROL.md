# QTS — Canonical Project Control & Architectural Register

```
Document Version : 1.0.0
Status           : AUTHORITATIVE / CANONICAL SINGLE SOURCE OF TRUTH
Repository       : alfrotan-glitch/Trading-System
Target Symbol    : XAUUSD (Gold / US Dollar Spot)
Target Broker    : MetaTrader 5 (MT5)
```

---

## 1. PRODUCT GOAL

QTS (Quantitative Trading System) is an autonomous quantitative research, risk-governed validation, and forward-execution platform for gold spot trading (`XAUUSD`). Its objective is to discover genuine, reproducible statistical advantages in financial microstructure, validate them against adversarial stress models and execution reality, and execute authorized forward validation trading on MetaTrader 5 without risking unallocated or live capital.

---

## 2. CURRENT PRODUCT STATE

* **Operational Status**: Hardened research and DEMO execution workstation.
* **Trading State**: `NO_TRADE` — zero active trading strategies authorized for real capital.
* **Capital Risk**: `REAL_CAPITAL_EXPOSURE = 0` — live trading is permanently locked.
* **DEMO State**: Diagnostic execution probe (`DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1`, H-EXEC-01, `ELIGIBLE_DIAGNOSTIC`) is registered. It is not a validated edge. Orders still require `QTS_MODE=demo_execution`, a confirmed identity pin, fresh readiness, and `run_pretrade_gate`. Identity is not pinned. No order has been submitted. The MT5 order `comment` is now broker-safe (deterministic `qts` + 13-char hash prefix, ≤16 ASCII chars — the previous 31-char id made `order_send` return `None` with `-2 Invalid comment`; dry-run re-verified with zero submissions). The desktop demo screen is a guided workflow (`/api/demo/guide`): connect → confirm identity → prepare → refresh → trade, in plain language, driving the same pin/stage/authority machinery as the CLI; engineering internals remain under Advanced only. The desktop UI is a product shell for a non-technical user: primary navigation is Home · Market · Trading · Reports; every engineering surface (research, data, evidence, audit, governance, diagnostics) lives under one collapsed Advanced area; the header shows only brand, demo-account connection, overall status, and a quiet "Live locked" note; prices appear only when fresh; opportunities are never invented; all safety machinery (pre-trade gate, identity pin, readiness, kill switch, LIVE lock, `REAL_CAPITAL_EXPOSURE = 0`) is unchanged and enforced by the backend, not the UI.
* **Research State**: `NO_VALIDATED_EDGE` certified after exhaustive evaluation of 139M ticks across 15 preregistered directional hypotheses and 10 impulse strategy families.
* **Product Rebuild Acceptance (2026-09-29, branch `arena/01a0ce9f-trading-system`, HEAD `08feded`)**: One canonical launch path (`scripts/run_qts.bat`, self-bootstrapping) plus documented shim. Two visible modes: Development mode (header chip: "Development mode"; trading section states the practice account is not connected and nothing fakes broker state) and Demo mode (full WM Markets MT5 workflow, unchanged safety chain). Two clean-clone defects found by the mandatory clean-clone acceptance test and fixed: (1) startup health falsely BLOCKED every fresh install when `qts.db` was missing/empty/first-run — a fresh install now passes startup while unreadable stores still fail closed; (2) `ExperimentStore.all_experiments()` ordered by a payload-only column (`trial_count`) and crashed every store with a raw `sqlite3.OperationalError` — ordering now happens in Python, schema untouched. Final verification at HEAD: full suite **1344 passed, 0 failed, 12 skipped** (10 = Chromium browser tests not runnable in this sandbox, 2 = adversarial impulse families with no events across seeds 5..14); jsdom user-journey tour against the clean-clone app **13/13**; launcher startup health `overall=True` on a fresh GitHub clone with zero carried-over state. No order was submitted during this work; `NO_VALIDATED_EDGE` unchanged; no research gate weakened.
* **Execution outcome contract — zero-to-end audit (2026-09-30, branch `arena/01a0f151-trading-system`, commit `ARCH-023`)**: Incident `demo-20260928T140630-884971d1e6` — `MT5 order_send returned None: (-2, 'Invalid "comment" argument')`. The MetaTrader5 client library refused the request structure, so **nothing was transmitted**; the broker never saw an order. QTS classified every `None` as AMBIGUOUS, wrote a durable reconciliation suspension, and then could never resolve it: `reconcile()` compares the in-memory order map against the venue, and a restarted process has an empty map, so the unresolved order was invisible to the only check that could clear it. Three contracts were missing and are now defined in `docs/evidence/execution_outcome_contract.md`: (1) **transmission classification** — `qts.adapters.broker_outcome` decides NOT-TRANSMITTED only for allowlisted client-side refusal codes and treats everything else, including unrecognised codes, as UNKNOWN; the engine classifies by exception type instead of substring-matching the error text; (2) **one broker request construction** — `submit` now calls `build_broker_request`, which validates every field against `validate_broker_request`, so the pre-trade dry run proves the request that will actually be sent (it previously never validated `comment`); (3) **broker-authoritative resolution** — `DemoSession.resolve_unresolved_executions` asks the broker whether an unresolved order executed and accepts only a definite answer: proven-not-executed closes the row REJECTED with the evidence recorded, proven-executed is adopted and the suspension deliberately stays, and an unreadable link resolves nothing. It runs as a predicate inside the ONE canonical recovery transition — no second recovery path. Journal and idempotency ledger are written together so the two outcome stores cannot disagree. Freshness was re-audited and left unchanged: `raw_age 3833.7s > 60s` is a true positive on any clock basis because `true_age = raw_age + offset >= raw_age`. Verification: focused 12 new tests (9 fail before the fix); **full suite 1393 passed, 0 failed, 3 skipped**; ruff clean; static validation 0 failed.
* **Durable suspension recovery lifecycle repair (2026-09-30, branch `arena/01a0f151-trading-system`, commits `98da5dc` + `762fcea` + `1894e5a`)**: Root cause of the Windows report — MT5 connected, `trade_allowed=True`, XAUUSD@ quote FRESH, `run_reconciliation: PASS`, `POST /api/demo/guide/resume` → 200, and the system still `overall=False status=Suspended` with every order 409. TWO durable records can suspend trading (`risk_state.killed` → `kill_switch_functional`; `reconcile_state.suspended` → `reconciliation_ready`) and only the first had a recovery edge: `ExecutionEngine.heal_reconcile()` had **zero production callers**, so the reconciliation row was write-only, and because the registered policy maps `reconciliation_ready` onto the kill conditions `reconciliation_suspension`/`reconciliation_drift`, the next order after a “successful” resume re-raised the kill switch and re-halted the stage — a deterministic self-resurrecting stop (reproduced end to end). Reporting hid it: `run_reconciliation` scanned the last 50 audit events for `DRIFT`/`SUSPENDED` (evidence, not state), so it answered “healthy” once those aged out while the durable row still refused every order; `market_data_stale` in the persisted reason was frozen historical evidence, not an active blocker. Fix: `load_reconcile_suspension()` is the ONE reader of that row (engine, LIVE gate, `/api/health`+`/api/risk`, startup health are thin adapters); `DemoSession.durable_suspension_state()` is the ONE read every surface reports; `DemoSession.resume_from_suspension()` is the ONE recovery transition — each record recovered through its own authority and predicate (fresh broker-authoritative `reconcile()` with `requires_suspend=False`; an explicit operator decision with a recorded reason), all-or-nothing, idempotent, re-read and verified after the write, audited in both directions including refusals. `/api/demo/guide/resume` status is now the outcome (200 recovered / 409 blocked with machine-readable `active_blockers` / 400 invalid) and `qts demo clear-kill` exits 2 clearing nothing when a predicate fails. Two further defects found while unifying: `DemoSession` used its configured `db_path` verbatim while the `RiskEngine` it constructs anchored the same value, splitting the suspension set across two SQLite files outside the state root (and its `mkdir` silently re-anchored `state_root()`); and `live_gate.check_reconciliation_health` read a hard-coded cwd-relative `data/sqlite/qts.db`, returning PASS when that file was absent — a LIVE gate failing OPEN, now regression-pinned. No gate weakened: recovery grants no permission (stage stays HALTED, every pre-trade check still runs), no audit row deleted (the original fault is carried as `previous_reason`), no threshold or risk ceiling touched, LIVE locked, DEMO-only unchanged, and every new test asserts `terminal.requests == []`. See `docs/evidence/canonical_authorities.md` §9. Verification: focused 388 passed; **full suite 1378 passed, 0 failed, 3 skipped** (playwright unavailable + 2 seed-dependent impulse families); ruff clean.
* **First-time-user journey fixes (2026-09-30, branch `arena/01a0ce9f-trading-system`, commit `185b788`)**: A fresh-clone, fresh-state first-time-user journey (README Quickstart verbatim; every CTA clicked through the live UI; DEMO-only confirmations; nothing bypassed or invented) produced three functional defects, each fixed with journey evidence only: (1) Setup save returned a raw 400 for a blank terminal path although the field hint says "Leave blank to auto-detect" — blank now means auto-detect (stored value untouched; fail-closed validation for over-long/non-string paths unchanged); (2) with the kill switch active and no terminal connected, the guide hid the `resume` action behind connection/identity/readiness steps, making the operator stop impossible to clear from the UI — the kill-switch branch now precedes connectivity; clearing still requires confirmation + a reason and grants nothing (stage must be prepared again; every gate applies); (3) Home's "Connect account" was a silent no-op — it now answers with an honest toast. Also: README Quickstart now includes `qts data bootstrap` (first launch otherwise reports `Blocked — verify_data`), and the Setup Step-1 caption no longer claims a restart is required (mode applies live). +3 regression tests. No gate weakened; LIVE lock untouched. Verification: target suites 79 passed; ruff+mypy clean; jsdom end-to-end re-runs of every fixed flow; **full suite 1355 passed, 0 failed, 12 honest skips** (10 Chromium-unavailable + 2 impulse families). Report: `artifacts/QTS_FIRST_TIME_USER_JOURNEY_REPORT.md`.
* **Quote-freshness single-contract fix (2026-09-30, branch `arena/01a0ce9f-trading-system`, commits `f80a592` + `793509f`)**: Root cause of "Market: waiting for a fresh price" + guide stuck at "Almost ready" while startup health/readiness were green on WMMarkets-Demo: two freshness contracts judged the same live quote — the readiness gate proved freshness on the RAW broker stamp against the server clock, while the product quote probes judged the NORMALIZED `event_time`, and the assumed-UTC fallback offset was cached for the whole TTL, so one transient `copy_rates` failure fabricated hours-future event times and starved every quote (and the guide's `quote_fresh` stage-1 prerequisite) until expiry. Fix: one shared contract — `demo_gate.evaluate_tick_epoch_freshness` (the readiness gate's server-clock contract) is now THE answer to "is this broker quote fresh?", reached via `MT5Adapter.raw_tick_freshness`; the fallback offset is never cached (every tick re-measures; a measured offset is still retained, FS-c42bbd contract unchanged); the provider judges fallback-basis ticks on the raw stamp and its own tighter `max_tick_age_s` cap still applies (adversarial-caught hardening); `_quote_probe` reports fresh + raw server-basis age under fallback so pre-trade age caps consume a real fact; startup health's quote note uses the same contract. No gate weakened — stale/corrupt/future stamps still fail closed loudly; LIVE lock, DEMO-only, identity pin, risk limits, reconciliation untouched. Verification: 5 new regression tests (`tests/test_quote_freshness_contract.py`), timestamp/FS-c42bbd contracts, full adversarial tree, all demo-lifecycle integration tests, desktop suite 38, jsdom tour 13/13, ruff+mypy clean; **full suite 1352 passed, 0 failed, 12 skipped** (all pre-existing honest skips).
* **MT5 REAL startup probe fix (2026-09-29, branch `arena/01a0ce9f-trading-system`)**: Root cause of `verify_account_MT5: FAIL MT5 mode 'REAL' was not probed — a mode name is not a connection`: `src/qts/desktop/health.py check_mt5()` only read the `QTS_MT5_MODE` environment label and never probed, so any REAL configuration failed startup even with a running terminal and connected Demo account. Fixed: REAL mode now performs a deterministic probe through the canonical path — `adapter_from_setup()` (machine-local setup: terminal_path + XAUUSD→XAUUSD@ map) → `MT5Adapter.ensure_session()` (establish + verify IPC) → `broker_identity()` → `get_symbol_spec(XAUUSD@)` → `ticks()` — the same sequence Demo execution uses; no new MT5 connection implementation. Pass requires the account to be DEMO (`is_demo is True`; REAL/CONTEST/unknown fail closed); failure details carry the precise reason. MOCK behaviour unchanged; unrecognized modes fail closed with the allowed vocabulary. Regression tests (3 new): REAL + reachable terminal recognized via canonical adapter with XAUUSD→XAUUSD@; missing module or dead IPC fails closed with probe reason; a passing REAL probe unlocks nothing (LIVE stays LOCKED, readiness still requires the real terminal, demo execution un-armed). Startup health on this sandbox (no MT5) honestly reports `MT5 REAL probe failed: RuntimeError: MetaTrader5 package not installed`; on the Windows machine with the WM Markets Demo terminal the probe establishes IPC and reports the connected DEMO account.
* **Autonomous DEMO lifecycle proof attempt (2026-09-29)**: Mission: prove the full loop Real MT5 Demo → XAUUSD@ → real data → decision → risk → Demo order → broker position → management → close → reconciliation → evidence. **Result: the loop is proven in code and simulation, but no real Demo order was submitted — the blocker is the environment, not the product.** This sandbox is Linux; the MetaTrader5 Python package and the MT5 terminal are Windows-only (`pip install MetaTrader5` → "No matching distribution found"). Verified at runtime with `QTS_MODE=demo_execution`: mode resolves to DEMO_EXECUTION (`money_at_risk=false`), readiness honestly reports 2/14 (only local controls pass; all 12 MT5 checks fail with "MetaTrader5 not installed"), LIVE stays `LOCKED`, and an order attempt is refused 409 with nine explicit fail-closed reasons — nothing can bypass the gates. The real-MT5 code path was audited and found free of blockers (entry comment `mt5_comment_for` ≤16 ASCII, close comment sanitized via `mt5_safe_comment_text`, registry params/code hashes verified, provider integrity guards, halt conditions, close lifecycle, reconciliation). Lifecycle proof achieved against the repo's stateful MT5 double: **76/76** demo-lifecycle integration tests pass, plus a labeled simulation rehearsal (`artifacts/demo_lifecycle_rehearsal_SIMULATION.txt`) driving the REAL registered policy `DEMO-EXECPROBE-XAUUSD-V1` (H-EXEC-01, frozen params, params-hash verified) through one full round turn: readiness 14/14 → pin+confirm → authority ENABLED → SELL XAUUSD@ 0.01 with SL 2.00 away, 16-char comment, IOC → position observed → time-box close at 900 s (retcode 10009) → reconciliation drift=NONE → journal CLOSED with exit_reason and realized P&L. Under the shipped session (Mon–Fri 08:00–16:00 UTC) the same loop correctly refused to trade outside hours (0 broker requests). **Remaining blocker:** run on the Windows machine with the MT5 terminal + WM Markets Demo account: `setup_windows.bat` → `run_qts.bat` → Trading-page guide (connect → record identity → confirm → prepare) → `qts demo run --strategy DEMO-EXECPROBE-XAUUSD-V1 --confirm --risk-ack` during the declared session. `NO_VALIDATED_EDGE` unchanged — the probe is a measurement instrument, not a strategy, and its P&L is never edge evidence.

---

## 3. TARGET ARCHITECTURE

QTS follows a strict inward dependency direction:

```
UI / CLI (Presentation Layer)
    ↓
API Routes / Application Services (Orchestration Layer)
    ↓
Governance / Lifecycle Authorities (Policy & Gate Layer)
    ↓
Risk Engine / Pretrade Gates (Safety Enforcement Layer)
    ↓
Execution Engine & Autopilot (Order & Position Lifecycle)
    ↓
Adapters (Broker & Simulation Infrastructure)
    ↓
Domain Core (Entities, Value Objects, Domain Events)
```

### Invariants:
1. **Domain Isolation**: `qts.domain` contains pure dataclasses, value objects, and events. It has zero external dependencies.
2. **Adapter Decoupling**: `qts.adapters` implements connectivity (`MT5Adapter`, `RealisticPaperBroker`, `ShadowBroker`) adhering to `BrokerAdapter` defined in `qts.adapters.base`. Adapters never import from `qts.execution`.
3. **Execution Purity**: `qts.execution` manages order state transitions, idempotency, pretrade validation, and reconciliation.
4. **Safety Monolith**: `qts.risk.engine.RiskEngine` is the sole, authoritative SQLite-persisted risk manager and kill switch.

---

## 4. CANONICAL COMPONENTS

| Component | Canonical Location | Responsibility |
|---|---|---|
| **Broker Abstraction** | `qts.adapters.base.BrokerAdapter` | Interface defining broker interactions, order placement, position queries, and account telemetry. |
| **Simulated Broker** | `qts.adapters.paper_adapter.RealisticPaperBroker` | Sole paper broker simulating realistic MT5 behavior, spreads, slippage, and specs. |
| **Live MT5 Broker** | `qts.adapters.mt5_adapter.MT5Adapter` | IPC connector to the MetaTrader 5 Windows terminal client. |
| **Connection Factory** | `qts.adapters.mt5_factory` | Resilient resolver handling terminal path normalization and venue symbol mapping. |
| **Path Authority** | `qts.config.paths` | Authoritative state root resolver anchoring data, logs, pins, and databases to `~/.qts`. |
| **Risk Authority** | `qts.risk.engine.RiskEngine` | Authoritative SQLite-persisted portfolio risk manager and kill switch. |
| **Pretrade Gate** | `qts.execution.demo_pretrade.run_pretrade_gate` | The only order gate. Every check that runs must be `PASS`. `UNKNOWN` does not pass. The names live in that module, not in a second list. |
| **Order Journal** | `qts.execution.demo_journal.DemoOrderJournal` | Relational SQLite store tracking client order IDs, broker tickets, fills, and realized P&L. |
| **Session Manager** | `qts.execution.demo_session.DemoSession` | Atomic order slot coordinator and lifecycle executor. |
| **Autonomous Loop** | `qts.execution.demo_autopilot.run_autopilot` | Forward evaluation loop managing position exits and periodic reconciliation. |
| **Validation Pipeline** | `qts.validation.pipeline.ValidationPipeline` | Out-of-sample statistical validator (CPCV, DSR, WFE). |
| **Metrics Authority** | `qts.validation.metrics` | Canonical implementations of Sharpe, Sortino, Calmar, Drawdown, and expectancy. |
| **Desktop UI** | `qts.desktop.ui` | Zero-dependency ES2022/CSS workstation built on progressive disclosure. |

---

## 5. CANONICAL DATA FLOWS

```
Market Data Feed (MT5 IPC or Parquet Store)
    │
    ▼
Forward Observatory / Research Pipeline
    │
    ▼
Hypothesis Evaluation & Feature Extraction
    │
    ▼
Statistical Validation (Holm-Bonferroni, DSR, Cost Stress)
    │
    ▼
Committed Evidence Manifest (data/evidence/*.json)
```

---

## 6. CANONICAL EXECUTION FLOW

```
[Signal / Intent]
       │
       ▼
[Pretrade Gate (demo_pretrade.py)] ──(Fail)──► [Order Refused / Stage HALTED]
       │ (Pass 23 checks)
       ▼
[Atomic Order Slot Claim (SQLite BEGIN IMMEDIATE)]
       │
       ▼
[Venue Symbol Mapping (XAUUSD -> XAUUSD@)]
       │
       ▼
[BrokerAdapter.submit(intent)]
       │
       ▼
[DemoOrderJournal.record_order()] ──► [Broker Position Tracked]
       │
       ▼
[Periodic / Post-Close Reconciliation] ──(Drift > 0)──► [Trigger KILL SWITCH]
```

---

## 7. SAFETY INVARIANTS

1. **`REAL_CAPITAL_EXPOSURE = 0`**: Under no circumstances may any order route real capital.
2. **`LIVE = LOCKED`**: Live execution gates fail closed unconditionally until multiple explicit governance criteria are met.
3. **Explicit DEMO Scope**: DEMO execution requires an un-revoked, cryptographic authorization artifact, fresh readiness pass (<60s TTL), and manual confirmation.
4. **Identity Pinning**: Discrepancies between pinned broker identity and active terminal session immediately halt execution.
5. **Durable Kill Switch**: Kill switch activation persists across process restarts via SQLite transactions.

---

## 8. RESEARCH INVARIANTS

1. **No Fabricated Alpha**: Strategies are never invented to force trading activity.
2. **Deterministic Costs**: Backtests and evaluation pipelines must enforce realistic transaction costs ($0.15–$0.25 spread + $0.02 slippage).
3. **Multi-Testing Correction**: Multiple hypothesis tests must apply Holm-Bonferroni adjustments.
4. **Zero Future Information**: Time-series splits must remain strictly sequential. Held-out partitions are never touched during discovery.

---

## 9. UX PRINCIPLES

1. **Five-Question Instant Clarity**: Every user must immediately understand upon opening the dashboard:
   - Is QTS running?
   - What is the market doing?
   - Is there a validated opportunity?
   - Can QTS trade?
   - What should I do next?
2. **Progressive Disclosure**: Plain-English human explanations on primary views; engineering telemetry, SHA hashes, and raw logs contained in drawers and Advanced tabs.
3. **Truth in Display**: Missing data is explicitly displayed as `UNAVAILABLE` or ` — `. Never fabricate zeroes or default metrics.

---

## 10. ROADMAP & PHASES

* [x] **Phase 0: Baseline Verification**
* [x] **Phase 1: Adapter boundary** — `BrokerAdapter` lives in `qts.adapters.base`. One paper broker: `RealisticPaperBroker`.
* [x] **Phase 2: Safety authority** — `RiskEngine` is the only kill switch. Canonical metrics live in `qts.validation.metrics`.
* [x] **Phase 3: CLI and API packages** — `qts.cli` and `qts.api.routes`.
* [x] **Phase 4: Dead prototypes removed** — `invented_strategies.py` and `discovery_pipeline.py` deleted. `agent.py` and `memory.py` stay because the research loop and campaign engine call them.
* [x] **Phase 5: One research invocation** — `qts research run-hypothesis <id>`. Hypothesis modules stay separate.
* [x] **Phase 6: Tests** — research tests live in `tests/research/`. Python UI tests live in `tests/ui/`. Shared fixtures stay at `tests/` because other suites import them by that path.
* [x] **Phase 7: Documentation** — `docs/01` through `docs/10` are the operating guides. Cited records stay beside them. Uncited dated records are in `docs/evidence/`.
* [x] **Phase 8: This file is the project-control register.**
* [x] **Phase 9: Product navigation** — Home, Market, Trading, Reports. One quiet, collapsed Advanced area holds all twenty engineering pages (research, data, trading tools, risk, evidence & audit, governance, system). Legacy product URLs redirect into this IA.
* [x] **Phase 10: Full regression verification** — see Test Status. The 2026-09-25 audit restored `tests/integration` to the default suite.
* [x] **Phase 11: Final product audit** — Home answers in plain language; second submit helper removed; matching shim removed; unused dependencies removed.
* [ ] **Phase 12: Windows MT5 identity pin** — operator action, not a repository change. Do not run `qts demo connectivity --pin` from this workspace.

---

## 11. FORBIDDEN DUPLICATIONS

1. **Paper Brokers**: Only `qts.adapters.paper_adapter.RealisticPaperBroker` is permitted. No in-file stub adapters.
2. **Kill Switches**: Only `qts.risk.engine.RiskEngine` maintains kill switch state. No in-memory secondary flags. The durable reconciliation suspension (`reconcile_state.suspended`, owned by `qts.execution.engine.ExecutionEngine`) is a distinct condition, not a second kill switch; it is read ONLY through `qts.execution.engine.load_reconcile_suspension` and recovered ONLY through `qts.execution.demo_session.DemoSession.resume_from_suspension`. No component may add a third suspension record, a second reader, or a parallel recovery path.
3. **Path Resolution**: Only `qts.config.paths` resolves machine-local state paths. No hardcoded string paths.
4. **Order State Stores**: Only `qts.execution.demo_journal.DemoOrderJournal` persists execution history.
5. **Single current version**: This working tree is one unreleased product version. Git history stores previous versions. Do not add `v2`, `new`, `old`, `legacy`, `final`, `backup`, `copy`, or `archive` copies of an existing file. Update the canonical file. A new file is allowed only for a genuinely new responsibility. Dead files and dead code are deleted, not archived. Duplicate responsibility is consolidated. Every future change must preserve this hygiene. `QTS_PROJECT_CONTROL.md` remains the only project-control document.

---

## 12. CHANGE REGISTER

| ID | Date | Phase | Change Description | Impact | Test Evidence | Decision |
|---|---|---|---|---|---|---|
| **ARCH-001** | 2026-09-25 | Phase 0 | Initialized canonical project control document | Establishes single source of truth | All tests baseline green | APPROVED |
| **ARCH-002** | 2026-09-25 | Phase 1 | Extracted BrokerAdapter to adapters.base; eliminated PaperBrokerAdapter | Inverts dependency; establishes single RealisticPaperBroker | Full suite green | APPROVED |
| **ARCH-003** | 2026-09-25 | Phase 2 | RiskEngine is the only kill switch | EmergencyControls cannot arm an independent halt | adversarial emergency test | APPROVED |
| **ARCH-004** | 2026-09-25 | Phase 2 | DemoOrderJournal is the DEMO evidence record; OrderManager is the engine working set; broker positions are venue truth | Stops a second evidence store | demo session wiring | APPROVED |
| **ARCH-005** | 2026-09-25 | Phase 3 | CLI package and API routers | Composition stays in cli.main and api.server | demo API and CLI tests | APPROVED |
| **ARCH-006** | 2026-09-25 | Phase 4 | Deleted unreferenced invented_strategies and discovery_pipeline | Dead prototypes are not product code | import search | APPROVED |
| **ARCH-007** | 2026-09-25 | Phase 5 | qts research run-hypothesis is the only new invocation path | Does not merge hypotheses or change NO_VALIDATED_EDGE | catalog unit test | APPROVED |
| **ARCH-008** | 2026-09-25 | Phase 9 | Product navigation with Advanced disclosure | Home answers the five operator questions | shell IA test updated | APPROVED |
| **ARCH-009** | 2026-09-25 | Phase 11 | Restored `tests/integration` to the default suite. The skip matched the directory name, not an explicit marker. | No integration file was dropped. Parent `6f0c0fd` collected 1,324. This tree collects 1,320: plus `tests/unit/test_research_catalog.py` (3), minus `tests/unit/test_direct_broker_submit_guard.py` (7) deleted with its helper. | collection comparison | APPROVED |
| **ARCH-010** | 2026-09-25 | Phase 11 | Deleted `submit_with_order_check`. Deleted the matching re-export shim. Restored the zip-inventory script the workflow calls. Removed unused `pydantic-settings` and `python-dateutil`. | One submit path: `DemoSession`. One matching engine: `qts.adapters.matching`. | direct-submit search; ruff | APPROVED |
| **ARCH-011** | 2026-09-25 | Phase 11 | Home and trading copy no longer lead with telemetry codes or a fake broker name. | Safety facts stay visible. Codes stay under details. | UI tests | APPROVED |
| **ARCH-012** | 2026-09-25 | Phase 11 | Risk card no longer invents `$500` or a 22-check count. A research file pass is not labeled ready for demo. Live docs no longer describe a multi-signature unlock that is not in the code. | Missing limits stay unreported. Live stays locked. | UI source tests | APPROVED |
| **ARCH-013** | 2026-09-25 | Phase 11 | Governance screen no longer claims it recorded a live request. `/api/risk` clear state says `RISK CLEAR — NOT AN ORDER`. | A button cannot invent an audit record. | `test_risk_veto_visibility`, UI shell | APPROVED |
| **ARCH-014** | 2026-09-25 | Phase 11 | Header **Stop trading** calls `POST /api/demo/kill` and does not claim success if the request fails. Data-quality copy no longer invents a 12-check count. Troubleshooting uses the 60s freshness limit. | The documented emergency control exists. A failed stop stays visible. | UI source test | APPROVED |
| **ARCH-015** | 2026-09-25 | Phase 11 | Home and Trading read the durable kill switch from `/api/health` and `/api/risk`. A limit flag is no longer labeled armed. The journal path in the demo guide matches `journal_db`. | A stop stays visible after it is raised. | operations test | APPROVED |
| **ARCH-016** | 2026-09-25 | Phase 11 | Product pages lead with plain sentences: what is connected, whether an order is allowed, and that live trading cannot be opened here. | A clearer label does not hide Demo vs Live, the kill switch, or a missing reading. | UI shell tour | APPROVED |
| **ARCH-017** | 2026-09-25 | Phase 11 | Mypy errors in the research runners were annotation and name-shadow fixes. The duplicate `build/qts.spec` was removed. The single-current-version rule is now section 11. | Formulas and gates were not loosened. Live stays locked. | `mypy src`, full pytest | APPROVED |
| **ARCH-018** | 2026-09-28 | Phase 11 | Fixed the real MT5 integration bug: `order_send` returned `None` with `(-2, 'Invalid "comment" argument')` because a 31-char `client_order_id` was sent as the comment. The comment is now a deterministic `qts` + 13-char sha256 prefix (≤16 ASCII chars); `order_check` validates the exact send-time comment. | No gate, risk limit, authorization or LIVE lock changed. Dry-run against an exploding `order_send` shows zero submissions. | `test_mt5_comment_contract` (8), full suite green | APPROVED |
| **ARCH-019** | 2026-09-28 | Phase 11 | Guided DEMO product workflow: `GET /api/demo/guide` (read-only plain-language state) and `record-identity` / `confirm-identity` / `prepare` / `refresh` / `resume` drive the SAME pin/stage/authority machinery as the CLI. The demo screen leads with one headline, one reason, one next action, an order ticket (stop required), and human error mapping; internals stay under Advanced. | Fail-closed, honest, no bypass. Refusals are 409 with a human result. | `test_demo_guide_api` (14), full suite green, live uvicorn verification | APPROVED |
| **ARCH-020** | 2026-09-30 | Phase 11 | Durable suspension recovery is ONE canonical transition. `reconcile_state.suspended` had no recovery edge reachable from any surface (`heal_reconcile` had zero production callers), so a cleared kill switch was re-raised by the policy kill condition `reconciliation_suspension` on the next order: a self-resurrecting stop. `DemoSession.resume_from_suspension` now recovers the COMPLETE durable set through each record's own authority and predicate — all-or-nothing, idempotent, verified after the write, audited in both directions. `/api/demo/guide/resume` and `qts demo clear-kill` both run it; the HTTP status is the outcome (200 recovered / 409 blocked / 400 invalid). | No gate weakened. Recovery grants no permission: stage stays HALTED, every pre-trade check still runs. Historical evidence preserved (no audit row deleted, original reason carried as `previous_reason`). LIVE locked, DEMO-only unchanged. | `test_suspension_recovery_lifecycle` (14), guide-API resume semantics (4), CLI recovery/refusal (2); full suite 1375 passed | APPROVED |
| **ARCH-021** | 2026-09-30 | Phase 11 | One durable store per session, and one reader for `reconcile_state`. `DemoSession` used its configured `db_path` verbatim while the `RiskEngine` it constructs anchored the same value through `qts.config.paths`, splitting the two halves of the suspension set across two SQLite files outside the state root (and its `mkdir` silently re-anchored `state_root()`). `live_gate.check_reconciliation_health` read a hard-coded cwd-relative `data/sqlite/qts.db` and returned PASS when that file was absent — a LIVE gate failing OPEN. `_reconciliation_status`, `check_reconciliation_health` and the engine are now adapters over `load_reconcile_suspension`, all anchored via `artifact_path("db")`. | Fail-closed strengthened; a read probe no longer creates the store. Section 11.3 (path resolution) is now actually enforced for the durable suspension set. | `test_system_hardening_and_invariants` (2 new, fail before the fix), `test_restart_state_recovery` live-gate anchoring regression; full suite 1378 passed | APPROVED |
| **ARCH-022** | 2026-09-30 | Phase 11 | Startup health probes read their own durable authority, never an audit keyword scan. `restore_pending_orders` scanned the last 20 audit events for the substring `"AMBIGUOUS"`: an order with a genuinely unknown outcome stopped being reported once 20 newer events existed (fail OPEN), a resolved order kept blocking startup until it aged out, and the payload-text match also tripped on a reconciliation report carrying `drift="AMBIGUOUS"` — a different condition. It now reads `demo_order_journal` (Section 11.4, the only store of execution history) for `AMBIGUOUS` rows and for submissions still in flight with no recorded outcome, and names the blocking order. | Fail-closed strengthened on unknown order state; no new store, no new state machine. | `test_suspension_recovery_lifecycle` (3 new, all fail before the fix in both directions); full suite 1381 passed | APPROVED |
| **ARCH-023** | 2026-09-30 | Phase 11 | Execution outcome contract. `order_send` returning `None` was unconditionally classified AMBIGUOUS, so `(-2, 'Invalid "comment" argument')` — a request the client library refused to marshal and never transmitted — durably suspended trading, and nothing could resolve it because `reconcile()` only compares the in-memory order map with the venue (empty after a restart). Added `qts.adapters.broker_outcome` (transmission classification; UNKNOWN unless non-transmission is proven), `validate_broker_request` (one contract, enforced inside the single canonical request builder, which `submit` now uses instead of its own duplicate construction), and `DemoSession.resolve_unresolved_executions` (broker-authoritative resolution, run as a predicate inside the ONE canonical recovery transition). `history_deals` grew a strict mode so a failed lookup can no longer masquerade as proof that nothing executed. The engine classifies by exception type instead of substring-matching the error text. | Fail-closed strengthened: unrecognised error codes are UNKNOWN; resolution requires positive broker evidence; adoption never re-sends. No threshold, risk limit, authorization or live lock touched. | `test_execution_outcome_contract` (12 new, 9 fail before the fix); full suite 1393 passed | APPROVED |
| **ARCH-024** | 2026-09-30 | Phase 11 | Refusal explanation authority. The pre-trade gate names 28 predicates with details, but `SubmissionResult` flattened them to `reasons[]` and the browser re-derived a sentence from an 11-entry JavaScript dictionary (4 of whose keys match no predicate the gate emits), keyed on `reasons[0].split(':')`. Coverage was 7/28; everything else — including `policy_execution_assumptions`, `kill_switch_functional` and `max_daily_loss` — rendered as a generic 'a safety check refused the order' line, and 5 of the 6 refusal paths in `submit()` produced no predicate id at all. New `qts.execution.demo_refusal` owns the plain sentence + retry condition for every predicate; `SubmissionResult.as_dict()` is the single chokepoint that attaches it; non-gate refusals carry `blocked_by` in the same vocabulary; the UI renders the server's object. | No gate, threshold, limit or status code changed — 409 still refuses. Unidentifiable refusals are reported as unidentifiable, never invented. | `test_demo_refusal_explanations` (17 new, 5 end-to-end fail before the fix); completeness test pins 28/28 explained; full suite 1410 passed | APPROVED |
| **ARCH-025** | 2026-09-30 | Phase 11 | Canonical predicate registry, enforced at runtime. The completeness test added with ARCH-024 scanned the source for `record("literal")` and passed at 28/28 — while five predicates emitted as `record(*_helper(...))` (`symbol_mapping_canonical`, `order_size_within_hard_max`, `stop_loss_present`, `stop_within_policy_distance`, `max_total_exposure`) had no explanation at all and were invisible to it. `record()` now rejects any name absent from `REFUSAL_EXPLANATIONS`, so an unexplained predicate cannot be emitted at all; the completeness test resolves helper-returned names through the AST instead of a literal list. | Registry is the single source for gate, refusal, UI and tests. 33 predicates covered. No gate logic, threshold or verdict changed. | `test_the_gate_refuses_to_emit_an_unregistered_predicate`; dynamic completeness test; both fail before the fix | APPROVED |
| **ARCH-026** | 2026-09-30 | Phase 11 | Position-close authorization and lifecycle. `POST /api/demo/close` trusted two payload booleans and had no authorization boundary; `DemoSession.close_position` swallowed broker-state errors into an empty position list and closed anyway, never checked ticket ownership, passed the close volume through unvalidated, matched the journal on symbol+side (attaching a close to an unrelated order), marked a partially closed row `CLOSED`, and reported the pre-close unrealized `profit` as realized P&L. Close now answers to the same canonical gate as the order path via `CLOSE_AUTHORITY_PREDICATES` (identity/account/mode/instrument authority; entry-quality predicates deliberately excluded so a risk-reducing close is never trapped), validates ticket ownership and volume against broker min/step/remainder, keeps partial closes `OPEN` with remaining exposure recorded, and takes realized P&L from deal history with an explicit `realized_pnl_source` label. | One authority, reused — no second gate or state machine. Broker errors are refusals with named predicates, never fake success and never a 500. Four new refusal ids registered. | `test_hardening_close_and_boundaries` (21 tests; 19 fail before the fix) | APPROVED |
| **ARCH-027** | 2026-09-30 | Phase 11 | Live-safety, CORS, paths, CI. (a) `CURRENT_EDGE_STATUS` was read by the risk API and the UI but by no live check — `live_readiness_report()` could reach `ready: true` with `NO_VALIDATED_EDGE`; `check_validated_edge()` is now a hard gate entry (`proof_tier: research`). (b) `QTS_CORS_WILDCARD=1` set `allow_origins=["*"]` on an API that places and closes orders; the escape hatch is removed for an explicit `QTS_CORS_ORIGINS` allowlist that rejects `*`. (c) `edge.py`/`ops.py` wrote evidence and opened SQLite databases relative to the process cwd; all nine sites now resolve through `artifact_path()` with new registered keys. (d) `.github/workflows` held 16 research jobs triggered only by pushes to `arena/01a0cdf1-trading-system`, each holding `contents: write` with `persist-credentials: true` and ending in `git push origin HEAD:<that branch>` — so nothing linted or tested this branch or any PR, and a manual dispatch would have pushed this branch's HEAD into another session's branch. Replaced by one least-privilege `ci.yml` (`contents: read`) running lint + static validation + the full suite against pinned `constraints.txt`. (e) Startup health printed `MT5 REAL connected ... account=DEMO`, where "REAL" meant the MT5 library rather than real money; the status line now reads `MT5 terminal attached (live IPC link, DEMO account — no real money)`. | Historical research evidence and outputs untouched; only the automation that could never run here was removed (recoverable from git history and still present on its own branch). No threshold, limit or gate relaxed. | 11 further tests in `test_hardening_close_and_boundaries`; repository-wide workflow invariant test replaces the single-file pin; full suite 1432 passed / 0 failed / 3 skipped | APPROVED |
| **ARCH-028** | 2026-09-30 | Phase 11 | Database path anchoring. Roughly twenty modules default to `db_path="data/sqlite/qts.db"` (audit log, idempotency store, experiment/campaign/registry/memory research stores, promotion, demo authority, desktop state restore, regime and forward observatories). `qts.db.connect()` passed the value straight to `sqlite3`, which resolves it against the process working directory — so the same `SqliteAuditLog()` opened a different file depending on where the CLI, the API or a test was launched from, silently splitting audit, kill-switch and journal state across several databases. `connect()` and `immediate()` now anchor relative paths through `resolve_state_path()`. One chokepoint rather than twenty rewritten defaults; `state_root()` remains the single authority, including its isolated-workspace rule, so a test that chdirs into its own fixture tree still gets that tree. `:memory:`, `file:` URIs and absolute paths pass through untouched. | No schema, no migration, no new abstraction. Full suite re-run because this touches every database in the system. | `test_every_database_resolves_to_one_location_whatever_the_cwd`, `test_anchoring_leaves_memory_and_absolute_paths_alone` (both fail before the fix); full suite 1432 passed / 0 failed / 3 skipped | APPROVED |

---

## 13. TEST STATUS

* **Python default suite** (`pytest`): exit 0 on 2026-09-28. Collection is 1,353: **1,341 passed** plus 12 honest skips — 2 in `tests/adversarial/test_impulse_lookahead.py` (fixed seed window produces no events for family `IMP-VE-V`) and 10 in `tests/ui/test_browser.py` where `playwright` is installed but no Chromium binary exists in this sandbox (CDN blocked); on a machine with Chromium those 10 run. Without `playwright` installed the same suite collects 1,344 with 3 skips (the browser module skips once at import).
* **Python integration suite** (`pytest tests/integration --run-integration`): 119 passed. The same 119 are also in the default collection. The directory-name skip is gone.
* **JavaScript UI tests** (`npm test`): 48 passed. `node --check` passed for the desktop UI scripts. The UI shell tour is inside `tests/ui/test_ui_logic.py` and passed with the default suite.
* **Linters**: `ruff check src tests` clean. `mypy src` clean: 0 errors in 166 source files. No formula was changed to satisfy the type checker.

---

## 14. KNOWN LIMITATIONS

1. **MetaTrader 5 Host Requirement**: The official `MetaTrader5` Python package requires Windows. In Linux environments, mock/simulated adapters provide full fidelity.
2. **Absence of Directional Edge**: Historical research falsified all directional trading hypotheses at realistic transaction costs (`NO_VALIDATED_EDGE`).

---

## 15. DEFINITION OF DONE

1. All tests in `tests/` pass without regression.
2. Zero dead code or unreferenced modules.
3. Adapters completely decoupled from execution engine.
4. Monolithic CLI and API files decomposed into cohesive packages.
5. Desktop UI presents clear, human-intelligible product views with progressive disclosure.

---

## 16. DESKTOP CLONE

Reviewed 2026-09-25. A plain `git clone` checks out `main`. `main` is the initial commit and is not this desktop build. The desktop clone is:

```bat
git clone --branch arena/01a0ce9f-trading-system https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System
scripts\setup_windows.bat
scripts\run_qts.bat
```

Launch is `scripts\run_qts.bat`. It must print `UI source: src\qts\desktop\ui` and open `http://127.0.0.1:8000/`. There is no port 8901. `python -m qts.api.server` is not a launch command. Live trading stays locked. The bootstrap dataset is synthetic and is not a quote.

Python 3.14 is accepted. The batch version check must not contain a percent sign, because `cmd.exe` consumes it and the check becomes a SyntaxError. Python 3.15 is refused.

---

## 17. REVIEW, 2026-09-28

Reviewed on `0b7ab14` and the fixes in the following commit. Not a visual acceptance. Not a claim that the suite passed on Python 3.14.7.

Fixed:

* `/api/paper` no longer reports a missing `pnl` or `drawdown` as zero. The committed paper file has `final_equity` and no `pnl`. That figure stays a historical paper result, not current money.
* A demo close toast no longer fills a missing result with `0.00` or a missing reconciliation with `CLEAN`.
* `/api/health` no longer labels a structural live-gate pass as `ELIGIBLE`. `live_status` stays `LOCKED` or `BLOCKED`. `live_gate_ready` records the structural result without calling it permission.
* `/api/live/status` no longer says explicit confirmation is the next step when structural checks pass.
* `scripts\launch_desktop.bat` calls `scripts\run_qts.bat`. It does not start a second server and does not override `QTS_ENV`.
* The uninstalled `docs/ci/ci.yml` is removed. It was not in `.github/workflows`, and its `on: push` line was not a running workflow.
* A failed setup test still exits 1. The message now says the desk can be opened, and that a failed test is not a completed setup.

Not accepted: the rendered product still has not been inspected in a browser. `NO_VALIDATED_EDGE` stands. Live trading stays locked. Real exposure stays `$0`.

---

## 18. REVIEW, 2026-09-28 (guided DEMO workflow + MT5 comment fix)

Reviewed on `cd5a774` plus the polish commit that follows it.

Fixed:

* The real MT5 integration bug: `order_send` returned `None` with `(-2, 'Invalid "comment" argument')` because the 31-char `client_order_id` was sent as the comment. The comment is now deterministic `qts` + 13-char sha256 prefix (≤16 ASCII chars); `order_check` validates the exact send-time comment. Dry-run against an exploding `order_send`: zero submissions. No gate, risk limit, authorization, stage permission or LIVE lock was touched.
* The demo screen is now a guided workflow for a non-engineer: one status headline, one plain reason, one next action (Check connection / Record identity / Confirm identity / Prepare / Refresh / Resume), and an order ticket (Buy/Sell, broker-spec size, required stop loss, preview, place) that only appears when trading is actually possible. Every action drives the same pin/stage/authority machinery as the CLI; refusals are 409 with a human result; order failures map to one plain sentence with raw reasons under collapsible Technical details. Internal lifecycle names do not appear above the `technical` key (asserted by test).

Verified: full suite 1,341 passed / honest skips; ruff clean; mypy clean (166 files); live uvicorn app served the guided UI, answered `GET /api/demo/guide` honestly without a terminal (fail closed, single reason), refused unconfirmed mutations (400) and kept every pre-trade gate on `POST /api/demo/order` (409 with full reasons). The jsdom shell tour renders the demo view through the real modules and passed.

Not accepted: no real browser exists in this sandbox (Playwright CDN and Debian mirrors are blocked), so a rendered-pixel inspection is still outstanding; the Playwright suite runs it automatically wherever Chromium is available. `NO_VALIDATED_EDGE` stands. Live trading stays locked. Real exposure stays `$0`. No order was submitted to any broker.
