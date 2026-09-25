# 1 — System Architecture

**Status:** Accepted  
**Type:** Modular monolith, event-driven, deterministic  
**Invariant:** Capital preservation — fail closed, NO_TRADE is valid.

## 1.1 Goals (in priority order)

1. Scientific validity & reproducibility
2. Resistance to overfitting / leakage / bias
3. Realistic execution modeling
4. Risk containment & reconciliation
5. Observability & auditability
6. Extensibility (instrument/broker/venue/strategy)

Non-goals at v1: sub-microsecond HFT, distributed microservices, managed cloud.

## 1.2 High-Level View

```
┌─────────────────────────────────────────────────────────────────┐
│                        Research Plane                            │
│  Hypothesis → Feature Store → Experiment → Validation → Report   │
│                 ↕ Experiment Memory (SQLite + lineage)          │
└──────────────────────────────┬──────────────────────────────────┘
                               │ promotes (only with evidence)
┌──────────────────────────────▼──────────────────────────────────┐
│                        Strategy Plane                            │
│  Strategy (Alpha) → PortfolioConstruction → ExecutionModel      │
│                ↘ RegimeDetector (hypothesis, not mandate)       │
└──────────────────────────────┬──────────────────────────────────┘
                               │ OrderIntent
┌──────────────────────────────▼──────────────────────────────────┐
│                         Risk Plane  (independent)                │
│  RiskEngine.pre_trade() → veto/adjust → kill-switch → post-trade│
└──────────────────────────────┬──────────────────────────────────┘
                               │ approved Order
┌──────────────────────────────▼──────────────────────────────────┐
│                       Execution Plane                            │
│  ExecutionEngine → BrokerAdapter (MT5/Paper/Replay) → Reconciler│
│  OrderStateMachine, idempotency, retry, drift detection         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ fills / positions / account
┌──────────────────────────────▼──────────────────────────────────┐
│                          Data Plane                              │
│  DataStore (Parquet+SQLite) → Normalization → Quality → Provenance │
│  Historical + Live feeds, versioned manifests, timezone UTC     │
└─────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                      Observability Plane                         │
│  AuditLog (JSONL+SQLite) → Metrics → Health → Alerting → Dash  │
└─────────────────────────────────────────────────────────────────┘
```

All planes communicate via **typed domain events** on an in-process **EventBus** (interface). At v1 the bus is a deterministic sorted queue (backtest) or asyncio queue (live). A Rust bus can replace it without changing strategies.

## 1.3 Modular Monolith — Why

- Single repo, single deployable, clear module boundaries with **dependency rule**: `domain` has zero dependencies; every other module depends inward.
- No network partition between Risk and Execution — veto is a function call, not a hope.
- Starts as one process; can extract adapters/services later behind the same interfaces when evidence demands distribution.

Dependency rule (enforced by import linter):

```
domain ──► (nothing)
data, execution, risk, research, validation, regime, portfolio, observability, security, lifecycle, adapters ──► domain
research ──► data, validation
execution ──► data, risk, observability
adapters ──► execution (implements BrokerAdapter)
config ──► all (read-only)
```

## 1.4 Event Model

- **Event time** is `event_time: datetime (UTC, ns)`. Processing time is `recorded_at`.
- Events are immutable, `frozen=True` Pydantic models, with `event_id` (UUID7 time-ordered), `source`, `version`.
- Ordering: backtest → sort by `(event_time, source_priority, event_id)`; live → same tie-break but arrivals drive.
- Strategy callbacks: `on_start`, `on_bar`, `on_tick`, `on_order_update`, `on_fill`, `on_reconcile`, `on_stop`. Same in backtest and live.

Event types: `Bar`, `Tick`, `Signal`, `OrderIntent`, `OrderSubmitted`, `OrderAccepted`, `OrderRejected`, `Fill`, `PositionUpdate`, `AccountUpdate`, `RiskVeto`, `ReconcileEvent`, `RegimeLabel`.

## 1.5 Execution Deployment

```
                    ┌─────────────────────┐
                    │   Paper / Backtest  │  python -m qts run --mode backtest --config ...
                    └──────────┬──────────┘
                               │ same strategy code
┌──────────┐  ZeroMQ/pipe  ┌────▼──────────────────┐   ┌──────────────┐
│  MT5     │◄────────────►│  qts live process     │──►│  SQLite/      │
│ Terminal │  or MT5 Py   │  (MT5Adapter+Engine)  │   │  Parquet     │
└──────────┘              └───────────────────────┘   └──────────────┘
                                   │ audit JSONL
                                   ▼
                              Observability
```

