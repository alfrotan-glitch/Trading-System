# MT5 Boundary Report — Connectivity Contract, Not Production Readiness

**Updated:** 2026-09-18
**Branch:** `arena/01a0b358-trading-system`
**Environment:** Linux development sandbox; MetaTrader 5 is not installed and
no broker terminal/account was connected.

## Verdict

**NOT READY FOR LIVE OR DEMO EXECUTION.**

This document records the fail-closed MT5 interface and the limits of the
available verification. It is not evidence of a real terminal, account,
quote, fill, order, reconciliation state, slippage, latency, or P&L.

- `DEMO_FORWARD/OBSERVE_ONLY` is the only broker-facing product path. With a
  real terminal it may collect provenance-bound ticks; it has no order path.
- `DEMO_EXECUTION` is disabled by product policy. No readiness or mock result
  creates a demo order permission.
- `LIVE` is separately locked and requires independent governance and
  claim-grade research evidence.

## A. Interface and fail-closed checks

The MT5 adapter and market-data path retain strict checks for:

- initialize/login/terminal/account availability;
- authoritative symbol mapping and broker `SymbolSpec` fields;
- positive, ordered bid/ask and expected symbol identity;
- timestamp freshness/future rejection and measured-offset provenance;
- spread/session/tradability conditions;
- broker metadata completeness and contradictory geometry;
- unknown account equity/currency/leverage and missing fields;
- reconciliation, idempotency, stale quote, and broker-disconnect vetoes in
  separately gated generic execution infrastructure.

Missing or ambiguous broker facts are `UNAVAILABLE`/blocked, never defaults.
The MT5 timestamp contract remains authoritative UTC receipt time plus the
measured broker-server offset, with the last valid offset retained.

## B. What was actually verified here

The repository's mock/adversarial tests exercise adapter contracts and
negative cases: invalid/stale/crossed quotes, wrong account type, missing
metadata, symbol mismatch, quantity/price geometry, timestamp behavior,
reconciliation drift, restart persistence, and observation-only order absence.
These tests verify code behavior only; mock connectivity is never upgraded to
real-environment evidence.

The current sandbox itself has:

- no MT5 installation or terminal;
- no real demo-account credentials/session;
- zero canonical forward observations;
- no raw Desktop broker evidence committed;
- no real fill/order/execution history claim.

## C. Real-terminal observation protocol

On the operator's Windows/MT5 machine:

1. Configure the terminal path and broker symbol without storing credentials in
   QTS; use the documented OS/environment credential boundary.
2. Run the 14-check readiness report and inspect every failing reason.
3. Start only `DEMO_FORWARD` observation after readiness passes.
4. Verify each accepted tick has broker symbol, raw timestamp, measured offset,
   timestamp basis, receipt time, session, and code lineage.
5. Confirm the canonical SQLite observation store is append-only and that no
   order API is reachable from the collector.
6. Export the manifest only for inspection; do not treat the export as the
   source or as completeness proof.

A readiness pass permits observation diagnostics only. `/api/demo/enable` is a
policy refusal with HTTP `409`; it does not start an order lifecycle.

## D. Generic execution code versus this product boundary

The repository contains generic broker/execution components used by tests and
by separately gated infrastructure. Their existence is not evidence that the
DEMO_FORWARD collector can submit orders, and they do not override
`DemoExecutionAuthority` or the product policy. Never route observation ticks
into an order engine to satisfy a test or demonstration.

## E. Required evidence before any future governance review

A future review would need, at minimum:

- real-terminal proof at the required evidence tier;
- licensed, provenance-qualified history and immutable dataset manifest;
- measured bid/ask/session/tick and execution-cost evidence where claimed;
- reproducible hypothesis/experiment lineage and cumulative trial accounting;
- locked OOS, walk-forward, null/placebo, regime, perturbation, cost, and
  forward evidence with limitations;
- reconciliation and account authority evidence from the real environment;
- explicit human approval. None of these requirements is waived by a mock
  pass or by a paper/shadow result.

**Current decision:** preserve the fail-closed boundary, collect no orders,
keep DEMO execution disabled, keep LIVE locked, and acquire real evidence
before making a production claim.
