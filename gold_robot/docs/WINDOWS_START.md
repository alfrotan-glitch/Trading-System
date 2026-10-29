# QTS Gold MT5 — Windows Operator Guide

**Scope:** WMMarkets MetaTrader 5, XAUUSD@, Strategy Tester and controlled DEMO evaluation. LIVE trading is locked. No profitable edge has been independently validated.

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
| 5 | Generate four MT5 Strategy Tester `.set` profiles | None |
| 6 | Compare four saved native MT5 tester reports | None |
| 7 | Exit | None |

`ROBOT.bat` is the separate Python research/DEMO entry point. For the MT5 Expert Advisor use `START_HERE.bat`. The MT5 workflow does not require the Python desktop.

## Strategy Tester

Press `Ctrl+R` in MetaTrader 5. Select Expert `QTS_Gold_Robot`, symbol `XAUUSD@`, timeframe **M15** (then test **M5** separately), model **Every tick based on real ticks**, and initial deposit **USD 3,000** (the smallest amount observed as selectable in this operator's terminal). This is a tester setting, not a required real-money deposit.

Use menu option **5** to generate four profiles in `gold_robot/reports_local/tester_presets/`. Load one profile at a time under Tester > Inputs:

- `EntryStyle=0,1,2,3` in four separate runs with identical dates, spread/cost conditions and deposit.
- `EnableDemoOrders=true` **in Strategy Tester only**; `EnableDemoForwardOrders=false`.
- `TesterIgnoreDailyAndPeakStops=true` for the experimental opportunity census; this bypass affects only Tester.
- `RiskPerTradePct=0.5` and `EnableEntryDiagnostics=true` for like-for-like research.

The tester-only bypass does **not** disable per-trade risk, minimum lot, margin, protective stops, spread limits or incident halts. The four candidates are research hypotheses, not approved trading strategies. Option 5 also creates four `tester_presets/safety_on/` files with the ordinary daily/peak stops ACTIVE. Rerun any promising candidate with the safety-on version; results from stop-bypassed census tests are not production-like.

Let each run finish and confirm the Strategy Tester completion message. From the Tester Backtest/Report results, use Save as Report to export the native HTML report; a MetaTester agent log (including a file renamed to .htm) is NOT an HTML performance report. Export the MT5 Deals, Orders and Journal separately. Save the native HTML reports as `QTS_0.htm`, `QTS_1.htm`, `QTS_2.htm`, `QTS_3.htm` in `gold_robot/reports_local/native/`; use menu option **6** for a read-only comparison. Missing files or zero trades are not successful results.

## Connected virtual DEMO

DEMO-forward orders require a successfully compiled EA, a valid broker preflight, a verified WMMarkets DEMO USD account, the exact `XAUUSD@` symbol and both `EnableDemoOrders=true` and `EnableDemoForwardOrders=true`. Defaults are off. The independent connected-DEMO risk cap defaults to **0.25% per trade** and daily drawdown controls remain active. See [DEMO Forward Operations](DEMO_FORWARD_OPERATIONS.md).

## Troubleshooting and acceptance

- If MetaEditor is missing, press F4 in MT5 and locate the corresponding `metaeditor64.exe`; use File > Open Data Folder to identify the same terminal.
- If the source hashes, compile log, EX5 or preflight CSV are missing/stale, the readiness report must show `ACTION_REQUIRED`. Re-run preflight after installing current sources.
- If the broker reports `BLOCKED_MIN_LOT` or a risk/margin block, do not narrow the stop just to force an order.
- Check Experts/Journal for spread, market hours, real ticks, authorization and diagnostic rejection reasons. Signal counts are not executed-trade counts.
- Neither successful installation nor `READY_FOR_TESTER_ONLY` demonstrates after-cost profit or real-money permission.

Broker data and generated reports are local and excluded from Git. Do not share account credentials. Further reading: [Tester Research](MT5_3000_UNLIMITED_TESTER_2026-10-26.md) and [Stop-Loss Forensics](OWNER_PLAN_STOPLOSS_ROOTCAUSE_2026-10-26.md).
