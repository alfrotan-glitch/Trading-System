# QTS GOLD — adversarial review from ten specialist perspectives
Date: 2026-10-25
Baseline: main at db4d4541df65213d4b9338b6af705c9237943221
Scope: alfrotan-glitch/Trading-System, especially gold_robot/ and broker-facing QTS.
Disposition: NO_VALIDATED_EDGE / MQL5 CURRENT REVISION NOT RELEASED / LIVE LOCKED.

## Method and scope honesty

Ten specialist lenses were reviewed as ten independent analytic workstreams,
with parallel retrieval of relevant repository evidence. No external humans
or autonomous software agents were hired or launched. Ratings below are
engineering *priority* ratings, NOT simulated peer reviews, third-party
certifications or demonstrated monetary returns.

No real WMMarkets broker test or MetaEditor native compile was performed.
All negative strategy evidence below is taken from repository reports, not a
fresh independent reproduction.

## Ten adversarial workstreams

| # | Specialist lens | Finding | Priority | Concrete repository evidence | Required owner-visible acceptance |
|---|---|---|---|---|---|
| 1 | Quant/statistician — edge | M15 EMA 12/48 holdout: -2.52 net bps at 2-bp extra cost; opening-range breakout: -2.98 net bps. **No validated positive expectation**. | P0 | docs/research/mt5_broker_ema_365d_20261023.md; docs/research/mt5_broker_opening_range_365d_20261023.md | Completely new preregistered untouched WMMarkets holdout with positive after-cost expectancy, confidence bounds and trial-accounting; otherwise no promotion |
| 2 | Market-data forensic specialist | Seven-day tick profile contains 935,472 rows but neither commission/slippage/swap nor broker timing basis is verified. A measured quoted spread is **not** round-turn costs. | P0 | data/evidence/mt5_tick_cost_profile_2026-10-23.json | Broker-specific executable Bid/Ask archive, timestamps, trading hours, contract spec, gap reports and direct fee evidence |
| 3 | Strategy researcher | Three existing M5 families (breakout, pullback, liquidity sweep) already exist; adding LuxAlgo/UTBot/OTT without an incremental matched test risks feature mining and overlapping signals. | P1 | gold_robot/research/scalp_signals.py; docs/research/indicator_buy_sell_comparative_2026-10-25.md | Fixed comparator hypotheses and incremental net contribution on future ticks; no unlicensed copied indicator internals |
| 4 | Transaction-cost accountant | The legacy research edge screen silently treated all gross P&L as pre-slippage and subtracted slippage, even when actual broker fill prices already embedded it. It also did not require a unique completed-trade ID. | P0 | gold_robot/research/edge_gate.py (baseline before this PR); gold_robot/research/reference_benchmark.py | Explicit gross basis, all costs, duplicate prevention, complete trades not partial closes, cost stress, no fabricated fees |
| 5 | Risk officer | MQL EA defaults to 1.0% per trade with cap 2.0%; QTS Python risk authority commonly uses 50 bps. On $100/$200 a minimum 0.01 lot may breach risk budget. No risk setting alone guarantees gap-loss ceiling. | P0 | gold_robot/mt5_robot/QTS_Gold_Robot.mq5; src/qts/risk/engine.py; gold_robot/docs/RELEASE_STATUS.json | Harmonized owner-approved per-account risk with minimum-volume/margin tests on $100/$200; portfolio correlated exposure and marked-equity daily stops |
| 6 | Broker execution / MQL5 specialist | MQL5 orders use deep LIMIT, strategy gate, persistent receipt reconciliation. Older native run accepted 136 pending orders but only 18 completed fills; native compile evidence is NOT for latest revision. | P0 | gold_robot/docs/PERFORMANCE_REPORT.md; gold_robot/docs/ACCEPTANCE_CHECKLIST.md | Current-source MetaEditor zero-error compile, native real-tick backtest of M5/M15, connected DEMO order lifecycle, restart, partial fills and expired orders |
| 7 | Backtest/causality specialist | Backtest engine submits on next bar (good) but its BacktestResult.trades equals fill-record count; profit_factor is derived from bar returns rather than completed-trade ledger. Reporting them as trade-count or trade-PF is misleading. | P1 | src/qts/backtest/engine.py, lines around BacktestResult return; src/qts/validation/metrics.py | Distinct fill count, completed position count, and explicitly labelled return-based vs realized-trade PF; no overlap with future data |
| 8 | Security / deployment specialist | Both code paths have blocks for real-money execution and account authority, but these safeguards must not be weakened to increase trading frequency. Separate Python app and MQL EA must not accidentally run independently against the same account. | P0 | README.md; gold_robot/README.md; src/qts/risk/authority.py | Single documented operator workflow and process/account ownership, confirmed REAL fail-closed behavior, no bypass of provenance/strategy gates |
| 9 | Reliability / site operations specialist | Durable order idempotency/reconciliation exist, but current latest EA requires connected DEMO chaos testing, and historical test logs do not certify unexpected restart/order state. | P1 | src/qts/execution/idempotency.py; gold_robot/docs/ACCEPTANCE_CHECKLIST.md | Disconnection, timeout, duplicated callback, partial close, weekend gaps, restart; zero duplicate economic exposure |
| 10 | Release / customer quality specialist | Research workstation may be built, but Gold EA release manifest explicitly states NOT_RELEASED and latest EX5 not natively compiled. Hence neither profitable production robot nor customer-ready live algorithm exists. | P0 | gold_robot/docs/RELEASE_STATUS.json; gold_robot/README.md | Reproducible binary source checksums, native compile/strategy tester proof, demo forward evidence, clear product gating and rollback |

