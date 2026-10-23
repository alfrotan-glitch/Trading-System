# Preregistration — fixed three-bar sequence assay

## Question

Does a fixed three-bar same-sign sequence in completed five-minute XAUUSD
returns predict a cost-surviving 15-minute move on the confirmed broker
bid/ask ledger?

This assay is research-only. It does not authorize any order;
`LIVE` remains locked and order submission remains disabled.

## Data and execution

- Use the complete local 365-day MT5 bid/ask tick ledger with the confirmed
  same-session timestamp basis and dataset digest binding.
- Aggregate ticks into one-minute bid/ask bars without repair or reordering,
  then retain only complete contiguous five-minute groups of five one-minute
  bars. Missing minutes invalidate the affected five-minute group.
- At the close of bar `i`, inspect the signs of the three completed returns
  `i-2`, `i-1`, and `i`. A signal exists only when all three are nonzero and
  have the same sign, and all four bars through the next entry are contiguous.
- Entry is the next five-minute bar open. Exit is the close three bars after
  entry. Longs use ask at entry and bid at exit; shorts use bid at entry and
  ask at exit. At most one position is open.

## Fixed hypotheses

Both hypotheses are specified before evaluation:

1. `H-SEQ-01-CONT`: follow the sign of the three-bar sequence.
2. `H-SEQ-01-FADE`: take the opposite sign of the sequence.

The sequence length, five-minute interval, latency, exit horizon, and the two
direction mappings are fixed. There is no threshold search, session filter,
regime filter, model fit, or post-hoc selection between the two predeclared
hypotheses.

## Evaluation and gates

Use five chronological walk-forward folds over the last 80% of the discovery
prefix after a fixed 20% warm-up, plus one untouched 40% holdout. Apply extra
round-trip cost stress of 0, 1, and 2 bps to the entry mid; 2 bps is the
primary gate. Require at least 500 non-overlapping trades per fold and in the
holdout, at least four positive folds at 2 bps, positive holdout mean net bps,
and a 95% moving-block bootstrap interval above zero.

Classify a hypothesis as `PROMISING_NOT_VALIDATED` only if every gate passes;
otherwise classify it as `REJECTED` when the sample minimum is met and a gate
fails, or `INCONCLUSIVE` when sample or inference requirements are unmet. No
result promotes a strategy into QTS.

Quoted bid/ask cost is measured. Commission, slippage, and financing remain
unmeasured. No MT5 order API is called; record zero orders,
`DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
