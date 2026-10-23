# Preregistration — fixed EMA(12/48) trend-state XAUUSD assay

## Question

Does following the causal sign of a five-minute EMA(12)-EMA(48) state predict
a cost-surviving next 30-minute XAUUSD move on the confirmed broker bid/ask
ledger?

This is research-only. It does not authorize any order; `LIVE` remains locked
and order submission remains disabled.

## Fixed rule and execution

- Use the complete local 365-day MT5 bid/ask tick ledger with confirmed
  same-session timestamp basis and dataset digest binding.
- Aggregate only complete contiguous five-minute bars, without repair or
  reordering.
- At the close of bar `i`, update EMA(12) and EMA(48) on close mids using the
  standard alpha `2/(period+1)`. Follow the sign: long when EMA(12) is above
  EMA(48), short when below. Reset both EMAs at any observed gap and require
  48 contiguous bars before the first signal.
- Enter at the next five-minute bar open using ask for long and bid for short.
  Exit after exactly 6 bars including entry for the primary horizon and 24
  bars including entry for the fixed stability horizon. Use bid for long exits
  and ask for short exits.
- Select at most one non-overlapping position. Gaps invalidate the affected
  signal-to-exit interval.

## Evaluation and gates

Use five chronological folds over the last 80% of the discovery prefix after
a fixed 20% warm-up, plus one untouched 40% holdout. Apply 0, 1, and 2 bps
extra round-trip stress to entry mid; 2 bps is primary. Require at least 500
non-overlapping trades in every fold and holdout, at least four positive folds,
positive holdout mean, and a 95% moving-block bootstrap interval above zero for
both horizons. A result is `PROMISING_NOT_VALIDATED` only if every gate passes;
otherwise it is `REJECTED` when both horizons meet the sample minimum and a
gate fails, or `INCONCLUSIVE` when sample or inference requirements are unmet.

Quoted bid/ask cost is measured. Commission, slippage, and financing remain
unmeasured. No MT5 order API is called; record zero orders,
`DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
