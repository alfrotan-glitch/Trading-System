# Architecture Decision Records — Technology Selection

**Date:** 2026-09-16  
**Status:** Accepted  
**Context:** Green-field autonomous quant platform, XAUUSD/MT5 initial target, must remain instrument/broker pluggable.

---

## Methodology

Each candidate examined on: architecture, event model, data model, execution realism, reproducibility, extensibility, observability, risk handling, licensing, maintenance, known limitations, suitability.

Popularity ≠ quality. We inspected code, docs, issues, and institutional literature (Lopez de Prado, Pardo, Bailey et al., Harvey et al.).

---

## ADR-001: Do Not Fork LEAN, NautilusTrader, or Freqtrade — Clean-Room Modular Monolith with Isolated Adapters

### Candidates

#### QuantConnect LEAN
- **Language:** C# engine + Python/C# strategies. 200+ indicators, Alpha/Portfolio/Execution/Risk framework separation — strong institutional pattern.
- **Event model:** Time-slice synchronized event loop, `OnData(Slice)` unified callback. Good for multi-asset.
- **Execution:** Simulated brokerage, brokerage adapters (IB, OANDA, etc). Unified backtest/live via `LiveMode` flag. Barrier: backtest assumes idealized fills unless slippage model supplied.
- **Data:** Lean Data Library, Object Store, point-in-time fundamental support. Strong.
- **Observability:** Cloud-dependent for full telemetry; local OSS leaves monitoring to user.
- **Licensing:** Apache 2.0.
- **Maintenance:** Very active (QuantConnect team + community), 12k+ unit tests.
- **Limitations:** C# core is large (≈ 300k LOC), steep to fork safely; Python is a wrapper over C# — debugging impedance; heavy abstraction overhead vs. direct event bus; cloud coupling encourages QuantConnect-hosted data.
- **Verdict:** **Adapt pattern, isolate behind interfaces. Do not fork.** LEAN's Framework separation (Alpha → Portfolio → Execution → Risk) is correct and we adopt it. But forking it for XAUUSD/MT5 would carry C# runtime, build, and cloud assumptions unnecessarily.

#### NautilusTrader
- **Language:** Rust core + Python (Cython) strategy API. 30k+ tests incl. property + Miri.
- **Event model:** Deterministic message bus, Rust `tokio` actor-engine, nanosecond timestamps, lock-free queues. Best-in-class backtest→live parity (same engine, same matching).
- **Execution:** Rich order semantics (IOC/FOK/iceberg/OCO), full reconciliation, Redis persistence. Slippage/latency injection supported.
- **Data:** Ticks, L2/L3, bars, adapters isolate venue differences. Zero-copy structures.
- **Licensing:** LGPL-3.0 (copyleft considerations for proprietary extensions; adapter isolation mitigates but not eliminates).
- **Maintenance:** Strong (team + 23k stars), Rust toolchain required.
- **Limitations:** Rust+Cython build complexity; vectorized research → event-driven rewrite friction; Python callbacks still pay overhead; long-horizon XAUUSD daily/hourly does not need sub-μs; LGPL requires care.
- **Verdict:** **Adapt architecture, isolate, prepare for future Rust core swap. Do not depend on Rust today.** NautilusTrader proves deterministic event-driven with single engine for replay and live is essential. We replicate its *semantics* in pure Python first (deterministic event loop, message bus, identical strategy callbacks in backtest and live) so team can iterate without Rust toolchain. We place a `ExecutionEngine` interface where a Rust engine can replace Python later — measured decision after profiling, not premature.

#### Freqtrade
- **Language:** Python, candle (OHLCV) based.
- **Event model:** Vectorized/candle loop, not tick/L2. Entries at open, exits at next open; “all orders fill if price within high/low”.
- **Execution:** Simulated; paper/dry-run strongly recommended because backtest fill assumptions are coarse. No realistic order-book replay.
- **Data:** OHLCV download via ccxt; `timeframe_detail` mitigates intra-candle ambiguity but needs extra memory.
- **Strengths:** Rapid iteration, Hyperopt, FreqAI retraining loop, great for crypto directional validation.
- **Limitations:** Not institutional microstructure simulation; not designed for FX/metals spread/slippage regimes; selection bias if dynamic pairlists used in backtest.
- **Verdict:** **Reject as core engine. Reuse ideas only.** Hyperopt/fast-iteration UX is instructive, but fill/execution realism fails our “prevent spurious profitability” requirement for XAUUSD where spread, slippage, and session liquidity matter materially.

