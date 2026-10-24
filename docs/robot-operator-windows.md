# QTS Robot — Windows operator guide

## What you receive

QTS is a **single integrated gold robot workstation** rather than multiple
separate executables. It already has a desktop, the Windows MetaTrader 5
broker integration, a controlled autonomous DEMO-order loop, reconciliation,
broker-identity verification, order journal and durable risk stops.

**The software architecture is not the missing piece of profitability.**
Current historical XAUUSD scalping tests show *negative* estimated after-cost
expectancy for both confirmed and anticipatory entries. The untested
counter-pressure challenger is also not evidence of an edge.
A successful Python backtest or a running MT5 connection is not a profitable
robot. LIVE stays structurally locked.

## Daily operation

1. On Windows, open **MetaTrader 5** and sign in to your **DEMO account**.
2. Open the existing `Trading-System` folder.
3. Double-click **`ROBOT.bat`**. It forwards to the only canonical
   launcher, `scripts/run_qts.bat`, and opens the QTS desktop.
4. The **Home** and **Trading / Demo** pages show the demo connection, gold
   quote, next setup step, mode, stops and any existing authorization.
5. If the execution policy or registry refuses DEMO orders, the refusal is
   intentional and does **not** authorize disabling safety checks. The
   operator must obtain valid DEMO authorization and satisfy every existing
   readiness, identity, risk, stage and strategy registration check.

**Launching the desktop is NOT starting autopilot or placing an order.**
The existing autonomous DEMO autopilot is authorization-gated and
operator-controlled; no automatic approval or hidden order route has been
added. None of the historical negative strategies is marketed as profitable.

## After a Windows memory failure

A fatal `init_import_site: MemoryError()` before any QTS code means the
Python interpreter could not initialize under current memory conditions.
Save work and restart Windows, close memory-heavy programs, inspect free
RAM and ensure the Windows pagefile is enabled (prefer Windows-managed).
If starting Python still fails, fix the machine memory constraint before
attempting a tick replay. The launcher reports this without touching tick
data. Do not delete the `data/raw/mt5_ticks` directory.

## Economic readiness versus software readiness

Technical DEMO order plumbing may pass tests even while a strategy is
negative after execution costs. Independently verified positive expectancy,
reasonable drawdown, a sufficiently long unseen forward sample, measured
broker fills/spread/commission/slippage, and explicit owner risk authority
are separate prerequisites for promoting a real-money robot.

`LIVE = LOCKED`; **no order from a double-click**; no claim of profit.
