# QTS Gold | Native January 2025-to-Date Backtest

**RESEARCH ONLY - LIVE LOCKED - NOT VALIDATED FOR REAL MONEY**

## What to run on Windows

1. Close the MT5 terminal before automated tester installation/launch.
2. In the Trading-System-Clean repository run:
   ```powershell
   git pull --ff-only origin main
   if ($LASTEXITCODE -ne 0) { throw "Git update failed" }
   .\QTS_BACKTEST_2025_TO_DATE.bat
   ```
3. The one-click launcher runs the historical research leader
   `DUAL_DIRECTIONAL` (Retest BUY + Sweep SELL) using native WMMarkets
   `XAUUSD@` M15 real ticks, a simulated USD 3,000 deposit, from
   `2025.01.01` to the beginning of the current PC-local calendar day.
   `ToDate` is EXCLUSIVE; current partial trading-day data are excluded.
   On 2026-11-03, the requested end is `2026.11.03`. The broker's
   server timestamps, not Afghanistan local timestamps, determine bars.
4. After the test, Explorer highlights
   `QTS_2025_TO_DATE_EVIDENCE.zip`. Send that one ZIP for independent
   review. No real account or broker live order permission is enabled.

A different dual hypothesis can be examined separately:
```powershell
.\QTS_BACKTEST_2025_TO_DATE.ps1 -Variant DUAL_BOTH
.\QTS_BACKTEST_2025_TO_DATE.ps1 -Variant DUAL_QUALITY
```
Never sum PnL from these overlapping independent MT5 simulations.

## Interpretation

- The native monthly ledger shows both strategies' closed-bar BUY/SELL
  signals. Signals after a broker safety halt are observations, NOT fills.
- The original MT5 deal export and position forensics are preserved.
  Incomplete broker entry/exit attribution fails closed.
- `HISTORICAL_SAFETY_STOP_NO_GO` indicates protective halted entries;
  broker positions before the stop are NOT full-period performance.
- `HISTORICAL_MARKET_DATA_COVERAGE_NO_GO` indicates older real ticks
  may be missing, with gaps or fewer than 300 native closed M15 bars in
  an interior calendar month.
- `HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED` is technical
  completion, NOT a profitability or LIVE approval.
- The request can be large and broker terminal disk/tick availability
  can limit historical testing. Missing data are UNKNOWN, not losses
  or zero-signal months. NO-GO returns a nonzero Windows exit status
  even if it produces a diagnostic ZIP.

Existing risk and margin limits, original-stop safety checks, account
real-money lock, and incident reconciliation are unchanged. Recorded MT5
commission zero must be treated as unverified, and past broker trading
behavior is not an independently validated profitable edge.
