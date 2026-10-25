# QTS Gold Robot — Windows MT5 scalping research

**Status:** NOT RELEASED · no validated profitable strategy · LIVE orders locked.

This folder begins the direct GitHub integration of the locally reviewed Windows XAUUSD Expert Advisor. The complete uploaded MQL5 source is **not yet committed here**. The current files are production-minded, separately tested *research components*, not a runnable bot by themselves. Do not mistake this for a release.

## What is available on GitHub

- `research/small_account_risk.py`: risk-budget and volume-rounding audit for $100/$200 equity, 1% default and 2% absolute configured ceiling, estimated fees/slippage, broker-minimum-lot and margin veto.
- `research/edge_gate.py`: independently reports fills/day, win rate, net expectancy, profit factor, day-block bootstrap, drawdown, and costs from explicit trade ledgers; positive historical screens are never labelled live-approved.
- `tests/`: regression tests for zero-trade, many-trade-but-losing, margin, fee, and capital-loss cases.
- `.github/workflows/gold-robot-research.yml`: CI executes the research tests on GitHub.

## Findings from the supplied local EA source

The original native tester Jan–Jun 2025 run reported 136 accepted pending LIMIT orders and 18 completed trades, a 13.2% fill rate, native net **-$5.54**, and PF **0.98** on a simulated $10,000 balance before additional assumptions. It cannot be represented as evidence for a $100/$200 account or sustained profitable daily scalping.

The source-only experimental local upgrade introduced an M5 research option, a near-market structural retest LIMIT candidate alongside the original former-stop LIMIT, configurable 1.0R research TP, stronger fee/slippage-aware risk sizing, and capacity for eight daily fills / twenty pending attempts. These are *limits, not promised trades*. The revised source-level Python suite passed 63 tests locally but **no native MetaEditor build or real-tick tester run** has been completed for that revised EA.

## Non-negotiable validation

1. Import the sanitized canonical EA and execution policy, maintaining real-account prohibition.
2. Compile with the installed local MetaEditor and run real-tick MT5 Strategy Tester on **both $100 and $200 starting equity** with actual contract/margin/tick information, costs, and commission stress.
3. Compare former-stop LIMIT vs nearer retest LIMIT on independent development and validation data. Score actual filled trades and missed orders, rather than signal frequency alone.
4. Record trades per day, TP-before-SL, median time-to-exit, gross P&L, net after spread/commission/slippage, confidence intervals, maximum drawdown and restart safety.
5. Do not enable unattended DEMO or LIVE execution just to increase trade count. No algorithm can guarantee daily profit or near-100% target hits.

The public GitHub repository intentionally excludes account logins, passwords, broker tick history, installed binaries, tester logs and other machine-local data.
