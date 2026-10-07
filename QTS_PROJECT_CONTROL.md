# QTS — Canonical Project Control & Architectural Register

```
Document Version : 1.0.0
Status           : AUTHORITATIVE / CANONICAL SINGLE SOURCE OF TRUTH
Repository       : alfrotan-glitch/Trading-System
Target Symbol    : XAUUSD (Gold / US Dollar Spot)
Target Broker    : MetaTrader 5 (MT5)
```
| **ARCH-050** | 2026-10-07 | Canonical execution safety | Closed the micro execution-path database exception: broker-capable `qts run --mode micro` now consumes the same durable risk/idempotency/reconciliation database and the one snapshot-to-engine risk translation. It refuses before broker construction when the canonical kill switch or durable reconciliation suspension is active. | APPROVED — merged to `main`; latest-head CI remains a separate verification record |


---

## 1. PRODUCT GOAL

QTS (Quantitative Trading System) is an autonomous quantitative research, risk-governed validation, and forward-execution platform for gold spot trading (`XAUUSD`). Its objective is to discover genuine, reproducible statistical advantages in financial microstructure, validate them against adversarial stress models and execution reality, and execute authorized forward validation trading on MetaTrader 5 without risking unallocated or live capital.

---

## 1A. STANDARDIZATION BASELINE (2026-10-06)

The repository is being treated as one product, not as a collection of historical experiments.

- Canonical branch: `main`.
- Runtime authority remains singular: domain → governance/gates → risk → execution → broker adapter.
- Proven-unused runtime abstractions removed: legacy `risk.capital_policy`, unused `qts.security` secrets layer, and the unused external-provider catalog embedded in the runtime provider.
- Sixteen obsolete XAUUSD research workflows that targeted historical branches were removed. Research scripts remain available; research execution is no longer mixed into the product's CI control plane.
- One canonical GitHub CI workflow now owns quality checks.
- Local verification is tiered: `pytest` is the fast developer suite; `pytest --run-integration --run-research` is the full verification suite.
- No strategy has been promoted by this cleanup. `NO_VALIDATED_EDGE` remains authoritative.
- Deletion is evidence-driven: a module is removed only when it is unused or superseded; useful research, safety, and execution components are retained even if they are not on the hot path.

This is a standardization pass, not a cosmetic file-count target. The objective is a smaller, clearer system without weakening execution safety or research integrity.

## 2. CURRENT PRODUCT STATE

