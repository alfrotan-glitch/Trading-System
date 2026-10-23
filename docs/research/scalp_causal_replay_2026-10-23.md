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

## Stop-fill assumption sensitivity

The replay retains its original conservative stop-exit result. It also reports
`mean_net_bps_if_stop_at_trigger` using the same trade decisions and cost
assumptions, replacing only the intrabar stop exit by a hypothetical stop-price
fill, after the configured exit-slippage assumption. The difference is reported
as `stop_fill_assumption_drag_bps_per_trade`. This is a sensitivity comparison,
**not an upper/lower guarantee**: an actual stop order may slip or gap beyond
its trigger; broker executions must ultimately be validated using sequenced
raw ticks and actual DEMO fills. Neither variant establishes a trading edge.

## Raw MT5 tick stop-touch diagnostic

The optional `--tick-stop-audit` mode reads original raw Parquet quote records
in bounded batches. It locates the first observed **bid** crossing a BUY stop
or **ask** crossing a SELL stop for every stop-ending trade in each of the
previously simulated confirmed and anticipatory trade paths. Tick order must
be nondecreasing; missing stop touches remain explicitly missing and no quote
sequence is fabricated or repaired. Both paths are checked in one raw pass.

The result compares mean quote-side first-touch PnL **among matched stop
trades only**, not the PnL of a rerun strategy. A first observed quote is
not an executed stop order; commission, order routing, slippage, latency,
price gaps and changed subsequent trade paths remain uncertain. This research
never authorizes DEMO or LIVE orders and is not evidence of validated edge.

## Causal tick-sequenced execution replay (research only)

`--tick-execution-replay` independently recomputes two strategy paths using
the original chronological broker bid/ask tick ledger. A signal requires a
completed minute bar; an order candidate enters at the *first quote of the
following minute*, only after passing the frozen spread, movement and
no-chase gates. Exits at the earliest eligible tick use the closing side
(bid for BUY / ask for SELL) and check broker-side stop, discretionary
cost-reserved profit/loss thresholds, and a bounded holding time.

Unlike the earlier stop-touch audit, this replay recomputes *subsequent*
entry opportunities after each tick-level exit. Raw quotes are not fills:
slippage and commission are named assumptions, latency and broker liquidity
are unmeasured, and all trade reports stay in gitignored local raw paths.
Only the previously defined discovery sample is read, and the strategy
does not self-authorize broker orders, DEMO registration, or LIVE execution.

## Windows low-memory tick replay (2026-10-23)

The local research driver uses Arrow batches of 8,192 raw quotes for tick
replays and 16,384 quotes during the preliminary bar build. Bar arrays are
released before the tick pass and the JSON report is written incrementally
through an atomic replacement. Chronology, full discovery scope, broker-side
stops and frozen signal/exit thresholds are unchanged. No sampling, dropping,
reordering, or strategy optimization is permitted. A failed run leaves the
previous successfully written report intact; do not mistake it for new results.
