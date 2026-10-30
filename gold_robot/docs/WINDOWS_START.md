# QTS Gold MT5 — Windows Operator Guide

**Scope:** WMMarkets MetaTrader 5, XAUUSD@, Strategy Tester and controlled DEMO evaluation. LIVE trading is locked. No profitable edge has been independently validated.

## One-click automatic research testing

For ordinary use, **close the WMMarkets MT5 terminal** and double-click `QTS_AUTO_TEST.bat` in the repository root. No tester menus, manual .set loading or report naming are required. The script resolves the one installed QTS terminal through MetaQuotes `origin.txt`, verifies matching canonical source and EX5 (or compiles via the matching MetaEditor), copies and checks each Tester parameter profile in the available terminal data/install folders (refusing mismatched copies), prepares eight risk-stops-active `EntryStyle=0..7` profiles (seven fixed strategies and one adaptive router), and runs command-line MT5 Strategy Tester jobs sequentially. The common symbol is `XAUUSD@`, M15, model 4 (real ticks), USD 3,000 simulated, latest six completed calendar months, local agents only. It saves all exports and a local `OPEN_RESULTS.html` under `gold_robot/reports_local/auto_runs/<timestamp>/`. If the terminal is open, multiple targets exist, native ticks are not confirmed, or MT5 cannot export a fresh report, it does not claim success. Do not use a real account; LIVE remains blocked in the EA.

**Trade-by-trade reporting:** each completed native test attempts to export a broker-history forensic CSV from the MT5 Common Files folder. The automatic runner copies it into `native/QTS_0_trades.csv` through `native/QTS_7_trades.csv` and builds `QTS_TRADE_BY_TRADE.html`. Each position is grouped by broker position ID and shows entry/exit, initial versus closing SL/TP, broker exit reason, fees, holding time, exit slippage and incomplete evidence flags. A missing CSV is a research evidence gap, not success. Exact market path, MFE/MAE, and counterfactual reasons for a stop-out require more market data than a deal ledger.

**Attribution of the 8th (adaptive) strategy without new tests:** close MT5 and run `QTS_SHARE_RESULTS.bat` after updating main. It generates `QTS_ADAPTIVE_REVIEW.html` and `.json` alongside the original run. This reconciles every Style 7 broker position with native MT5 trade count and net PnL and groups actual broker entry comments by the selected fixed family. It is not a causal proof of the optimal counterfactual strategy or an independent validation; without original closed-bar decision records market regime per trade remains unknown. Unrecognized setup comments and incomplete transactions are flagged explicitly.

**Sharing evidence without another backtest:** after closing MT5, double-click `QTS_SHARE_RESULTS.bat` from the repository root. It locates the newest completed local run and opens the folder containing `QTS_SHARE_RESULTS.zip` (auto-created after future runs as well). The ZIP contains only summaries and per-position deal CSVs; it deliberately excludes account-bearing native MT5 HTML, terminal logs, account statements and passwords. If any of seven deal CSVs is missing it marks the package INCOMPLETE_FORENSIC_EVIDENCE. Share the ZIP for actual individual-trade analysis; a plain comparison table cannot answer why specific positions reached SL or TP.

**Important:** Native completion and real-tick mode still do not prove an after-cost profitable edge. The actual broker charges, trade count, drawdown, unseen performance and MT5 report inputs remain subject to verification.

## Installation

1. Install WMMarkets MetaTrader 5 and log into a DEMO account. Detach any old QTS EA from the chart.
2. Clone the `main` branch into a new directory. For an unmodified existing clone use `git pull --ff-only origin main`.
3. Run `START_HERE.bat`, option **1**. Select one MT5 Data Folder and its matching MetaEditor. The installer backs up existing files and installs the EA, both include files and broker-preflight script in that same terminal. It must produce **0 errors, 0 warnings** and a fresh EX5 for both components. On failure, inspect the compile log; installation must not be considered successful.
4. Open `XAUUSD@` in the DEMO terminal, refresh Navigator > Scripts and run `QTS_Broker_Preflight`. Return to `START_HERE.bat`, option **2**, to generate a local HTML/JSON readiness report under `gold_robot/reports_local/`.

## Launcher options

| Option | Action | Broker orders |
|---|---|---|
| 1 | Install and compile the MT5 EA and preflight script | None |
| 2 | Generate a local read-only readiness report | None |
| 3 | Open the separate Python research desktop | None |
| 4 | Open this guide | None |
| 5 | Generate seven MT5 Strategy Tester `.set` profiles | None |
| 6 | Compare seven saved native MT5 tester reports | None |
| 7 | Exit | None |
| 8 | Find saved MT5 logs in common folders or choose a file, then open HTML/JSON audit | None |

