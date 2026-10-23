# Preregistration — fixed volatility-regime directional assay

## Question

Does a fixed regime-adaptive rule on confirmed-basis XAUUSD bid/ask data
survive executable quote costs and chronological out-of-sample testing?

This is a research assay only. It does not authorize an order; `LIVE` remains
locked and order submission remains disabled.

## Data and construction

- Use the complete local 365-day MT5 bid/ask tick ledger whose timestamp basis
  was measured in the same read-only session and bound to the dataset digest.
- Aggregate ticks into one-minute bid/ask bars without repair or reordering,
  then retain only complete contiguous five-minute groups of five consecutive
  one-minute bars. A missing minute invalidates that five-minute group.
- The signal is formed at a completed five-minute bar close. Entry is the next
  five-minute bar open. Exit is the close three bars after entry (15 minutes).
  Any sample crossing a missing five-minute interval is excluded.
- Define the existing chronological 60/40 discovery/holdout boundary by the
  five-minute bar timestamps. The holdout is evaluated once and is not used
  to select a rule.

## Fixed rule

At signal bar `i`, calculate the absolute log return of each completed
five-minute bar. Let `recent_rv` be the mean absolute return over bars
`i-11..i`, and `baseline_rv` be the mean over bars `i-59..i-12`.

- If `recent_rv / baseline_rv >= 1.5`, take the sign of the completed bar `i`
  return (volatility-expansion continuation).
- If `recent_rv / baseline_rv <= 0.75`, take the opposite sign (volatility-
  contraction reversal).
- Otherwise do not trade. Zero-return signals are ignored.

The thresholds, windows, horizon, and direction mapping are fixed before the
run. There is no parameter search, fitted model, threshold search, session
filter, or post-hoc rule selection.

At most one trade may be open. After a selected signal, the next eligible
signal begins only after the fixed exit. Long execution uses ask at entry and
bid at exit; short execution uses bid at entry and ask at exit.

## Evaluation and gates

Evaluate five chronological folds over the last 80% of discovery after a 20%
warm-up, plus one frozen 40% holdout. Report every fold and the holdout.
Apply extra round-trip stress of 0, 1, and 2 bps to the entry mid; the 2 bps
case is the primary cost gate. Require at least 500 non-overlapping trades in
each fold and the holdout, at least four positive folds at 2 bps, positive
holdout mean net bps, and a 95% moving-block bootstrap interval above zero.

The result is `PROMISING_NOT_VALIDATED` only if every gate passes. Otherwise it
is `REJECTED` when the sample minimum is met and a cost/inference gate fails,
or `INCONCLUSIVE` when sample or inference requirements are not met. No result
promotes a strategy into QTS.

Commission, slippage, and financing are unmeasured. Quoted bid/ask cost is
measured directly from the ledger. No MT5 order API is called; the output must
record zero orders, `DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
