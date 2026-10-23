# Regime scalping — causal broker-quote replay

The research-only function `qts.research.scalp_replay.replay_scalp_bars`
reuses the same `propose_scalp_entry` and `decide_scalp_exit` functions
as the unregistered one-minute DEMO scalp candidate.

**No same-bar trading:** signals at the close of minute *t* become
eligible only at the first observable bid/ask quote in minute *t+1*.
The entry uses ask for a BUY or bid for a SELL. The exit uses bid/ask
on the correct closing side. Replay subtracts an explicit estimated
entry and exit slippage and round-trip commission. A separate reserve
is used in exit decisions, not booked as a second commission.

**Known limitations:** raw one-minute bar mid highs/lows cannot prove the
order in which the stop or target was hit, or the bid/ask at the exact
intrabar extreme. The simulator therefore labels possible stop fills as
uncertain and charges an adverse approximate execution, rather than
claiming a stop-price fill. Gaps force a close at the first subsequent
observed quote; trading resumes only after fresh contiguous history.
Results are research indicators, not actual live fills or a validated edge.

Research only: no strategy registry is modified, no broker API calls
are made, and LIVE remains locked. Run only on the historical discovery
portion during development; do not optimize parameters using the
already repeatedly inspected holdout. A new independent holdout and
measured DEMO execution costs are necessary before claiming profitability.
