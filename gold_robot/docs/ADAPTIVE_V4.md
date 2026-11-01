# QTS Gold V4 — A different strategy for each *eligible opportunity*

**Research only. LIVE LOCKED; profitable edge NOT validated.**

## The defect this addresses

The existing Style 7 adaptive router determines a closed-bar trend/range/transition regime but considers only Style 0–6. The independent SMC Style 8 is not evaluated. Choosing among 0–6 therefore did **not** mean that the robot evaluated every compatible strategy. V4 is an isolated, optional competing hypothesis, not a rewrite of an already viewed baseline.

### At every NEW completed M15 candle

1. Update the ADX/EMA-gap/ATR market regime using only *closed* candles. Require three consecutive closed-bar regime observations; abstain on missing indicators or ATR spikes.
2. Reevaluate every eligible independent family: former-stop (0), retest (1), break-and-retest (2), sweep-and-reclaim (3), trend-impulse (4), range-rejection (5), inside-bar breakout (6), and SMC FVG/OB mitigation (8). Style 7 is the selector, not another entry strategy.
3. Route the candidate through its **own** signal generator and own limit-order/SL/TP construction. An SMC opportunity must use `CompletedSmcSignal` and `PrepareSmcLimit`, never be relabeled as Style 4.
4. For *each* candidate, veto unsuitable direction/geometry, unaffordable broker minimum lot or margin, closed H1/M15/M5 context, support/resistance, after-cost reward to stressed-stop risk below 1.25, or transition uncertainty. The broker's `OrderCalcProfit` and the EA's conservative assumed cost/slippage inputs are used; no purported win probability is invented.
5. Score only surviving candidates using frozen context priority, after-cost reward/risk, spread/risk, and current distance from the passive limit entry. Choose one best-scoring candidate with a deterministic tie-break; never place multiple orders from the same decision. If none survives, `NO_TRADE`.
6. Log every reviewed style with signal/limit/risk/context/score rejection reason and the final choice. The parent EA **rechecks** the chosen candidate and preserves its atomic order mutex, broker preflight, server-side expiry, global drawdown guards and demo/tester-only trading permissions.
7. New opportunities can select *different* strategies based on contemporaneous closed-bar conditions, but V4 does NOT rewrite or reverse an existing position's original stop/target using later signals; that would be a new and separately validated position-management model.

### Why M1 scalp (Style 9) is excluded from this V4 M15 selector

Style 9 **requires M1 as SignalTimeframe and a frozen 15-minute position cap**. Combining it with an M15 Style 7 parent EA without a genuinely independent M1 indicator/clock/position-state engine would silently run wrong data and duration. V4 explicitly excludes 9; testing that additional family requires a distinct clock-synchronized multi-timeframe sub-engine and an isolated hypothesis. Do not claim all ten strategies are integrated.

### Isolated native Strategy Tester A/B

The new `TesterUseAdaptiveRouterV4` input defaults **false** and is permitted only with `TesterUseMarketContextV3=true`, `EntryStyle=7`, `SignalTimeframe=PERIOD_M15` and `MQL_TESTER` enabled. No connected DEMO or LIVE authorization. The installer includes hash-matched `AdaptiveV4Research.mqh` and restores the old file/EX5 on an unsuccessful native compile.

From the repository on Windows, using the real-tick Strategy Tester, run **separate** historical datasets with identical symbol, broker and account assumptions:

```powershell
.\gold_robot\research\RunAutomaticTester.ps1 -OnlyStyles 7 -ResearchVariant BASELINE -FromDate 2026.04.01 -ToDate 2026.10.01 -NoOpen
.\gold_robot\research\RunAutomaticTester.ps1 -OnlyStyles 7 -ResearchVariant CONTEXT_V3 -FromDate 2026.04.01 -ToDate 2026.10.01 -NoOpen
.\gold_robot\research\RunAutomaticTester.ps1 -OnlyStyles 7 -ResearchVariant ADAPTIVE_V4 -FromDate 2026.04.01 -ToDate 2026.10.01 -NoOpen
```

**These 2026 April–October dates have already been inspected and are exploratory**, not an untouched holdout. The script only captures native reports; there is no automatic promotion, learning from winning hindsight, or evidence of profitability without independent evaluation. Inspect original HTML, orders, deals, Experts journals, style-selection reasons and stop/rebound paths; preserve raw data hashes. Across future complete months compare V4 and V3 not only on win rate but net after independently measured costs, skipped setups, per-strategy attributed fills, maximum drawdown, position frequency, account-size feasibility and statistical uncertainty.

The V4 scoring weights are **frozen engineering hypotheses**, not learned optimum parameters. Tuning them after seeing P&L resets the unseen evaluation window.

**Native Windows MetaEditor zero-errors/zero-warnings compilation and WMMarkets real-tick testing are pending. Static GitHub tests do not substitute for them.**
