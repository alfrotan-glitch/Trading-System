# Preregistration — fixed opening-range XAUUSD assay

## Question

Does a fixed UTC opening-range breach predict a cost-surviving intraday
XAUUSD move on the confirmed broker bid/ask ledger, and does fading the same
breach perform better than following it?

This is a research-only assay. It does not authorize any order;
`LIVE` remains locked and order submission remains disabled.

## Data and execution

- Use the complete local 365-day MT5 bid/ask tick ledger with the confirmed
  same-session timestamp basis and dataset digest binding.
- Aggregate ticks into one-minute bid/ask bars without repair or reordering.
- For each UTC day, examine exactly two fixed event starts: 08:00 and 13:30.
- Build the opening range from the first 30 complete contiguous one-minute
  bars. The range high and low are the extrema of the quote mid high/low.
- In the next 60 complete contiguous minutes, use the first bar whose mid
  high exceeds the range high or whose mid low falls below the range low. If
  both boundaries are breached in that bar, discard the event as ambiguous.
- The breach bar is observed at its close. Enter at the next one-minute bar
  open, using ask for a long and bid for a short. Exit at the close of the
  30th one-minute bar including the entry bar, using bid for a long and ask
  for a short. Events with gaps through the exit are discarded.
- At most one position is selected at a time; a later signal is skipped while
  the prior fixed exit is open.

## Fixed hypotheses

1. `H-ORB-01-BREAK`: follow the first boundary breach.
2. `H-ORB-01-FADE`: take the opposite direction.

The event times, range length, breakout window, latency, exit horizon, and
both direction mappings are fixed before evaluation. There is no parameter,
session, threshold, regime, model, or post-hoc selection search.

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
