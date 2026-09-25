# QTS benchmark and justified-gap analysis

**Date:** 2026-09-18
**Scope:** QTS research, simulation, observation, and the retained execution boundary
**Decision rule:** adopt a pattern only when it improves safety, reproducibility, data truthfulness, or operator control in the current modular monolith. Framework-specific breadth, performance claims, and live-order features are not goals for this review.

## Executive result

QTS already has the most important safety patterns found in the benchmark set:

- a modular data/execution/risk boundary;
- a versioned Parquet data store with SQLite manifests and quality gates;
- explicit spread, slippage, latency, commission, and partial-fill configuration;
- a fail-closed independent risk authority;
- persistent idempotency, order-state transitions, audit events, and reconciliation;
- next-bar execution that prevents same-bar close look-ahead;
- immutable research configuration and provenance fields; and
- a hard boundary that keeps DEMO execution disabled by current policy.

The review found three concrete, narrow gaps worth correcting now:

1. **Backtest state isolation:** a backtest previously constructed its risk engine on the shared database and called `reset_kill()`. Research replay must never clear a durable safety stop. Reconciliation suspension state was also made explicitly non-persistent for backtests.
2. **Run/data lineage:** `BacktestResult.manifest_hash` previously hashed a run payload rather than the selected dataset manifest, while `config_hash` covered only matching settings. Results now carry the actual dataset checksum, a full run-configuration hash, and resolved code identity.
3. **Event lineage:** new domain events previously defaulted to the package string `0.1.0`; old rows were read back with the same fabricated fallback. New events now resolve the code identity, and legacy missing values remain `UNAVAILABLE`.

No event bus, cache, Rust core, cloud data service, tick/L2 simulator, rate-limit framework, or live-order path was added. Those are either already represented by a smaller QTS boundary, require evidence QTS does not have, or would widen scope without a current safety or research acceptance criterion.

## Benchmark selection and evidence

These are architecture and operational benchmarks, not claims that any framework guarantees profitability or safety. They were selected because their maintained public documentation describes both research/simulation and execution concerns.

