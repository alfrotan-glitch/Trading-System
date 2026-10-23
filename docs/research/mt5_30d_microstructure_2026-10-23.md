# XAUUSD@ 30-day MT5 microstructure continuation — 2026-10-23

**Disposition:** `INCONCLUSIVE`; no validated edge, no promotion, no orders.

This is the larger continuation of the seven-day fixed microstructure scan. It
uses the same predeclared engine and does not retune thresholds or open a
locked period. The sanitized evidence is
`data/evidence/mt5_30d_microstructure_summary_2026-10-23.json`.

## Data and measured quote spread

- One complete read-only tick window: 4,124,595 rows.
- Acquisition and deferred analysis: `COMPLETE` / `PASS`.
- Raw millisecond timestamps: no backward steps; bid/ask validity checks pass;
  no zero spreads.
- Four exact full-row repeats were retained and counted, not discarded.
- Quoted spread: median 0.5769 bps, mean 0.5794 bps, p95 0.6668 bps, maximum
  3.0910 bps.
- The historical raw server/UTC timestamp basis remains unverified.

## Fixed scan result

Mutual information is 0.0303 bits. `H-INT-01` is rejected; `H-QD-01`,
`H-QD-02`, and `H-SP-01` reach `TESTED`; `H-MV-01`, `H-SPR-01`, and
`H-VOL-01` remain inconclusive. The overall decision is still
`INCONCLUSIVE`, with `edge_claim=NOT ESTABLISHED` and
`strategy_promoted=false`.

`TESTED` is not a trading approval: the engine is a discovery scan, not a
broker-fill backtest, and there is no independent out-of-sample or forward
execution evidence. The unresolved clock basis also blocks session claims.

The next useful work is to confirm the timestamp basis and accumulate a longer
prospective broker ledger, then evaluate frozen hypotheses once on unseen data.
Another threshold sweep on this 30-day window would be parameter mining.

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