#### Other engines inspected briefly
- **Backtrader / Zipline / bt / vectorbt:** Valuable for study, unmaintained or vectorized/portfolio-only. Vectorized (vectorbt) is fast but hides execution leakage. We keep a vectorized path **only** inside feature research (pandas), never for execution validation.
- **Jesse:** Strong integrity for crypto, multi-timeframe; narrower asset focus than needed.
- **Hummingbot/K (krypto-trading-bot):** Market-making focused, no historical LOB backtest — forward-test only. Instructive for live microstructure but not our research backbone.

### Decision

**Clean-room modular monolith in Python** that:

1. **Reuses:** LEAN's Framework separation, NautilusTrader's deterministic event-bus + adapter isolation + reconciliation pattern, Freqtrade's experiment iteration ergonomics, Lopez de Prado's purged/CPCV and Deflated Sharpe/PSR concepts, Pardo's walk-forward.
2. **Adapts:** Event loop (Python asyncio + sorted event queue, nanosecond `pd.Timestamp` UTC) behind a `Engine` interface → swappable to Rust.
3. **Isolates behind interfaces:** `DataFeed`, `BrokerAdapter` (MT5, Paper, Replay), `ExecutionEngine`, `RiskEngine`, `RegimeDetector`.
4. **Rewrites:** Validation stack (walk-forward + adversarial + stress) as first-class, not bolted on; provenance & versioning; lifecycle gates.
5. **Builds from scratch:** Experiment memory / lineage store, risk authority, audit observability, MT5 reconciliation (MT5 is external authority — never trust API success as fill).
6. **Rejects:** Candle-only fill assumptions; cloud-coupled data; copyleft core dependency at v1; microservices prematurely.

### Consequences

- Fast iteration, no Rust gate for contributors; deterministic backtests via pure Python.
- Clear upgrade path: if Python event loop saturates (μs needed), implement Rust engine fulfilling same interfaces — strategies unchanged.
- LGPL avoided at core; adapters can be LGPL if desired without contaminating core.
- Higher initial implementation cost than forking — justified by auditability and XAUUSD realism control.

---

## ADR-002: Python 3.11+ with Pydantic v2, pandas, numpy — no Spark/Dask at v1

- **Decision:** Python for research ubiquity; Pydantic for strong typing/validation; pandas for feature research (isolated from execution engine); SQLite + Parquet for storage (file-portable, reproducible). DuckDB optional for analytics.
- **Alternatives:** Spark/Dask for scale — rejected at v1. XAUUSD 1m bars are ~500k rows/year; single-node suffices. Premature distribution harms determinism.
- **Static analysis:** ruff, mypy strict, bandit.

## ADR-003: Storage — SQLite for OLTP lineage + Parquet for market data

- **Decision:** SQLite (WAL) for experiments, orders, fills, lineage; Parquet partitioned by `instrument/date` for bars/ticks with checksums and manifest. Reproducible without external DB.
- **Alternatives:** Postgres (adopt when multi-user), TimescaleDB, QuestDB — interface `DataStore` abstracts.

## ADR-004: Event Time — UTC nanosecond, monotonic, single source

- **Decision:** All timestamps `UTC`, `tz-aware`, `ns` resolution; event time ≠ processing time; data `event_time`, execution `exchange_time`, audit `recorded_at`. Bar `open_time` inclusive, `close_time` exclusive.
- **Rationale:** Prevents look-ahead via timestamp leakage, critical for walk-forward purging.

## ADR-005: Backtest Engine — Deterministic sorted event queue, not vectorized

- **Decision:** Backtests replay ticks/bars ordered by `event_time`; matching engine applies spread/slippage/latency/partial-fill models; strategy sees same callbacks as live (`on_bar`, `on_tick`, `on_order_update`).
- **Vectorized path** allowed only in `research.features` for feature discovery, with explicit leakage guards.

## ADR-006: Risk is Independent Authority

- **Decision:** `RiskEngine` evaluates every `OrderIntent` pre-trade (position, exposure, leverage, daily loss, drawdown, vol-aware sizing, kill-switch) and can veto. Post-trade it monitors drift. Strategy never overrides risk.
- **Pattern:** LEAN Risk Management model + Nautilus portfolio/risk separation, but stricter: fail-closed, explicit `VetoReason`.

## ADR-007: Validation is a Pipeline, Not a Flag

- **Decision:** Dedicated `validation` package with composable checks: splits (train/val/holdout), anchored/walk-forward, purged/CPCV, regime-conditioned, perturbation, Monte Carlo (trade reshuffle, bootstrap), cost/slippage/delay/spread stress, missing-data injection, DSR/PSR/PBO reporting. No strategy advances lifecycle without `ValidationReport`.