* **Operational Status**: Hardened research and DEMO execution workstation.
* **Trading State**: `NO_TRADE` — zero active trading strategies authorized for real capital.
* **Capital Risk**: `REAL_CAPITAL_EXPOSURE = 0` — live trading is permanently locked.
* **DEMO State**: Diagnostic execution probe (`DEMOPOL-EXEC-COST-XAUUSD-2026-09-24-V1`, H-EXEC-01, `ELIGIBLE_DIAGNOSTIC`) is registered. It is not a validated edge. Orders still require `QTS_MODE=demo_execution`, a confirmed identity pin, fresh readiness, and `run_pretrade_gate`. Identity is not pinned. No order has been submitted. The MT5 order `comment` is now broker-safe (deterministic `qts` + 13-char hash prefix, ≤16 ASCII chars — the previous 31-char id made `order_send` return `None` with `-2 Invalid comment`; dry-run re-verified with zero submissions). The desktop demo screen is a guided workflow (`/api/demo/guide`): connect → confirm identity → prepare → refresh → trade, in plain language, driving the same pin/stage/authority machinery as the CLI; engineering internals remain under Advanced only. The desktop UI is a product shell for a non-technical user: primary navigation is Home · Market · Trading · Reports; every engineering surface (research, data, evidence, audit, governance, diagnostics) lives under one collapsed Advanced area; the header shows only brand, demo-account connection, overall status, and a quiet "Live locked" note; prices appear only when fresh; opportunities are never invented; all safety machinery (pre-trade gate, identity pin, readiness, kill switch, LIVE lock, `REAL_CAPITAL_EXPOSURE = 0`) is unchanged and enforced by the backend, not the UI.
* **Research State**: `NO_VALIDATED_EDGE` certified after exhaustive evaluation of 139M ticks across 15 preregistered directional hypotheses and 10 impulse strategy families.
* **Product Rebuild Acceptance (2026-09-29, canonical `main` history, HEAD `08feded`)**: One canonical launch path (`scripts/run_qts.bat`, self-bootstrapping) plus documented shim. Two visible modes: Development mode (header chip: "Development mode"; trading section states the practice account is not connected and nothing fakes broker state) and Demo mode (full WM Markets MT5 workflow, unchanged safety chain). Two clean-clone defects found by the mandatory clean-clone acceptance test and fixed: (1) startup health falsely BLOCKED every fresh install when `qts.db` was missing/empty/first-run — a fresh install now passes startup while unreadable stores still fail closed; (2) `ExperimentStore.all_experiments()` ordered by a payload-only column (`trial_count`) and crashed every store with a raw `sqlite3.OperationalError` — ordering now happens in Python, schema untouched. Final verification at HEAD: full suite **1344 passed, 0 failed, 12 skipped** (10 = Chromium browser tests not runnable in this sandbox, 2 = adversarial impulse families with no events across seeds 5..14); jsdom user-journey tour against the clean-clone app **13/13**; launcher startup health `overall=True` on a fresh GitHub clone with zero carried-over state. No order was submitted during this work; `NO_VALIDATED_EDGE` unchanged; no research gate weakened.
* **First-time-user journey fixes (2026-09-30, canonical `main` history, commit `185b788`)**: A fresh-clone, fresh-state first-time-user journey (README Quickstart verbatim; every CTA clicked through the live UI; DEMO-only confirmations; nothing bypassed or invented) produced three functional defects, each fixed with journey evidence only: (1) Setup save returned a raw 400 for a blank terminal path although the field hint says "Leave blank to auto-detect" — blank now means auto-detect (stored value untouched; fail-closed validation for over-long/non-string paths unchanged); (2) with the kill switch active and no terminal connected, the guide hid the `resume` action behind connection/identity/readiness steps, making the operator stop impossible to clear from the UI — the kill-switch branch now precedes connectivity; clearing still requires confirmation + a reason and grants nothing (stage must be prepared again; every gate applies); (3) Home's "Connect account" was a silent no-op — it now answers with an honest toast. Also: README Quickstart now includes `qts data bootstrap` (first launch otherwise reports `Blocked — verify_data`), and the Setup Step-1 caption no longer claims a restart is required (mode applies live). +3 regression tests. No gate weakened; LIVE lock untouched. Verification: target suites 79 passed; ruff+mypy clean; jsdom end-to-end re-runs of every fixed flow; **full suite 1355 passed, 0 failed, 12 honest skips** (10 Chromium-unavailable + 2 impulse families). Report: `artifacts/QTS_FIRST_TIME_USER_JOURNEY_REPORT.md`.
* **Quote-freshness single-contract fix (2026-09-30, canonical `main` history, commits `f80a592` + `793509f`)**: Root cause of "Market: waiting for a fresh price" + guide stuck at "Almost ready" while startup health/readiness were green on WMMarkets-Demo: two freshness contracts judged the same live quote — the readiness gate proved freshness on the RAW broker stamp against the server clock, while the product quote probes judged the NORMALIZED `event_time`, and the assumed-UTC fallback offset was cached for the whole TTL, so one transient `copy_rates` failure fabricated hours-future event times and starved every quote (and the guide's `quote_fresh` stage-1 prerequisite) until expiry. Fix: one shared contract — `demo_gate.evaluate_tick_epoch_freshness` (the readiness gate's server-clock contract) is now THE answer to "is this broker quote fresh?", reached via `MT5Adapter.raw_tick_freshness`; the fallback offset is never cached (every tick re-measures; a measured offset is still retained, FS-c42bbd contract unchanged); the provider judges fallback-basis ticks on the raw stamp and its own tighter `max_tick_age_s` cap still applies (adversarial-caught hardening); `_quote_probe` reports fresh + raw server-basis age under fallback so pre-trade age caps consume a real fact; startup health's quote note uses the same contract. No gate weakened — stale/corrupt/future stamps still fail closed loudly; LIVE lock, DEMO-only, identity pin, risk limits, reconciliation untouched. Verification: 5 new regression tests (`tests/test_quote_freshness_contract.py`), timestamp/FS-c42bbd contracts, full adversarial tree, all demo-lifecycle integration tests, desktop suite 38, jsdom tour 13/13, ruff+mypy clean; **full suite 1352 passed, 0 failed, 12 skipped** (all pre-existing honest skips).
* **MT5 REAL startup probe fix (2026-09-29, canonical `main` history)**: Root cause of `verify_account_MT5: FAIL MT5 mode 'REAL' was not probed — a mode name is not a connection`: `src/qts/desktop/health.py check_mt5()` only read the `QTS_MT5_MODE` environment label and never probed, so any REAL configuration failed startup even with a running terminal and connected Demo account. Fixed: REAL mode now performs a deterministic probe through the canonical path — `adapter_from_setup()` (machine-local setup: terminal_path + XAUUSD→XAUUSD@ map) → `MT5Adapter.ensure_session()` (establish + verify IPC) → `broker_identity()` → `get_symbol_spec(XAUUSD@)` → `ticks()` — the same sequence Demo execution uses; no new MT5 connection implementation. Pass requires the account to be DEMO (`is_demo is True`; REAL/CONTEST/unknown fail closed); failure details carry the precise reason. MOCK behaviour unchanged; unrecognized modes fail closed with the allowed vocabulary. Regression tests (3 new): REAL + reachable terminal recognized via canonical adapter with XAUUSD→XAUUSD@; missing module or dead IPC fails closed with probe reason; a passing REAL probe unlocks nothing (LIVE stays LOCKED, readiness still requires the real terminal, demo execution un-armed). Startup health on this sandbox (no MT5) honestly reports `MT5 REAL probe failed: RuntimeError: MetaTrader5 package not installed`; on the Windows machine with the WM Markets Demo terminal the probe establishes IPC and reports the connected DEMO account.
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
2. **Kill Switches**: Only `qts.risk.engine.RiskEngine` maintains kill switch state. No in-memory secondary flags.
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

Reviewed 2026-10-07. `main` is the canonical product branch and the desktop clone uses it directly:

```bat
git clone https://github.com/alfrotan-glitch/Trading-System.git
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

---

## 19. FINAL BRANCH CONSOLIDATION, 2026-10-07

* PR #4 was merged into `main` as `4238cb2d270358597197a1c9c5222f1259d8ce53`.
* `main` is now the sole canonical product branch.
* The former canonical branch `arena/01a0ce9f-trading-system` contains no changes ahead of `main`; it is retained only until repository branch deletion is performed.
* Other `arena/*` branches were audited before cleanup. Stale branches that are behind `main`, or that contain unrelated/obsolete divergent history, must not be merged merely to preserve their history. Their useful work is already represented in the canonical product history where applicable; the branches are cleanup targets, not product sources.
* No strategy was promoted. `NO_VALIDATED_EDGE`, `REAL_CAPITAL_EXPOSURE = 0`, and `LIVE = LOCKED` remain authoritative.
