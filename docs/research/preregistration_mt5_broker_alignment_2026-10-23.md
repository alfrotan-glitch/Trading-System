# Preregistration — fixed multi-timeframe XAUUSD alignment assay

## Question

Does agreement of fixed 15-minute, one-hour, and four-hour completed-bar
return signs predict a cost-surviving next 15-minute XAUUSD move on the
confirmed broker bid/ask ledger?

This is research-only. It does not authorize any order;
`LIVE` remains locked and order submission remains disabled.

## Fixed rule and execution

- Use the complete local 365-day MT5 bid/ask tick ledger with confirmed
  same-session timestamp basis and dataset digest binding.
- Aggregate only complete contiguous five-minute bars, without repair or
  reordering.
- At the close of bar `i`, calculate close-to-close return signs over exactly
  3, 12, and 48 completed five-minute bars (15 minutes, one hour, four hours).
- Signal only when all three nonzero signs agree; follow that common sign.
- Enter at the next five-minute bar open using ask for long and bid for short.
  Exit after exactly 3 bars including entry for the primary horizon and 12
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
