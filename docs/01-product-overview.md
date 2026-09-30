# 1. Product Overview

## Mission
QTS is a gold research workstation. It can watch a demo account. It cannot open live trading.

Real-money trading stays locked. There is no multi-party approval that opens it from this workstation, and a demo result cannot create one. The research conclusion remains no validated edge.

---

## Core Principles

### 1. Truth in State & Measurements
- **No Fabricated Evidence:** Missing data is explicitly reported as `UNAVAILABLE` or `INSUFFICIENT_EVIDENCE`—never defaulted to zero or cosmetically smoothed.
- **Authoritative Broker Truth:** The connected broker terminal (MetaTrader 5) is the primary source of truth for accounts, execution receipts, and positions.
- **Zero Real Capital Exposure by Default:** Live trading remains locked behind structural code invariants (`REAL_CAPITAL_EXPOSURE = 0`).

### 2. Research Integrity & Statistical Defense
- **Pre-Registration Required:** Hypotheses and strategies must be preregistered with frozen parameter hashes before evaluation.
- **Multiple Testing Protection:** Data mining and p-hacking are penalized using Holm family-wise error rate control and Deflated Sharpe Ratio (DSR) metrics.
- **No Forward Fitting:** Strategies cannot adjust parameters dynamically during live or demo execution to chase short-term variance.

### 3. Fail-Closed Execution Safety
- **Fail-closed pre-trade gate:** Every would-be order must satisfy account type verification, pinned broker identity, canonical symbol binding, fresh quote checks, spread limits, daily loss limits, and drawdown ceilings. The check list is `qts.execution.demo_pretrade`, not a second document.
- **Continuous Broker Reconciliation:** Internal portfolio positions are reconciled with broker-reported tickets after every single order and position closure. Any drift triggers an immediate system halt.
- **Durable Kill Switch:** SQLite-persisted halt mechanisms guarantee that emergency stops survive process restarts.

---

## Product Mental Model

QTS organizes operator workflows across three distinct operational layers:

```
┌─────────────────────────────────────────────────────────────┐
│                      Executive Layer                        │
│   (Plain English status, 6-pillar telemetry, primary next)  │
├─────────────────────────────────────────────────────────────┤
│                      Operator Layer                         │
│     (Demo controls, position management, risk limits)       │
├─────────────────────────────────────────────────────────────┤
│                 Technical & Evidence Layer                  │
│   (Pre-trade gates, broker receipts, raw audit journals)    │
└─────────────────────────────────────────────────────────────┘
```

Non-technical operators see clear operational status, plain-language blockers, and actionable recommendations. Engineers and risk officers can drill down into cryptographic policy hashes, broker retcodes, microsecond latency telemetry, and SQLite event logs.