Live trading requires explicit `--mode live --env live --confirm` and valid `ValidationReport` + `RiskLimits` + `kill-switch` armed; otherwise process refuses to start (fail closed).

## 1.6 Determinism

- Backtests are deterministic given: `data_version`, `config_hash`, `code_version`, `seed`, `execution_model_params`. Stored in `Experiment.manifest_hash`.
- RNG is per-experiment seeded `numpy.random.Generator(PCG64)`. No global `random`.
- Order matching uses same code path in backtest as paper; only `BrokerAdapter` differs.

## 1.7 Configuration

- `configs/*.yaml` validated by Pydantic `Settings`; env separation `dev|paper|live` with distinct DB paths and secret scopes.
- Secrets never in YAML; referenced via `secret://` URIs resolved by `security.SecretsProvider` (env/1Password/Vault).

## 1.8 Cross-Cutting Concerns

- **Security:** secret isolation, least privilege, safe logging (redaction), env isolation.
- **Observability:** audit log is the source of truth; metrics derived.
- **Testing:** determinism tests gate releases.
- **Versioning:** semantic versioning + manifest hashes + data version pinning.

## 1.9 Evolution

- Phase 1: Python event loop, SQLite/Parquet, MT5 paper.
- Phase 2: MT5 live (shadow → candidate → live), regime research, ML feature store.
- Phase 3: If profiling shows bottleneck, Rust engine behind `Engine` interface; DuckDB/Postgres optional.
- Never: microservices without latency/throughput evidence.

## 1.10 Failure Modes & Defaults

| Situation | Default |
|-----------|---------|
| Data gap/duplicate | Halt strategy, emit `DataQualityAlert`, NO_TRADE (`NoTradeReason.DATA_QUALITY_FAIL`) |
| Risk veto | NO_TRADE, log `RiskVeto` + `NoTrade` with `NoTradeReason.RISK_VETO` |
| Broker drift detected | Pause trading, `ReconcileReport.requires_suspend=True` → NO_TRADE |
| Validation inconclusive (NOT_IMPLEMENTED) | BLOCK — ValidationReport.passed=False, never promote |
| Systems disagree | NO_TRADE |
| Kill-switch triggered | Cancel all, flatten (if configured), SUSPEND, persist killed flag in SQLite |

## 1.11 Execution Semantics — Next-Bar & Quantity (Phase 1 Fidelity)

- **Next-bar open:** Signal generated on `bar.close_time` (N) is queued as `pending_intent`; fill occurs at `bar N+1 open` via synthetic `exec_bar` (`open==high==low==close==open(N+1)`, `close_time = open_time+1ms`). Same-bar close fills are prohibited — lookahead closed. Audit hash includes `execution: next_bar_open`.
- **Quantity canonical:** `OrderIntent.quantity` is **lots** (broker lots). Notional = `lots × contract_size × price`. For XAUUSD `contract_size=100` (1 lot =100 oz), `lot_size=0.01` (0.01 lot =1 oz, step). Risk `pre_trade` enforces `min_quantity`, `quantity_step` (quantized to `instrument.lot_size`) and notional `max_notional` using the formula above.
- **Idempotency:** `client_order_id` primary key in SQLite `IdempotencyStore` + in-memory `OrderManager.orders`. Duplicate (persistent) returns placeholder `REJECTED/duplicate-persistent` with no fill — survives restart.
- **Reconciliation gate:** `ReconcileReport.drift != NONE` → `requires_suspend=True` → ExecutionEngine must enforce NO_TRADE and alert; quantity mismatch is never auto-healed.
- **Validation gates:** `ValidatorPipeline` requires real evidence: `walk_forward_folds`, `cpcv_folds>=5`, `perturbed_sharpes>=7`, `stress_results` from re-run `BacktestEngine.run_stress` (spread multiplier applied, not PF×factor). Missing → `NOT_IMPLEMENTED → BLOCKS` and `passed=False`.
- **PSR/DSR/CPCV:** `probabilistic_sharpe_ratio`/`deflated_sharpe_ratio` Bailey & Lopez de Prado with `E[max] = (1-γ)Φ⁻¹(1-1/N)+γΦ⁻¹(1-1/(Ne))`, skew/kurtosis, n=obs. DSR==PSR when N=1, DSR ↓ as N↑. PBO via CPCV combinatorial.
- **NO_TRADE explicit:** Empty signal, veto, kill, drift, gap, invalid qty all emit `EventType.NO_TRADE` with `NoTradeReason` — not absent log but auditable decision.
- **Durability:** Audit JSONL shipped via `Shipper` (Local|S3). S3 key includes content hash for idempotency; boto3 if available else local fallback.
