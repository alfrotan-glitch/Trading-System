# QTS Gold V4 — what happened AFTER each stopped strategy?

**Read-only | Research only | No validated positive edge | LIVE LOCKED**

## Motivation

A single native MT5 Adaptive Router Style 7 result hides which actual strategy
produced a stop. The previous evidence pipeline independently records the
original broker entry order comment (`QTSV4-S8-R2`), associates it with
the original MT5 broker position and selected strategy 0..6/8, and reconstructs
the real STOP event timestamps/SL/TP from native deals.

The existing `stop_reversal_audit.py` does the important second half:
replay **chronological executable Bid for a prior BUY** and **Ask for a prior
SELL**, detect entry-price reclaim and original-TP touches after exit, and
mark incomplete quote coverage as UNKNOWN.

The new `v4_post_stop_cohorts.py` combines these two independently obtained
evidence paths so that, for example, **SMC/TREND** and **SWEEP/RANGE** stopped
positions are NOT mixed together under the generic Style 7 label.

## What automatic MT5 research writes

Every eligible `RunAutomaticTester.ps1 -OnlyStyles 7 -ResearchVariant ADAPTIVE_V4`
run additionally creates:

`QTS_V4_POST_STOP_STRATEGY_COHORTS.json`

Without the separate **post-exit native bid/ask tick history** it deliberately
reports `TICKS_MISSING_NO_GO`. A timestamped broker DEAL_HISTORY / HTML report
is insufficient to say whether price later reached the original target.
This is not a failed Strategy Tester run or proof of a losing strategy; the
trading evidence is simply **UNKNOWN**.

## Complete the optional stop-path replay when real quote evidence exists

The owner/operator's previously collected native `QTS_STOP_CASES.csv` and
matched native broker `ticks_*.csv` can be processed with the existing read-only
auditor:

```powershell
python gold_robot/research/stop_reversal_audit.py --stops "QTS_STOP_CASES.csv" --tick-dir "directory_with_matching_ticks" --output "QTS_STOP_REPLAY.json"
```

After generating this separate native tick-backed replay for the **same exact
V4 run**, join it to the V4 position identity report:

```powershell
python gold_robot/research/v4_post_stop_cohorts.py --attribution "QTS_V4_POSITION_ATTRIBUTION.json" --post-stop-replay "QTS_STOP_REPLAY.json" --output "QTS_V4_POST_STOP_STRATEGY_COHORTS_WITH_QUOTES.json"
```

`QTS_STOP_CASES.csv` must originate from the same Style 7 run and contain
`trade_id=7:<broker_position_id>`; build it using
`build_post_stop_inputs.py` and the matching native evidence ZIP, never by
manually guessing exit times, SL, or original TP.

The new audit independently reconciles all stopped position identities,
original broker entry/exit prices, side, SL, TP and stop time. A missing,
foreign, duplicate or modified stop case fails as an **evidence mismatch**.
All horizons (5/15/30/60/120 min) must have complete quote coverage before
a touch or non-touch is counted. Incomplete coverage remains UNKNOWN, with
explicit known/unknown denominators per strategy and market regime.

## Interpretation

A valid post-stop target touch means only that the executable quote eventually
crossed the *original* target after the real position was already stopped. It
is NOT a profitable hypothetical trade and does NOT prove a wider SL,
reverse-at-stop, improved forecast, or missed fill. It does not include the
timing/cost/risks of staying exposed. It must NOT automatically retune the
robot or increase its trade volume.

The same rule applies to missing tick windows: `0 verified TP touches`
with `0 complete quote windows` is UNKNOWN, not an observed 0% recovery.

No research tool may authorize live trading or claim profitability from these
retrospective observations. A promising pattern is only a new candidate
hypothesis, to be preregistered and evaluated in genuine untouched windows,
with the owner's true WMMarkets broker contract and target capital.