## Priority decision: do not repeat previous mistakes

1. **Stop asserting profit before proving it.** Unverified GitHub/Reddit success
   curves, parameter tuning and single vendor accounts never constitute a
   reproducible WMMarkets strategy edge.
2. **One canonical MT5 execution engine.** Do not spin up standalone duplicate
   EAs under different magic numbers as a shortcut around position ownership.
3. **Measure total risk, not raw win-rate.** Count correlated exposure,
   position-equity drawdown, realized and unrealized losses, broker minimum
   volume, gap loss and transaction costs.
4. **Adopt published *ideas* legally, not private algorithms.** Prioritize
   a small number of meaningful market-mechanism hypotheses; compare each
   against a neutral price/time matched baseline.
5. **Pin the new sample before testing.** Old QTS 2025-26 windows are research
   evidence and cannot be recycled as a pristine unseen holdout.

## Work implemented in the accompanying PR

- Hardens gold_robot/research/edge_gate.py: explicitly identifies gross P&L
  pricing basis and whether slippage has already been included in fills.
- Requires independent completed trade IDs and valid Gregorian dates; rejects
  duplicate IDs and false active-day counts.
- Requires trial count and uses multiplicity-aware tail resolution; a 1-day
  lucky sample cannot produce a positive screen.
- 7-trade-day circular block bootstrap and >=3 months, >=20 trade days,
  >=100 complete trades, >=40 active market days are necessary for any
  *research-positive* classification.
- Requires a nonzero stated extra-cost stress and broker-native data claim.
  **All provenance is self-reported and not externally verified**.
- Extensive regression tests for cost basis, concentration, multiple trials,
  simulated provenance, rejected malformed records.
- Changes are research-only: no change to MT5 EA, settings, broker order path,
  LIVE authorization, or user capital.

## Follow-up release gates (strict order)

G0  Reject invalid/missing broker provenance, real-tick history, timestamps.
G1  Verify current EA compiles on owner's Windows MetaEditor with its include.
G2  Confirm $100 and $200 accounts have legally affordable size/margin risk.
G3  Frozen strategy vs external-EA baseline: same tick window, same account,
    same cost basis and matched risk; capture filled and unfilled intents.
G4  Walk-forward + untouched later holdout + trial correction, multi-regime.
G5  Stress spreads/slippage/fees, stop gaps, latency and missing ticks.
G6  Connected authorized DEMO full lifecycle plus restart/chaos.
G7  Independent operator acceptance and rollback. LIVE still structurally
    prohibited by QTS source; do not infer real-money permission from G0–G7.

## Honest result

The audit identifies important measurable blockers and one corrected research
screen. It DOES NOT provide a profitable MT5 binary or certify a production
trading strategy. Negative or missing results remain explicit failures.
