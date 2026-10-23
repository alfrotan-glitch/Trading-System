# Preregistration — corrected compressed-range XAUUSD breakout assay

## Motivation and correction

An earlier M15 discovery screen named `H-VOL-COMP-BREAK-8` reported positive
holdout results under assumed price-distance costs. Its implementation did
not apply the recorded compression condition to the breakout signal, so that
result is not evidence for the stated hypothesis. This assay fixes that
definition before looking at the confirmed broker-ledger result. It is a
retest of a recorded, non-promoted hypothesis, not a parameter search.

This is research-only. It does not authorize any order;
`LIVE` remains locked and order submission remains disabled.

## Fixed question and data

Does a completed fifteen-minute close break from a compressed recent range
predict a cost-surviving next-bar move on the confirmed broker bid/ask ledger?

- Use the complete local 365-day MT5 bid/ask tick ledger with confirmed
  same-session timestamp basis and dataset digest binding.
- Aggregate without repair or reordering into complete contiguous fifteen-
  minute bars. Missing minutes invalidate the affected bar.
- For signal bar `i`, compute each prior bar's mid-price range divided by its
  close mid. The recent range statistic is the median of bars `i-32` through
  `i-1`. The baseline is the median of the 256 prior recent-range statistics
  ending at `i-1`. Compression requires recent < baseline.
- The signal direction is +1 when the completed close exceeds the prior
  32-bar mid high, or -1 when it falls below the prior 32-bar mid low. No
  signal is created when neither boundary is breached.
- Enter at the next fifteen-minute bar open using ask for long and bid for
  short. Exit at the close of the eighth bar including entry, using bid for
  long and ask for short. A sixteen-bar exit is the fixed stability check.
- Select at most one non-overlapping position; a signal during an open
  position is skipped.

## Evaluation and gates

Use five chronological folds over the last 80% of the discovery prefix after
a fixed 20% warm-up, plus one untouched 40% holdout. Apply 0, 1, and 2 bps
extra round-trip stress to entry mid; 2 bps is primary. Require at least 500
non-overlapping trades in every fold and holdout, at least four positive folds,
positive holdout mean, and a 95% moving-block bootstrap interval above zero for
both the eight-bar primary and sixteen-bar stability horizons. A result is
`PROMISING_NOT_VALIDATED` only if every gate passes; otherwise it is
`REJECTED` when both horizons meet the sample minimum and a gate fails, or
`INCONCLUSIVE` when sample or inference requirements are unmet.

Quoted bid/ask cost is measured. Commission, slippage, and financing remain
unmeasured. No MT5 order API is called; record zero orders,
`DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