## ADR-008: MT5 Adapter — External Authority with Reconciliation

- **Decision:** MT5 via `MetaTrader5` Python package where available; otherwise socket/ZeroMQ bridge. Adapter implements `BrokerAdapter` and never assumes fill on send. Separate `Reconciler` polls account/positions/orders, detects drift, duplicate-order prevention via `client_order_id`.

## ADR-009: AI is Hypothesis Generator, Not Oracle

- **Decision:** LLM/ML for hypothesis, feature search, regime labeling, adversarial review, experiment interpretation — each idea becomes a falsifiable hypothesis with experiment. No AI output bypasses validation.

## ADR-010: Observability — Audit Log is Primary, Dashboard Secondary

- **Decision:** Structured JSONL audit log + SQLite `events` table for every decision (data version, signal, risk veto, order, fill, reconcile). OpenTelemetry optional. Build dashboard only after audit is trustworthy.



## ADR-011: Next-Bar Open Execution — Lookahead Closed (2026-09-16)

- **Context:** Same-bar close fill lets strategy trade on a price not known until bar close — spurious profitability (zigzag leakage). Must be falsifiable.
- **Decision:** Signal on `bar N close_time` → `pending_intents` → synthetic `exec_bar` at `N+1 open` (`open==high==low==close==open(N+1)`, `close_time = open_time+1ms`) via `BacktestEngine.run`. MatchingEngine price at open + spread/slippage. Audit `execution: next_bar_open`. `test_next_bar_execution_no_lookahead` (hold_long bar_idx 1, price==next open) proves it.
- **Alternatives:** Same-bar close with delay 1ms → rejected due to lookahead. Tick replay → future when ticks available.
- **Consequence:** Zigzag fixture PF was `inf` under next-bar (previous test incorrectly expected <1.5); fixed test to assert timing not profitability. Re-simulation required for stress (see ADR-013).

## ADR-012: Quantity Canonical in Lots, Notional = lots × contract_size × price (2026-09-16)

- **Context:** XAUUSD MT5: 1 lot = 100 oz; micro contracts 1. Dollar notional miscomputed if `contract_size` ignored.
- **Decision:** `Instrument{lot_size=0.01, contract_size=100}`; `OrderIntent.quantity` is lots. Risk: `notional = qty * contract_size * est_price`, exposure lots `abs(sum qty + delta)`, leverage `notional/equity`. `MT5Adapter.lots_to_mt5_volume` quantizes to `lot_size` step `ROUND_HALF_UP`. Risk vetoes `MIN_QUANTITY_VIOLATION` / `QUANTITY_STEP_VIOLATION`. `test_quantity_lots_to_notional` verifies 0.1 lot = 20000 USD (std) vs 200 USD (micro 1) → different veto.
- **Replaces:** Ad-hoc `quantity * price` (would misstate by 100×).

## ADR-013: Validation Must Have Real Evidence — NOT_IMPLEMENTED Blocks (2026-09-16)

- **Context:** Dummy `wfe=0.54`, `pf*1.5` placeholders passed weak strategies.
- **Decision:** `ValidatorPipeline.validate(...)` requires real evidence: `walk_forward_folds` (list `is_sharpe/oos_sharpe` from independent backtests via `walk_forward_splits`), `cpcv_folds>=5` (combinatorial `cpcv_splits` + per-trial `best_is_test_sharpe/median_test_sharpe` for PBO), `perturbed_sharpes>=7` (re-run with fast ±5/10/20%), `stress_results` from `BacktestEngine.run_stress` (re-run at spreads 1.0/1.5/2.0, not multiplication). Missing → `Check(status=NOT_IMPLEMENTED, required=True) → passed=False → never promote`. `validate()` docstring documents caller responsibility.
- **Evidence:** `tests/integration/test_validation.py` now uses flat equity (`is_eq=oos_eq=[10000]*6`), perturbed zeros, realistic stress; placeholder fails.

## ADR-014: Persistence for Kill-Switch and Idempotency Survives Restart (2026-09-16)

- **Decision:** `RiskEngine.killed` stored in SQLite `risk_state (k, killed, reason, updated_at)`; new engine `RiskEngine(db_path)` loads it. `ExecutionEngine.submit_intent` checks `is_duplicate_in_memory or is_duplicate_persistent` (IdempotencyStore SQLite PRIMARY KEY); if persistent without in-memory it creates `REJECTED/duplicate-persistent` placeholder → no second fill even after process restart. Reconcile drift sets `requires_suspend=True` and emits `NO_TRADE`.

