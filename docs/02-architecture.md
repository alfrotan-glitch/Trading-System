# 2. System Architecture

## Component Overview

QTS is architected with strict boundary separation between domain logic, infrastructure adapters, execution engines, and presentation layers.

```
┌─────────────────────────────────────────────────────────────┐
│                    Web & Desktop UI                         │
│   (Vanilla ES Modules, Zero Build Step, Semantic CSS)       │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Server Layer                     │
│         (34 Unified REST Endpoints, Boundary Security)      │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
┌──────────────▼──────────────┐ ┌──────────────▼──────────────┐
│     Execution & Safety      │ │     Research & Validation   │
│  - DemoSession              │ │  - Impulse Event Study      │
│  - Pre-Trade Gate (22 chks) │ │  - Statistical Engine (DSR) │
│  - RiskEngine & KillSwitch  │ │  - Walk-Forward Optimizer   │
│  - Reconciliation Engine    │ │  - Data Quality Verifier    │
│  - DemoOrderJournal         │ │  - Artifact Registry        │
└──────────────┬──────────────┘ └──────────────┬──────────────┘
               │                               │
┌──────────────▼───────────────────────────────▼──────────────┐
│                     Domain Layer (Core)                     │
│    Instruments, Orders, Fills, Positions, Modes, Invariants │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                    Adapter & Platform                       │
│    - MT5Adapter (IPC / Windows Native / Injected Mock)      │
│    - SQLite Persistent Stores (State Root Anchored)         │
│    - Authoritative Symbol & Path Resolvers                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Subsystems

### 1. Domain Layer (`src/qts/domain/`)
- Pure value objects: `Instrument`, `OrderIntent`, `Order`, `Fill`, `Position`, `SymbolSpec`.
- Execution modes: `DEVELOPMENT`, `PAPER`, `SHADOW`, `DEMO_FORWARD`, `DEMO_EXECUTION`, `LIVE`.
- Invariant: Real-capital modes (`LIVE`) cannot be declared via config files or UI; only verified multi-signature governance artifacts can enable live execution.

### 2. Broker Adapters (`src/qts/adapters/`)
- `MT5Adapter`: High-performance IPC bridge to the MetaTrader 5 terminal. Manages connection sessions, symbol subscription, market depth, tick queries, order submission, deal polling, and position management.
- `MT5Factory`: Single authoritative resolver for terminal paths, canonical-to-venue symbol translation (`XAUUSD` $\leftrightarrow$ `XAUUSD@`), and connection credentials.

### 3. Execution & Safety (`src/qts/execution/`)
- `DemoSession`: Coordinates staged arming, preflight verification, order submission, receipt capture, deal reconciliation, and position closure.
- `DemoPretradeGate`: 22 required safeguards evaluated atomically before any intent touches broker transport.
- `ReconciliationEngine`: Compares internal portfolio positions with venue tickets; detects quantity mismatches, ghost orders, or unattributed fills.
- `DemoOrderJournal`: Append-only SQLite audit log recording every signal, request, broker ticket, spread, slippage, and P&L.

### 4. Risk Engine (`src/qts/risk/`)
- `RiskEngine`: Enforces daily loss limits, drawdown caps, max lots per order, and max simultaneous exposure.
- Persistent Kill Switch: Durable flag stored in SQLite ensuring immediate cessation of trading upon operator command or gate breach.

### 5. API Layer (`src/qts/api/server.py`)
- Modern ASGI service built on FastAPI. Exposes 34 clean REST endpoints across telemetry, system status, setup, market data, research results, risk limits, and demo execution.
- Protected by strict origin boundary validation (mitigating DNS rebinding, CSRF, and iframe hijacking).

### 6. Desktop UI (`src/qts/desktop/ui/`)
- High-efficiency vanilla JavaScript architecture using modern ES modules.
- Zero build tools or transpilation required; instant hot-reloading and predictable client execution.
- 8 primary navigation domains: Overview, Research, Market, Trading, Risk, Evidence, System, Governance.
