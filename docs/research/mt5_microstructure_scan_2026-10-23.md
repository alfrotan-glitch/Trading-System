# XAUUSD@ MT5 microstructure scan — 2026-10-23

**Disposition:** `INCONCLUSIVE`; no strategy, edge, promotion, or order.

The repository's fixed microstructure discovery engine was run on the complete
seven-day local MT5 bid/ask tick dataset. It was not retuned and no locked
period was opened. The sanitized machine-readable summary is
`data/evidence/mt5_microstructure_scan_2026-10-23.json`.

## Result

| Item | Result |
|---|---|
| Dataset | 935,472 rows; complete; same source digest as the quote-cost profile |
| Historical timestamp basis | `BLOCKED` — raw server/UTC interpretation remains unverified |
| Mutual information | 0.0198 bits |
| Process-only intensity hypothesis | `REJECTED` |
| Directional/volatility hypotheses | `INCONCLUSIVE` |
| Edge claim | `NOT ESTABLISHED` |
| Strategy promoted | `false` |

The short sample and unresolved historical clock basis prevent session-aware or
execution-aware claims. The scan also does not contain fills, commission,
slippage, swap, or forward validation. Its measured quote-spread companion is
documented separately in
`docs/research/mt5_tick_cost_profile_2026-10-23.md`.

## Decision

This channel is not eligible for QTS registration or automatic execution. The
next useful experiment is to extend the read-only tick ledger over a longer
period while preserving raw broker time, measured offset evidence, receipt
time, and quote provenance. If the timestamp basis becomes confirmed, the
predeclared microstructure family can be evaluated again on genuinely unseen
data; no threshold or hypothesis should be mined from this seven-day result.

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
