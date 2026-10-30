# QTS Gold Robot — MetaTrader 5 on Windows

**Status: installed/compiled source research; current revision requires local MetaEditor verification. No confirmed profitable strategy. LIVE LOCKED.**

This directory contains **one canonical Expert Advisor**, `mt5_robot/QTS_Gold_Robot.mq5`, plus its `ExecutionPolicy.mqh`, `StructureResearch.mqh`, `OpportunityResearch.mqh`, `AdaptiveResearch.mqh`, installer, broker audit and research. It is **not** the Python `ROBOT.bat` engine.

## Clone, install, report

**Automatic testing (recommended):** close the WMMarkets MT5 window, then double-click **`QTS_AUTO_TEST.bat`** in the repository root. It locates the installed canonical QTS EA, compiles it if needed, runs seven fixed and one adaptive M15 real-tick Strategy Tester cases with normal daily/peak risk stops, saves native HTML results, and opens one local `OPEN_RESULTS.html` summary. If the terminal, login/history or report export cannot be verified, it fails closed and explains the exact blocker. It never sends connected orders, never changes login/passwords, and never certifies profitable edge. For manual installation or diagnostics, double-click **`START_HERE.bat`**. Select **1** to install/compile the Gold EA and preflight script using **one selected MT5 terminal and compiler**. On your `XAUUSD@` chart run `QTS_Broker_Preflight`. Select **2** to create a local, clean HTML/JSON broker/readiness report, which rejects stale or mismatched broker-preflight sources and artifacts; it never sends orders.

**Adaptive forensic breakdown (without retesting MT5):** `QTS_SHARE_RESULTS.bat` now first generates `QTS_ADAPTIVE_REVIEW.html` and `.json` from the last run's `QTS_TRADE_BY_TRADE.json` and comparison report. It shows which fixed family Style 7 *actually* selected for each filled position, contribution by family, stop/target exits, monthly results, added-cost stress scenarios and worst positions, with a strict aggregate reconciliation. Its strategy labels come from exact broker entry-order comments, never guessed market regimes. Without the original decision log it cannot prove which other strategy would have won on the same entry. Then it packages the JSON with the original deals; no new MT5 test is needed.

**After a completed automatic run:** double-click `QTS_SHARE_RESULTS.bat` to locate the latest run and create `QTS_SHARE_RESULTS.zip` containing trade-level CSV and summary JSON only, without raw MT5 native HTML, account statements, passwords, terminal logs or broker login information. The ZIP is created locally; the script never uploads anything. Share that ZIP only if you want an independent per-trade investigation. If any strategy CSV is missing, the ZIP explicitly says `INCOMPLETE_FORENSIC_EVIDENCE` and must not be treated as a finished trade audit.

[The Windows operator guide](docs/WINDOWS_START.md) is the recommended complete operator procedure. The generated reports are excluded from Git. For quick reporting without the menu, double-click `MAKE_REPORT.bat`.

## SL → post-exit quote-path investigation (research only)