`ROBOT.bat` is the separate Python research/DEMO entry point. For the MT5 Expert Advisor use `START_HERE.bat`. The MT5 workflow does not require the Python desktop.

## Strategy Tester

Press `Ctrl+R` in MetaTrader 5. Select Expert `QTS_Gold_Robot`, symbol `XAUUSD@`, timeframe **M15** (then test **M5** separately), model **Every tick based on real ticks**, and initial deposit **USD 3,000** (the smallest amount observed as selectable in this operator's terminal). This is a tester setting, not a required real-money deposit.

Use menu option **5** to generate seven profiles in `gold_robot/reports_local/tester_presets/`. Load one profile at a time under Tester > Inputs:

- `EntryStyle=0,1,2,3,4,5,6` in seven separate runs with identical dates, spread/cost conditions and deposit.
- `EnableDemoOrders=true` **in Strategy Tester only**; `EnableDemoForwardOrders=false`.
- `TesterIgnoreDailyAndPeakStops=true` for the experimental opportunity census; this bypass affects only Tester.
- `RiskPerTradePct=0.5` and `EnableEntryDiagnostics=true` for like-for-like research.

The tester-only bypass does **not** disable per-trade risk, minimum lot, margin, protective stops, spread limits or incident halts. The seven candidates are research hypotheses, not approved trading strategies. Option 5 also creates seven `tester_presets/safety_on/` files with the ordinary daily/peak stops ACTIVE. Rerun any promising candidate with the safety-on version; results from stop-bypassed census tests are not production-like.

Let each run finish and confirm the Strategy Tester completion message. From the Tester Backtest/Report results, use Save as Report to export the native HTML report; a MetaTester agent log (including a file renamed to .htm) is NOT an HTML performance report. Export the MT5 Deals, Orders and Journal separately. Save the native HTML reports as `QTS_0.htm` through `QTS_6.htm` in `gold_robot/reports_local/native/`; use menu option **6** for a read-only comparison. Missing files or zero trades are not successful results.

For logs accidentally saved as `.htm`, or journal files with other names, use menu **8**. It checks `gold_robot/reports_local/native/`, Downloads, Desktop and Documents (including OneDrive copies where configured), and identifies MT5 agent logs by their content rather than filenames. If no log is found, Windows offers a file picker. Selecting a saved log does not move or rename it; the program still opens an HTML summary when no file was found. Actual native MT5 HTML performance reports belong in option 6. Option 8 needs Python 3; its figures are diagnostics, not validated profitability.

## Connected virtual DEMO

DEMO-forward orders require a successfully compiled EA, a valid broker preflight, a verified WMMarkets DEMO USD account, the exact `XAUUSD@` symbol and both `EnableDemoOrders=true` and `EnableDemoForwardOrders=true`. Defaults are off. The independent connected-DEMO risk cap defaults to **0.25% per trade** and daily drawdown controls remain active. See [DEMO Forward Operations](DEMO_FORWARD_OPERATIONS.md).

## Troubleshooting and acceptance

- If MetaEditor is missing, press F4 in MT5 and locate the corresponding `metaeditor64.exe`; use File > Open Data Folder to identify the same terminal.
- If the source hashes, compile log, EX5 or preflight CSV are missing/stale, the readiness report must show `ACTION_REQUIRED`. Re-run preflight after installing current sources.
- If the broker reports `BLOCKED_MIN_LOT` or a risk/margin block, do not narrow the stop just to force an order.
- Check Experts/Journal for spread, market hours, real ticks, authorization and diagnostic rejection reasons. Signal counts are not executed-trade counts.
- Neither successful installation nor `READY_FOR_TESTER_ONLY` demonstrates after-cost profit or real-money permission.

Broker data and generated reports are local and excluded from Git. Do not share account credentials. Further reading: [Tester Research](MT5_3000_UNLIMITED_TESTER_2026-10-26.md) and [Stop-Loss Forensics](OWNER_PLAN_STOPLOSS_ROOTCAUSE_2026-10-26.md).

## Adaptive strategy router (Style 7, research only)

Style 7 does **not** know the best strategy in advance and does not use realized future returns. Each M15 completed candle, it reads closed-bar ADX, EMA separation and ATR, classifies market context as range / transition / trend, and checks allowed family-specific signals and feasible LIMIT entries. If multiple candidates qualify, fixed ex-ante priorities and reward-to-risk/spread estimates choose one, with one shared broker execution and risk pipeline. If none qualify, there is no trade. `QTS ROUTER DECISION` identifies the selected family and closed-bar context; the broker deal CSV preserves the actual setup as order comment. No online learning, dynamic historical performance fitting, or profit guarantee is claimed. All historical comparisons of Style 7 must be performed **after this decision logic is fixed**; the earlier six months used to evaluate the seven static hypotheses are not an untouched holdout. LIVE is still locked.
