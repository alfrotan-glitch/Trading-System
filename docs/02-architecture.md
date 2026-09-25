# 2. System Architecture

## Component Overview

QTS is architected with strict boundary separation between domain logic, infrastructure adapters, execution engines, and presentation layers.

Dependency direction is inward. Outer layers may call inner layers. Inner layers do not call outer layers.

```
UI / CLI
  → API and application services
    → governance (lifecycle, authorization, policy)
      → risk (RiskEngine, the only kill switch)
        → execution (DemoSession, pre-trade gate, journal)
          → adapters (BrokerAdapter, MT5, paper, shadow)
            → domain (instruments, orders, modes)
```

`qts.adapters` does not import `qts.execution`. The UI renders and requests. It does not decide whether an order may be sent. CLI commands call application services; they do not own a second risk engine.

---

## Key Subsystems

### 1. Domain Layer (`src/qts/domain/`)
- Pure value objects: `Instrument`, `OrderIntent`, `Order`, `Fill`, `Position`, `SymbolSpec`.
- Execution modes: `DEVELOPMENT`, `PAPER`, `SHADOW`, `DEMO_FORWARD`, `DEMO_EXECUTION`, `LIVE`.
- Invariant: `LIVE` cannot be selected from a config file, the UI, or a DEMO authorization artifact. There is no multi-signature unlock in this repository. The live readiness report is fail-closed and is not an order.

### 2. Broker Adapters (`src/qts/adapters/`)
- `MT5Adapter`: High-performance IPC bridge to the MetaTrader 5 terminal. Manages connection sessions, symbol subscription, market depth, tick queries, order submission, deal polling, and position management.
- `MT5Factory`: Single authoritative resolver for terminal paths, canonical-to-venue symbol translation (`XAUUSD` $\leftrightarrow$ `XAUUSD@`), and connection credentials.

### 3. Execution & Safety (`src/qts/execution/`)
- `DemoSession`: Coordinates staged arming, preflight verification, order submission, receipt capture, deal reconciliation, and position closure.
- `run_pretrade_gate`: the single fail-closed order gate. `UNKNOWN` does not pass.
- `ReconciliationEngine`: Compares internal portfolio positions with venue tickets; detects quantity mismatches, ghost orders, or unattributed fills.
- `DemoOrderJournal`: Append-only SQLite audit log recording every signal, request, broker ticket, spread, slippage, and P&L.

### 4. Risk Engine (`src/qts/risk/`)
- `RiskEngine`: Enforces daily loss limits, drawdown caps, max lots per order, and max simultaneous exposure.
- Persistent Kill Switch: Durable flag stored in SQLite ensuring immediate cessation of trading upon operator command or gate breach.

### 5. API Layer (`src/qts/api/`)
- `server.py` composes the FastAPI app, origin boundary, and process-local seams.
- Route modules under `src/qts/api/routes/` cover demo, market, research, trading, risk, and system.
- Shared helpers live in `src/qts/api/deps.py`. Routes do not own risk or order policy.

### 6. Desktop UI (`src/qts/desktop/ui/`)
- Vanilla JavaScript. No build step.
- Product navigation: Home, Market, Opportunities, Trading, Risk, Reports.
- Engineering detail lives under Advanced: Research, System, Governance.
- The command line is the package `src/qts/cli/`. Entry point remains `qts`.
