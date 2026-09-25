# Future hedge research specification

**Status: SPECIFICATION ONLY — no hedge has been established and no study has been run.**

This specification is the P1 handoff for a future hedge investigation. It does not rerun the frozen impulse study, unlock any research partition, or turn correlation into a hedge claim.

## Evidence boundary

Observation evidence and execution evidence are separate datasets:

- **Observation:** raw source timestamp, normalized UTC event time, server offset and basis, receipt time, bid, ask, accepted/rejected acquisition outcome, source/provenance, and quality diagnostics.
- **Execution:** decision timestamp, quote age at decision, quote age at submission, submission timestamp, acknowledgement timestamp, order/deal identifiers, requested price, fill timestamp, fill price, partial-fill state, slippage, fee/financing, and broker response or reject code.

The current repository has no canonical MT5 SQLite store and no broker execution history. A future observation export cannot be treated as fill, slippage, or submission evidence. `DEMO_EXECUTION` is authorized for the DEMO account but not trading (`NO_TRADE` until a registered strategy passes the staged gates), `LIVE = LOCKED`, and `NO_TRADE` remains the default.

## Required point-in-time dataset contract

Each immutable dataset version must carry:

1. provider, instrument/contract, venue, symbol mapping, license reference, and acquisition timestamp;
2. raw source checksum and immutable version identifier;
3. event timestamp, receipt timestamp, timezone/UTC normalization rule, and revision/vintage timestamp where applicable;
4. bid/ask or an explicit mid-only declaration; no high-low-as-spread substitution;
5. gap, duplicate, stale, field-completeness, session/roll, and outlier measurements;
6. transformation manifest, including futures roll and corporate/index constituent rules;
7. research eligibility decision scoped to a declared claim, never a universal `quality passed` label.

Joins must be as-of/point-in-time. A release or revision published after the simulated decision is unavailable to that decision. Missing observations remain missing; they are not interpolated, forward-filled, synthesized, or silently repaired.

## Preregistered analysis sequence

1. Freeze the data versions and a chronological train/validation/test partition before feature or hedge selection.
2. Declare the hedge instrument, exposure map, rebalance schedule, sizing rule, signal latency, and maximum holding period.
3. Estimate hedge ratios only on the then-available training window; use no future prices, revised macro values, or future contract constituents.
4. Apply explicit spread, commission, fee, financing, roll, conversion, latency, and slippage costs. Use measured execution distributions when available; otherwise the result is `UNVERIFIED — reason: execution-cost evidence absent`, not a measured claim.
5. Evaluate fixed volatility/trend/liquidity/event regimes declared before testing. Report coverage and missingness per regime.
6. Run walk-forward and untouched out-of-sample evaluation. Keep an untouched final test set and do not retune against it.
7. Correct for multiple hedge candidates, windows, lags, regimes, and parameter choices (for example, a preregistered family-wise or false-discovery procedure).
8. Stress the result across costs, timestamps, roll rules, sample windows, symbol mappings, and regime definitions.
9. Report stability, drawdown/tail behavior, turnover, capacity, and failure modes, not only correlation or average return.
10. Require independent provenance review and an explicit `RESEARCH_ELIGIBLE` decision before any conclusion is promoted.

## Decision vocabulary

- `UNVERIFIED — reason: ...` for an executed computation whose evidence boundary is incomplete.
- `NOT_ACQUIRED`, `NOT_AVAILABLE`, or `CAPABILITY_UNVERIFIED` when the source was not obtained or could not be probed.
- `REJECTED — reason: ...` for a completed analysis that fails a preregistered gate.
- `NO_HEDGE_CLAIM` unless chronological, cost-adjusted, regime-specific, out-of-sample, multiplicity-corrected, and stability checks all pass with qualified provenance.

The authoritative input inventory is `data/evidence/data_gap_matrix.json`. It intentionally contains catalog opportunities and measured gaps without calling them acquired or research-eligible evidence.
