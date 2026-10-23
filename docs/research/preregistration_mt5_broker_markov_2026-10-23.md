# Preregistration — fixed five-minute return-sign Markov assay

## Question

Does a first-order statistical transition model for completed five-minute
XAUUSD return signs predict a cost-surviving 15-minute move on the confirmed
broker bid/ask ledger?

This is a research assay, not a strategy authorization. `LIVE` remains locked
and order submission remains disabled.

## Data and execution

- Use the complete local 365-day MT5 bid/ask tick ledger whose timestamp basis
  was measured in the same read-only session and bound to its dataset digest.
- Aggregate raw ticks into one-minute bid/ask bars without repair or
  reordering, then retain only complete contiguous five-minute groups of five
  consecutive one-minute bars. Missing minutes invalidate a group.
- A signal is formed at the close of five-minute bar `i`. Entry is the next
  five-minute open, and exit is the close three bars after entry. Samples
  crossing a five-minute gap are excluded.
- The state is only the sign of the completed bar `i` mid-price log return.
  Zero-return states are ignored. The target is whether the executable
  entry-mid to exit-mid move is positive.

## Fixed statistical model

For each walk-forward training prefix, estimate the conditional probability of
a positive target for each state (`-1` and `+1`) using Laplace Beta(1,1)
smoothing. The model is fit only on samples whose signal and exit are before
the test fold. A state produces a long signal when its estimated probability is
at least `0.55`, a short signal at most `0.45`, and no signal otherwise.

The thresholds, smoothing, state definition, bar interval, latency, and exit
horizon are fixed before the run. There is no feature search, threshold search,
session filter, regime selection, or post-hoc model choice. At most one trade
is open; a new eligible signal begins only after the prior fixed exit.

Long execution uses ask at entry and bid at exit. Short execution uses bid at
entry and ask at exit.

## Evaluation and gates

Use five chronological walk-forward folds over the final 80% of the discovery
prefix after a fixed 20% warm-up. Fit each fold on all earlier discovery
samples, then evaluate that fold only. Fit once on all discovery samples for
the untouched 40% holdout. Apply extra round-trip stress of 0, 1, and 2 bps to
the entry mid; 2 bps is the primary gate.

Require at least 500 non-overlapping trades in every fold and the holdout, at
least four positive folds at 2 bps, positive holdout mean net bps, and a 95%
moving-block bootstrap interval above zero. Classify as
`PROMISING_NOT_VALIDATED` only if all gates pass; otherwise use `REJECTED` when
the sample minimum is met and a gate fails, or `INCONCLUSIVE` when sample or
inference requirements are unmet. No result authorizes product integration.

Quoted bid/ask cost is measured. Commission, slippage, and financing remain
unmeasured. No MT5 order API is called; record zero orders,
`DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
