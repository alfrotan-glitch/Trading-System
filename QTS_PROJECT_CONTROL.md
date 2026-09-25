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
* **DEMO State**: Stage 1 connectivity and diagnostic execution probe (`DEMO-EXECPROBE-XAUUSD-V1` under `H-EXEC-01`) wired and armed with 23 pretrade checks, identity pinning, and durable SQLite journal.
* **Research State**: `NO_VALIDATED_EDGE` certified after exhaustive evaluation of 139M ticks across 15 preregistered directional hypotheses and 10 impulse strategy families.

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
| **Pretrade Gate** | `qts.execution.demo_pretrade` | 23 fail-closed checks required before any order can be submitted. |
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
* [x] **Phase 9: Product navigation** — Home, Market, Opportunities, Trading, Risk, Reports. Advanced holds Research, System, Governance.
* [x] **Phase 10: Full regression verification** — default `pytest` 1206 passed, 121 skipped; integration suite 119 passed with `--run-integration`.
* [ ] **Phase 12: Windows MT5 identity pin** — operator action, not a repository change. Do not run `qts demo connectivity --pin` from this workspace.

---

## 11. FORBIDDEN DUPLICATIONS

1. **Paper Brokers**: Only `qts.adapters.paper_adapter.RealisticPaperBroker` is permitted. No in-file stub adapters.
2. **Kill Switches**: Only `qts.risk.engine.RiskEngine` maintains kill switch state. No in-memory secondary flags.
3. **Path Resolution**: Only `qts.config.paths` resolves machine-local state paths. No hardcoded string paths.
4. **Order State Stores**: Only `qts.execution.demo_journal.DemoOrderJournal` persists execution history.

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

---

## 13. TEST STATUS

* **Python default suite**: 1,206 passed, 121 skipped (the skips are the integration suite plus 2 intentional skips).
* **Python integration suite** (`pytest tests/integration --run-integration`): 119 passed.
* **JavaScript UI tests**: 45 passed.
* **Linters**: `ruff check src/ tests/` clean. `mypy` clean on adapters, execution, API, CLI, and the research catalog.

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
