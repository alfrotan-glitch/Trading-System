# QTS Gold — WMMarkets DEMO Forward Operations

**Status:** Virtual-money evaluation only. No validated profitable edge; LIVE and CONTEST account execution remain blocked.

## Prerequisites

Use the current `main` source. From `START_HERE.bat`, select **1** and require fresh native MetaEditor output with **0 errors, 0 warnings** and EX5 files. The installer verifies source hashes and retains a rollback backup. Open `XAUUSD@` on a WMMarkets DEMO account, run Navigator > Scripts > `QTS_Broker_Preflight`, then use option **2** for the HTML/JSON broker report. These steps are read-only.

## Three distinct modes

| Mode | Authorization | Behavior |
|---|---|---|
| Observation (default) | Either DEMO flag false | Detect and log signals; no broker orders |
| Strategy Tester | Tester mode, `EnableDemoOrders=true` | Simulated orders for independent `EntryStyle` comparisons |
| Connected DEMO Forward | WMMarkets DEMO, USD, `XAUUSD@`, both DEMO flags true | Pending LIMIT orders with virtual funds and active safety controls |

To start connected DEMO Forward, explicitly attach `QTS_Gold_Robot` to the DEMO `XAUUSD@` chart, turn on MT5 Algo Trading with supervision, and set `EnableDemoOrders=true` and `EnableDemoForwardOrders=true`. Keep `RiskPerTradePct=0.25` and `DemoForwardRiskCapPct=0.25` as a conservative baseline. The independent DEMO cap applies even if the requested per-trade risk is higher.

`TesterIgnoreDailyAndPeakStops` has no effect in connected DEMO; daily/peak equity stops and order limits stay active. Avoid manual positions or other robots on the same symbol. Use a dedicated DEMO account to prevent interference.

Enable `EnableEntryDiagnostics=true` for one `QTS ENTRY AUDIT` line per closed candle in the MT5 Experts log. Diagnostic `OBSERVE` signals and rejection reasons are read-only, including when DEMO orders are disabled; they are not trading approval or evidence of positive expectancy. Check Experts/Journal for `HALTED` and `NO NEW ORDERS`; never shrink stops just to increase trade count.

## Entry candidates

- `EntryStyle=0`: former-stop LIMIT baseline.
- `EntryStyle=1`: shallower retest LIMIT.
- `EntryStyle=2`: closed-bar structural break, acceptance and retest.
- `EntryStyle=3`: closed-bar sweep, reclaim and confirmation; related historical family previously tested negative.

Use only one EntryStyle at a time in connected DEMO. Do not run duplicate instances with the same magic number. Pending orders require valid SL/TP, lot, margin, ATR/spread and execution checks.

## When not to trade, even on DEMO

Do not enable orders after a failed compile, stale or blocked broker preflight, changed broker/server/symbol, wrong account currency, invalid quotes or wide spreads, incompatible min lot/risk, conflicting open positions, or inability to supervise disconnections and operational halts.

## Monitoring and stopping

Record broker fills, cancels, spread, slippage, commission, swap, stops and realized drawdown using MT5 History > Deals and Experts/Journal. The robot's local `QTS_Gold_Robot_Broker_Deals.csv` is supplementary, not a replacement for broker history.

Set `PauseNewEntries=true` or `EnableDemoForwardOrders=false` to stop new entries. This does **not** guarantee that existing positions are closed; protective management continues. `EmergencyFlattenOwned=true` requests closure of the robot's owned positions, but actual fills depend on broker connectivity and response. Inspect MT5 positions manually after stopping the EA.

A passing DEMO trial does not unlock LIVE. Require independent out-of-sample after-cost evidence and explicit authorization before any real-money release.
