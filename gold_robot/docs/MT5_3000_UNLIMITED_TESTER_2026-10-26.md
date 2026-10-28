# QTS Gold MT5 — Tester-Only Opportunity Census

**Research note, 2026-10-26.** Strategy Tester only. LIVE locked; no validated profitable edge.

## Tester-only bypass

With `TesterIgnoreDailyAndPeakStops=true`, the EA disregards daily-loss and peak-equity halt thresholds and the daily trade/pending counts **only inside MQL_TESTER**, allowing later opportunities to be observed after a losing session. Original settings include a 3% daily loss halt, 8% peak drawdown halt, and 8-trade/20-pending daily limits; inspect the current EA Inputs for authoritative values. Setting the flag to false restores those gates.

The bypass does **not** remove per-trade risk sizing, protective SL/TP, legal minimum volume, margin, spread, session, pending-order or execution-incident controls. Connected DEMO and REAL do not receive the tester bypass. It does not force entries when the strategy does not qualify.

## Four independent entry hypotheses

| EntryStyle | Name | Design |
|---|---|---|
| 0 | `QTS_FORMER_STOP_LIMIT` | Former-stop LIMIT baseline |
| 1 | `QTS_RETEST_LIMIT` | Shallower pullback LIMIT |
| 2 | `QTS_BREAK_ACCEPT_RETEST` | Established structure breaks; later closed candle confirms and retests |
| 3 | `QTS_SWEEP_RECLAIM` | Structure is swept, reclaimed and confirmed on closed candles |

New structure levels derive only from completed candles preceding the signal/confirmation candles, preventing future-bar lookahead. Stops reference invalidation/wicks with ATR/spread allowances; orders failing risk, price or legal lot tests are rejected. These are candidates, not known winners. A related sweep strategy previously lost money in independent research.

OTT, QQE MOD and LuxAlgo SMC have not been incorporated as external source code because independent incremental edge, licensing and robust MT5 translation were not established.

## Reproducible MT5 experiment

1. Update a clean `main` checkout; never mix old ZIP source files into the installed folder.
2. Detach the old EA, run root `START_HERE.bat` option **1**, and verify fresh EX5 files and **0 errors, 0 warnings** for both EA and broker preflight. A failed install must roll back.
3. Open MT5 Strategy Tester with `Ctrl+R`, Expert `QTS_Gold_Robot`, `XAUUSD@`, M15 (repeat M5 separately), **Every tick based on real ticks**, and initial deposit **USD 3,000** (the terminal's user-observed minimum selectable tester deposit).
4. Use `EnableDemoOrders=true` **inside Tester**, `EnableDemoForwardOrders=false`, `TesterIgnoreDailyAndPeakStops=true`, `EnableEntryDiagnostics=true`, and baseline `RiskPerTradePct=0.5`. Run EntryStyle 0, 1, 2 and 3 separately with identical dates, broker times, spreads, commission and latency assumptions.
5. Save each Backtest Report, Deals, Orders and Journal, and preserve actual inputs. Raw signals, accepted orders and filled orders must be counted separately; many LIMIT orders may never fill.

## Stop-loss and evidence interpretation

A stop followed by a price rebound does not establish that the stop was defective. Use `gold_robot/research/stop_reversal_audit.py` with initial stops, execution tickets and correctly timestamped Bid/Ask ticks to examine possible 5/15/30/60/120-minute reversion. This does **not** establish profits from hypothetical holding.

Compare after-cost net profit, profit factor, expectancy in R, rejected orders, stop frequency, max equity drawdown, loss streaks and stability on unseen periods. Tester-only relaxed stops can reveal much larger drawdowns; report them faithfully. Only independent after-cost and broker-execution evidence can support further evaluation.
