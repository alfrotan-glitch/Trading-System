# QTS Gold — Would I entrust my own capital? (2026-11-01)

**Current decision: NO. LIVE LOCKED.** Passing source-code tests, finding technical setups, or obtaining a promising tester report cannot justify putting real money in the EA.

The read-only `research/capital_readiness.py` tool accepts native, separately saved MT5 Strategy Tester baseline and V3 (Adaptive Style 7/M15) run folders. Its output is an explicit **capital decision report**, not an order permission or a release token. No code path changes `EnableDemoOrders`, `ConnectedDemoForwardAuthorized`, `RealAccountBlocked`, or account permissions.

## One-click report (Windows)

After cloning or updating the project and installing Python 3, double-click **`gold_robot/REVIEW_CAPITAL_READINESS.bat`**. It scans **all** reports under `gold_robot/reports_local/auto_runs`, finds matching baseline/V3 months, flags missing/duplicate arms, and opens:

`gold_robot/reports_local/capital_readiness/QTS_CAPITAL_READINESS.json`

The report remains **NO-GO** when there are zero matched studies (currently expected). Do not reinterpret an empty result as zero risk.

For explicit archive locations, run from repository root:

```powershell
python gold_robot/research/capital_readiness.py --pair "path/to/nov_baseline" "path/to/nov_v3" --output "gold_robot/reports_local/capital_readiness/manual_review.json" --capital 200
```

Repeat `--pair` chronologically for additional completed months; `--as-of YYYY-MM-DD` can be used in deterministic regression tests.

## Evidence audit, not box ticking

For each monthly BASELINE/CONTEXT_V3 pair, QTS requires:

- Exact same symbol `XAUUSD@`, tester model = 4 (real ticks), timeframe M15, deposit, completed calendar month, and source-manifest SHA256 fingerprint.
- An original MT5 HTML report for Style 7, with SHA256 matching the result row, independently re-read net profit, profit factor, trade count and maximal equity drawdown.
- Original `QTS_7_trades.csv` with one complete entry and exit per position, unique deal IDs, broker-recorded gross P&L, swap, commissions, fees and chronological broker timestamps within the claimed period.
- Strict reconciliation of original broker deals against native HTML amounts and position counts, with **USD 10 extra adverse execution cost per traded lot** for a conservative research stress scenario. This is an assumed sensitivity scenario, **not** a measured WMMarkets charge.
- Only complete monthly research windows starting November 2026 count as prospectively eligible (months before that have already been inspected). Gaps, repeated months, duplicate results or a source-code change between monthly tests become explicit research blockers.
- A preliminary research threshold of 6 non-overlapping future months and 200 V3 positions, positive stressed net and positive stressed net versus BASELINE, and reported monthly equity drawdown no more than 10% of its tester deposit. These thresholds are **screening choices**, not validation of expected performance or a probability of profit.

Even a hypothetically perfect 6-month study does **not** approve real money, because missing broker execution proof cannot be manufactured from MT5 historical HTML. The following remain mandatory independent conditions:

1. Native MetaEditor compile of the final source (zero errors/warnings) and verified EX5 identity on the actual Windows broker terminal.
2. Measured WMMarkets XAUUSD@ contract, spread, commission, stop distance, slippage and minimum-volume behaviour in an isolated connected demo with no real-money authority.
3. Actual lot/margin/risk affordability at the owner’s **target capital (default $200)**. Results from $3,000 tester deposits are not a valid substitute.
4. Repeatable independent untouched forward research; tracked missed opportunities and stop→price-reclaim→original TP events using complete executable bid/ask ticks. Explicitly evaluate latency, costs, rejected orders, gaps, disconnects, rollovers and news shocks.
5. An independent human acceptance review of code, build provenance, final model/rules, financial risks, and a signed staged deployment plan.

The tool intentionally **always returns `capital_decision: DO_NOT_ENTRUST_REAL_CAPITAL`** and `can_send_orders: false`, including for strong synthetic or observational results. Future live authorization is a separate engineering/security decision that requires real qualified evidence and explicit operator approval. Any code change intended to unlock real trades is out of scope of these research tools.

## Do not overstate

A lower drawdown or higher net return in an MT5 backtest can be the result of changed sample selection, different fills or overfitting. The V3 static thresholds have not been proven to increase expected P&L. The engine has incomplete live economic-news integration and requires an independent source to verify its offline calendar inputs.

**The output is a refusal-to-trade safety checklist with linked native evidence, not a guarantee of capital preservation.**