Run \`QTS_SHARE_RESULTS.bat\` after an eight-strategy real-tick test, then
double-click the repository-root \`QTS_POST_STOP_REVIEW.bat\`.
It reads only the saved evidence ZIP and produces a normalized SL-case CSV
plus a conservative evidence summary in the selected run's \`post_stop_review\`
folder. No MT5 login or broker order is needed.

**A saved SL/TP ledger has no future quotes.** To answer whether the quote
later returned to entry or reached the *original TP*, first export the
same-broker executable bid/ask ticks via \`research/ExportBrokerData.mq5\`.
Set \`QTS_BROKER_TICKS_DIR\` to the resulting directory of daily
\`ticks_<day>.csv\` files before rerunning the batch file. The existing
\`stop_reversal_audit.py\` now verifies complete 5/15/30/60/120-minute
post-stop tick windows and records first TP touch and best/worst executable
quote extrema; absent data remains UNKNOWN. Never mistake a later TP touch
for realizable trade profits. See
[the 2026-10-30 forensic audit](docs/POST_STOP_FORENSIC_EVIDENCE_2026-10-30.md).

## Seven fixed strategies plus one adaptive research router

| Input `EntryStyle` | Behavior |
|---|---|
| 0 (default) | Deep former-stop LIMIT |
| 1 | Shallower retest LIMIT |
| 2 | Closed-bar structural breakout → confirmation → retest LIMIT |
| 3 | Closed-bar sweep → reclaim → confirmation LIMIT (previous family negative in independent research) |
| 4 | Strong trend impulse → passive shallow retracement LIMIT (Tester-only) |
| 5 | Prior range-edge rejection → fade/retest LIMIT (Tester-only) |
| 6 | Mother / inside / breakout pattern → passive retest LIMIT (Tester-only) |
| 7 | **Adaptive router**: on each completed bar, classify range / transition / trend from closed ADX and EMA gap; evaluate allowed fixed families, select at most one risk-feasible LIMIT candidate or abstain (Tester-only, unvalidated) |

Each candidate uses the **same EA order validation, safety ledger, SL/TP and cost/risk checks**. **Styles 4–7 are strictly Strategy Tester-only** and cannot initialize on a connected DEMO or REAL terminal. Individual position outcomes are exported with broker entry/exit reasons and price/SL/TP evidence; trading cost and signal quality require separate evaluation. No external LuxAlgo/OTT/QQE implementation has been silently injected. New entries are permitted in **Strategy Tester** or in an explicitly authorized **WMMarkets connected DEMO Forward** trial (both `EnableDemoOrders` and `EnableDemoForwardOrders` must be true). Defaults are observe-only. Connected DEMO Forward is capped to at most **0.25% of equity** per new trade by default, maintains daily and drawdown latches, and remains unvalidated. REAL accounts are structurally blocked. See [DEMO Forward guide](docs/DEMO_FORWARD_OPERATIONS.md).

The input `TesterIgnoreDailyAndPeakStops=true` allows a Strategy Tester census of later opportunities after a losing day: daily equity halt, peak-equity halt and trade/pending daily counts are ignored **only in tester**. Per-trade risk, legal volume, broker margin, SL/TP, spread, session and execution-incident halts remain enforced. Connected demo and real accounts cannot use this bypass.

Choose **option 5** to generate seven consistent `.set` input profiles in `gold_robot/reports_local/tester_presets`; in MT5 Strategy Tester use **Inputs → Load** one at a time. These profiles always set `EnableDemoForwardOrders=false`. Generate only; they do not launch the terminal or place broker orders.

Native MT5 tester deposit for the operator's setup: **USD 3,000**, the smallest value their terminal permits selecting. This is **not** a claim that WMMarkets real account funding minimum is USD 3,000 or that any deposit should be funded. Run M15 then M5 separately, on **Every tick based on real ticks**, seven entries one at a time, and keep costs and test periods fixed.

Choose **option 6** to compare the seven user-exported native MT5 HTML reports (named `QTS_0.htm` through `QTS_6.htm` in `gold_robot/reports_local/native`). The report displays original Tester metrics, missing/invalid files conspicuously and never promotes a strategy automatically. It does not send broker orders. Agent `.log` files are not HTML reports: allow the MT5 test to finish, export **Save as Report** from the Backtest/Report panel, and preserve journal logs separately. The comparator explicitly labels mislabeled logs `LOG_ONLY`.

Style 0 uses `RewardToRisk` as a **minimum** while selecting a prior swing extreme as its target; it can realize far more than 1R. Styles 1–7 target approximately the configured multiple of stop distance, subject to technical level feasibility. These are different research exit models and must not be mistaken for identical fixed 1:1 scalps.

Option 5 creates seven opportunity-census tester profiles and seven alternative `tester_presets/safety_on/` profiles; use the latter to check ordinary daily/peak equity stops before evaluating readiness. Neither profile authorizes connected DEMO or REAL orders.

For agent logs, choose **option 8** in `START_HERE.bat` (requires Python 3) or run `AUDIT_LOGS.bat`. It searches `gold_robot/reports_local/native`, Downloads, Desktop and Documents by actual log contents (not QTS filename), and allows choosing a saved file from a Windows picker when no log is detected. A readable HTML report and JSON are created even if the search found no logs; the result is marked `NO_AGENT_LOGS_FOUND`, not a failed strategy. Native MT5 HTML reports should be analyzed with option 6. No file copying or renaming is required. The read-only audit reports completed, incomplete and duplicate sessions, and an explicitly hypothetical cost-stress scenario. It never certifies a profitable edge or changes MT5.

## Verification and evidence

- Latest canonical EA was changed after an earlier user-verified successful MetaEditor compile; **the current source must still compile on the operator's terminal**.
- Repository tests and GitHub Windows PowerShell smoke tests validate static invariants and report generation, **not live broker trading or a profitable edge**.
- Historical M15 result: 18 completed trades, PF 0.98, a net loss (older source revision); **not** proof of performance of the new entries.
- DEMO-forward virtual-money tests are explicitly opt-in; verify MT5 native compilation and broker limits before enabling. Commission, swap, slippage, rejects, disconnects and independent after-cost expectancy remain unverified.
- Real-money account trading is structurally blocked and must not be enabled in a source-only handoff.

Read the [2026-10-29 production evidence gate](docs/PRODUCTION_EVIDENCE_2026-10-29.md), [engineering release handoff](docs/RELEASE_HANDOFF_2026-10-27.md), [release status](docs/RELEASE_STATUS.json), [prior trade evidence](docs/PERFORMANCE_REPORT.md), [research with $3000](docs/MT5_3000_UNLIMITED_TESTER_2026-10-26.md), and [Stop Loss root cause plan](docs/OWNER_PLAN_STOPLOSS_ROOTCAUSE_2026-10-26.md).
