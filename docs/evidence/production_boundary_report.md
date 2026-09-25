# Production Boundary Report — Current Safety Contract

**Updated:** 2026-09-18
**Branch:** `arena/01a0b574-trading-system`
**Current-state authority:** [`docs/current_state.md`](current_state.md)
**Environment:** Linux development sandbox; no MT5 terminal or broker session.

## Current decision

QTS is a research-first workstation. **DEMO execution is disabled and LIVE is
locked.** The existence of generic adapters, paper fills, shadow intents, or
mock boundary tests does not constitute a production order capability or a
profitability claim.

## Mode boundaries

| Mode | Allowed behavior | Forbidden interpretation |
|---|---|---|
| DEVELOPMENT | synthetic/backtest mechanism work | real-market or broker evidence |
| PAPER | simulated fills on declared data | actual fills, actual slippage, account state |
| SHADOW | would-be intents and hypothetical divergence | submitted orders or broker fills |
| DEMO_FORWARD | real MT5 demo-account observations when a real terminal is connected; zero orders | DEMO execution, fill/P&L, or LIVE permission |
| DEMO_EXECUTION | none in this product | readiness/acknowledgement cannot enable it |
| LIVE | none without separate governance and real-environment evidence | automatic promotion or UI enablement |

`DemoExecutionAuthority`, the API, execution checks, and UI all converge on
this policy. A tampered state row or a successful readiness probe cannot cross
it.

## What is measured versus unavailable

The paper/shadow artifacts are explicitly labelled simulation/would-be. The
canonical comparison currently has 6 paper records, 10 shadow intents, zero
DEMO_FORWARD observations, and measured event alignment of 0.5. Demo fill,
slippage, latency, spread, exit, and realized-PnL metrics are `UNAVAILABLE`
with reasons because DEMO_EXECUTION is disabled and no observation session is
present.

The canonical forward store currently reports zero active sessions, ticks,
signals, and real-market ticks. Its derived manifest remains an honest zero
export. No quarantined legacy JSON is reintroduced as evidence.

## Observation safety

`ForwardObservatory` is the only canonical observation store. The collector:

- uses the existing market-data/timestamp validation contract;
- records source, broker, symbol, raw timestamp, measured offset, timestamp
  basis, receipt time, and code lineage;
- appends observations to SQLite before reporting a durable session state;
- has no order submission call;
- records unknown/stale/future/invalid observations as blocked rather than
  manufacturing values.

## Generic execution infrastructure

QTS retains generic order lifecycle/risk/reconciliation components for
separately scoped paper/shadow/generic boundary tests. They must not be wired
into DEMO_FORWARD observation. Generic adapter tests with injected mocks prove
negative behavior and interface handling; they do not prove real MT5
connectivity, broker metadata, fills, or live readiness.

## Research boundary

Current canonical data is one 500-bar synthetic XAUUSD 1H fixture plus a REAL
provenance-qualified Dukascopy tick-derived XAUUSD 15m dataset (26,038 bars,
407 days). The REAL dataset passes the existing quality, readiness and
bar-research adequacy gates, but it stays below the 2-year regime target and
carries no continuous bid/ask/tick spread fields (R5 `FAIL`, non-blocking).
Campaign and edge artifacts conclude `BLOCKED_INSUFFICIENT_DATA`, and the
REAL-data impulse campaign concludes `REGIME_DEPENDENT` / `go_block BLOCK`;
blocked/rejected trials remain in the cumulative ledger. Non-finite stress
values are explicit invalid blocking measurements. No candidate is promoted.

## Review requirements

Before any future product decision, acquire provenance-qualified history and
real-terminal observation evidence, bind every claim to immutable dataset and
experiment lineage, regenerate all derived evidence, inspect negative results,
and record explicit human governance. Never enable an order path to satisfy a
test or demo.

**Conclusion:** current production boundary is safe for research and
observation-only operation; it is not a claim of DEMO execution or LIVE
readiness.
