# Preregistration — fixed RSI(2) oscillator XAUUSD assay

## Question

Does fading fixed RSI(2) close extremes predict a cost-surviving next
30-minute XAUUSD move on the confirmed broker bid/ask ledger?

This is research-only. It does not authorize any order;
`LIVE` remains locked and order submission remains disabled.

## Fixed rule and execution

- Use the complete local 365-day MT5 bid/ask tick ledger with confirmed
  same-session timestamp basis and dataset digest binding.
- Aggregate only complete contiguous five-minute bars, without repair or
  reordering.
- At the close of bar `i`, calculate simple RSI(2) from the two latest close
  mid changes through `i`. If RSI is at or below 10, signal long; if RSI is at
  or above 90, signal short. A flat two-change window is RSI 50 and is not a
  signal.
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
