# QTS Gold Robot intraday research candidate — 2026-10-25

**Status: RESEARCH / NO VERIFIED EDGE / LIVE BLOCKED.**

This source revision expands the tester-only candidate menu; it does not prove or promise profitability, fill frequency, or broker-safe realized maximum loss.

## What changes

- M5 is now a permitted signal timeframe (alongside M15/M30/H1); original M15 remains default until native verification.
- Two pending-LIMIT hypotheses are available: `QTS_FORMER_STOP_LIMIT` (unchanged default), and `QTS_RETEST_LIMIT` with an ATR-sized shallow entry offset and SL behind causal closed-bar structure. Neither uses market orders.
- TP uses a *research* multiple, default 1.0R for the new snapshot, but retest placement refuses targets beyond recently observed bar extremes; try 0.8R, 1.0R, 1.5R, and 2.0R in preregistered experiments.
- Daily fill ceiling increased from 3 to 8, and pending attempts from 5 to 20. Limits do NOT imply or force eight fills a day.
- Risk defaults to 1% of equity with a strict configured maximum of 2%; the engine now adds assumed round-turn per-lot fees and adverse-stop-price allowance to `OrderCalcProfit` risk before sizing down to a legal volume step. Broker min-lot or margin failure means no order. Defaults: fee $10 per 1 lot and adverse-stop-price 0.10 XAUUSD points (illustrative assumptions; replace with measured broker costs).
- Max daily loss default 3%, max peak equity drawdown 8%. Hard-stop closures can exceed limits in gaps.

## Critical blockers

1. MQL source-level tests passing is NOT a MetaEditor compilation and NOT a broker execution validation.
2. The account must be tested with $100 and $200 Strategy Tester deposits, using actual volume step, tick value, margin, bid/ask spread, real-tick mode, applicable commissions, and gap costs.
3. For each setup report signals per day, placed/filled rates, post-cost net, R expectancy, confidence intervals, drawdown, stop-outs, partial fills, time-to-TP/SL, and walk-forward stability.
4. No special preference for trade frequency is allowed to bypass the evidence gate; DEMO submissions remain disabled until an independent positive edge is found, and LIVE remains blocked.
5. If 0.01 lot cannot stay under the configured risk limit at an economically justified stop, skip the trade. Avoid synthetic wins from a target so small that the broker spread consumes the profit.

- Additional gross TP fee-floor veto: `OrderCalcProfit` checks account-currency profit at the actual pending entry/target against `MinimumTargetFeeMultiple` times assumed round-turn fees. This is not a win-probability or profitability guarantee.