| Benchmark | Authoritative evidence inspected | Reusable pattern | QTS decision |
|---|---|---|---|
| QuantConnect LEAN | [LEAN getting started](https://www.quantconnect.com/docs/v2/lean-engine/getting-started), [reality-modeling concepts](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts) | Separate data feed, transaction processing, real-time, setup, and result components; configurable security and portfolio reality models; one engine can operate in research, backtest, or live contexts. | **ADAPT** boundaries and reality-model semantics; do not fork the large C# engine or copy its asset-class breadth. |
| NautilusTrader | [architecture](https://nautilustrader.io/docs/latest/concepts/architecture/), [backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/), [data](https://nautilustrader.io/docs/latest/concepts/data/) | Common core across backtest/sandbox/live; deterministic event ordering; explicit DataEngine, ExecutionEngine, RiskEngine, Portfolio, Cache, and adapter boundaries; catalog-backed data; fail-fast data-integrity policy and reconciliation. | **KEEP/ADAPT** the semantics already present in QTS. Defer a general message bus/cache and high-performance Rust implementation until measured need. |
| Backtrader | [broker and orders](https://backtrader.readthedocs.io/en/latest/user-guide/brokers/brokers.html), [analyzers](https://backtrader.readthedocs.io/en/latest/api/analyzers/backtrader.analyzer.html) | Explicit commission/slippage/order models; order/trade/cash-value notifications; analyzers separated from strategy logic. | **KEEP** QTS's matching configuration, audit events, and result metrics. Do not introduce a second broker abstraction merely to match its API. |

### What was not treated as evidence

- A framework's marketing language, star count, or claimed latency was not used as a QTS requirement.
- A backtest result was not treated as broker or market evidence.
- OHLC high-low ranges were not treated as measured spread or order-book liquidity.
- Optional framework features such as cloud deployment, dozens of asset classes, optimization UX, or a distributed message bus were not adopted without a QTS acceptance criterion.

## Extracted pattern ledger

| ID | Mature pattern | QTS evidence | Decision |
|---|---|---|---|
| P1 | Ports and adapters around normalized data and venue execution | `src/qts/data/provider.py`, `src/qts/adapters/`, `src/qts/execution/engine.py` | **KEEP**. This is the right modular-monolith boundary for MT5 and future adapters. |
| P2 | Risk is a separate authority, before and after execution | `src/qts/risk/engine.py`, `src/qts/adapters/order_check.py`, `src/qts/execution/engine.py` | **KEEP**. The fail-closed unknown-account/unknown-price behavior is stronger than a permissive simulation default. |
| P3 | Venue state is reconciled; accepted is not the same as filled | `ExecutionEngine.reconcile()`, `poll_live_fills()`, `tests/test_poll_fill_attribution.py` | **KEEP**. No order path is added to observation or DEMO. |
| P4 | Execution realism is explicit and configurable | `src/qts/execution/matching.py`, `BacktestEngine.run()` next-bar convention | **KEEP**. Costs and delays are modeled where evidence supports them; unavailable broker facts stay unavailable. |
| P5 | Data is cataloged, versioned, quality-checked, and checksum-bound | `src/qts/data/store.py`, `src/qts/data/quality.py`, `src/qts/data/inventory.py` | **KEEP**; **ADAPT** result lineage to use the actual manifest checksum. |
| P6 | Deterministic replay and stable event ordering | `src/qts/backtest/engine.py` sorts bars and uses an explicit next-bar rule; `src/qts/domain/events.py` records event and recorded times | **ADAPT**, not a rewrite. Current bar replay is deterministic; a general bus/tick ordering contract remains future work. |
| P7 | Research runs retain immutable configuration, seed, data, code, and outcomes | `src/qts/research/experiment.py`, `src/qts/research/campaign.py` | **ADAPT** the standalone `BacktestResult` so it cannot lose the same lineage. |
| P8 | Backtest/sandbox/live share enough core semantics to reduce divergence | QTS shares `MatchingEngine`, `ExecutionEngine`, `RiskEngine`, `Portfolio`, and domain values, but `BacktestEngine` still owns a direct bar loop | **ADAPT later**. The gap is real, but completing it would be a runtime redesign and is not required while execution is locked. |
| P9 | Typed message bus and in-memory cache | Nautilus uses both; QTS uses direct calls plus audit/storage | **DEFER / NOT APPLICABLE now**. No measured throughput, concurrency, or recovery requirement justifies replacing working direct calls. |
| P10 | Tick/L2/order-book replay and queue-aware matching | Nautilus documents these; QTS's current canonical evidence is OHLC and `BacktestEngine` is bar-based | **DEFER**. Implement only after a real, provenance-bound tick/order-book dataset exists and an acceptance test defines the fill semantics. |
| P11 | Broad brokerage, asset-class, cloud, and deployment integrations | LEAN/Nautilus expose many optional integrations | **REJECT for this gap cycle**. They do not improve the current XAUUSD/MT5 safety boundary and could fabricate unsupported metadata if copied carelessly. |

## Concrete gap matrix

Statuses use the following meanings:

- **KEEP:** QTS already satisfies the useful pattern; no code change is justified.
- **ADAPT:** a small QTS-native correction is justified and implemented or explicitly scoped.
- **DEFER:** real gap, but a required input, measurement, or policy milestone is absent.
- **REJECT:** framework-specific feature is not a QTS requirement.
- **NOT APPLICABLE:** no current QTS operating mode can safely use the feature.

| Gap | Exact QTS path/symbol | Evidence of gap | Acceptance criterion | Decision/status |
|---|---|---|---|---|
| G-01 Dataset and run identity could be confused | `src/qts/backtest/engine.py:BacktestResult`, `BacktestEngine.run()`; `src/qts/data/store.py:Manifest` | The old `manifest_hash` was derived from strategy/run JSON, and `config_hash` covered only `MatchingConfig`. This was weaker than the manifest/checksum contract already used by research records. | For a valid run, `result.manifest_hash == store.manifest(data_version).checksum`; `result.config_hash` changes when seed, strategy parameters, costs, risk limits, or code identity changes; result exposes resolved code identity. Missing/mismatched manifest fails closed. | **ADAPT — implemented.** |
| G-02 Simulation could mutate durable safety state | `src/qts/backtest/engine.py`; `src/qts/risk/engine.py:RiskEngine`; `src/qts/execution/engine.py:ExecutionEngine` | The old backtest path used the shared DB and called `risk.reset_kill()`. A replay must not clear an operator kill switch or persist a simulation reconciliation suspension. | A backtest completes without clearing an existing durable `risk_state` kill; it does not create/use `reconcile_state` in the shared DB; live/paper/shadow defaults remain durable. | **ADAPT — implemented.** |
| G-03 Events could lose producing-code identity | `src/qts/domain/events.py:DomainEvent`; `src/qts/observability/audit.py:SqliteAuditLog.query()`; `src/qts/observability/lineage.py` | New events defaulted to `0.1.0`; missing legacy DB values were read back as the same string. That is not provenance. | New events carry `code_version()`; legacy rows with no stored value return `UNAVAILABLE`; no event path fabricates a revision. | **ADAPT — implemented.** |
| G-04 Backtest/live callback parity is incomplete | `src/qts/backtest/engine.py`; `src/qts/execution/engine.py`; `src/qts/research/strategy.py` | QTS has shared domain/execution components but the backtest owns a direct bar loop and does not yet expose one common strategy lifecycle for every environment. | Future work must demonstrate identical strategy callback inputs and order-state events under replay and observation, without enabling DEMO orders; add only after a measured parity failure or explicitly authorized milestone. | **ADAPT — defer.** |
| G-05 General event bus/cache is absent | `src/qts/domain/events.py`; direct component calls in `src/qts/execution/engine.py` | A framework benchmark has a bus/cache, but QTS has no measured scale or recovery problem requiring one. | Add only if a benchmark shows a reproducible throughput, ordering, or restart-recovery failure that direct calls cannot meet; preserve typed events and modular monolith. | **DEFER / NOT APPLICABLE now.** |
| G-06 Tick/L2 replay is absent from the canonical backtest | `src/qts/backtest/engine.py` module docstring; `src/qts/execution/matching.py` | QTS can match a supplied tick in isolation, but the canonical replay reads bars. Current evidence does not include a provenance-bound order book or measured spread/liquidity. | Require a real tick/order-book manifest, deterministic timestamp/tie-break contract, fill-model tests, and explicit `UNAVAILABLE` handling before implementation. | **DEFER.** |
| G-07 Venue-specific order breadth/rate limits are incomplete | `src/qts/adapters/mt5_adapter.py`; `src/qts/risk/engine.py` | Mature systems support more order types and submission controls, but QTS's current product policy keeps DEMO execution disabled and LIVE locked. | Implement only against an authorized venue requirement and broker evidence; never add a live/DEMO order path to make the benchmark feature pass. | **DEFER / policy-blocked.** |
| G-08 Cloud/distributed/microservice architecture | repository-wide architecture | The benchmark systems offer optional cloud, external buses, and higher-scale runtime pieces. QTS is a single-node modular monolith by design. | No change unless a measured workload or recovery requirement exceeds the current SQLite/Parquet design; otherwise the additional boundary is risk, not evidence. | **REJECT.** |

## Implemented changes in this gap cycle

### 1. Isolate simulation safety state

- `RiskEngine(..., persist_kill=False)` provides an explicitly non-durable kill state for research/simulation.
- `BacktestEngine` uses that mode and no longer calls `reset_kill()` against the shared database.
- `ExecutionEngine(..., persist_reconcile_state=False)` prevents replay-only suspension state from being written to the shared database.
- Default live/paper/shadow construction remains durable; this does not weaken any production gate.

### 2. Bind backtest output to real lineage

- `BacktestEngine.run()` requires a matching dataset manifest and fails closed if it is missing or mismatched.
- `BacktestResult.manifest_hash` now means the selected manifest's content checksum.
- `config_hash` now includes strategy, parameters, data identity, seed, time bounds, execution convention, matching settings, risk limits, initial balance, and code identity.
- `BacktestResult.code_version` exposes the resolved producing-code identity.
- New data manifests use `qts.observability.lineage.code_version()` rather than a package-only placeholder.

### 3. Preserve event provenance

- `DomainEvent.code_version` resolves through the existing lineage helper.
- Reading older audit rows with no code version returns `UNAVAILABLE`, not a fabricated `0.1.0`.

## Verification and acceptance evidence

Focused regression coverage is in `tests/integration/test_backtest_determinism.py`:

- a backtest cannot clear a durable risk kill switch or create shared reconciliation state;
- result identity uses the real data checksum and changes with run configuration;
- domain-event defaults use resolved code lineage.

The full verification record will be reported with the implementation commit. Browser checks remain subject to the repository's existing Playwright/Chromium availability constraint; no browser skip is treated as product evidence.

## Explicit non-goals retained

- `DEMO_EXECUTION_DISABLED = True` remains in force and public wording remains `DEMO_EXECUTION = DISABLED BY POLICY`.
- No broker order path is enabled for DEMO_FORWARD/OBSERVE_ONLY or SHADOW.
- No real spread, slippage, fills, account state, execution history, completeness, or provenance is inferred from synthetic/OHLC data.
- No external framework is vendored or forked.
- No microservice, database, message bus, cloud service, or AI subsystem is introduced.

## Sources

All external sources below were accessed on 2026-09-18 and are used only for documented architecture/operational patterns:

1. QuantConnect, **LEAN Engine — Getting Started**: <https://www.quantconnect.com/docs/v2/lean-engine/getting-started>
2. QuantConnect, **Reality Modeling — Key Concepts**: <https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts>
3. NautilusTrader, **Architecture**: <https://nautilustrader.io/docs/latest/concepts/architecture/>
4. NautilusTrader, **Backtesting**: <https://nautilustrader.io/docs/latest/concepts/backtesting/>
5. NautilusTrader, **Data**: <https://nautilustrader.io/docs/latest/concepts/data/>
6. Backtrader, **Brokers and Orders**: <https://backtrader.readthedocs.io/en/latest/user-guide/brokers/brokers.html>
7. Backtrader, **Analyzer API**: <https://backtrader.readthedocs.io/en/latest/api/analyzers/backtrader.analyzer.html>

The benchmark sources describe capabilities and design choices of their systems; they do not constitute market evidence for QTS or permission to enable execution.
