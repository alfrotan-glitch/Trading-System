# QTS Gold Robot — Windows MetaTrader 5 Expert Advisor

**Status: RESEARCH / NOT RELEASED. No verified positive trading edge. LIVE orders are blocked.**

This directory contains the imported, canonical **MQL5** gold Expert Advisor,
its execution-policy include file, the Windows installer, offline research and tests.

## Use the correct Windows launcher

- **`gold_robot/INSTALL_ROBOT.bat`** installs/compiles the MQL5 EA in MetaTrader 5.
  Installing does not enable trades or change account type.
- **`ROBOT.bat` in the repository root** starts the *separate Python QTS workstation*.
  It does **not** install this MQL5 EA. These are two different execution engines.

## What the Gold EA currently implements

- Original deep former-stop LIMIT and an experimental shallower structural-retest LIMIT.
- M15 is still the default signal timeframe. M5 is available as a research input;
  its profitability and real-tick execution have **not** been independently validated.
- Risk defaults to 1% of equity; user-configurable risk is **capped at 2%**.
- Daily equity loss threshold defaults to 3%, now supplemented by a pre-order
  check of the **remaining daily risk headroom** during lot sizing and immediately
  before sending an order.
- Broker-based estimated loss, margin, minimum volume, quote freshness,
  spread limits, durable protective order and position monitoring.
- No forced number of trades, martingale, discretionary loosening of structural
  stop placement or guaranteed take-profit success.

**The strategy evidence gate permits order submission only in Strategy Tester.**
The installed EA defaults to no orders; it cannot start real-account trading.
This gate must not be relaxed simply to increase trade count.

## Accounts with $100–$200

A 0.01-lot minimum, broker leverage and the true required stop distance can make
a small account impossible to trade within 1–2% risk. A rejected transaction is
the correct result when legal volume or margin cannot meet the risk budget.
The 2% setting is a ceiling, not a promised or required risk per trade.

Broker stops and modeled adverse price gaps are **not a guaranteed maximum loss**.
Spread, commission and swap assumptions are not yet fully verified against WMMarkets.

## Independent verification

1. Review source and compile the **latest** EA in local MetaEditor.
2. Use real broker bid/ask ticks in native MT5 Strategy Tester for $100 and $200.
   The offline `research/RunNativeValidation.ps1` script accepts `-DepositUsd 100`
   or `-DepositUsd 200`, saves separate reports and currently uses the M15
   historical fixture. It does **not** automatically verify M5.
3. Verify actual costs, min lot, margin, pending fill and timeout rates,
   broker disconnections, restart recovery, and stop-loss gaps.
4. Compare alternative strategies and take-profit distances by positive
   **net expectancy**, not merely trading frequency or advertised win rate.
5. Retain the real-money lock until all release criteria are met.

Read `docs/PERFORMANCE_REPORT.md` for the **older** M15 EA's loss-making
six-month native report (18 trades; PF 0.98); the report does not measure
profitability of the latest code. Read `docs/INTRADAY_DESIGN.md` and
`docs/RELEASE_STATUS.json` for current limitations.

GitHub CI validates Python tests and source safety checks, **not an MQL5
MetaEditor compilation or connected broker execution**. The user should not
interpret passing CI as profitable or deployment-ready.