## ADR-015: Durable Audit via Shipper + Explicit NO_TRADE (2026-09-16)

- **Decision:** `observability/shipper.py` `Shipper` protocol with `LocalShipper` and `S3Shipper` (boto3, idempotent key `sha256`, prefix). Credentials via env/IAM not YAML. `DomainEvent.EventType.NO_TRADE` + `domain/no_trade.py` `NoTradeReason` enumerates all capital-preservation paths (empty signal, veto, kill, drift, gap, invalid qty). Every veto/kill/drift emits `NO_TRADE`. Failure when uncertain is now measured, not missing.

## ADR-016: Data Quality Enforced at Write (2026-09-16)

- **Decision:** `SqliteParquetDataStore.write_bars(..., strict_quality=True)` runs `validate_bars` (monotonic, no_future, OHLC invariants, no_duplicates, tz_aware, volume) before write; fail-closed raises `ValueError`. Report persisted in `quality_reports` SQLite table and manifest JSON, queryable via `store.quality_report(version)` and `qts data validate`. Read path preserves invariants.

## ADR-017: MT5 Raw Tick History — Acquire First, Analyze Later (2026-09-19)

- **Context:** `scripts/probe_mt5_history.py` coupled MT5 history queries to a per-row audit (JSON + SHA-256 per row, duplicate/spread analysis). CPU-bound per-row Python scaled with rows, not window span; a multi-hour 30d+ run was interrupted inside `_audit_rows()` and produced nothing durable. Requirements: lossless preservation of *every* returned row and field, bounded memory, interrupt/restart safety, provable integrity, no fabricated completeness, and no raw broker rows in Git.
- **Decision:** Strict separation of concerns for MT5 history. (1) Acquisition (`qts.data.mt5_history_acquisition`): only query → receive → preserve → persist → integrity metadata; chunked half-open windows (default 24h) with recursive halving to a floor on failure/oversize; one atomic Parquet part per chunk verified by vectorized read-back equality; fsync'd `manifest.json` ledger per chunk; dataset digest = SHA-256 over sorted `<part> <part-sha256>` lines; raw tree `data/raw/mt5_ticks/` gitignored; DEMO-only, order-free (AST-pinned MT5 allowlist). (2) Analysis (`qts.data.mt5_history_analysis`): offline-only, never imports MetaTrader5; streaming per-part counters for duplicates/collisions/spreads/gaps/jumps/basis forensics + full integrity revalidation against the manifest. (3) The capability probe keeps only seconds-scale metadata (schema v2); `_audit_rows` removed from the query path. (4) Partial/interrupted states are first-class statuses (`IN_PROGRESS`, `PARTIAL_*`, `EMPTY_COMPLETE`, `FAILED_*`) — a killed run can never be read as complete; resume is chunk-exact (byte equality vs uninterrupted proven by test).
- **Alternatives rejected:** single all-at-once `copy_ticks_range` per window (loses everything on failure; span-capped servers); in-acquisition audit (the failure being fixed); raw CSV/JSON per tick (redundant, slower, lossy float formatting — Parquet round-trip check already demonstrates losslessness); a database/service for tick storage (unnecessary engine; Parquet + manifest suffices).
- **Consequence:** Synthetic-fixture benchmark at operator-scale (4,373,160 rows/30d): acquisition ~11s, full deferred analysis ~4s, peak RSS ~312MB — versus the interrupted multi-hour coupled run. Execution evidence (fills/slippage/latency/realized costs) remains out of scope: this layer produces quote evidence only; R5 is not solved by it.


## Summary Table

| Need | Reuse | Adapt | Isolate | Rewrite | Build | Reject |
|------|-------|-------|---------|---------|-------|--------|
| Event-driven engine | Nautilus semantics | LEAN Framework | `Engine` interface | Python queue v1 | Reconciler | Candle-only fills |
| Data provenance | LEAN manifest ideas | Nautilus adapters | `DataFeed` | Versioning | Quality gates | Cloud-only store |
| Validation | Pardo/LdP formulas | CPCV/purging | `Validator` | Pipeline | Adversarial suite | Single backtest |
| Risk | LEAN limits | Nautilus portfolio | `RiskEngine` | — | Kill switches | Strategy-owned sizing |
| Research memory | Freqtrade iteration UX | — | `ExperimentStore` | — | Lineage graph | — |

All ADRs are versioned and require evidence to overturn.
