# QTS Gold | Windows Operator Guide

Canonical repository: alfrotan-glitch/Trading-System (`main`).
Canonical MT5 Expert Advisor: `gold_robot/mt5_robot/QTS_Gold_Robot.mq5`.
Supported target: WMMarkets MetaTrader 5, `XAUUSD@`.

**Safety status: LIVE LOCKED. No independently validated after-cost profitable edge.**
All native Strategy Tester orders are simulated. Connecting a DEMO account does
not itself authorize forward trading. Real-money orders remain forbidden.

## One-click automatic research testing

Double-click **`START_HERE.bat`** in the repository root. This is the supported
daily Windows entry point; the other root `QTS_*.bat` launchers are maintained
as technical/research compatibility tools, not separate production robots.

| Menu | Action |
| --- | --- |
| 1 | Retest vs Sweep/Reclaim: native MT5 real-tick tests of Styles 1 and 3 |
| 2 | Full native tests of ten independent styles: 0-8 on M15, Style 9 on M1 |
| 3 | Install/update the single canonical MT5 Expert Advisor |
| 4 | Open the most recent saved native tester HTML summary |
| 5 | Generate a local broker/installation readiness report |
| 6 | Advanced tools: presets, V4 decision diagnosis, post-stop data, saved-report comparison, research desktop |
| 7 | Exit |

**First-time install:** Install the broker's Windows MT5 terminal, sign in to
a WMMarkets DEMO account and close MT5 before running installation or unattended
native Strategy Tester jobs. Choose menu 3, verify zero MetaEditor compilation
errors, and use menu 5 to inspect readiness and broker restrictions.

**Run comparison:** Choose menu 1. Historical positive results for Style 1
(Retest) and Style 3 (Sweep/Reclaim) are research candidates, not approved
winners. The same installed canonical EA, broker, real-tick model and configured
date window are used for both. Missing trades, zero fills, incomplete quotes
or non-reconciled broker fees must be treated as incomplete evidence.

**Run all styles:** Choose menu 2. The native runner handles the fixed styles,
adaptive router and SMC on M15 plus the separately configured M1 scalp style.
The sample period defaults to the last six completed calendar months.
This is a research screen; previously examined months are NOT an untouched
holdout. A fresh out-of-sample/forward period is required before selecting
the strongest strategy.

## Native tester evidence and interpretation

Every automatic run creates its own unique directory at
`gold_robot/reports_local/auto_runs/<timestamp>/` with `OPEN_RESULTS.html`,
`OPEN_RESULTS.json`, simulator reports and, when valid, native broker-deal CSVs.
Evidence ZIP packaging is pinned to that exact run. Failed or incomplete
runs do NOT borrow files from a previous run. `QTS_SHARE_RESULTS.bat` can be
used separately to package existing research, with its own source disclosure.

The MT5 tester uses **Every tick based on real ticks** for `XAUUSD@` and a
research-only simulated USD 3,000 initial balance. This balance does not
establish the broker's minimum real deposit. The usual research presets
limit per-trade risk to 0.50%. Tester-only flags may intentionally bypass
daily equity stops for an opportunity census; never interpret that as an
operationally safe/live configuration. Re-run any candidate with ordinary
risk stops enabled and broker costs reconciled.

Treat every positive backtest as exploratory until real bid/ask history,
execution fees, commissions, swap, slippage, drawdown, minimum tradable
volume, sufficient sample size and independent holdout have been examined.
An SL followed later by the original TP is NOT proof that widening the
original SL would have been profitable. Unknown quote windows remain UNKNOWN.

## Audit H1 trend, M15 ATR, spread and entry hour (READ ONLY)

This is *descriptive retrospective research*, not a new trading bot and
not an automatic change to Retest or Sweep/Reclaim. On Windows, open your
WMMarkets **DEMO** MT5 terminal, then double-click `START_HERE.bat` and
select **6 (Advanced) > B (Historical market-context audit)**. Paste the
full absolute path to the **QTS_HOLDOUT_REVIEW.zip** from your targeted
native Strategy Tester run. This runs the existing Python interpreter
(`py -3`) and the MetaTrader5 Python package; no connected orders are sent.

The output is saved in the same folder as
`QTS_MARKET_CONTEXT_REVIEW.json`. It records closed H1 EMA20/EMA50 trend,
closed M15 ATR14 relative to trailing history, historical executable
bid/ask spread and UTC entry hour **at or before each trade's entry**.
Current forming candles and ticks after entry are excluded. For missing
quotes, stale bars, unverified DEMO broker or partial evidence the
analysis fails closed; it never fabricates market context.

Review the `cohorts` section to compare historical BUY vs SELL,
H1-aligned vs countertrend, volatility and spread groups. All these
months have already been inspected, so **no cohort is a proven edge**.
Do not turn a retrospective grouping into an EA veto until tested with
predeclared rules, actual broker costs and future untouched data.

## Safety and installation troubleshooting

- Only the repository `main` is the active development branch.
- Never attach the EA to a real-money account or disable real-account gates.
- The EA defaults to disabled connected DEMO orders; any forward DEMO test
  requires separate explicit authorization and the correct broker identity.
- If MetaEditor compilation, binary/source checksum verification, terminal
  selection or quote history fails, treat the operation as NO-GO.
- If native MT5 exports are incomplete, inspect the relevant
  `OPEN_RESULTS.json` and broker history rather than reusing an older report.
- An untracked local file may exist without being part of Git; examine
  `git status --short` before stashing, moving or deleting it.

Advanced background: [Gold EA overview](../README.md),
[Connected DEMO operations](DEMO_FORWARD_OPERATIONS.md),
[Post-stop investigations](OWNER_PLAN_STOPLOSS_ROOTCAUSE_2026-10-26.md).
