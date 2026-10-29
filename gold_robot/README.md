# QTS Gold Robot — MetaTrader 5 on Windows

**Status: installed/compiled source research; current revision requires local MetaEditor verification. No confirmed profitable strategy. LIVE LOCKED.**

This directory contains **one canonical Expert Advisor**, `mt5_robot/QTS_Gold_Robot.mq5`, plus its `ExecutionPolicy.mqh`, `StructureResearch.mqh`, installer, broker audit and research. It is **not** the Python `ROBOT.bat` engine.

## Clone, install, report

From the repository root, double-click **`START_HERE.bat`**. Select **1** to install/compile the Gold EA and preflight script using **one selected MT5 terminal and compiler**. On your `XAUUSD@` chart run `QTS_Broker_Preflight`. Select **2** to create a local, clean HTML/JSON broker/readiness report, which rejects stale or mismatched broker-preflight sources and artifacts; it never sends orders.

[The Windows operator guide](docs/WINDOWS_START.md) is the recommended complete operator procedure. The generated reports are excluded from Git. For quick reporting without the menu, double-click `MAKE_REPORT.bat`.

## Four MT5 Strategy Tester candidate entries

| Input `EntryStyle` | Behavior |
|---|---|
| 0 (default) | Deep former-stop LIMIT |
| 1 | Shallower retest LIMIT |
| 2 | Closed-bar structural breakout → confirmation → retest LIMIT |
| 3 | Closed-bar sweep → reclaim → confirmation LIMIT (previous family negative in independent research) |

Each candidate uses the **same EA order validation, safety ledger, SL/TP and cost/risk checks**. No external LuxAlgo/OTT/QQE implementation has been silently injected. New entries are permitted in **Strategy Tester** or in an explicitly authorized **WMMarkets connected DEMO Forward** trial (both `EnableDemoOrders` and `EnableDemoForwardOrders` must be true). Defaults are observe-only. Connected DEMO Forward is capped to at most **0.25% of equity** per new trade by default, maintains daily and drawdown latches, and remains unvalidated. REAL accounts are structurally blocked. See [DEMO Forward guide](docs/DEMO_FORWARD_OPERATIONS.md).

The input `TesterIgnoreDailyAndPeakStops=true` allows a Strategy Tester census of later opportunities after a losing day: daily equity halt, peak-equity halt and trade/pending daily counts are ignored **only in tester**. Per-trade risk, legal volume, broker margin, SL/TP, spread, session and execution-incident halts remain enforced. Connected demo and real accounts cannot use this bypass.

Choose **option 5** to generate four consistent `.set` input profiles in `gold_robot/reports_local/tester_presets`; in MT5 Strategy Tester use **Inputs → Load** one at a time. These profiles always set `EnableDemoForwardOrders=false`. Generate only; they do not launch the terminal or place broker orders.

Native MT5 tester deposit for the operator's setup: **USD 3,000**, the smallest value their terminal permits selecting. This is **not** a claim that WMMarkets real account funding minimum is USD 3,000 or that any deposit should be funded. Run M15 then M5 separately, on **Every tick based on real ticks**, four entries one at a time, and keep costs and test periods fixed.

Choose **option 6** to compare the four user-exported native MT5 HTML reports (named `QTS_0.htm` through `QTS_3.htm` in `gold_robot/reports_local/native`). The report displays original Tester metrics, missing/invalid files conspicuously and never promotes a strategy automatically. It does not send broker orders. Agent `.log` files are not HTML reports: allow the MT5 test to finish, export **Save as Report** from the Backtest/Report panel, and preserve journal logs separately. The comparator explicitly labels mislabeled logs `LOG_ONLY`.

Style 0 uses `RewardToRisk` as a **minimum** while selecting a prior swing extreme as its target; it can realize far more than 1R. Styles 1–3 target approximately the configured multiple of stop distance. These are different research exit models and must not be mistaken for identical fixed 1:1 scalps.

Option 5 creates four opportunity-census tester profiles and four alternative `tester_presets/safety_on/` profiles; use the latter to check ordinary daily/peak equity stops before evaluating readiness. Neither profile authorizes connected DEMO or REAL orders.

For agent logs, put `QTS_*.log` or mislabeled `QTS_*.htm` files in `gold_robot/reports_local/native`, then run `AUDIT_LOGS.bat` (optional Python 3). The read-only audit reports completed, incomplete and duplicate sessions, and an explicitly hypothetical cost-stress scenario. It never certifies a profitable edge or changes MT5.

## Verification and evidence

- Latest canonical EA was changed after an earlier user-verified successful MetaEditor compile; **the current source must still compile on the operator's terminal**.
- Repository tests and GitHub Windows PowerShell smoke tests validate static invariants and report generation, **not live broker trading or a profitable edge**.
- Historical M15 result: 18 completed trades, PF 0.98, a net loss (older source revision); **not** proof of performance of the new entries.
- DEMO-forward virtual-money tests are explicitly opt-in; verify MT5 native compilation and broker limits before enabling. Commission, swap, slippage, rejects, disconnects and independent after-cost expectancy remain unverified.
- Real-money account trading is structurally blocked and must not be enabled in a source-only handoff.

Read the [2026-10-29 production evidence gate](docs/PRODUCTION_EVIDENCE_2026-10-29.md), [engineering release handoff](docs/RELEASE_HANDOFF_2026-10-27.md), [release status](docs/RELEASE_STATUS.json), [prior trade evidence](docs/PERFORMANCE_REPORT.md), [research with $3000](docs/MT5_3000_UNLIMITED_TESTER_2026-10-26.md), and [Stop Loss root cause plan](docs/OWNER_PLAN_STOPLOSS_ROOTCAUSE_2026-10-26.md).
