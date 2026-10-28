# QTS Gold — WMMarkets MT5 Quick Start

**Version 2026-10-27.** Installation and DEMO/tester evaluation only. LIVE locked and positive after-cost expectancy unverified.

Read the [Windows operator guide](WINDOWS_START.md), [DEMO Forward operations](DEMO_FORWARD_OPERATIONS.md) and [engineering handoff](RELEASE_HANDOFF_2026-10-27.md).

## Install and verify

1. Update a clean checkout of `main` without merging it with old ZIP packages or deleting MT5 data.
2. Run repository-root `START_HERE.bat` option **1**; choose one MT5 Data Folder and its matching MetaEditor. The installer backs up previous files and installs the EA and Broker Preflight to the same terminal.
3. Require fresh EX5 files and **0 errors, 0 warnings** for both native compiles. A failed compile means installation is not verified.
4. In a WMMarkets DEMO account, open `XAUUSD@`, refresh Navigator > Scripts and run `QTS_Broker_Preflight`. Use menu option **2** to create the local HTML/JSON report. Do not enable DEMO orders if the report shows `ACTION_REQUIRED` or `BLOCKED_*`.

## Broker risk example (not permission to trade)

| Parameter | Research baseline |
|---|---|
| Modeled account value | USD 3,000 |
| Per-trade risk | 0.25% = USD 7.50 |
| Example gold stop distance | USD 4.00 |
| Modeled round-trip commission | USD 10 per lot; unverified |

A previously observed minimum lot was approximately 0.01 and contract size approximately 100 oz/lot, but the current broker's specifications are authoritative. If min-lot stressed loss exceeds USD 7.50, the trade must be blocked; do not compress the stop to circumvent sizing limits.

## Compare entry styles

Generate the four `.set` profiles using menu option **5**. In MT5 Tester (Ctrl+R), use `QTS_Gold_Robot`, `XAUUSD@`, M15, Every tick based on real ticks and USD 3,000 tester deposit. Keep dates and execution-cost assumptions equal across EntryStyle 0–3. Save Reports, Orders, Deals and Journal; put `QTS_0.htm` through `QTS_3.htm` under `gold_robot/reports_local/native/`, then run menu option **6** to compare them.

## Connected DEMO Forward

Only after successful native compile and broker preflight, use a dedicated WMMarkets DEMO USD account with exact `XAUUSD@`, `EnableDemoOrders=true` and `EnableDemoForwardOrders=true`. Both defaults are false. Effective risk defaults to a 0.25% cap, daily/peak stops remain active and `TesterIgnoreDailyAndPeakStops` cannot bypass them outside Tester. `PauseNewEntries=true` stops new entries but does not close existing positions.

## Unmet release evidence

GitHub checks do not prove a successful compile on this user's terminal, matching independent real-tick net profitability, current broker charges or DEMO fill/cancel safety after disconnects. For stop-loss analysis preserve broker fills and timestamped Bid/Ask ticks across the stop and subsequent candles. Do not use this handoff to solicit real-money deposits.
