QTS GOLD MT5 - WINDOWS QUICK START
=================================

CANONICAL MAIN BRANCH:
https://github.com/alfrotan-glitch/Trading-System

1. Clone only main in a clean folder.
2. Double-click START_HERE.bat in the root folder.
3. Option 1 installs and compiles the current QTS_Gold_Robot EA and broker-check script.
4. In WMMarkets MetaTrader 5, open XAUUSD@ and run QTS_Broker_Preflight from Navigator > Scripts.
5. Option 2 creates a professional local HTML/JSON readiness report.

Exact MT5 Expert Advisor source:
  mt5_robot/QTS_Gold_Robot.mq5
Dependencies:
  mt5_robot/ExecutionPolicy.mqh
  mt5_robot/StructureResearch.mqh

Native MetaEditor must confirm 0 errors, 0 warnings.
For the latest edited source, this must be verified on the operator's Windows terminal.

Use MT5 Strategy Tester for research: XAUUSD@ / M15 / real ticks / 3000 USD
(the operator's current minimum selectable tester deposit). Check EntryStyle 0-3
separately. The optional daily-loss/count bypass is restricted to Strategy Tester.
Broker, per-trade SL/TP, volume, spread, margin and execution-safety checks remain.

No independently validated profitable strategy. No orders on real-money accounts.
Installation/reporting never submits orders. A clean report is not profit evidence.

Full instructions: docs/WINDOWS_START_DARI.md
Safety limitations: docs/RELEASE_STATUS.json
Historical research: docs/PERFORMANCE_REPORT.md
